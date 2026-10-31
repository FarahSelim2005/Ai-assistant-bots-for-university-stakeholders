"""Read, edit and save documents, one small handler per format.

A document is split into numbered text "parts": paragraphs (also in tables, headers and
footers), slide texts, spreadsheet cells, PDF text lines or text blocks. An edit is
{"op": "replace" | "insert_after" | "delete", "id": <part id>, "text": <new text>}. The
handlers change only those parts inside the original file, so everything else (fonts,
styles, tables, images, headers, numbering, page layout, formulas) stays as it was.
"""
import copy
import io
import re
import statistics
import zipfile
from dataclasses import dataclass, field

import pymupdf
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

EDITABLE_TYPES = {".docx", ".xlsx", ".pptx", ".pdf", ".txt", ".md"}
OFFICE_FOLDER = {".docx": "word/", ".xlsx": "xl/", ".pptx": "ppt/"}  # inside the zip file
MAX_SPREADSHEET_CELLS = 3000  # cells shown to the model; bigger sheets: the first ones

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"     # Word
A = "http://schemas.openxmlformats.org/drawingml/2006/main"            # PowerPoint text
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass
class Part:
    id: str
    text: str
    where: str = ""  # e.g. "table", "header", "slide 2", "page 1", "formula, kept"


@dataclass
class Report:
    applied: int = 0
    skipped: list[str] = field(default_factory=list)  # why some edits were not applied


# ---------------------------------------------------------------- checks

def check_file(filename: str, data: bytes, max_mb: float) -> str:
    """The file's extension if it is a supported, readable document of that type;
    otherwise a ValueError with a message for the user. The content is checked too,
    not only the name (a renamed .exe is refused)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in EDITABLE_TYPES:
        raise ValueError("This file type cannot be edited. Upload a .docx, .xlsx, .pptx, .pdf, .txt or .md file.")
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"The file is larger than {max_mb:g} MB.")
    if ext in OFFICE_FOLDER:
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # old binary Office format, also used when encrypted
            raise ValueError("This file is password-protected or in an old format (.doc, .xls, .ppt). "
                             "Remove the password or save it again as " + ext + ".")
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            raise ValueError(f"This is not a valid {ext} file. It may be damaged.")
        if "[Content_Types].xml" not in names or not any(n.startswith(OFFICE_FOLDER[ext]) for n in names):
            raise ValueError(f"This is not a valid {ext} file.")
    elif ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise ValueError("This is not a valid PDF file.")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass:
                    raise ValueError("This PDF is password-protected. Remove the password and upload it again.")
        except ValueError:
            raise
        except Exception:
            raise ValueError("This PDF could not be opened. It may be damaged.")
    else:
        if b"\x00" in data[:4096]:
            raise ValueError(f"This does not look like a text ({ext}) file.")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("This text file is not UTF-8. Save it again as UTF-8 and upload it.")
    return ext


def open_document(ext: str, data: bytes):
    """The handler for a checked file (see check_file)."""
    handlers = {".docx": DocxHandler, ".pptx": PptxHandler, ".xlsx": XlsxHandler,
                ".pdf": PdfHandler, ".txt": TextHandler, ".md": TextHandler}
    try:
        return handlers[ext](data)
    except ValueError:
        raise
    except Exception:
        raise ValueError(f"This {ext} file could not be read. It may be damaged.")


def plain_text(ext: str, data: bytes) -> str:
    """The text of a document, for answering questions about it in the normal chat."""
    handler = open_document(ext, data)
    lines = []
    for part in handler.parts():
        where = f"[{part.where}] " if part.where and ext in (".pptx", ".xlsx") else ""
        label = f"{part.id}: " if ext == ".xlsx" else ""
        lines.append(f"{where}{label}{part.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------- Word and PowerPoint

class XmlParagraphs:
    """Paragraph edits shared by Word (w:p, w:r, w:t) and PowerPoint (a:p, a:r, a:t).

    New text goes into the paragraph's first text element and the others are emptied:
    the paragraph keeps its style, list numbering and the first run's font; images and
    other non-text content of the paragraph stay where they are.
    """

    def __init__(self, ns: str, keep_one_in: set[str]):
        self.p, self.r, self.t = f"{{{ns}}}p", f"{{{ns}}}r", f"{{{ns}}}t"
        self.keep_one_in = keep_one_in  # containers that must keep one paragraph (cells, text boxes)
        self.paragraphs: dict[str, object] = {}  # part id -> paragraph element
        self.part_list: list[Part] = []

    def own_texts(self, p) -> list:
        """The paragraph's text elements, not those of paragraphs nested in it (text boxes)."""
        return [t for t in p.iter(self.t) if next(t.iterancestors(self.p), None) is p]

    def text(self, p) -> str:
        return "".join(t.text or "" for t in self.own_texts(p))

    def add(self, p, where: str) -> None:
        text = self.text(p)
        if text.strip():
            part_id = str(len(self.paragraphs) + 1)
            self.paragraphs[part_id] = p
            self.part_list.append(Part(part_id, text, where))

    def set_text(self, p, text: str) -> None:
        texts = self.own_texts(p)
        if not texts:  # e.g. a copied paragraph whose only run was a picture
            run = p.makeelement(self.r, {})
            run.append(p.makeelement(self.t, {}))
            p.append(run)
            texts = self.own_texts(p)
        texts[0].text = text
        if self.t.startswith(f"{{{W}}}"):
            texts[0].set(XML_SPACE, "preserve")  # keep spaces at the start or end (Word)
        for t in texts[1:]:
            t.text = ""

    def copy_after(self, p, text: str):
        """A new paragraph with the same style (and list numbering) right after `p`."""
        new = copy.deepcopy(p)
        for element in list(new.iter()):  # no copied pictures, text boxes or bookmarks
            name = element.tag.rsplit("}", 1)[-1]
            if name in ("drawing", "pict", "AlternateContent", "bookmarkStart", "bookmarkEnd"):
                element.getparent().remove(element)
        self.set_text(new, text)
        p.addnext(new)
        return new

    def apply(self, edits: list[dict]) -> Report:
        report = Report()
        for edit in edits:
            p = self.paragraphs.get(edit["id"])
            if p is None:
                report.skipped.append(f"Part {edit['id']} does not exist.")
                continue
            lines = edit.get("text", "").split("\n")
            if edit["op"] == "replace":
                self.set_text(p, lines[0])
                last = p
                for line in lines[1:]:  # a multi-line answer becomes several paragraphs
                    last = self.copy_after(last, line)
            elif edit["op"] == "insert_after":
                last = p
                for line in lines:
                    last = self.copy_after(last, line)
                self.paragraphs[edit["id"]] = last  # a second insert after the same part goes below
            elif edit["op"] == "delete":
                parent = p.getparent()
                siblings = [c for c in parent if c.tag == self.p]
                if parent.tag in self.keep_one_in and len(siblings) == 1:
                    self.set_text(p, "")  # a table cell or text box must keep one paragraph
                else:
                    parent.remove(p)
            report.applied += 1
        return report


