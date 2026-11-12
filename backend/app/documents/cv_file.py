"""Turn the CV model's restructured CV (plain text in a GIU template) into files: a PDF to
view and download, and a Word version the student can still change.

The answer looks like: "Template: Student", the name, contact lines, then sections with
headings in capitals (SUMMARY, EDUCATION ...), "- " bullets, and at the end the CV ANALYSIS
("تحليل الـ CV" in Arabic): the rating and notes, shown in the chat and left out of the files.
Arabic CVs come back in Arabic, with Arabic headings, and are laid out right to left.

The PDF is ATS-friendly: real selectable text in one column, standard section headings, no
tables or pictures. Its page count follows the content (no shrinking to fit fewer pages).
"""
import html
import io
import os
import re
from pathlib import Path

import pymupdf
from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Pt

# The analysis after the CV (CV model v6); older answers end with the "What I changed:" notes.
ANALYSIS_HEADING = re.compile(r"^[ \t#*]*(?:CV ANALYSIS|تحليل الـ? ?CV)[ \t*]*:?[ \t]*$", re.MULTILINE | re.IGNORECASE)
NOTES_HEADINGS = ("What I changed:", "ما غيرته:")
HEADING = re.compile(r"^[A-Z][A-Z &/]{2,34}$")        # SUMMARY, WORK EXPERIENCE, SKILLS
LABEL_LINE = re.compile(r"^([A-Z][A-Z &/]{1,30}):\s*(.+)$")  # "TOOLS: Excel, SQL" (London template)
# Section headings of Arabic CVs: the ones the CV model is told to use, and other common ones
ARABIC_HEADINGS = {"الملخص", "التعليم", "الخبرات العملية", "المشاريع", "المهارات", "الدورات وورش العمل",
                   "اللغات", "المراجع", "الخبرات", "الخبرة العملية", "الشهادات", "الجوائز", "المنشورات",
                   "الأنشطة والتطوع", "الأنشطة", "التطوع", "نبذة عني", "الملف الشخصي"}
ARABIC_LETTERS = re.compile(r"[؀-ۿ]")
LATIN_LETTERS = re.compile(r"[A-Za-z]")
YEAR_OR_DATES = re.compile(r"\d{4}|\[add dates\]")  # Arabic entries are found by their dates


def split_cv(answer: str) -> tuple[str, str]:
    """(the CV, the analysis after it). The CV becomes the files; the analysis is the chat
    message. Without an analysis heading the CV ends at the older "What I changed:" notes."""
    match = ANALYSIS_HEADING.search(answer)
    cut = match.start() if match else min((answer.find(h) for h in NOTES_HEADINGS if h in answer), default=len(answer))
    return answer[:cut].rstrip(), answer[cut:].strip()


def is_arabic(text: str) -> bool:
    """An Arabic CV (laid out right to left): over 40% of its letters are Arabic (it still
    has English terms, emails and links)."""
    return len(ARABIC_LETTERS.findall(text)) > 0.4 * len(LATIN_LETTERS.findall(text) + ARABIC_LETTERS.findall(text))


def is_heading(line: str) -> bool:
    return bool(HEADING.match(line)) or line.rstrip(":").strip() in ARABIC_HEADINGS


def is_restructured_cv(answer: str) -> bool:
    """True if the answer is a rewritten CV (and not, e.g., an error or a review)."""
    return answer.lstrip().startswith("Template:") or len(cv_lines(answer)[1]) >= 2


