"""Read a file that a user attached to a chat message.

The browser sends the file as base64 text inside the JSON body, so no extra
upload library is needed. Documents become plain text for the prompt; images
become data URLs that a vision model can look at. Files are not saved.

PDF text is read with PyMuPDF, which knows where each text block is on the page, so
two-column layouts (e.g. Canva CVs with a sidebar) are read column by column instead
of line by line across both columns. pypdf is the fallback.

Some PDFs contain no text, only a picture of each page (scanned documents, or CVs
exported from Canva as images). For those, the page pictures are taken out of the
PDF and sent to the vision model instead.
"""
import base64
import binascii
import io
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import config

DOCUMENT_TYPES = {".pdf", ".txt", ".md"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_PDF_PAGES_AS_IMAGES = 2  # a CV is 1-2 pages; more would make the request slow


@dataclass
class Attachment:
    filename: str
    text: str | None = None  # documents: the extracted text
    # images: "data:image/...;base64,..." for the vision model (one per page for image-only PDFs)
    image_urls: list[str] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        return bool(self.image_urls)


def read_attachment(filename: str, data_base64: str) -> Attachment:
    """Decode and check an uploaded file. Raises ValueError with a user-friendly message."""
    extension = Path(filename).suffix.lower()
    if extension not in DOCUMENT_TYPES and extension not in IMAGE_TYPES:
        raise ValueError("Unsupported file type. Upload a PDF, TXT, MD, PNG, JPG or WEBP file.")

    try:
        data = base64.b64decode(data_base64, validate=True)
    except binascii.Error:
        raise ValueError("The file could not be read. Please try uploading it again.")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"The file is larger than {config.MAX_UPLOAD_MB} MB.")

    if extension in IMAGE_TYPES:
        return Attachment(filename, image_urls=[f"data:{IMAGE_TYPES[extension]};base64,{data_base64}"])

    text = extract_text(extension, data)
    if text.strip():
        # Long files are cut so the prompt stays small and the answer stays fast.
        return Attachment(filename, text=text[:config.MAX_ATTACHMENT_CHARS])
    if extension == ".pdf":
        pictures = pdf_page_images(data)
        if pictures:
            return Attachment(filename, image_urls=pictures)
    raise ValueError("No readable text or page pictures found in this file. "
                     "Try exporting it again as a PDF with text, or upload it as an image.")


def extract_text(extension: str, data: bytes) -> str:
    """Plain text of a PDF, TXT or MD file."""
    if extension == ".pdf":
        try:
            return pdf_text_in_reading_order(data)
        except Exception:  # PyMuPDF could not read it: try pypdf
            pass
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError:
            raise ValueError("This PDF could not be opened. It may be damaged or password-protected.")
    return data.decode("utf-8", errors="replace")


def pdf_text_in_reading_order(data: bytes) -> str:
    """PDF text page by page, two-column pages column by column, plus the real link URLs.

    Link text such as "LinkedIn" does not contain its URL, so the URLs of the PDF's
    links are added at the end as "Links: <url>, <url>".
    """
    pages, links = [], []
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for page in pdf:
            pages.append(page_text(page))
            links += [link["uri"] for link in page.get_links() if link.get("uri")]
    text = "\n\n".join(p for p in pages if p)
    if links:
        text += "\n\nLinks: " + ", ".join(dict.fromkeys(links))  # without duplicates
    return text


