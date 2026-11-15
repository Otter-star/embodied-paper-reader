"""Import one prepared paper into the Zotero Desktop 10 personal library."""

import argparse
from datetime import datetime, timezone
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import url2pathname

from bs4 import BeautifulSoup
from filelock import FileLock, Timeout
import pymupdf
import requests

if os.name == "nt":
    from keyring.backends.Windows import WinVaultKeyring, pywintypes
    from keyring.errors import KeyringError
    CREDENTIAL_ERRORS = (OSError, KeyringError, pywintypes.error)
else:
    CREDENTIAL_ERRORS = (OSError,)


ROOT = Path(__file__).resolve().parents[1]
AUDITS = ROOT / "local" / "zotero-audit"
BASE = "http://127.0.0.1:23119"
ITEMS = "/api/users/0/items"
MARKER = "[embodied-paper-reader] 中文导读"
ARXIV = r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})"
AUTH_SERVICE = "embodied-paper-reader/ZoteroLocalAPI"


def credential_backend():
    return WinVaultKeyring() if os.name == "nt" else None


class Pending(Exception):
    """A specific unresolved check that is safe to report to the caller."""


def digest(text):
    return sha256(text.encode()).hexdigest()


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def identifiers(text):
    text = text.lower()
    found = set(re.findall(r"https?://[^\s<>]+", text))
    found.update(re.findall(r"10\.\d{4,9}/[^\s<>]+", text))
    for match in re.finditer(r"(?:arxiv[:. ]+|arxiv\.org/(?:abs|html|pdf)/)(" + ARXIV + r")(?:v\d+)?\b", text):
        found.add("arxiv:" + match[1])
    return {s.rstrip("/.,;)") for s in found}


def match_parent(items, paper):
    canonical_identifier = paper["canonical"].rsplit("@", 1)[0]
    wanted = identifiers("\n".join([canonical_identifier, paper["source"], *paper["aliases"]]))
    wanted_strong = {s for s in wanted if s.startswith(("arxiv:", "10."))}
    exact, url_matches, fallback = [], [], []
    conflicting = False
    for item in items:
        if item["itemType"] in {"attachment", "note", "annotation"}:
            continue
        fields = ["DOI", "url", "extra", "archiveID"]
        existing = identifiers("\n".join(item.get(k, "") for k in fields))
        if existing & wanted_strong:
            exact.append(item)
            continue
        authors = [a for a in item.get("creators", []) if a["creatorType"] == "author"]
        first_author = authors[0] if authors else {}
        surname = first_author.get("lastName") or first_author.get("name", "").rsplit(" ", 1)[-1]
        same_title_author = (normalized(item.get("title", "")) == normalized(paper["title"]) and surname
                             and normalized(surname) ==
                             normalized(paper["authors"][0].rsplit(" ", 1)[-1]))
        if not (existing & wanted or same_title_author):
            continue
        for prefix in ("arxiv:", "10."):
            requested = {s for s in wanted if s.startswith(prefix)}
            present = {s for s in existing if s.startswith(prefix)}
            if requested and present and requested.isdisjoint(present):
                conflicting = True
        if existing & wanted:
            url_matches.append(item)
        elif same_title_author:
            fallback.append(item)
    if exact:
        return unique(exact, "父条目")
    if conflicting:
        raise Pending("候选父条目的 DOI 或 arXiv 标识冲突，需要消歧")
    return unique(url_matches or fallback, "父条目")


def unique(items, label):
    if len(items) > 1:
        raise Pending(label + "存在多个匹配，需要消歧")
    return next(iter(items), None)


def audit_path(canonical):
    kind, identifier = canonical.split(":", 1)
    if kind == "arxiv" and re.fullmatch(r"\d{4}\.\d{4,5}v\d+", identifier):
        return AUDITS / f"arxiv_{identifier}.json"
    readable = kind + "_" + identifier.split("@")[0]
    prefix = re.sub(r"[^a-z0-9.-]+", "_", readable.lower())[:64]
    h = digest(canonical)
    path = AUDITS / f"{prefix}_{h[:16]}.json"
    legacy_prefix = re.sub(r"[^a-z0-9.-]+", "_", readable)[:64]
    legacy_path = AUDITS / f"{legacy_prefix}_{h[:16]}.json"
    if not path.exists() and legacy_path.exists():
        path = legacy_path
    if path.exists() and json.loads(path.read_text("utf8"))["canonical"] != canonical:
        path = AUDITS / f"{prefix}_{h}.json"
    return path


def persist(path, audit):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf8")
    temp.replace(path)


