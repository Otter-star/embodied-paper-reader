import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
import requests

from scripts import zotero_sync as sync
with patch.dict(sys.modules, zotero_sync=sync):
    from scripts import zotero_lookup as lookup


class PersonalLibrary:
    """Small in-memory substitute for the Desktop API. Files are real PDFs."""

    def __init__(self, folder):
        self.folder = folder
        self.rows = {}
        self.files = {}

    def items(self, suffix):
        if suffix.split("?")[0] == "/top":
            return [r for r in self.rows.values() if "parentItem" not in r]
        parent = suffix.split("/")[1]
        return [r for r in self.rows.values() if r.get("parentItem") == parent]

    def create(self, fields):
        key = str(len(self.rows) + 1)
        self.rows[key] = dict(fields, key=key, version=1)
        return key

    def file_path(self, key):
        return self.files.get(key)

    def upload(self, key, path, expected_sha256):
        dest = self.folder / (key + ".pdf")
        dest.write_bytes(path.read_bytes())
        self.files[key] = dest

    def write(self, method, path, json):
        note = self.rows[path.rsplit("/", 1)[1]]
        assert method == "PATCH" and note["version"] == json["version"]
        note.update(note=json["note"], version=note["version"] + 1)


class SyncTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.library = PersonalLibrary(self.folder)
        self.paper = dict(canonical="arxiv:2406.00001v3", version="2406.00001v3", title="Test Paper",
                          short_title="Test", date="2024", authors=["A. Author"], aliases=["10.1234/test"],
                          source="https://arxiv.org/html/2406.00001v3", pdf_url="https://arxiv.org/pdf/2406.00001v3",
                          entry={"itemType": "preprint"}, pdf="paper.pdf", note="note.html")
        self.note = self.folder / "note.html"
        self.guide = "<h1>[embodied-paper-reader] 中文导读 · Test (2406.00001v3)</h1><p>初稿</p>"
        self.note.write_text(self.guide, "utf8")
        self.make_pdf("2406.00001v3")
        self.audit = {"runs": []}
        self.path = self.folder / "audit.json"

    def make_pdf(self, version):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((50, 50), "Test Paper\nA. Author\narXiv:" + version)
            doc.save(self.folder / "paper.pdf")

    def execute(self):
        run = {}
        self.audit["runs"].append(run)
        sync.sync(self.library, self.paper, self.folder, self.audit, self.path, run)
        return run

    def test_interrupt_then_retry_and_update(self):
        upload = self.library.upload
        self.library.upload = lambda *args: self.fail("simulated interruption")
        with self.assertRaisesRegex(AssertionError, "simulated interruption"):
            self.execute()
        self.assertEqual(json.loads(self.path.read_text("utf8"))["runs"][0]["before"], [None] * 3)
        self.library.upload = upload
        resumed = self.execute()
        self.assertEqual(resumed["before"][:2], resumed["after"][:2])
        self.assertEqual(self.execute()["delta"], [0, 0, 0])
        self.note.write_text(self.guide.replace("初稿", "全文"), "utf8")
        self.assertEqual(self.execute()["after"], resumed["after"])
        note = self.library.rows[self.audit["note_key"]]
        note["note"] += "<p>个人批注</p>"
        with self.assertRaisesRegex(sync.Pending, "人工修改"):
            self.execute()
        self.assertIn("个人批注", note["note"])

    def test_wrong_revision_writes_nothing(self):
        self.make_pdf("2406.00001v2")
        with self.assertRaisesRegex(sync.Pending, "版本"):
            self.execute()
        self.assertFalse(self.library.rows)

    def test_other_version_and_private_note(self):
        parent = self.library.create({"itemType": "conferencePaper", "title": "Test: paper!",
                                      "creators": [{"creatorType": "author", "lastName": "Author"}]})
        old = self.library.create(dict(itemType="attachment", contentType="application/pdf", parentItem=parent))
        self.make_pdf("2406.00001v2")
        self.library.upload(old, self.folder / "paper.pdf", None)
        private = self.library.create(dict(itemType="note", parentItem=parent, note="<p>个人笔记</p>"))
        original = copy.deepcopy(self.library.rows)
        self.make_pdf("2406.00001v3")
        self.assertEqual(self.execute()["delta"], [0, 1, 1])
        for key in [parent, old, private]:
            self.assertEqual(original[key], self.library.rows[key])

    def test_doi_filename(self):
        self.assertEqual(sync.audit_path("doi:10.1109/lra.2024.3350982@vor").name,
                         "doi_10.1109_lra.2024.3350982_b17a9ffde63a88ce.json")

    def test_uppercase_doi_filename_preserves_existing_audit(self):
        canonical = "doi:10.15607/RSS.2024.XX.090@vor"
        with patch.object(sync, "AUDITS", self.folder):
            expected = self.folder / ("doi_10.15607_rss.2024.xx.090_" + sync.digest(canonical)[:16] + ".json")
            self.assertEqual(sync.audit_path(canonical), expected)
            legacy = self.folder / ("doi_10.15607_.2024._.090_" + sync.digest(canonical)[:16] + ".json")
            sync.persist(legacy, {"canonical": canonical, "runs": []})
            self.assertEqual(sync.audit_path(canonical), legacy)

    def test_complete_html_uses_heading_and_imports_body(self):
        document = "<!doctype html><html><head><title>Page title</title></head><body>" + self.guide + "</body></html>"
        self.note.write_text(document, "utf8")
        self.assertEqual(sync.note_title(document), sync.note_title(self.guide))
        self.execute()
        stored = self.library.rows[self.audit["note_key"]]["note"]
        self.assertEqual(stored, self.guide)
        self.assertEqual(self.execute()["delta"], [0, 0, 0])

    def test_versioned_pdf_source_suffix(self):
        self.paper["source"] = "https://arxiv.org/pdf/2406.00001v3.pdf"
        self.assertEqual(self.execute()["delta"], [1, 1, 1])

    def test_same_url_annotated_pdf_reuses_attachment(self):
        initial = self.execute()
        pdf_path = self.library.files[initial["after"][1]]
        with pymupdf.open(pdf_path) as document:
            document.set_metadata({"subject": "Personal annotation"})
            document.saveIncr()
        changed_bytes = pdf_path.read_bytes()
        repeated = self.execute()
        self.assertEqual(repeated["delta"], [0, 0, 0])
        self.assertEqual(repeated["after"], initial["after"])
        self.assertEqual(pdf_path.read_bytes(), changed_bytes)

    def test_same_url_wrong_revision_is_preserved(self):
        initial = self.execute()
        pdf_path = self.library.files[initial["after"][1]]
        self.make_pdf("2406.00001v2")
        pdf_path.write_bytes((self.folder / "paper.pdf").read_bytes())
        self.make_pdf("2406.00001v3")
        original = copy.deepcopy(self.library.rows)
        with self.assertRaisesRegex(sync.Pending, "版本或身份冲突"):
            self.execute()
        self.assertEqual(original, self.library.rows)

    def test_missing_attachment_is_restored_in_place(self):
        initial = self.execute()
        self.library.files.pop(initial["after"][1])
        restored = self.execute()
        self.assertEqual(restored["after"], initial["after"])
        self.assertEqual(restored["delta"], [0, 0, 0])
        self.assertFalse(restored["pdf_file_present_before"])

    def test_parent_conflicts_and_ambiguity_write_nothing(self):
        parent = dict(itemType="conferencePaper", title="Test Paper",
                      creators=[{"creatorType": "author", "lastName": "Author"}])
        for fields in ({"extra": "arXiv:2406.99999"}, {"DOI": "10.9999/other"}):
            with self.subTest(fields=fields):
                self.library.rows.clear()
                self.library.create({**parent, **fields})
                original = copy.deepcopy(self.library.rows)
                with self.assertRaisesRegex(sync.Pending, "标识冲突"):
                    self.execute()
                self.assertEqual(original, self.library.rows)
        self.library.rows.clear()
        self.library.create(parent)
        self.library.create(parent)
        with self.assertRaisesRegex(sync.Pending, "多个匹配"):
            self.execute()

    def test_shared_strong_identifier_reuses_cross_publication_parent(self):
        parent = dict(itemType="conferencePaper", title="Test Paper",
                      creators=[{"creatorType": "author", "lastName": "Author"}])
        for fields in (
            {"extra": "arXiv:2406.00001", "DOI": "10.9999/journal"},
            {"extra": "arXiv:2406.99999", "DOI": "10.1234/test"},
        ):
            with self.subTest(fields=fields):
                self.library.rows.clear()
                key = self.library.create({**parent, **fields})
                result = self.execute()
                self.assertEqual(result["after"][0], key)
                self.assertEqual(result["delta"], [0, 1, 1])

    def test_exact_parent_is_unaffected_by_conflicting_title_candidate_order(self):
        base = dict(itemType="conferencePaper", title="Test Paper",
                    creators=[{"creatorType": "author", "lastName": "Author"}])
        exact = {**base, "key": "preprint", "extra": "arXiv:2406.00001"}
        other = {**base, "key": "journal", "DOI": "10.9999/journal"}
        for items in ([exact, other], [other, exact]):
            with self.subTest(first=items[0]["key"]):
                self.assertEqual(sync.match_parent(items, self.paper)["key"], "preprint")
        duplicate = {**exact, "key": "duplicate"}
        with self.assertRaisesRegex(sync.Pending, "多个匹配"):
            sync.match_parent([exact, duplicate], self.paper)

    def test_single_field_personal_author_matches_existing_parent(self):
        parent = self.library.create(dict(
            itemType="conferencePaper", title="Test Paper",
            creators=[{"creatorType": "author", "name": "A. Author", "fieldMode": 1}],
        ))
        result = self.execute()
        self.assertEqual(result["after"][0], parent)
        self.assertEqual(result["delta"], [0, 1, 1])

    def test_unicode_compatibility_forms_match_pdf_text(self):
        for title, extracted in (
            ("π₀ Flow Model", "π0 Flow Model"),
            ("Ｆｌｏｗ Model", "Flow Model"),
            ("A ﬁne policy", "A fine policy"),
        ):
            with self.subTest(title=title):
                paper = {**self.paper, "title": title}
                pdf = {"first_page": extracted + "\nA. Author\narXiv:2406.00001v3"}
                sync.verify_source(paper, pdf)

    def test_local_api_result_set_beyond_25_items_is_fully_matched(self):
        rows = [
            {"data": {"key": str(i), "itemType": "preprint", "title": "Other paper " + str(i)}}
            for i in range(29)
        ]
        rows.append({"data": {
            "key": "target", "itemType": "preprint", "title": "Test Paper",
            "extra": "arXiv:2406.00001",
        }})
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(rows).encode("utf8")
        client = object.__new__(sync.Zotero)
        with patch.object(client, "call", return_value=response):
            items = client.items("/top")
        self.assertEqual(len(items), 30)
        self.assertEqual(sync.match_parent(items, self.paper)["key"], "target")

    def test_note_hash_uses_actual_readback_and_requires_baseline(self):
        create = self.library.create

        def wrapped_create(fields):
            if fields["itemType"] == "note":
                fields = {**fields, "note": '<div data-schema-version="9">' + fields["note"] + "</div>"}
            return create(fields)

        with patch.object(self.library, "create", side_effect=wrapped_create):
            self.execute()
        stored = self.library.rows[self.audit["note_key"]]["note"]
        self.assertEqual(self.audit["last_written_note_sha256"], sync.digest(stored))
        self.assertNotEqual(sync.digest(stored), sync.digest(self.guide))
        self.note.write_text(self.guide.replace("初稿", "全文"), "utf8")
        self.execute()
        self.audit.pop("last_written_note_sha256")
        self.note.write_text(self.guide.replace("初稿", "再次更新"), "utf8")
        with self.assertRaisesRegex(sync.Pending, "缺少上次写入凭据"):
            self.execute()

    def test_missing_manifest_fields_fail_before_api_access(self):
        paper = {**self.paper, "canonical": "doi:10.1234/test@vor"}
        paper.pop("authors")
        manifest = self.folder / "paper.json"
        manifest.write_text(json.dumps(paper), "utf8")
        with patch.object(sync, "Zotero") as client:
            with self.assertRaisesRegex(sync.Pending, "authors、pdf_sha256"):
                sync.main(manifest)
            client.assert_not_called()

    def test_manifest_types_fail_before_api_access(self):
        invalid_fields = (
            ("authors", "A. Author"), ("authors", [""]),
            ("aliases", "10.1234/test"), ("aliases", [123]),
            ("entry", []), ("entry", {"itemType": None}),
            ("source", 123), ("canonical", None), ("title", ""),
        )
        manifest = self.folder / "invalid.json"
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                manifest.write_text(json.dumps({**self.paper, field: value}), "utf8")
                with patch.object(sync, "Zotero") as client:
                    with self.assertRaises(sync.Pending):
                        sync.main(manifest)
                    client.assert_not_called()

    def test_file_url_404_is_missing_other_http_errors_propagate(self):
        client = object.__new__(sync.Zotero)
        for status in (404, 403):
            response = requests.Response()
            response.status_code = status
            error = requests.HTTPError(response=response)
            with patch.object(client, "call", side_effect=error):
                if status == 404:
                    self.assertIsNone(client.file_path("test"))
                else:
                    with self.assertRaises(requests.HTTPError):
                        client.file_path("test")

    def test_actionable_error_summaries(self):
        for status, route, message in (
            (401, "/api/users/0/items", "写入授权无效"),
            (403, "/api/", "设置→高级"),
            (403, "/api/local/authorize", "写入授权未获准"),
            (403, "/api/users/0/items", "拒绝"),
        ):
            with self.subTest(status=status, route=route):
                response = requests.Response()
                response.status_code = status
                response.request = requests.Request("GET", sync.BASE + route).prepare()
                summary = sync.error_summary(requests.HTTPError(response=response))
                self.assertIn(message, summary)
                if status == 403 and route == "/api/users/0/items":
                    self.assertIn("审计", summary)
                    self.assertNotIn("设置→高级", summary)
        self.assertIn("23119", sync.error_summary(requests.ConnectionError("private details")))
        self.assertNotIn("private details", sync.error_summary(requests.ConnectionError("private details")))
        denied = sync.error_summary(requests.ConnectionError("[WinError 10013] private details"))
        self.assertIn("执行环境拒绝", denied)
        self.assertIn("申请本机访问权限", denied)
        self.assertNotIn("private details", denied)

    def test_lookup_reports_notes_and_missing_files_without_note_text(self):
        self.execute()
        self.library.create(dict(itemType="note", parentItem=self.audit["runs"][-1]["after"][0],
                                 note="<p>Personal reading text</p>"))
        self.library.server = "test"
        with patch.object(lookup, "known_versions", return_value={}):
            papers, _, _ = lookup.lookup(self.library, "Test")
            self.assertTrue(papers[0]["has_notes"])
            self.assertEqual(papers[0]["workflow_note_count"], 1)
            self.assertTrue(papers[0]["pdfs"][0]["file_available"])
            self.assertEqual(papers[0]["pdfs"][0]["verified_version"], self.paper["canonical"])
            self.assertNotIn("Personal reading text", json.dumps(papers))
            self.library.files.clear()
            papers, _, _ = lookup.lookup(self.library, "Test")
            self.assertFalse(papers[0]["pdfs"][0]["file_available"])