class DocxHandler:
    kind, output_extension = "Word document", ".docx"

    def __init__(self, data: bytes):
        self.document = Document(io.BytesIO(data))
        self.xml = XmlParagraphs(W, {f"{{{W}}}tc", f"{{{W}}}txbxContent", f"{{{W}}}hdr", f"{{{W}}}ftr"})
        for p in self.document.element.body.iter(self.xml.p):  # in reading order, tables included
            in_table = next(p.iterancestors(f"{{{W}}}tbl"), None) is not None
            self.xml.add(p, "table" if in_table else "")
        seen = set()
        for section in self.document.sections:
            for where, part in (("header", section.header), ("footer", section.footer)):
                element = part._element
                if part.is_linked_to_previous or id(element) in seen:
                    continue
                seen.add(id(element))
                for p in element.iter(self.xml.p):
                    self.xml.add(p, where)

    def parts(self) -> list[Part]:
        return self.xml.part_list

    def apply(self, edits: list[dict]) -> Report:
        return self.xml.apply(edits)

    def save(self) -> bytes:
        out = io.BytesIO()
        self.document.save(out)
        return out.getvalue()


class PptxHandler:
    kind, output_extension = "PowerPoint presentation", ".pptx"

    def __init__(self, data: bytes):
        self.presentation = Presentation(io.BytesIO(data))
        self.xml = XmlParagraphs(A, {f"{{{A}}}txBody", "{http://schemas.openxmlformats.org/presentationml/2006/main}txBody"})
        for number, slide in enumerate(self.presentation.slides, 1):
            for p in slide.shapes._spTree.iter(self.xml.p):  # text boxes, placeholders, groups, tables
                self.xml.add(p, f"slide {number}")

    def parts(self) -> list[Part]:
        return self.xml.part_list

    def apply(self, edits: list[dict]) -> Report:
        return self.xml.apply(edits)

    def save(self) -> bytes:
        out = io.BytesIO()
        self.presentation.save(out)
        return out.getvalue()


# ---------------------------------------------------------------- Excel

CELL = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")


