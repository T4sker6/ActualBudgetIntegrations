"""Parser wyciągów PKO — SZKIELET (do zaimplementowania).

Skopiuj ten moduł jako wzór przy dodawaniu własnego banku. Funkcja parse musi
zwrócić shared.models.ParsedStatement (numer rachunku, lista transakcji, salda).
"""

from __future__ import annotations

from shared.models import ParsedStatement


def parse(pdf_bytes: bytes, password: str) -> ParsedStatement:
    raise NotImplementedError(
        "Parser PKO nie jest jeszcze zaimplementowany. "
        "Zaimplementuj parse() na wzór VeloBankIntegration/parse_pdf.py."
    )
