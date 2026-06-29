"""Parser PDF wyciągu VeloBank → ParsedStatement.

Wyciąg to tabela, ale pdfplumber.extract_table() jej nie odczytuje (brak realnej
siatki), więc parsujemy tekst (extract_text) liniowo:

- Linia ROZPOCZYNAJĄCA transakcję ma postać:
    RRRR.MM.DD RRRR.MM.DD <typ + marker...> <kwota> <saldo_po>
  (dwie daty na początku, dwie liczby PL na końcu).
- Kolejne linie (do następnej transakcji) to kontynuacja opisu: numer rachunku
  kontrahenta, jego nazwa/adres oraz „Tytułem: ...". Bywają przeplecione stopką/
  nagłówkiem strony — te linie (boilerplate) pomijamy.

Z pełnego opisu wyciągamy payee (kontrahent) i notes („Tytułem"). Do daty w Actual
używamy Daty księgowania. Liczby w formacie PL (spacja = tysiące, przecinek = grosze).
"""

from __future__ import annotations

import io
import re
import sys
from datetime import date, datetime
from decimal import Decimal

import pdfplumber

from shared.models import ParsedStatement, Transaction

DATE = r"\d{4}\.\d{2}\.\d{2}"
AMOUNT = r"-?\d[\d  ]*,\d{2}"
DATE_RE = re.compile(DATE)
AMOUNT_RE = re.compile(AMOUNT)
START_RE = re.compile(
    rf"^({DATE})\s+({DATE})\s+(.*?)\s+({AMOUNT})\s+({AMOUNT})\s*$"
)

# Markery, po których w opisie pojawia się nazwa kontrahenta
PAYEE_MARKERS = ("Prowadzonego na rzecz:", "Prowadzony na rzecz:", "Odbiorca:", "Nadawca:")

# Linie nagłówka/stopki strony do pominięcia (po prefiksie lub dokładnym dopasowaniu)
BOILERPLATE_PREFIX = (
    "VeloBank S.A.", "Rondo Ignacego", "The Warsaw Hub", "00-843 Warszawa",
    "Infolinia +48", "velobank.pl", "Kod BIC", "Wyciąg nr", "Wyciąg za okres",
    "Numer rachunku:", "IBAN:", "Pakiet:", "Waluta rachunku:", "Numer ewidencyjny:",
    "Rachunek prowadzony", "Data Data", "księgowania", "Rejestru Sądowego",
    "numerem KRS", "Środki zgromadzone", "czerwca 2016r", "w tym zakresie",
    "Dokument wygenerowany", "podpisu ani stempla", "Data i godzina:",
    "Obroty WN - suma", "Obroty MA - suma",
)
BOILERPLATE_EXACT = {"Polska", "MICHAŁ SALWACH"}


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(" ", "").replace(" ", "").replace(",", "."))


def _to_date(text: str) -> date:
    return datetime.strptime(text, "%Y.%m.%d").date()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _last_amount(line: str) -> Decimal | None:
    found = AMOUNT_RE.findall(line)
    return _to_decimal(found[-1]) if found else None


def _is_boilerplate(line: str) -> bool:
    if line in BOILERPLATE_EXACT:
        return True
    return any(line.startswith(p) for p in BOILERPLATE_PREFIX)


# Miasta usuwane z końca nazwy kontrahenta (Velo dokleja miasto do nazwy sklepu)
CITIES = {
    "krakow", "krakow.", "krakowie", "warszawa", "warszawie", "poznan", "poznaniu",
    "sopot", "sopocie", "gdansk", "gdansku", "wroclaw", "wroclawiu", "lodz", "katowice",
    "gdynia", "gdyni", "bydgoszcz", "lublin", "szczecin",
}


def _strip_diacritics(text: str) -> str:
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return text.translate(table)