class XlsxHandler:
    """Cells are the parts ("Sheet1!B3"). Text and number cells can be changed or
    emptied, and empty cells filled; formulas are shown but never changed. Rows and
    columns are not inserted."""
    kind, output_extension = "Excel workbook", ".xlsx"

    def __init__(self, data: bytes):
        self.workbook = load_workbook(io.BytesIO(data))  # formulas stay formulas ("=SUM(...)")
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        # openpyxl cannot keep charts and pictures of an existing workbook.
        self.has_drawings = any(n.startswith(("xl/drawings/", "xl/charts/", "xl/media/")) for n in names)

    def parts(self) -> list[Part]:
        parts = []
        for sheet in self.workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is None or len(parts) >= MAX_SPREADSHEET_CELLS:
                        continue
                    formula = isinstance(cell.value, str) and cell.value.startswith("=")
                    parts.append(Part(f"{sheet.title}!{cell.coordinate}", str(cell.value),
                                      "formula, kept" if formula else sheet.title))
        return parts

    def apply(self, edits: list[dict]) -> Report:
        report = Report()
        if self.has_drawings:
            report.skipped.append("Charts and pictures in this workbook are not kept in the edited file.")
        for edit in edits:
            sheet_name, _, coordinate = edit["id"].rpartition("!")
            if sheet_name not in self.workbook.sheetnames or not CELL.match(coordinate):
                report.skipped.append(f"{edit['id']} is not a cell of this workbook.")
                continue
            if edit["op"] == "insert_after":
                report.skipped.append("New rows or columns cannot be inserted; ask to fill specific cells instead.")
                continue
            cell = self.workbook[sheet_name][coordinate]
            if isinstance(cell.value, str) and cell.value.startswith("="):
                report.skipped.append(f"{edit['id']} has a formula, which was kept.")
                continue
            try:
                cell.value = None if edit["op"] == "delete" else cell_value(edit.get("text", ""), cell.value)
            except AttributeError:  # a merged cell other than its top-left one
                report.skipped.append(f"{edit['id']} is part of merged cells and cannot be changed alone.")
                continue
            report.applied += 1
        return report

    def save(self) -> bytes:
        out = io.BytesIO()
        self.workbook.save(out)
        return out.getvalue()


def cell_value(text: str, old):
    """Numbers stay numbers: "1,250" -> 1250 for a number cell or an empty cell."""
    if old is None or isinstance(old, (int, float)):
        number = text.replace(",", "").strip()
        if re.fullmatch(r"-?\d+", number):
            return int(number)
        if re.fullmatch(r"-?\d*\.\d+", number):
            return float(number)
    return text


# ---------------------------------------------------------------- PDF

class PdfHandler:
    """PDF text lines are the parts. A changed line is removed (redacted) and the new
    text is written in the same place, size and colour, in a standard font (Helvetica).
    New lines cannot be inserted into a PDF, and Arabic cannot be written into it: for
    those, the PDF should be converted to Word first (see pdf_to_docx)."""
    kind, output_extension = "PDF", ".pdf"

    def __init__(self, data: bytes):
        self.pdf = pymupdf.open(stream=data, filetype="pdf")
        if self.pdf.needs_pass:
            raise ValueError("This PDF is password-protected. Remove the password and upload it again.")
        self.lines: dict[str, tuple] = {}  # id -> (page number, rectangle, size, colour, bold, text)
        for number, page in enumerate(self.pdf):
            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"])
                    if not text.strip():
                        continue
                    span = max(line["spans"], key=lambda s: len(s["text"]))
                    self.lines[str(len(self.lines) + 1)] = (
                        number, pymupdf.Rect(line["bbox"]), span["size"], span["color"], bool(span["flags"] & 16), text)

    def parts(self) -> list[Part]:
        return [Part(i, line[5], f"page {line[0] + 1}") for i, line in self.lines.items()]

    def apply(self, edits: list[dict]) -> Report:
        report = Report()
        writes: dict[int, list] = {}
        for edit in edits:
            line = self.lines.get(edit["id"])
            if line is None:
                report.skipped.append(f"Part {edit['id']} does not exist.")
                continue
            if edit["op"] == "insert_after":
                report.skipped.append("New lines cannot be added inside a PDF. Ask to convert it to Word to add text.")
                continue
            text = edit.get("text", "") if edit["op"] == "replace" else ""
            if any(ord(ch) > 0x24F for ch in text):
                report.skipped.append("Arabic or other non-Latin text cannot be written into a PDF here. "
                                      "Ask to convert it to Word instead.")
                continue
            page_number, rect, size, colour, bold, _ = line
            self.pdf[page_number].add_redact_annot(rect)
            writes.setdefault(page_number, []).append((rect, size, colour, bold, text))
            report.applied += 1
        for page_number, items in writes.items():
            page = self.pdf[page_number]
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)  # keep pictures and lines
            for rect, size, colour, bold, text in items:
                if text:
                    write_in_box(page, rect, text, size, colour, bold)
        return report

    def save(self) -> bytes:
        return self.pdf.tobytes(garbage=3, deflate=True)