def inspect_pdf(path, text_evidence=None):
    fingerprint = sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as doc:
        first = doc[0].get_text()
    result = {"path": str(path.resolve()), "bytes": path.stat().st_size,
              "sha256": fingerprint, "first_page": first, "text_source": "pdf"}
    if not first.strip():
        record = text_evidence
        cached = AUDITS / ("pdf-text_" + fingerprint + ".json")
        if record is None and cached.is_file():
            record = json.loads(cached.read_text("utf8"))
        if record is None:
            raise Pending("PDF 首页未提取到文字；需要已目视复核且绑定 PDF 哈希的 OCR 证据")
        fields = ("source_pdf_sha256", "first_page_text", "method", "reviewed_at")
        if not isinstance(record, dict) or any(not isinstance(record.get(k), str) or not record[k].strip() for k in fields):
            raise Pending("OCR 证据需包含源 PDF 哈希、首页文本、提取方法和复核日期")
        if record["source_pdf_sha256"] != fingerprint:
            raise Pending("OCR 证据与当前 PDF 哈希不符")
        result.update(first_page=record["first_page_text"], text_source="reviewed_ocr",
                      text_evidence={k: record[k] for k in ("method", "reviewed_at")})
    return result


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
                or source.path.rstrip("/") not in {
                    "/html/" + version, "/pdf/" + version, "/pdf/" + version + ".pdf", "/abs/" + version
                }):
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
        self.environment_key = bool(self.key)
        self.credentials_checked = False
        self.once = False

    def call(self, method, path, **kwargs):
        result = self.http.request(method, BASE + path, timeout=kwargs.pop("timeout", 60),
                                   allow_redirects=False, **kwargs)
        result.raise_for_status()
        return result

    def items(self, suffix):
        # The local API returns all matches by default, unlike the Web API.
        return [row["data"] for row in self.call("GET", ITEMS + suffix).json()]

    def credential(self, operation, *values):
        try:
            backend = credential_backend()
            if backend:
                result = getattr(backend, operation)(AUTH_SERVICE, self.server, *values)
                return result if operation == "get_password" else True
        except CREDENTIAL_ERRORS:
            print("本机凭据存储不可用；本次授权仅保留在内存，后续可能再次询问。", flush=True)

    def authorize(self):
        if not self.key and not self.credentials_checked:
            self.credentials_checked = True
            self.key = self.credential("get_password")
        if not self.key:
            print("请在 Zotero 中选择“始终允许”，后续可复用本机授权。", flush=True)
            grant = self.call("POST", "/api/local/authorize", json={"appName": "embodied-paper-reader"}, timeout=240).json()
            self.key = grant["key"]
            self.once = not grant["remember"]
            if grant["remember"]:
                self.credential("set_password", self.key)

    def write(self, method, path, **kwargs):
        extra_headers = kwargs.pop("headers", {})
        for attempt in range(2):
            self.authorize()
            headers = {"Zotero-API-Key": self.key, **extra_headers}
            try:
                return self.call(method, path, headers=headers, **kwargs)
            except requests.HTTPError as error:
                if error.response.status_code != 401 or attempt or self.environment_key:
                    raise
                self.credential("delete_password")
                self.key = None
                self.once = False
            finally:
                if self.once:
                    self.key = None

    def create(self, fields):
        result = self.write("POST", ITEMS, json=[fields]).json()
        if result["failed"]:
            raise Pending("Zotero 拒绝创建" + fields["itemType"] + "，HTTP " + str(result["failed"]["0"]["code"]))
        return result["successful"]["0"]["key"]

    def file_path(self, key):
        try:
            url = self.call("GET", f"{ITEMS}/{key}/file/view/url").text.strip()
        except requests.HTTPError as exc:
            if exc.response.status_code == 404:
                return None
            raise
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
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    if heading:
        return heading.get_text(" ", strip=True)
    lines = (soup.body or soup).get_text("\n", strip=True).splitlines()
    return lines[0] if lines else ""


def note_body(html):
    # Zotero can wrap the submitted HTML in its own schema-version div.
    soup = BeautifulSoup(html, "html.parser")
    for wrapper in soup.select("div[data-schema-version]"):
        wrapper.unwrap()
    body = soup.body or soup
    return "".join(str(e) for e in body.contents if str(e).strip())


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
            elif paper["canonical"].startswith("arxiv:"):
                # An existing copy can have different bytes (e.g. embedded annotations).
                try:
                    pdf = inspect_pdf(path)
                    verify_source(paper, pdf)
                except (Pending, pymupdf.FileDataError):
                    if same_url:
                        raise Pending("已有附件与目标 PDF 版本或身份冲突，需要核对")
                    continue
                pdfs.append({"key": item["key"], **pdf})
            elif same_url:
                raise Pending("已有附件与目标 PDF 内容不一致，需要核对版本")
    found.update(note=unique(notes, "工作流导读"), pdf=unique(pdfs, "同版 PDF"))
    return found


def keys(state):
    return [state["parent"], *(state[k]["key"] if state[k] else None for k in ("pdf", "note"))]


