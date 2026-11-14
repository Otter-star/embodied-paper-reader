"""Look up local papers, report public metadata, and optionally copy a verified PDF."""

import argparse
import json
import re
import shutil
from urllib.parse import quote

import requests

from zotero_sync import AUDITS, ARXIV, ROOT, Pending, Zotero, digest, inspect_pdf, normalized, persist


def known_versions(server):
    versions = {}
    for path in AUDITS.glob("*.json"):
        audit = json.loads(path.read_text("utf8"))
        if audit.get("server") != server:
            continue
        for run in audit.get("runs", []):
            if run.get("status") == "通过" and run.get("pdf"):
                versions[run["pdf"]["sha256"]] = audit["canonical"]
    return versions


def lookup(client, query):
    versions = known_versions(client.server)
    papers, files = [], []
    raw = []
    for parent in client.items("/top?q=" + quote(query)):
        if parent["itemType"] in {"attachment", "note", "annotation"}:
            continue
        children = client.items("/" + parent["key"] + "/children")
        raw.append({"parent": parent, "children": children})
        paper = {k: parent.get(k, "") for k in ("title", "date", "DOI", "url")}
        paper["authors"] = [a.get("name") or " ".join([a.get("firstName", ""), a.get("lastName", "")]).strip()
                            for a in parent.get("creators", []) if a["creatorType"] == "author"]
        paper["pdfs"] = []
        for child in children:
            if child["itemType"] != "attachment" or child.get("contentType") != "application/pdf":
                continue
            path = client.file_path(child["key"])
            version = None
            if path and path.is_file():
                pdf = inspect_pdf(path)
                if normalized(parent["title"]) in normalized(pdf["first_page"]):
                    version = versions.get(pdf["sha256"])
                    printed = set(re.findall(r"arXiv:\s*(" + ARXIV + r"v\d+)\b", pdf["first_page"], re.I))
                    if version is None and len(printed) == 1:
                        version = "arxiv:" + printed.pop()
                    if version:
                        files.append({"canonical": version, "path": path, "sha256": pdf["sha256"]})
            paper["pdfs"].append({"source_url": child.get("url", ""), "verified_version": version})
        papers.append(paper)
    return papers, files, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--export-version", help="Canonical identifier of a verified local PDF")
    args = parser.parse_args()
    AUDITS.mkdir(parents=True, exist_ok=True)
    record = AUDITS / ("lookup_" + digest(args.query)[:16] + ".json")
    try:
        client = Zotero()
        papers, files, raw = lookup(client, args.query)
        persist(record, {"query": args.query, "server": client.server, "matches": raw})
        result = {"papers": papers, "local_record": record.relative_to(ROOT).as_posix()}
        if args.export_version:
            matches = [f for f in files if f["canonical"] == args.export_version]
            if len(matches) != 1:
                raise Pending("待导出的版本未唯一匹配，需核对现有附件")
            selected = matches[0]
            folder = ROOT / "local" / "papers" / ("reuse_" + digest(args.export_version)[:16])
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / (selected["sha256"] + ".pdf")
            shutil.copyfile(selected["path"], destination)
            result["exported_pdf"] = destination.relative_to(ROOT).as_posix()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Pending, requests.RequestException, OSError, ValueError, KeyError, RuntimeError) as exc:
        persist(record, {"error": str(exc)})
        print("待验证", str(exc) if isinstance(exc, Pending) else type(exc).__name__,
              record.relative_to(ROOT).as_posix())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