def page_text(page) -> str:
    """One page's text, in reading order.

    Works on text lines (x0, y0, x1, y1, text): PyMuPDF's blocks can join lines of both
    columns. Two columns (e.g. a sidebar and a main column) are found by their gap: the
    vertical line, between 25% and 75% of the page width, that the fewest lines cross.
    Lines crossing it are "wide" (e.g. the name at the top). It is a two-column page if
    both sides hold a fair share of the text, unless the right side is only short pieces
    on the same lines as the left side (right-aligned dates in a one-column CV). Then the
    lines above the right column (the header) come first, then the whole left column,
    then the whole right column, then the other wide lines. Otherwise all lines are read
    from top to bottom.
    """
    width = page.rect.width
    lines = [(*line["bbox"], "".join(span["text"] for span in line["spans"]))
             for block in page.get_text("dict")["blocks"] if block["type"] == 0
             for line in block["lines"]]
    lines = [line for line in lines if line[4].strip()]
    if not lines:
        return ""
    top_to_bottom = sorted(lines, key=lambda b: (round(b[1]), b[0]))

    def chars(group):
        return sum(len(b[4]) for b in group)

    def crossing(x):
        return [b for b in lines if b[0] < x < b[2]]

    gap = min(range(int(width * 0.25), int(width * 0.75), 2), key=lambda x: chars(crossing(x)))
    wide = crossing(gap)
    left = [b for b in lines if b[2] <= gap]
    right = [b for b in lines if b[0] >= gap]
    total = chars(lines)
    same_line = [b for b in right if any(abs(b[1] - a[1]) < 3 for a in left)]
    dates_beside_lines = len(same_line) >= 0.75 * len(right) and chars(right) < 25 * len(right)
    two_columns = (chars(left) > 0.2 * total and chars(right) > 0.2 * total and chars(wide) < 0.3 * total
                   and not dates_beside_lines)
    if not two_columns:
        return "\n".join(b[4].strip() for b in top_to_bottom)
    # Everything above the start of the right column is the header (name, title).
    right_top = min(b[1] for b in right)
    header = [b for b in lines if b[3] <= right_top + 1]
    by_height = lambda group: sorted((b for b in group if b not in header), key=lambda b: b[1])
    ordered = sorted(header, key=lambda b: (round(b[1]), b[0])) + by_height(left) + by_height(right) + by_height(wide)
    return "\n".join(b[4].strip() for b in ordered)


def pdf_page_images(data: bytes) -> list[str]:
    """The largest picture on each of the first pages, as data URLs (empty if none)."""
    urls = []
    for page in PdfReader(io.BytesIO(data)).pages[:MAX_PDF_PAGES_AS_IMAGES]:
        xobjects = page.get("/Resources", {}).get("/XObject", {})
        images = [ref.get_object() for ref in xobjects.values()]
        images = [img for img in images if img.get("/Subtype") == "/Image"]
        if images:
            largest = max(images, key=lambda img: img["/Width"] * img["/Height"])
            url = image_to_data_url(largest)
            if url:
                urls.append(url)
    return urls


def image_to_data_url(image) -> str | None:
    """A PDF picture as a JPEG or PNG data URL, or None for formats we cannot convert."""
    filters = image.get("/Filter")
    filters = [filters] if isinstance(filters, str) else list(filters or [])
    if filters == ["/DCTDecode"]:  # already a JPEG (typical for scans and photos)
        return "data:image/jpeg;base64," + base64.b64encode(image._data).decode()
    channels = colour_channels(image.get("/ColorSpace"))
    if filters == ["/FlateDecode"] and image.get("/BitsPerComponent") == 8 and channels in (1, 3):
        png = make_png(image["/Width"], image["/Height"], channels, image.get_data())
        return "data:image/png;base64," + base64.b64encode(png).decode()
    return None


def colour_channels(colour_space) -> int | None:
    """1 for grey, 3 for RGB, None for anything else."""
    colour_space = colour_space.get_object() if hasattr(colour_space, "get_object") else colour_space
    if colour_space == "/DeviceGray":
        return 1
    if colour_space == "/DeviceRGB":
        return 3
    if isinstance(colour_space, list) and colour_space and colour_space[0] == "/ICCBased":
        return colour_space[1].get_object().get("/N")
    return None


def make_png(width: int, height: int, channels: int, pixels: bytes) -> bytes:
    """Write raw 8-bit grey or RGB pixels as a PNG file (built-in zlib only)."""
    stride = width * channels
    rows = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    colour_type = 2 if channels == 3 else 0
    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
