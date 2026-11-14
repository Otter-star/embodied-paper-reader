"""Import one prepared paper into the Zotero Desktop 10 personal library."""

import argparse
from datetime import datetime, timezone
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import url2pathname

from bs4 import BeautifulSoup
from filelock import FileLock, Timeout
import pymupdf
import requests


ROOT = Path(__file__).resolve().parents[1]
AUDITS = ROOT / "local" / "zotero-audit"
BASE = "http://127.0.0.1:23119"
ITEMS = "/api/users/0/items"
MARKER = "[embodied-paper-reader] 中文导读"
ARXIV = r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})"


class Pending(Exception):
    """A specific unresolved check that is safe to report to the caller."""


def digest(text):
    return sha256(text.encode()).hexdigest()


def normalized(text):
    return "".join(c for c in text.casefold() if c.isalnum())


def identifiers(text):
    text = text.lower()
    found = set(re.findall(r"https?://[^\s<>]+", text))
    found.update(re.findall(r"10\.\d{4,9}/[^\s<>]+", text))
    for match in re.finditer(r"(?:arxiv[:. ]+|arxiv\.org/(?:abs|html|pdf)/)(" + ARXIV + r")(?:v\d+)?\b", text):
        found.add("arxiv:" + match[1])
    return {s.rstrip("/.,;)") for s in found}


def match_parent(items, paper):
    wanted = identifiers("\n".join([paper["canonical"], paper["source"], *paper["aliases"]]))
    exact, fallback = [], []
    for item in items:
        if item["itemType"] in {"attachment", "note", "annotation"}:
            continue
        fields = ["DOI", "url", "extra", "archiveID"]
        if identifiers("\n".join(item.get(k, "") for k in fields)) & wanted:
            exact.append(item)
        authors = [a for a in item.get("creators", []) if a["creatorType"] == "author"]
        if (normalized(item.get("title", "")) == normalized(paper["title"]) and authors
                and normalized(authors[0].get("lastName", "")) == normalized(paper["authors"][0].rsplit(" ", 1)[-1])):
            fallback.append(item)
    return unique(exact or fallback, "父条目")


def unique(items, label):
    if len(items) > 1:
        raise Pending(label + "存在多个匹配，需要消歧")
    return next(iter(items), None)


def audit_path(canonical):
    kind, identifier = canonical.split(":", 1)
    if kind == "arxiv" and re.fullmatch(r"\d{4}\.\d{4,5}v\d+", identifier):
        return AUDITS / f"arxiv_{identifier}.json"
    prefix = re.sub(r"[^a-z0-9.-]+", "_", kind + "_" + identifier.split("@")[0])[:64]
    h = digest(canonical)
    path = AUDITS / f"{prefix}_{h[:16]}.json"
    if path.exists() and json.loads(path.read_text("utf8"))["canonical"] != canonical:
        path = AUDITS / f"{prefix}_{h}.json"
    return path


def persist(path, audit):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf8")
    temp.replace(path)


def inspect_pdf(path):
    with pymupdf.open(path) as doc:
        first = doc[0].get_text()
    if not first.strip():
        raise Pending("PDF 首页未提取到文字")
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest(), "first_page": first}


def verify_source(paper, pdf):
    first = normalized(pdf["first_page"])
    if normalized(paper["title"]) not in first or normalized(paper["authors"][0]) not in first:
        raise Pending("PDF 首页与论文标题或第一作者不符")
    canonical = paper["canonical"]
    if canonical.startswith("arxiv:"):
        version = canonical.removeprefix("arxiv:")
        printed = re.findall(r"arXiv:\s*(" + ARXIV + r"v\d+)\b", pdf["first_page"], re.I)
        source = urlsplit(paper["source"])
        if (paper["version"] != version or set(printed) != {version} or source.hostname != "arxiv.org"
                or source.path.rstrip("/") not in {"/html/" + version, "/pdf/" + version, "/abs/" + version}):
            raise Pending("arXiv 正文版本与 PDF 首页未匹配")
    elif canonical != paper["version"] or pdf["sha256"] != paper["pdf_sha256"]:
        raise Pending("正式版文件与沿出版记录取得的 PDF 哈希不符")