def sync(client, paper, folder, audit, path, run):
    pdf_path = folder / paper["pdf"]
    evidence = json.loads((folder / paper["pdf_text_evidence"]).read_text("utf8")) if paper.get("pdf_text_evidence") else None
    source_pdf = inspect_pdf(pdf_path, evidence)
    verify_source(paper, source_pdf)
    if source_pdf["text_source"] == "reviewed_ocr":
        AUDITS.mkdir(parents=True, exist_ok=True)
        persist(AUDITS / ("pdf-text_" + source_pdf["sha256"] + ".json"), {
            "source_pdf_sha256": source_pdf["sha256"], "first_page_text": source_pdf["first_page"],
            **source_pdf["text_evidence"],
        })
    guide = note_body((folder / paper["note"]).read_text("utf8").strip())
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


def validate_manifest(paper):
    if not isinstance(paper, dict):
        raise Pending("清单必须是 JSON 对象")
    required = ["canonical", "version", "title", "short_title", "date", "authors",
                "aliases", "source", "pdf_url", "entry", "pdf", "note"]
    canonical = paper.get("canonical", "")
    if isinstance(canonical, str) and not canonical.startswith("arxiv:"):
        required.append("pdf_sha256")
    missing = [field for field in required if field not in paper]
    if missing:
        raise Pending("清单缺少：" + "、".join(missing))
    for field in required:
        if field not in {"authors", "aliases", "entry"}:
            if not isinstance(paper[field], str) or not paper[field].strip():
                raise Pending("清单 " + field + " 需为非空字符串")
    for field in ("authors", "aliases"):
        if not isinstance(paper[field], list) or not all(
            isinstance(value, str) and value.strip() for value in paper[field]
        ):
            raise Pending("清单 " + field + " 需为字符串列表")
    if not paper["authors"]:
        raise Pending("清单 authors 需包含至少一名作者")
    if not isinstance(paper["entry"], dict):
        raise Pending("清单 entry 需为对象")
    if not isinstance(paper["entry"].get("itemType"), str) or not paper["entry"]["itemType"].strip():
        raise Pending("清单 entry.itemType 需为非空字符串")
    if "pdf_text_evidence" in paper and (not isinstance(paper["pdf_text_evidence"], str) or not paper["pdf_text_evidence"].strip()):
        raise Pending("清单 pdf_text_evidence 需为非空字符串")


def error_summary(exc):
    if isinstance(exc, Pending):
        return str(exc)
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response.status_code == 401:
            return "Zotero 写入授权无效或已失效；重新授权，或更新 ZOTERO_LOCAL_API_KEY 后重跑"
        if response.status_code == 403:
            route = urlsplit(response.request.url).path if response.request else ""
            if route == "/api/local/authorize":
                return "Zotero 写入授权未获准；检查本机 API 设置和本地授权窗口的选择后重跑"
            if route == "/api/":
                return "Zotero 拒绝访问；在设置→高级启用“允许此计算机上的其他应用程序与 Zotero 通信”后重跑"
            return "Zotero 拒绝此操作（HTTP 403）；检查该操作的访问条件及本地审计后重跑"
        return f"Zotero HTTP {response.status_code}；详见本地审计"
    if isinstance(exc, requests.ConnectionError):
        if re.search(r"\b10013\b", str(exc)):
            return "执行环境拒绝本机连接（WinError 10013）；申请本机访问权限后重跑，再核实 Zotero 运行状态"
        return "无法连接 Zotero 本机 23119 端口；确认 Zotero 已启动，并检查本机访问权限后重跑"
    if isinstance(exc, requests.Timeout):
        return "Zotero 请求超时；检查本地授权窗口及连接状态后重跑"
    return type(exc).__name__


def main(manifest):
    paper = json.loads(manifest.read_text("utf8"))
    validate_manifest(paper)
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
            summary = error_summary(exc)
            if isinstance(exc, requests.HTTPError):
                run["response"] = exc.response.text
        persist(path, audit)
        print(run["time"], run["status"], summary, path.relative_to(ROOT).as_posix())
        return 0 if run["status"] == "通过" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--authorize", action="store_true", help="Authorize once and store reusable access in Windows credentials")
    parser.add_argument("--forget-authorization", action="store_true", help="Remove this Zotero instance's cached credential")
    try:
        args = parser.parse_args()
        if sum((bool(args.manifest), args.authorize, args.forget_authorization)) != 1:
            parser.error("提供一个清单，或选择 --authorize / --forget-authorization")
        if args.authorize:
            client = Zotero()
            client.authorize()
            print("本机授权已取得。" if not client.once else "本次仅单次授权；选择“始终允许”后才能跨进程复用。")
            raise SystemExit(0)
        if args.forget_authorization:
            cleared = Zotero().credential("delete_password")
            print("已清除当前 Zotero 实例的本机授权缓存。" if cleared else "没有清除缓存；请检查本机凭据存储。")
            raise SystemExit(0 if cleared else 1)
        raise SystemExit(main(args.manifest))
    except Pending as error:
        raise SystemExit("待验证：" + str(error))
    except Timeout:
        raise SystemExit("待验证：另一同步正在运行，完成后重试")
    except requests.RequestException as error:
        raise SystemExit("待验证：" + error_summary(error))
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit("待验证：清单或审计文件读写失败 (" + type(error).__name__ + ")")
