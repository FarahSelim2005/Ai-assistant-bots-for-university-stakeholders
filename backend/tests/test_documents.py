"""Tests for the document editor (app/documents). No model, network or database is used:
the model is replaced by a stand-in that returns fixed JSON edits.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import base64
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pymupdf
from docx import Document
from docx.shared import Pt
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from pptx import Presentation
from pptx.util import Inches

from app import config
from app.attachments import make_png
from app.documents import editor, formats, storage


# ------------------------------------------------------------ sample files

def sample_docx() -> bytes:
    """Heading, a bold run, a bullet list, a table, a picture and a header."""
    document = Document()
    document.sections[0].header.paragraphs[0].text = "GIU Report Header"
    document.add_heading("Annual Report", level=1)
    p = document.add_paragraph()
    run = p.add_run("This is teh first paragrph.")
    run.bold = True
    run.font.size = Pt(14)
    document.add_paragraph("First point", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Name", "Grade"
    table.cell(1, 0).text, table.cell(1, 1).text = "Sara", "1.7"
    picture = io.BytesIO(make_png(8, 8, 3, bytes([200, 0, 0] * 64)))
    document.add_picture(picture)
    document.add_paragraph("Last paragraph.")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def sample_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget"
    sheet["A1"], sheet["B1"] = "Item", "Cost"
    sheet["A2"], sheet["B2"] = "Laptop", 1000
    sheet["A3"], sheet["B3"] = "Mouse", 25
    sheet["A4"], sheet["B4"] = "Total", "=SUM(B2:B3)"
    sheet["A1"].font = Font(bold=True)
    workbook.create_sheet("Notes")["A1"] = "Approved by the dean"
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def sample_pptx() -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])  # title and content
    slide.shapes.title.text = "Project Plan"
    slide.placeholders[1].text_frame.text = "Collect the data"
    slide.placeholders[1].text_frame.add_paragraph().text = "Train the modle"
    picture = io.BytesIO(make_png(8, 8, 3, bytes([0, 0, 200] * 64)))
    slide.shapes.add_picture(picture, Inches(1), Inches(5))
    out = io.BytesIO()
    presentation.save(out)
    return out.getvalue()


def sample_pdf(text_lines=("Internship Report", "The studnet worked on data analysis.", "Supervisor: Dr. Ali")) -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate(text_lines):
        page.insert_text((72, 100 + i * 30), line, fontsize=14 if i == 0 else 11)
    return pdf.tobytes()


def scanned_pdf() -> bytes:
    """A PDF whose page is only a picture (like a scan)."""
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_image(page.rect, stream=make_png(20, 20, 3, bytes([240] * 1200)))
    return pdf.tobytes()


def fake_model(edits_by_text: dict, summary="Fixed it."):
    """A stand-in for chat_with_backup: edits the parts whose text contains a key."""
    calls = []

    def answer(messages, models, max_tokens=400, rounds=2, full_prompt=False):
        calls.append(messages)
        lines = messages[1]["content"].split("PARTS", 1)[1].splitlines()[1:]
        edits = []
        for line in lines:
            part_id = line[1:line.index("]")]
            for key, edit in edits_by_text.items():
                if key in line:
                    edits.append({"id": part_id, **edit})
        return "Here you go:\n```json\n" + json.dumps({"summary": summary, "edits": edits}) + "\n```"

    answer.calls = calls
    return answer


# ------------------------------------------------------------ checks of uploads

class UploadChecks(unittest.TestCase):
    def test_supported_files_pass(self):
        for name, data in [("a.docx", sample_docx()), ("a.xlsx", sample_xlsx()), ("a.pptx", sample_pptx()),
                           ("a.pdf", sample_pdf()), ("a.txt", b"hello"), ("a.md", "# Title\n\nمرحبا".encode())]:
            self.assertEqual(formats.check_file(name, data, 10), "." + name.split(".")[1])

    def test_unsupported_extension(self):
        with self.assertRaisesRegex(ValueError, "cannot be edited"):
            formats.check_file("virus.exe", b"MZ...", 10)

    def test_wrong_content_for_extension(self):
        with self.assertRaisesRegex(ValueError, "not a valid .docx"):
            formats.check_file("report.docx", b"just text", 10)
        with self.assertRaisesRegex(ValueError, "not a valid PDF"):
            formats.check_file("report.pdf", sample_docx(), 10)
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("readme.txt", "not office")
        with self.assertRaisesRegex(ValueError, "not a valid .xlsx"):
            formats.check_file("sheet.xlsx", zipped.getvalue(), 10)

    def test_too_large_and_empty(self):
        with self.assertRaisesRegex(ValueError, "larger than 1 MB"):
            formats.check_file("big.txt", b"a" * (1024 * 1024 + 1), 1)
        with self.assertRaisesRegex(ValueError, "empty"):
            formats.check_file("empty.txt", b"", 10)

    def test_password_protected(self):
        pdf = pymupdf.open()
        pdf.new_page().insert_text((72, 72), "secret")
        locked = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
        with self.assertRaisesRegex(ValueError, "password-protected"):
            formats.check_file("locked.pdf", locked, 10)
        with self.assertRaisesRegex(ValueError, "password-protected or in an old format"):
            formats.check_file("locked.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, 10)

    def test_binary_or_non_utf8_text(self):
        with self.assertRaisesRegex(ValueError, "text"):
            formats.check_file("notes.txt", b"\x00\x01\x02binary", 10)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            formats.check_file("notes.txt", "café".encode("latin-1"), 10)


# ------------------------------------------------------------ editing each format

class EditFormats(unittest.TestCase):
    def edit(self, data, ext, instruction, edits_by_text):
        model = fake_model(edits_by_text)
        with mock.patch.object(editor, "chat_with_backup", model):
            return editor.edit_document(data, ext, instruction, ["fake"], ["fake-vision"]), model

    def test_docx_targeted_edit_keeps_formatting(self):
        result, _ = self.edit(sample_docx(), ".docx", "Correct the spelling", {
            "teh first": {"op": "replace", "text": "This is the first paragraph."},
            "Sara": {"op": "replace", "text": "Sara Ahmed"},
            "Last paragraph": {"op": "insert_after", "text": "A new closing line."},
            "First point": {"op": "delete"},
        })
        document = Document(io.BytesIO(result.data))
        texts = [p.text for p in document.paragraphs]
        self.assertIn("This is the first paragraph.", texts)
        self.assertNotIn("First point", texts)
        self.assertEqual(texts[texts.index("Last paragraph.") + 1], "A new closing line.")
        run = next(p for p in document.paragraphs if p.text.startswith("This is the first")).runs[0]
        self.assertTrue(run.bold)                                   # run formatting kept
        self.assertEqual(run.font.size, Pt(14))
        self.assertEqual(document.tables[0].cell(1, 0).text, "Sara Ahmed")  # table kept and edited
        self.assertEqual(document.tables[0].cell(0, 1).text, "Grade")
        self.assertEqual(len(document.inline_shapes), 1)            # picture kept
        self.assertEqual(document.sections[0].header.paragraphs[0].text, "GIU Report Header")
        self.assertEqual(result.extension, ".docx")
        self.assertEqual(result.changes[0]["after"], "This is the first paragraph.")

    def test_docx_header_and_multiline_replace(self):
        result, _ = self.edit(sample_docx(), ".docx", "Change the header", {
            "GIU Report Header": {"op": "replace", "text": "GIU Annual Report 2025"},
            "Annual Report": {"op": "replace", "text": "Annual Report\nFaculty of Engineering"},
        })
        document = Document(io.BytesIO(result.data))
        self.assertEqual(document.sections[0].header.paragraphs[0].text, "GIU Annual Report 2025")
        texts = [p.text for p in document.paragraphs]
        self.assertEqual(texts[texts.index("Annual Report") + 1], "Faculty of Engineering")

    def test_xlsx_keeps_formulas_sheets_and_styles(self):
        result, _ = self.edit(sample_xlsx(), ".xlsx", "Translate items and change the mouse price to 30", {
            "Budget!A2": {"op": "replace", "text": "لابتوب"},
            "Budget!B3": {"op": "replace", "text": "30"},
            "=SUM": {"op": "replace", "text": "55"},           # a formula: must be refused
        })
        workbook = load_workbook(io.BytesIO(result.data))
        sheet = workbook["Budget"]
        self.assertEqual(sheet["A2"].value, "لابتوب")
        self.assertEqual(sheet["B3"].value, 30)                     # stays a number
        self.assertEqual(sheet["B4"].value, "=SUM(B2:B3)")          # formula kept
        self.assertTrue(sheet["A1"].font.bold)                      # style kept
        self.assertEqual(workbook.sheetnames, ["Budget", "Notes"])
        self.assertTrue(any("formula" in note for note in result.notes))

    def test_xlsx_fill_empty_cell(self):
        handler = formats.XlsxHandler(sample_xlsx())
        report = handler.apply(editor.valid_edits([{"op": "replace", "id": "Budget!C2", "text": "new"}], set(), True))
        self.assertEqual(report.applied, 1)
        self.assertEqual(load_workbook(io.BytesIO(handler.save()))["Budget"]["C2"].value, "new")

    def test_pptx_keeps_layout_and_pictures(self):
        result, _ = self.edit(sample_pptx(), ".pptx", "Fix the typo and add a step", {
            "modle": {"op": "replace", "text": "Train the model"},
            "Collect the data": {"op": "insert_after", "text": "Clean the data"},
        })
        slide = Presentation(io.BytesIO(result.data)).slides[0]
        body = [p.text for p in slide.placeholders[1].text_frame.paragraphs]
        self.assertEqual(body, ["Collect the data", "Clean the data", "Train the model"])
        self.assertEqual(slide.shapes.title.text, "Project Plan")
        self.assertEqual(sum(1 for s in slide.shapes if s.shape_type == 13), 1)  # 13 = picture

    def test_pdf_in_place_replace(self):
        result, _ = self.edit(sample_pdf(), ".pdf", "Fix the spelling", {
            "studnet": {"op": "replace", "text": "The student worked on data analysis."},
        })
        self.assertEqual(result.extension, ".pdf")
        text = pymupdf.open(stream=result.data, filetype="pdf")[0].get_text()
        self.assertIn("The student worked on data analysis.", text)
        self.assertNotIn("studnet", text)
        self.assertIn("Supervisor: Dr. Ali", text)                 # other lines untouched

    def test_pdf_insert_and_arabic_need_word(self):
        result, _ = self.edit(sample_pdf(), ".pdf", "Add a line and translate the title", {
            "Supervisor": {"op": "insert_after", "text": "Date: May 2025"},
            "Internship Report": {"op": "replace", "text": "تقرير التدريب"},
        })
        self.assertTrue(any("convert it to Word" in note for note in result.notes))
        self.assertIn("Internship Report", pymupdf.open(stream=result.data, filetype="pdf")[0].get_text())

    def test_pdf_convert_to_word_without_model(self):
        result, model = self.edit(sample_pdf(), ".pdf", "Convert this PDF to Word", {})
        self.assertEqual(result.extension, ".docx")
        self.assertEqual(model.calls, [])                            # no model needed for a conversion
        texts = [p.text for p in Document(io.BytesIO(result.data)).paragraphs]
        self.assertIn("The studnet worked on data analysis.", texts)

    def test_pdf_convert_and_edit(self):
        result, model = self.edit(sample_pdf(), ".pdf", "Convert to Word and fix the spelling", {
            "studnet": {"op": "replace", "text": "The student worked on data analysis."},
        })
        self.assertEqual(result.extension, ".docx")
        self.assertIn("The student worked on data analysis.", [p.text for p in Document(io.BytesIO(result.data)).paragraphs])

    def test_scanned_pdf_is_read_by_the_vision_model(self):
        def vision_then_edit(messages, models, max_tokens=400, rounds=2, full_prompt=False):
            if models == ["fake-vision"]:
                return "# Certificate\nAwarded to Omar Hassan"
            return json.dumps({"summary": "ok", "edits": []})
        with mock.patch.object(editor, "chat_with_backup", vision_then_edit):
            result = editor.edit_document(scanned_pdf(), ".pdf", "Correct the grammar", ["fake"], ["fake-vision"])
        self.assertEqual(result.extension, ".docx")
        self.assertIn("Awarded to Omar Hassan", [p.text for p in Document(io.BytesIO(result.data)).paragraphs])
        self.assertTrue(any("scanned" in note for note in result.notes))

    def test_markdown_and_text(self):
        md = "# Notes\n\nFirst paragrph.\n\n- item one\n- item two\n".encode()
        result, _ = self.edit(md, ".md", "fix spelling, add a section", {
            "paragrph": {"op": "replace", "text": "First paragraph."},
            "item one": {"op": "insert_after", "text": "## Summary\nAll done."},
        })
        self.assertEqual(result.data.decode(), "# Notes\n\nFirst paragraph.\n\n- item one\n- item two\n\n## Summary\nAll done.\n")
        result, _ = self.edit("line one\r\n\r\nline two\r\n".encode(), ".txt", "delete line two", {"line two": {"op": "delete"}})
        self.assertEqual(result.data, b"line one\r\n")

    def test_bad_model_answers_are_ignored(self):
        edits = editor.valid_edits([{"op": "run", "id": "1"}, {"op": "replace", "id": "999", "text": "x"},
                                    {"op": "replace", "id": "../etc/passwd", "text": "x"}, "text",
                                    {"op": "replace", "id": "2", "text": "ok"}], {"1", "2"}, spreadsheet=False)
        self.assertEqual(edits, [{"op": "replace", "id": "2", "text": "ok"}])
        self.assertIsNone(editor.parse_json("no json here"))

    def test_model_retried_once_when_not_json(self):
        replies = iter(["Sorry, here it is", json.dumps({"summary": "ok", "edits": []})])
        with mock.patch.object(editor, "chat_with_backup", lambda *a, **k: next(replies)):
            result = editor.edit_document(b"hello world", ".txt", "fix it", ["fake"], [])
        self.assertEqual(result.data, b"hello world\n")

    def test_model_asked_again_when_its_ids_are_wrong(self):
        replies = iter([json.dumps({"summary": "Fixed", "edits": [{"op": "replace", "id": "[1]", "text": "x"}]}),
                        json.dumps({"summary": "Fixed", "edits": [{"op": "replace", "id": "1", "text": "hello there"}]})])
        with mock.patch.object(editor, "chat_with_backup", lambda *a, **k: next(replies)):
            result = editor.edit_document(b"hello wrld", ".txt", "fix it", ["fake"], [])
        self.assertEqual(result.data, b"hello there\n")

    def test_no_false_success_when_nothing_changed(self):
        reply = json.dumps({"summary": "I fixed everything", "edits": [{"op": "replace", "id": "99", "text": "x"}]})
        with mock.patch.object(editor, "chat_with_backup", lambda *a, **k: reply):
            result = editor.edit_document(b"hello", ".txt", "fix it", ["fake"], [])
        self.assertIn("did not change anything", result.summary)

    def test_long_documents_are_sent_in_batches(self):
        text = "\n\n".join(f"Paragraph {i} " + "word " * 200 for i in range(20)).encode()
        result, model = self.edit(text, ".txt", "shorten", {})
        self.assertGreater(len(model.calls), 1)
        self.assertIn("part 1 of", model.calls[0][1]["content"])


# ------------------------------------------------------------ storage

class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "EDITS_DIR", Path(self.tmp.name) / "edits")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_versions_tokens_and_downloads(self):
        first = storage.save_version(7, b"v0", ".docx", filename="../../My Report.docx")
        self.assertEqual(first["filename"], "My Report.docx")       # no folders from the user's name
        second = storage.save_version(7, b"v1", ".docx")
        self.assertRegex(second["token"], r"^[0-9a-f]{32}$")
        self.assertEqual(second["version"], 1)
        self.assertEqual(storage.latest_file(7), (b"v1", ".docx"))
        path, name, _ = storage.file_for_download(7, second["token"])
        self.assertEqual((path.read_bytes(), name), (b"v1", "My Report_edited.docx"))
        self.assertTrue(storage.is_latest(7, second["token"]))
        self.assertFalse(storage.is_latest(7, first["token"]))

    def test_no_access_with_wrong_token_or_conversation(self):
        saved = storage.save_version(7, b"secret", ".pdf", filename="cv.pdf")
        for conversation, token in [(8, saved["token"]), (7, "0" * 32), (7, "../info.json"), (7, "..%2Finfo")]:
            self.assertIsNone(storage.file_for_download(conversation, token))
        self.assertFalse(storage.is_latest(8, saved["token"]))

    def test_new_upload_replaces_old_files_and_old_files_are_removed(self):
        storage.save_version(9, b"a", ".txt", filename="a.txt")
        storage.save_version(9, b"b", ".md", filename="b.md")
        self.assertEqual(len(list(storage.folder(9).glob("*.txt"))), 0)
        old = time.time() - (config.DOC_EDIT_KEEP_MINUTES + 1) * 60
        os.utime(storage.folder(9) / "info.json", (old, old))
        storage.remove_old_files()
        self.assertFalse(storage.folder(9).exists())

    def test_only_a_few_versions_are_kept(self):
        storage.save_version(5, b"0", ".txt", filename="a.txt")
        for i in range(8):
            storage.save_version(5, str(i).encode(), ".txt")
        self.assertEqual(len(list(storage.folder(5).glob("*.txt"))), storage.KEEP_VERSIONS)


class ChatReadsOfficeFiles(unittest.TestCase):
    def test_normal_chat_attachments_read_office_text(self):
        from app.attachments import read_attachment
        for name, data, expected in [("r.docx", sample_docx(), "Annual Report"), ("b.xlsx", sample_xlsx(), "Laptop"),
                                     ("p.pptx", sample_pptx(), "Project Plan")]:
            attachment = read_attachment(name, base64.b64encode(data).decode())
            self.assertIn(expected, attachment.text)


if __name__ == "__main__":
    unittest.main()