class Zotero:
    def __init__(self):
        self.http = requests.Session()
        self.http.trust_env = False
        response = self.call("GET", "/api/")
        self.server = response.headers["Zotero-Server-ID"]
        self.http.headers["Zotero-Server-ID"] = self.server
        self.key = os.environ.get("ZOTERO_LOCAL_API_KEY")
        self.once = False

    def call(self, method, path, **kwargs):
        result = self.http.request(method, BASE + path, timeout=kwargs.pop("timeout", 60),
                                   allow_redirects=False, **kwargs)
        result.raise_for_status()
        return result

    def items(self, suffix):
        return [row["data"] for row in self.call("GET", ITEMS + suffix).json()]

    def write(self, method, path, **kwargs):
        if not self.key:
            print("请在 Zotero 中授权 embodied-paper-reader 写入个人库。", flush=True)
            grant = self.call("POST", "/api/local/authorize", json={"appName": "embodied-paper-reader"}, timeout=240).json()
            self.key = grant["key"]
            self.once = not grant["remember"]
        headers = {"Zotero-API-Key": self.key, **kwargs.pop("headers", {})}
        try:
            return self.call(method, path, headers=headers, **kwargs)
        finally:
            if self.once:
                self.key = None

    def create(self, fields):
        result = self.write("POST", ITEMS, json=[fields]).json()
        if result["failed"]:
            raise Pending("Zotero 拒绝创建" + fields["itemType"] + "，HTTP " + str(result["failed"]["0"]["code"]))
        return result["successful"]["0"]["key"]

    def file_path(self, key):
        url = self.call("GET", f"{ITEMS}/{key}/file/view/url").text.strip()
        return Path(url2pathname(urlsplit(url).path)) if url.startswith("file:") else None

    def upload(self, key, path, expected_sha256):
        body = path.read_bytes()
        if sha256(body).hexdigest() != expected_sha256:
            raise Pending("待上传的文件在核验后发生了变化")
        route = f"{ITEMS}/{key}/file"
        headers = {"If-None-Match": "*"}
        fields = {"filename": path.name, "filesize": len(body), "mtime": int(path.stat().st_mtime * 1000),
                  "contentType": "application/pdf", "md5": md5(body).hexdigest()}
        upload = self.write("POST", route, data=fields, headers=headers).json()
        if not upload.get("exists"):
            self.call("POST", "/api/local/uploads/" + upload["uploadKey"], data=body,
                      headers={"Content-Type": "application/pdf"})
            self.write("POST", route, data={"upload": upload["uploadKey"]}, headers=headers)


def note_title(html):
    lines = BeautifulSoup(html, "html.parser").get_text("\n", strip=True).splitlines()
    return lines[0] if lines else ""


def note_body(html):
    # Zotero can wrap the submitted HTML in its own schema-version div.
    soup = BeautifulSoup(html, "html.parser")
    for wrapper in soup.select("div[data-schema-version]"):
        wrapper.unwrap()
    return "".join(str(e) for e in soup.contents if str(e).strip())


def inventory(client, paper, source_pdf, audit):
    parent = match_parent(client.items("/top"), paper)
    found = {"parent": parent["key"] if parent else None, "pdf": None, "note": None}
    if not parent:
        return found
    notes, pdfs = [], []
    for item in client.items("/" + parent["key"] + "/children"):
        if item.get("parentItem") != parent["key"]:
            continue
        if item["itemType"] == "note":
            title = note_title(item["note"])
            if (title.startswith(MARKER) and title.endswith("(" + paper["version"] + ")")
                    or item["key"] == audit.get("note_key")):
                notes.append(item)
        elif item["itemType"] == "attachment" and item.get("contentType") == "application/pdf":
            path = client.file_path(item["key"])
            same_url = item.get("url") == paper["pdf_url"]
            if not path or not path.is_file():
                if same_url:
                    pdfs.append({"key": item["key"], "missing": True})
                continue
            fingerprint = sha256(path.read_bytes()).hexdigest()
            if fingerprint == source_pdf["sha256"]:
                pdfs.append({"key": item["key"], **inspect_pdf(path)})
            elif same_url:
                raise Pending("已有附件与目标 PDF 内容不一致，需要核对版本")
            elif paper["canonical"].startswith("arxiv:"):
                # An existing copy can have different bytes (e.g. embedded annotations).
                try:
                    pdf = inspect_pdf(path)
                    verify_source(paper, pdf)
                except (Pending, pymupdf.FileDataError):
                    continue
                pdfs.append({"key": item["key"], **pdf})
    found.update(note=unique(notes, "工作流导读"), pdf=unique(pdfs, "同版 PDF"))
    return found


def keys(state):
    return [state["parent"], *(state[k]["key"] if state[k] else None for k in ("pdf", "note"))]


