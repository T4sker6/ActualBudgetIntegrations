"""Wyłuskanie PDF-ów z załączników ZIP maila."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from imap_tools import MailMessage


@dataclass
class PdfFile:
    source: str  # nazwa zip-a + wpisu, do logów/powiadomień
    data: bytes  # surowe (wciąż zaszyfrowane hasłem) bajty PDF


def zip_attachments(msg: MailMessage) -> list[tuple[str, bytes]]:
    """Zwraca załączniki .zip jako (nazwa, bajty)."""
    out = []
    for att in msg.attachments:
        name = (att.filename or "").lower()
        if name.endswith(".zip") or att.content_type == "application/zip":
            out.append((att.filename or "zalacznik.zip", att.payload))
    return out


def pdfs_from_zip(zip_name: str, zip_bytes: bytes, zip_password: bytes | None = None) -> list[PdfFile]:
    """Rozpakowuje PDF-y z jednego ZIP-a (w pamięci)."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            data = zf.read(info, pwd=zip_password)
            out.append(PdfFile(source=f"{zip_name}!{info.filename}", data=data))
    return out


def pdfs_from_message(msg: MailMessage, zip_password: bytes | None = None) -> list[PdfFile]:
    """Wszystkie PDF-y ze wszystkich załączników ZIP danego maila."""
    pdfs = []
    for zip_name, zip_bytes in zip_attachments(msg):
        pdfs.extend(pdfs_from_zip(zip_name, zip_bytes, zip_password))
    return pdfs
