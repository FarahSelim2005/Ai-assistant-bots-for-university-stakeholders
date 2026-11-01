"""Turn the CV model's restructured CV (plain text in a GIU template) into files: a PDF to
view and download, and a Word version the student can still change.

The answer looks like: "Template: Student", the name, contact lines, then sections with
headings in capitals (SUMMARY, EDUCATION ...), "- " bullets, and at the end the notes
"What I changed:" (not part of the CV, so left out of the files).
"""
import html
import io
import re

import pymupdf
from docx import Document
from docx.shared import Pt

NOTES_HEADINGS = ("What I changed:", "ما غيرته:")
HEADING = re.compile(r"^[A-Z][A-Z &/]{2,34}$")        # SUMMARY, WORK EXPERIENCE, SKILLS
LABEL_LINE = re.compile(r"^([A-Z][A-Z &/]{1,30}):\s*(.+)$")  # "TOOLS: Excel, SQL" (London template)


def is_restructured_cv(answer: str) -> bool:
    """True if the answer is a rewritten CV (and not, e.g., an error or a review)."""
    return answer.lstrip().startswith("Template:") or len(cv_lines(answer)[1]) >= 2


def cv_lines(answer: str) -> tuple[list[str], list[str]]:
    """(the CV's lines without the template line and the notes, the section headings)."""
    cut = min((answer.find(h) for h in NOTES_HEADINGS if h in answer), default=len(answer))
    lines = [line.rstrip() for line in answer[:cut].strip().splitlines()]
    if lines and lines[0].startswith("Template:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    headings = [line for line in lines if HEADING.match(line.strip())]
    return lines, headings


def blocks(answer: str) -> list[tuple[str, str]]:
    """The CV as (kind, text): name, contact, heading, entry, bullet, label, text."""
    lines, _ = cv_lines(answer)
    result, top = [], True  # the name and contact lines come before the first heading
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not result:  # the first line is the name, even in capitals ("FARAH SELIM")
            result.append(("name", line))
        elif HEADING.match(line):
            top = False
            result.append(("heading", line))
        elif top:
            result.append(("contact", line))
        elif line.startswith(("- ", "• ", "* ")):
            result.append(("bullet", line[2:].strip()))
        elif LABEL_LINE.match(line):
            result.append(("label", line))
        elif (title := line.split(",")[0]).upper() == title and any(ch.isalpha() for ch in title):
            result.append(("entry", line))  # "SOFTWARE INTERN, 2024 - 2025" or "..., [add dates]"
        else:
            result.append(("text", line))
    return result


HEADING_COLOUR = 0x9E1116   # section headings are red in the PDF (see the CSS below)
PAGE = pymupdf.paper_rect("a4")
TEXT_AREA = PAGE + (50, 45, -50, -45)
KEEP_WITH_NEXT = 45  # points: a heading needs about three lines of room below it on its page


def cv_pdf(answer: str) -> bytes:
    """A clean A4 PDF of the CV. A section heading is never left alone at the bottom of a
    page: if one lands there, the PDF is laid out again with a page break before it."""
    breaks: set[int] = set()
    for _ in range(4):  # each pass moves the headings that ended up at a page bottom
        pdf = render_cv(answer, breaks)
        stranded = stranded_headings(pdf)
        if not stranded - breaks:
            return pdf
        breaks |= stranded
    return pdf


def stranded_headings(pdf: bytes) -> set[int]:
    """Numbers (0, 1, ... in order) of the section headings with too little room below them."""
    stranded, number = set(), 0
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    if any(span["color"] == HEADING_COLOUR and span["text"].strip() for span in line["spans"]):
                        if line["bbox"][3] > TEXT_AREA.y1 - KEEP_WITH_NEXT:
                            stranded.add(number)
                        number += 1
    return stranded


def render_cv(answer: str, breaks: set[int]) -> bytes:
    """The CV laid out on A4 pages (PyMuPDF's Story: simple HTML); headings whose number is
    in `breaks` start a new page."""
    parts, in_list, heading = [], False, 0
    for kind, text in blocks(answer):
        if kind != "bullet" and in_list:
            parts.append("</ul>")
            in_list = False
        safe = html.escape(text)
        if kind == "name":
            parts.append(f"<h1>{safe}</h1>")
        elif kind == "contact":
            parts.append(f'<p class="contact">{safe}</p>')
        elif kind == "heading":
            style = ' style="page-break-before: always"' if heading in breaks else ""
            parts.append(f"<h2{style}>{safe}</h2>")
            heading += 1
        elif kind == "entry":
            parts.append(f'<p class="entry">{safe}</p>')
        elif kind == "label":
            label, _, rest = text.partition(":")
            parts.append(f"<p><b>{html.escape(label)}:</b>{html.escape(rest)}</p>")
        elif kind == "bullet":
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{safe}</li>")
        else:
            parts.append(f"<p>{safe}</p>")
    if in_list:
        parts.append("</ul>")
    css = ("body { font-family: sans-serif; font-size: 10pt; color: #222; }"
           "h1 { font-size: 20pt; margin: 0 0 2pt 0; }"
           "p.contact { color: #555; margin: 0 0 1pt 0; }"
           "h2 { font-size: 11pt; color: #9e1116; margin: 12pt 0 3pt 0; border-bottom: 1px solid #bbb; }"
           "p { margin: 2pt 0; } p.entry { font-weight: bold; margin-top: 6pt; }"
           "ul { margin: 1pt 0 2pt 0; } li { margin: 1pt 0; }")
    story = pymupdf.Story(html="".join(parts), user_css=css)
    out = io.BytesIO()
    writer = pymupdf.DocumentWriter(out)
    more = True
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(TEXT_AREA)
        story.draw(device)
        writer.end_page()
    writer.close()
    return out.getvalue()


def cv_docx(answer: str) -> bytes:
    """The same CV as an editable Word document."""
    document = Document()
    document.styles["Normal"].font.size = Pt(10.5)
    for kind, text in blocks(answer):
        if kind == "name":
            document.add_heading(text, level=0)
        elif kind == "heading":
            document.add_heading(text, level=1)
        elif kind == "bullet":
            document.add_paragraph(text, style="List Bullet")
        elif kind in ("entry", "label"):
            paragraph = document.add_paragraph()
            if kind == "label":
                label, _, rest = text.partition(":")
                paragraph.add_run(label + ":").bold = True
                paragraph.add_run(rest)
            else:
                paragraph.add_run(text).bold = True
        else:
            document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def docx_to_cv_text(data: bytes) -> str:
    """The text of a Word CV made by cv_docx (and maybe edited since), in the template's
    plain-text form again ("- " bullets, headings in capitals), so cv_pdf can lay it out."""
    lines = []
    for paragraph in Document(io.BytesIO(data)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        if style.startswith("Heading") and lines:
            lines.append("")  # a blank line before each section
        lines.append(f"- {text}" if style.startswith("List") else text)
    return "\n".join(lines)