def sync(client, paper, folder, audit, path, run):
    pdf_path = folder / paper["pdf"]
    source_pdf = inspect_pdf(pdf_path)
    verify_source(paper, source_pdf)
    guide = (folder / paper["note"]).read_text("utf8").strip()
    title = note_title(guide)
    if not (title.startswith(MARKER) and title.endswith("(" + paper["version"] + ")")):
        raise Pending("导读标题的论文版本未匹配")
    run.update(source=paper["source"], pdf_url=paper["pdf_url"], source_pdf=source_pdf)
    before = inventory(client, paper, source_pdf, audit)
    run["before"] = keys(before)
    run["pdf_file_present_before"] = bool(before["pdf"] and not before["pdf"].get("missing"))
    persist(path, audit)
    parent = before["parent"]
    if not parent:
        creators = []
        for author in paper["authors"]:
            first, _, last = author.rpartition(" ")
            creators.append({"creatorType": "author", "firstName": first, "lastName": last})
        parent = client.create({**paper["entry"], "title": paper["title"], "date": paper["date"],
                                "creators": creators, "extra": "\n".join([paper["canonical"], *paper["aliases"]])})
    pdf = before["pdf"]
    if not pdf:
        key = client.create({"itemType": "attachment", "parentItem": parent, "linkMode": "imported_url",
                             "url": paper["pdf_url"], "contentType": "application/pdf",
                             "title": paper["short_title"] + " · " + paper["version"], "filename": pdf_path.name})
        client.upload(key, pdf_path, source_pdf["sha256"])
    elif pdf.get("missing"):
        client.upload(pdf["key"], pdf_path, source_pdf["sha256"])
    note = before["note"]
    if not note:
        client.create({"itemType": "note", "parentItem": parent, "note": guide})
    elif note_body(note["note"]) != note_body(guide):
        if digest(note["note"]) != audit.get("last_written_note_sha256") or note["key"] != audit.get("note_key"):
            raise Pending("导读有人工修改或缺少上次写入凭据，已保留原笔记")
        client.write("PATCH", ITEMS + "/" + note["key"], json={"version": note["version"], "note": guide})
    after = inventory(client, paper, source_pdf, audit)
    run["after"] = keys(after)
    if not all(run["after"]) or after["pdf"].get("missing") or note_body(after["note"]["note"]) != note_body(guide):
        raise Pending("父项、PDF 或笔记正文回读未通过")
    if any(old and old != new for old, new in zip(run["before"], run["after"])):
        raise Pending("回读时已有条目的 Key 发生变化")
    audit.update(note_key=after["note"]["key"], last_written_note_sha256=digest(after["note"]["note"]))
    run.update(pdf=after["pdf"], note_matches=True, note_content_sha256=audit["last_written_note_sha256"],
               delta=[int(bool(b)) - int(bool(a)) for a, b in zip(run["before"], run["after"])])


def main(manifest):
    paper = json.loads(manifest.read_text("utf8"))
    path = audit_path(paper["canonical"])
    path.parent.mkdir(parents=True, exist_ok=True)
    # A single lock also serializes different versions that share a parent.
    with FileLock(str(AUDITS / "sync.lock"), timeout=0):
        audit = json.loads(path.read_text("utf8")) if path.exists() else {"canonical": paper["canonical"], "runs": []}
        run = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "待验证"}
        audit["runs"].append(run)
        try:
            client = Zotero()
            if audit.get("server", client.server) != client.server:
                raise Pending("审计记录属于另一个 Zotero 实例")
            audit["server"] = client.server
            sync(client, paper, manifest.parent, audit, path, run)
            run["status"] = "通过"
            summary = "父子关系、PDF 与笔记回读通过；增量 " + "/".join(map(str, run["delta"]))
        except (Pending, requests.RequestException, OSError, ValueError, KeyError, RuntimeError) as exc:
            run["error"] = str(exc) if not isinstance(exc, requests.RequestException) else type(exc).__name__
            if isinstance(exc, requests.RequestException) and exc.request is not None:
                run["request_method"] = exc.request.method
                run["request_route"] = re.sub(r"/uploads/[^/]+", "/uploads/<token>", urlsplit(exc.request.url).path)
            summary = str(exc) if isinstance(exc, Pending) else type(exc).__name__
            if isinstance(exc, requests.HTTPError):
                summary = f"Zotero HTTP {exc.response.status_code}"
                run["response"] = exc.response.text
        persist(path, audit)
        print(run["time"], run["status"], summary, path.relative_to(ROOT).as_posix())
        return 0 if run["status"] == "通过" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    try:
        raise SystemExit(main(parser.parse_args().manifest))
    except Timeout:
        raise SystemExit("待验证：另一同步正在运行，完成后重试")
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit("待验证：清单或审计文件读写失败 (" + type(error).__name__ + ")")
