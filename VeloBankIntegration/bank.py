"""Definicja banku Velo — metadane + delegacja parsowania do parse_pdf."""

from __future__ import annotations

from pathlib import Path

from shared.models import ParsedStatement

from . import parse_pdf


class VeloBank:
    name = "velo"
    imap_folder = "velo-billing"
    processed_folder = "velo-billing-processed"
    pdf_password_env = "VELO_PDF_PASSWORD"
    accounts_path = Path(__file__).resolve().parent / "accounts.json"

    def parse(self, pdf_bytes: bytes, password: str) -> ParsedStatement:
        return parse_pdf.parse(pdf_bytes, password)


BANK = VeloBank()
