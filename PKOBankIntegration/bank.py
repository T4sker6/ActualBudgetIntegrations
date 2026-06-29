"""Definicja banku PKO — SZKIELET (wzór do skopiowania przy dodawaniu banku)."""

from __future__ import annotations

from pathlib import Path

from shared.models import ParsedStatement

from . import parse_pdf


class PkoBank:
    name = "pko"
    imap_folder = "pko-billing"
    processed_folder = "pko-billing-processed"
    pdf_password_env = "PKO_PDF_PASSWORD"
    accounts_path = Path(__file__).resolve().parent / "accounts.json"

    def parse(self, pdf_bytes: bytes, password: str) -> ParsedStatement:
        return parse_pdf.parse(pdf_bytes, password)


BANK = PkoBank()