def _dedup_repeat(tokens: list[str]) -> list[str]:
    """'X X reszta' -> 'X reszta' (Velo powtarza nazwę: 'ROSSMANN 25 ROSSMANN 25 Krakow')."""
    n = len(tokens)
    for k in range(1, n // 2 + 1):
        if tokens[:k] == tokens[k : 2 * k]:
            return tokens[:k] + tokens[2 * k :]
    return tokens


def _clean_payee(name: str) -> str:
    name = name.replace("- ", " ").replace(" -", " ")  # myślnik z łamania wiersza
    tokens = _dedup_repeat(_norm(name).strip(" -").split())
    while tokens and _strip_diacritics(tokens[-1].lower()).strip(".,") in CITIES:
        tokens.pop()
    return _norm(" ".join(tokens))


def _derive_payee(full_desc: str, fallback_type: str) -> str:
    """Nazwa kontrahenta z opisu (po markerze Odbiorca/Nadawca/na rzecz, przed adresem)."""
    before = full_desc.split("Tytułem:", 1)[0]
    pos, mlen = -1, 0
    for mk in PAYEE_MARKERS:
        p = before.rfind(mk)
        if p > pos:
            pos, mlen = p, len(mk)
    cand = before[pos + mlen:] if pos >= 0 else before
    cand = _norm(cand)
    # usuń wiodący numer rachunku kontrahenta (IBAN/PL + grupy cyfr)
    cand = re.sub(r"^(?:[A-Z]{2}\d{2}\s*)?(?:\d[\d ]{5,}\s*)+", "", cand).strip()
    # utnij na adresie: "ul"/kod pocztowy
    cand = re.split(r"\bul\b\.?|\d{2}-\d{3}", cand, flags=re.IGNORECASE)[0]
    cand = _clean_payee(_norm(cand))
    return (cand or _norm(fallback_type))[:80] or "—"


def _derive_notes(full_desc: str, fallback_type: str) -> str:
    """Treść po 'Tytułem:'; gdy brak — typ transakcji."""
    if "Tytułem:" in full_desc:
        return _norm(full_desc.split("Tytułem:", 1)[1]) or _norm(fallback_type)
    return _norm(fallback_type)


def _extract_meta(full_text: str) -> tuple[str, dict]:
    meta: dict = {}
    m = re.search(r"Numer rachunku:\s*([\d  ]+)", full_text)
    account = _norm(m.group(1)) if m else ""
    m = re.search(r"Wyciąg nr\s*(\S+)", full_text)
    if m:
        meta["statement_no"] = m.group(1)
    m = re.search(rf"za okres od\s*({DATE})\s*do\s*({DATE})", full_text)
    if m:
        meta["period"] = f"{m.group(1)}–{m.group(2)}"
    return account, meta


def _build(cur: dict) -> Transaction:
    full = _norm(cur["head"] + " " + " ".join(cur["cont"]))
    # typ transakcji = opis head przed pierwszym markerem
    fallback_type = _norm(re.split(r"Odbiorca:|Nadawca:|Na rachunek:|Z rachunku:|Prowadzon", cur["head"])[0])
    return Transaction(
        booking_date=_to_date(cur["booking"]),
        transaction_date=_to_date(cur["trans"]),
        description=_derive_notes(full, fallback_type),
        payee=_derive_payee(full, fallback_type),
        amount=_to_decimal(cur["amount"]),
        balance_after=_to_decimal(cur["balance"]),
    )


def _parse_text(full_text: str) -> tuple[list[Transaction], Decimal | None, Decimal | None]:
    transactions: list[Transaction] = []
    opening = closing = None
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur is not None:
            transactions.append(_build(cur))
            cur = None

    for raw in full_text.splitlines():
        s = _norm(raw)
        if not s or _is_boilerplate(s):
            continue
        if s.startswith("Saldo początkowe"):
            opening = _last_amount(s)
            continue
        if s.startswith("Saldo końcowe"):
            closing = _last_amount(s)
            flush()
            continue
        if s.startswith("Obroty"):
            flush()
            continue
        m = START_RE.match(s)
        if m:
            flush()
            cur = {
                "booking": m.group(1), "trans": m.group(2), "head": _norm(m.group(3)),
                "amount": m.group(4), "balance": m.group(5), "cont": [],
            }
        elif cur is not None:
            cur["cont"].append(s)
    flush()
    return transactions, opening, closing


def parse(pdf_bytes: bytes, password: str) -> ParsedStatement:
    # PDF wewnątrz wyciągu jest jawny; password przekazujemy na wypadek, gdyby był szyfrowany.
    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password or "") as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    account, meta = _extract_meta(full_text)
    transactions, opening, closing = _parse_text(full_text)
    if opening is None:
        opening = Decimal("0.00")
    if closing is None:
        closing = transactions[-1].balance_after if transactions else opening

    return ParsedStatement(
        account_number=account,
        transactions=transactions,
        opening_balance=opening,
        closing_balance=closing,
        meta=meta,
    )


def _load_pdf_bytes(path: str, password: str) -> bytes:
    """Wczytuje bajty PDF z pliku .pdf lub z zaszyfrowanego .zip (to samo hasło)."""
    if path.lower().endswith(".zip"):
        import zipfile

        with zipfile.ZipFile(path) as zf:
            info = next(i for i in zf.infolist() if i.filename.lower().endswith(".pdf"))
            return zf.read(info, pwd=password.encode("utf-8") if password else None)
    with open(path, "rb") as f:
        return f.read()


if __name__ == "__main__":
    # CLI do kalibracji: python -m VeloBankIntegration.parse_pdf <plik.pdf|.zip> [hasło]
    import os

    if len(sys.argv) < 2:
        print("Użycie: python -m VeloBankIntegration.parse_pdf <plik.pdf|.zip> [hasło]")
        raise SystemExit(2)
    pwd = sys.argv[2] if len(sys.argv) > 2 else os.getenv("VELO_PDF_PASSWORD", "")
    stmt = parse(_load_pdf_bytes(sys.argv[1], pwd), pwd)

    print(f"Rachunek: {stmt.account_number}  meta={stmt.meta}")
    print(f"Saldo początkowe: {stmt.opening_balance}")
    total = sum((t.amount for t in stmt.transactions), Decimal("0"))
    for t in stmt.transactions:
        print(f"  {t.booking_date} | {t.amount:>11} | saldo {t.balance_after:>11} | {t.payee} || {t.description}")
    print(f"Suma transakcji: {total}")
    print(f"Saldo końcowe: {stmt.closing_balance}")
    expected = stmt.opening_balance + total
    ok = abs(expected - stmt.closing_balance) <= Decimal("0.01")
    print(f"Walidacja salda: {'OK' if ok else 'BŁĄD'} (pocz+suma={expected}, końc={stmt.closing_balance})")
