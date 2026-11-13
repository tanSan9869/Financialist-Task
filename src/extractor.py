"""CV link -> plain text. Never raises: always returns an ExtractResult."""
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .google_auth import get_credentials

GDOC = "application/vnd.google-apps.document"


@dataclass
class ExtractResult:
    ok: bool
    text: str = ""
    cv_hash: Optional[str] = None
    method: str = ""
    error: str = ""
    retryable: bool = False  # tooling missing on this machine (OCR/libreoffice); not the CV's fault


def _file_id(link):
    for pat in (r"/d/([\w-]{15,})", r"[?&]id=([\w-]{15,})"):
        m = re.search(pat, link or "")
        if m:
            return m.group(1)
    return None


def _drive_fetch(link):
    """Returns (bytes, is_gdoc_text). Service account first, then public download."""
    fid = _file_id(link)
    if not fid:
        raise ValueError("CV link is not a recognisable Google Drive/Docs link")
    try:
        drive = build("drive", "v3", credentials=get_credentials(), cache_discovery=False)
        meta = drive.files().get(fileId=fid, fields="mimeType,name", supportsAllDrives=True).execute()
        if meta["mimeType"] == GDOC:
            req = drive.files().export_media(fileId=fid, mimeType="text/plain")
        else:
            req = drive.files().get_media(fileId=fid, supportsAllDrives=True)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue(), meta["mimeType"] == GDOC
    except HttpError as e:
        if e.resp.status not in (403, 404):
            raise
    r = requests.get("https://drive.google.com/uc", params={"export": "download", "id": fid}, timeout=60)
    if r.status_code != 200 or b"<html" in r.content[:300].lower():
        raise PermissionError("file not shared with the service account or 'anyone with the link'")
    return r.content, False


def _sniff(data):
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"PK":
        return "docx"
    if data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
        return "doc"
    if (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"
            or data[:4] in (b"II*\x00", b"MM\x00*") or data[:2] == b"BM"):
        return "image"
    return "txt"


def _ocr_images(images):
    import pytesseract
    return "\n".join(pytesseract.image_to_string(im) for im in images)


def _pdf(data):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    return text, "pdfplumber"


def _pdf_ocr(data):
    from pdf2image import convert_from_bytes
    return _ocr_images(convert_from_bytes(data, dpi=200)[:6]), "ocr(pdf)"


def _docx(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" ".join(c.text for c in row.cells))
    return "\n".join(parts), "python-docx"


def _doc(data):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("legacy .doc needs libreoffice, which is not installed")
    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/in.doc", "wb") as f:
            f.write(data)
        subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", d, f"{d}/in.doc"],
                       check=True, capture_output=True, timeout=120)
        with open(f"{d}/in.docx", "rb") as f:
            return _docx(f.read())[0], "libreoffice+docx"


def _image(data):
    from PIL import Image
    return _ocr_images([Image.open(io.BytesIO(data))]), "ocr(image)"


def _txt(data):
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc), "txt"
        except UnicodeDecodeError:
            continue
    return "", "txt"


def extract(link, min_chars=80):
    try:
        data, is_text = _drive_fetch(link)
    except Exception as e:
        return ExtractResult(False, error=f"Download failed: {e}"[:400])
    if not data:
        return ExtractResult(False, error="Empty file (0 bytes)")
    h = hashlib.sha256(data).hexdigest()
    try:
        if is_text:
            text, method = data.decode("utf-8", "replace"), "gdoc-export"
        else:
            kind = _sniff(data)
            if kind == "pdf":
                text, method = _pdf(data)
                if len(text.strip()) < min_chars:  # scanned PDF -> OCR
                    text, method = _pdf_ocr(data)
            else:
                text, method = {"docx": _docx, "doc": _doc, "image": _image, "txt": _txt}[kind](data)
    except Exception as e:
        if type(e).__name__ in ("PDFInfoNotInstalledError", "TesseractNotFoundError") or "libreoffice" in str(e):
            return ExtractResult(False, cv_hash=h, retryable=True, error=f"Tooling missing: {type(e).__name__}")
        return ExtractResult(False, cv_hash=h,
                             error=f"Could not read file (corrupt/unsupported or OCR unavailable): {type(e).__name__}: {e}"[:400])
    text = text.strip()
    if len(text) < min_chars:
        return ExtractResult(False, cv_hash=h, method=method,
                             error=f"Extracted text empty/too short ({len(text)} chars) via {method}")
    return ExtractResult(True, text=text, cv_hash=h, method=method)