def cv_lines(answer: str) -> tuple[list[str], list[str]]:
    """(the CV's lines without the template line and the notes, the section headings)."""
    lines = [line.rstrip() for line in split_cv(answer)[0].strip().splitlines()]
    if lines and lines[0].startswith("Template:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    headings = [line for line in lines if is_heading(line.strip())]
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
        elif is_heading(line):
            top = False
            result.append(("heading", line.rstrip(":").strip()))
        elif top:
            result.append(("contact", line))
        elif line.startswith(("- ", "• ", "* ")):
            result.append(("bullet", line[2:].strip()))
        elif LABEL_LINE.match(line):
            result.append(("label", line))
        elif ((title := line.split(",")[0]).upper() == title and LATIN_LETTERS.search(title)
              and re.search(r"\d|\[add", line)):
            # "SOFTWARE INTERN, 2024 - 2025" or "..., [add dates]"; not a skills line ("SPSS, R, ...")
            result.append(("entry", line))
        elif not LATIN_LETTERS.search(title) and YEAR_OR_DATES.search(line):
            result.append(("entry", line))  # Arabic has no capitals: "مهندس برمجيات، 2023 - 2025"
        else:
            result.append(("text", line))
    return result


HEADING_COLOUR = 0x9E1116   # section headings are red in the PDF (see the CSS below)
PAGE = pymupdf.paper_rect("a4")
TEXT_AREA = PAGE + (50, 45, -50, -45)
# Layouts tried for a 1-page target, in order: (body pt, heading pt, spacing factor). Only the
# spacing and headings get a little smaller; the text never goes below 10pt.
LEVELS = [(10.5, 13, 1.0), (10.5, 12.5, 0.75), (10, 12, 0.55)]
# "Target length: 1 page" in the CV ANALYSIS (students and fresh graduates); not "1-2 pages"
ONE_PAGE_TARGET = re.compile(r"(?:target length|الطول)[^\n]*?(?:\b1 page\b|\bone page\b|صفحة واحدة|صفحه واحده)", re.IGNORECASE)
# Arabic CVs use Tahoma when the system has it (Windows): its letters keep their text in the
# PDF, so the CV can be copied and read by ATS software. MuPDF's built-in Arabic font (the
# fallback) looks fine, but its forms of "ل" come out as other characters when read back.
SYSTEM_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
ARABIC_FONT = ("tahoma.ttf", "tahomabd.ttf")
# A bracket closing English text ("باستخدام Python (pandas)") would jump to the other end of
# the line in a right-to-left CV; an invisible left-to-right mark after it keeps it in place.
LATIN_CLOSING_BRACKET = re.compile(r"(?<=[A-Za-z0-9.])([)\]])")


def is_one_page_target(analysis: str) -> bool:
    return bool(ONE_PAGE_TARGET.search(analysis))


def cv_pdf(answer: str, one_page: bool = False) -> bytes:
    """A clean A4 PDF of the CV; its page count follows the content. For a 1-page target
    (`one_page`), a CV that runs over one page is laid out again with slightly less spacing;
    if even the tightest layout needs more pages, the normal layout is kept."""
    normal = None
    for level in range(len(LEVELS) if one_page else 1):
        pdf = keep_headings_with_content(answer, level)
        normal = normal or pdf
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            if document.page_count == 1:
                return pdf
    return normal


def keep_headings_with_content(answer: str, level: int) -> bytes:
    """The CV laid out so no section heading is cut off from its content: a heading left at
    the bottom of a page gets a page break before it, and the PDF is laid out again."""
    breaks: set[int] = set()
    for _ in range(4):  # each pass moves the headings that ended up at a page bottom
        pdf = render_cv(answer, breaks, level)
        stranded = stranded_headings(pdf)
        if not stranded - breaks:
            return pdf
        breaks |= stranded
    return pdf


def stranded_headings(pdf: bytes) -> set[int]:
    """Numbers (0, 1, ... in order) of the section headings cut off from their content: the
    heading is the last line on its page. A heading only needs its first line with it, so a
    section that starts at a page bottom (heading + first line) is not moved as a whole."""
    rows = []  # (page, is it a heading) for each printed line, in order
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        for number, page in enumerate(document):
            seen = set()  # a right-to-left line can come back as several pieces at the same height
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [span for span in line["spans"] if span["text"].strip()]
                    if spans and (top := round(line["bbox"][1])) not in seen:
                        seen.add(top)
                        rows.append((number, any(span["color"] == HEADING_COLOUR for span in spans)))
    stranded, heading = set(), 0
    for index, (page, is_heading) in enumerate(rows):
        if not is_heading:
            continue
        section = []
        for row in rows[index + 1:]:
            if row[1]:
                break
            section.append(row)
        if sum(row[0] == page for row in section) < min(1, len(section)):
            stranded.add(heading)
        heading += 1
    return stranded


def render_cv(answer: str, breaks: set[int], level: int = 0) -> bytes:
    """The CV laid out on A4 pages (PyMuPDF's Story: simple HTML); headings whose number is
    in `breaks` start a new page. Arabic CVs are right to left: MuPDF then aligns right and
    orders mixed lines itself (emails, phone numbers and English terms stay readable)."""
    parts, heading, rtl = [], 0, is_arabic(answer)
    for kind, text in blocks(answer):
        safe = html.escape(LATIN_CLOSING_BRACKET.sub("\\1\u200e", text) if rtl else text)
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
            # A paragraph starting with "•" rather than <ul>: MuPDF puts list markers on the
            # left even in a right-to-left CV. Wrapped lines hang under the text, not the dot.
            parts.append(f'<p class="bullet">•&#160;{safe}</p>')
        else:
            parts.append(f"<p>{safe}</p>")
    side = "right" if rtl else "left"
    css, archive = "body { font-family: sans-serif; }", None
    if rtl and all((SYSTEM_FONTS / name).exists() for name in ARABIC_FONT):
        regular, bold = ARABIC_FONT
        css = (f"@font-face {{ font-family: cvfont; src: url({regular}); }}"
               f"@font-face {{ font-family: cvfont; font-weight: bold; src: url({bold}); }}"
               "body { font-family: cvfont; }")
        archive = pymupdf.Archive(str(SYSTEM_FONTS))
    # Readable sizes (body 10.5pt, headings 13pt) and normal spacing; a 1-page target may use
    # a tighter level (LEVELS): less space between lines and sections, text never under 10pt
    body, h2, s = LEVELS[level]
    css += (f"body {{ font-size: {body}pt; color: #222; }}"
            f"h1 {{ font-size: 20pt; margin: 0 0 {3 * s:.1f}pt 0; }}"
            f"p.contact {{ color: #555; margin: 0 0 {2 * s:.1f}pt 0; }}"
            f"h2 {{ font-size: {h2}pt; color: #9e1116; margin: {14 * s:.1f}pt 0 {4 * s:.1f}pt 0; border-bottom: 1px solid #bbb; }}"
            f"p {{ margin: {3 * s:.1f}pt 0; }} p.entry {{ font-weight: bold; margin-top: {8 * s:.1f}pt; }}"
            f"p.bullet {{ margin: {2 * s:.1f}pt 0; margin-{side}: 14pt; text-indent: -10pt; }}")
    # With dir="rtl" MuPDF already aligns right ("text-align: right" would flip it to the left)
    story = pymupdf.Story(html=f'<body dir="{"rtl" if rtl else "ltr"}">{"".join(parts)}</body>', user_css=css, archive=archive)
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
    if is_arabic(answer):  # right-to-left paragraphs (Word then puts bullets on the right too)
        for paragraph in document.paragraphs:
            paragraph._p.get_or_add_pPr().insert_element_before(
                OxmlElement("w:bidi"), "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
                "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
                "w:sectPr", "w:pPrChange")
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