def write_in_box(page, rect, text: str, size: float, colour: int, bold: bool) -> None:
    """Write text into a line's box; a longer text gets a smaller font, then more height."""
    rgb = tuple(((colour >> shift) & 255) / 255 for shift in (16, 8, 0))
    font = "hebo" if bold else "helv"
    box = pymupdf.Rect(rect.x0, rect.y0 - 1, max(rect.x1, rect.x0 + 20), rect.y1 + 2)
    for factor in (1.0, 0.9, 0.8, 0.7, 0.6):
        if page.insert_textbox(box, text, fontsize=size * factor, fontname=font, color=rgb) >= 0:
            return
    page.insert_textbox(pymupdf.Rect(box.x0, box.y0, box.x1, box.y1 + size * 4), text,
                        fontsize=size * 0.6, fontname=font, color=rgb)


def pdf_to_docx(data: bytes) -> bytes:
    """An editable Word version of a text PDF: one paragraph per line, in reading order
    (two-column pages column by column), larger lines as headings, a page break between
    pages. Layout, fonts and pictures are not kept."""
    from app.attachments import page_text  # reading order for two-column pages

    document = Document()
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        sizes = [span["size"] for page in pdf for block in page.get_text("dict")["blocks"] if block["type"] == 0
                 for line in block["lines"] for span in line["spans"] if span["text"].strip()]
        normal = statistics.median(sizes) if sizes else 11
        line_sizes = {}
        for page in pdf:
            for block in page.get_text("dict")["blocks"]:
                if block["type"] == 0:
                    for line in block["lines"]:
                        text = "".join(span["text"] for span in line["spans"]).strip()
                        line_sizes.setdefault(text, max(span["size"] for span in line["spans"]))
        for number, page in enumerate(pdf):
            if number:
                document.add_page_break()
            for text in page_text(page).split("\n"):
                text = text.strip()
                if not text:
                    continue
                if line_sizes.get(text, normal) >= normal * 1.3 and len(text) < 120:
                    document.add_heading(text, level=2)
                else:
                    document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def text_to_docx(text: str) -> bytes:
    """A Word document from plain text (e.g. a scanned PDF read by the vision model):
    "# Title" and short ALL-CAPS lines become headings, "- item" lines bullets."""
    document = Document()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            document.add_heading(line.lstrip("#").strip(), level=min(line.count("#", 0, 3), 3) or 1)
        elif line.startswith(("- ", "* ", "• ")):
            document.add_paragraph(line[2:].strip(), style="List Bullet")
        elif line.isupper() and len(line) < 60:
            document.add_heading(line, level=2)
        else:
            document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- .txt and .md

class TextHandler:
    """Blocks separated by blank lines are the parts (a Markdown heading with its text,
    a list, a paragraph); edited blocks are put back between the unchanged ones."""
    kind, output_extension = "text file", None  # keeps .txt or .md

    def __init__(self, data: bytes):
        text = data.decode("utf-8-sig")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        blocks = [b.strip("\n") for b in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))]
        self.blocks = {str(i): b for i, b in enumerate((b for b in blocks if b.strip()), 1)}
        self.order = list(self.blocks)
        self.after: dict[str, list[str]] = {}

    def parts(self) -> list[Part]:
        return [Part(i, self.blocks[i]) for i in self.order]

    def apply(self, edits: list[dict]) -> Report:
        report = Report()
        for edit in edits:
            if edit["id"] not in self.blocks:
                report.skipped.append(f"Part {edit['id']} does not exist.")
                continue
            if edit["op"] == "replace":
                self.blocks[edit["id"]] = edit.get("text", "")
            elif edit["op"] == "insert_after":
                self.after.setdefault(edit["id"], []).append(edit.get("text", ""))
            elif edit["op"] == "delete":
                self.blocks[edit["id"]] = None
            report.applied += 1
        return report

    def save(self) -> bytes:
        out = []
        for i in self.order:
            if self.blocks[i] is not None:
                out.append(self.blocks[i])
            out += self.after.get(i, [])
        return ("\n\n".join(b for b in out if b.strip()) + "\n").replace("\n", self.newline).encode("utf-8")
