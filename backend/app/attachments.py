"""Read a file that a user attached to a chat message.

The browser sends the file as base64 text inside the JSON body, so no extra
upload library is needed. Documents become plain text for the prompt; images
become a data URL that a vision model can look at. Files are not saved.
"""
import base64
import binascii
import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import config

DOCUMENT_TYPES = {".pdf", ".txt", ".md"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


@dataclass
class Attachment:
    filename: str
    text: str | None = None       # documents: the extracted text
    image_url: str | None = None  # images: "data:image/...;base64,..." for the vision model

    @property
    def is_image(self) -> bool:
        return self.image_url is not None


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
        return Attachment(filename, image_url=f"data:{IMAGE_TYPES[extension]};base64,{data_base64}")

    text = extract_text(extension, data)
    if not text.strip():
        raise ValueError("No readable text found in this file. "
                         "If it is a scanned document, upload it as an image instead.")
    # Long files are cut so the prompt stays small and the answer stays fast.
    return Attachment(filename, text=text[:config.MAX_ATTACHMENT_CHARS])


def extract_text(extension: str, data: bytes) -> str:
    """Plain text of a PDF, TXT or MD file."""
    if extension == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError:
            raise ValueError("This PDF could not be opened. It may be damaged or password-protected.")
    return data.decode("utf-8", errors="replace")
