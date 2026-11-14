import copy
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf

from scripts import zotero_sync as sync


class PersonalLibrary:
    """Small in-memory substitute for the Desktop API. Files are real PDFs."""

    def __init__(self, folder):
        self.folder = folder
        self.rows = {}
        self.files = {}

    def items(self, suffix):
        if suffix == "/top":
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
