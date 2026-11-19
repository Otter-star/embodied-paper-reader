"""Look up local papers, report public metadata, and optionally copy a verified PDF."""

import argparse
from datetime import datetime, timezone
import json
import re
import shutil
from urllib.parse import quote

import requests

from zotero_sync import (
    AUDITS, ARXIV, ROOT, MARKER, TEXT_LAYER_PRIORITY, Pending, Zotero, digest, error_summary,
    identifiers, inspect_pdf, normalized, note_title, persist,
)


def known_versions(server):
    versions = {}
    for path in AUDITS.glob("*.json"):
        audit = json.loads(path.read_text("utf8"))
        if audit.get("server") != server:
            continue
        for run in audit.get("runs", []):
            if run.get("status") == "通过" and run.get("pdf"):
                versions[run["pdf"]["sha256"]] = {
                    "canonical": audit["canonical"], "record": path.relative_to(ROOT).as_posix(),
                }
    return versions


def lookup(client, query):
    versions = known_versions(client.server)
    papers, files = [], []
    raw = []
    requested = identifiers(query)
    if re.fullmatch(ARXIV + r"(?:v\d+)?", query, re.I):
        requested.add("arxiv:" + re.sub(r"v\d+$", "", query.lower()))
    # Zotero's default q search does not include identifier fields such as Extra.
    candidates = client.items("/top") if requested else client.items("/top?q=" + quote(query))
    for parent in candidates:
        if parent["itemType"] in {"attachment", "note", "annotation"}:
            continue
        if requested and not requested.intersection(identifiers("\n".join(
                parent.get(k, "") for k in ("DOI", "url", "extra", "archiveID")))):
            continue
        children = client.items("/" + parent["key"] + "/children")
        checks = []
        raw.append({"parent": parent, "children": children, "pdf_checks": checks})
        paper = {k: parent.get(k, "") for k in ("title", "date", "DOI", "url")}
        paper["authors"] = [a.get("name") or " ".join([a.get("firstName", ""), a.get("lastName", "")]).strip()
                            for a in parent.get("creators", []) if a["creatorType"] == "author"]
        notes = [child for child in children if child["itemType"] == "note"]
        paper["has_notes"] = bool(notes)
        paper["workflow_note_count"] = sum(note_title(note["note"]).startswith(MARKER) for note in notes)
        paper["pdfs"] = []
        for child in children:
            if child["itemType"] != "attachment" or child.get("contentType") != "application/pdf":
                continue
            path = client.file_path(child["key"])
            version = None
            basis = None
            check = {"key": child["key"], "source_url": child.get("url", ""),
                     "path": str(path) if path else None,
                     "file_available": bool(path and path.is_file())}
            if path and path.is_file():
                pdf = inspect_pdf(path, require_first_page=False)
                check.update(pdf)
                check["title_matches"] = normalized(parent["title"]) in normalized(pdf["first_page"])
                if check["title_matches"]:
                    previous = versions.get(pdf["sha256"])
                    if previous:
                        version = previous["canonical"]
                        basis = {"kind": "verified_sync_audit", "record": previous["record"]}
                    printed = set(re.findall(r"arXiv:\s*(" + ARXIV + r"v\d+)\b", pdf["first_page"], re.I))
                    if version is None and len(printed) == 1:
                        version = "arxiv:" + printed.pop()
                        basis = {"kind": "pdf_first_page_arxiv"}
                    if version:
                        files.append({"canonical": version, "parent": parent["key"], "path": path,
                                      "sha256": pdf["sha256"], "body_text": pdf["body_text"]})
            check.update(verified_version=version, version_evidence=basis)
            checks.append(check)
            paper["pdfs"].append({"source_url": child.get("url", ""), "verified_version": version,
                                  "file_available": check["file_available"], "body_text": check.get("body_text")})
        papers.append(paper)
    return papers, files, raw


def preferred_copy(files, version):
    matches = [f for f in files if f["canonical"] == version]
    if len({f["parent"] for f in matches}) == 1:
        best = max(TEXT_LAYER_PRIORITY[f["body_text"]["status"]] for f in matches)
        matches = [f for f in matches if TEXT_LAYER_PRIORITY[f["body_text"]["status"]] == best]
        if len(matches) == 1:
            return matches[0]
    raise Pending("待导出的版本未唯一匹配，需核对现有附件")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--export-version", help="Canonical identifier of a verified local PDF")
    args = parser.parse_args()
    AUDITS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    record = AUDITS / ("lookup_" + digest(args.query)[:16] + "_" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    audit = {"checked_at": now.isoformat(timespec="microseconds"), "query": args.query,
             "status": "待验证", "zotero_record_writes": 0}
    try:
        client = Zotero()
        papers, files, raw = lookup(client, args.query)
        audit.update(server=client.server, matches=raw, papers=papers)
        result = {"checked_at": audit["checked_at"], "zotero_record_writes": 0,
                  "papers": papers, "local_record": record.relative_to(ROOT).as_posix()}
        if args.export_version:
            selected = preferred_copy(files, args.export_version)
            folder = ROOT / "local" / "papers" / ("reuse_" + digest(args.export_version)[:16])
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / (selected["sha256"] + ".pdf")
            shutil.copyfile(selected["path"], destination)
            result["exported_pdf"] = destination.relative_to(ROOT).as_posix()
        audit["status"] = "通过"
        persist(record, audit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Pending, requests.RequestException, OSError, ValueError, KeyError, RuntimeError) as exc:
        audit["status"] = "待验证"
        audit["error"] = str(exc)
        persist(record, audit)
        print(audit["checked_at"], "待验证", error_summary(exc), record.relative_to(ROOT).as_posix())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
