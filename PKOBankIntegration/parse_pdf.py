"""Parser PDF miesięcznego wyciągu PKO BP → ParsedStatement.

Wyciąg PKO nie jest dzienny (mail dzienny się nie da), więc ten moduł jest
używany RĘCZNIE przez CLI (`python -m PKOBankIntegration.parse_pdf <plik.pdf>`),
a nie przez orchestrator run.py. Wynik: wydruk kontrolny + saldo do weryfikacji
oraz CSV gotowy do ręcznego importu w Actual.

Jak w Velo parsujemy tekst (extract_text) liniowo — pdfplumber nie odczytuje tu
realnej tabeli. Każda transakcja to dwie „logiczne" linie + kontynuacje:

- Linia ROZPOCZYNAJĄCA (Data operacji):
      DD.MM.RRRR <identyfikator> <TYP OPERACJI> <kwota> <saldo>
  jedna data na początku, DWIE kwoty PL na końcu (kwota ze znakiem + saldo po).
- Linia DRUGA (Data waluty):
      DD.MM.RRRR <opis operacji...>
  data waluty + opis (kontrahent, tytuł, numer rachunku). Bywa sama data
  (np. AUTOOSZCZĘDZANIE — pusty opis). Dalsze linie to kontynuacja opisu.

Nagłówki/stopki stron oraz salda przeniesienia (Saldo z/do przeniesienia)
pomijamy. `Saldo poprzednie` = saldo początkowe, `Saldo końcowe` kończy wyciąg.
Liczby w formacie PL (spacja = tysiące, przecinek = grosze). Daty DD.MM.RRRR.
"""

from __future__ import annotations

import io
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal

import pdfplumber
from dotenv import load_dotenv

from shared.config import BASE_DIR
from shared.models import ParsedStatement, Transaction

load_dotenv(BASE_DIR / ".env")


def _env_list(name: str) -> list[str]:
    """Lista z .env rozdzielana '|' (np. PKO_HEADER_SKIP_EXACT=IMIĘ NAZWISKO|MIASTO)."""
    return [v.strip() for v in os.getenv(name, "").split("|") if v.strip()]

DATE = r"\d{2}\.\d{2}\.\d{4}"
AMOUNT = r"-?\d[\d  ]*,\d{2}"
DATE_RE = re.compile(DATE)
AMOUNT_RE = re.compile(AMOUNT)
# Linia startowa: data, identyfikator (1 token), typ, kwota, saldo.
START_RE = re.compile(
    rf"^({DATE})\s+(\S+)\s+(.*?)\s+({AMOUNT})\s+({AMOUNT})\s*$"
)
# Numer rachunku NRB: 26 cyfr, ciągiem lub w grupach (2 + 6×4), bez cyfry obok.
NRB_RE = re.compile(r"(?<!\d)\d{2}(?:[  ]?\d{4}){6}(?!\d)")

# Prefiksy linii nagłówka/stopki strony do pominięcia. Linie z danymi osobowymi
# (imię i nazwisko, adres) NIE są tu wpisane — przychodzą z .env (PKO_HEADER_SKIP_*).
BOILERPLATE_PREFIX = (
    "www.pkobp.pl", "w pozostałych przypadkach", "+48 81 535 60 60",
    "WYCIĄG za okres", "Nr:", "Nr rachunku/karty:", "Nr IBAN:",
    "PKO BP SA", "Rodzaj rachunku:",
    "Waluta rachunku:", "Data rozliczenia odsetek",
    "Stopa %:", "Limit kredytu", "dopuszczalnego salda debetowego:",
    "Obroty MA", "Obroty WN", "Saldo poprzednie", "Saldo z przeniesienia",
    "Saldo do przeniesienia", "Data operacji", "Data waluty",
    "Niniejszy dokument", "Powszechna Kasa Oszczędności", "Sąd Rejonowy", "NIP:",
    # marketing z ostatniej strony (i tak ucinany po „Saldo końcowe", ale na wszelki wypadek)
    "Informacja o Bankowym", "Środki na rachunku", "r. o Bankowym",
    "określonych w tej ustawie", "Szczegółowy zakres", "Zadbaj o wygodę",
    "Po każdej zrobionej", "wszystkich transakcjach", "Podstawa prawna",
    "2021/1230", "Jeśli korzystasz", "samodzielnie", "aktywować",
    "Aby korzystać", "zaktualizować",
) + tuple(_env_list("PKO_HEADER_SKIP_PREFIX"))
BOILERPLATE_EXACT = set(_env_list("PKO_HEADER_SKIP_EXACT"))

# Miasta ucinane z końca nazwy sprzedawcy (PKO dokleja miasto: „LIDL CONRADA Krakow PL").
# Własne (np. rodzinne miasto) dopisz w .env: PKO_EXTRA_CITIES=miasto1|miasto2.
CITIES = {
    "krakow", "warszawa", "poznan", "poznań", "sopot", "gdansk", "gdańsk",
    "wroclaw", "wrocław", "lodz", "łódź", "katowice", "gdynia", "lublin",
    "szczecin", "rzeszow", "rzeszów", "bielsko-biała", "bielsko",
} | {c.lower() for c in _env_list("PKO_EXTRA_CITIES")}


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(" ", "").replace(" ", "").replace(",", "."))


def _to_date(text: str) -> date:
    return datetime.strptime(text, "%d.%m.%Y").date()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _last_amount(line: str) -> Decimal | None:
    found = AMOUNT_RE.findall(line)
    return _to_decimal(found[-1]) if found else None


def _is_boilerplate(line: str) -> bool:
    if line in BOILERPLATE_EXACT:
        return True
    return any(line.startswith(p) for p in BOILERPLATE_PREFIX)


# ── Wyprowadzanie kontrahenta i tytułu z opisu ──────────────────────────────

# Tokeny adresu/referencji, na których ucinamy nazwę kontrahenta.
ADDRESS_STOP = {"UL", "AL", "OS", "WS", "PL", "REF", "DATA", "OD:", "DO:", "BID:"}


def _is_stop_token(tok: str) -> bool:
    if not tok:
        return False
    if tok[0].isdigit():  # numer budynku / kod pocztowy / fragment rachunku
        return True
    return tok.upper().rstrip(".") in ADDRESS_STOP


def _last_nrb(opis: str) -> str:
    """Znormalizowany (same cyfry) numer rachunku kontrahenta — ostatni NRB w opisie."""
    m = None
    for m in NRB_RE.finditer(opis):
        pass
    return "".join(ch for ch in m.group(0) if ch.isdigit()) if m else ""


def _counterparty(opis: str) -> str:
    """Nazwa kontrahenta = tekst po ostatnim numerze rachunku, do adresu/referencji."""
    matches = list(NRB_RE.finditer(opis))
    tail = opis[matches[-1].end():] if matches else opis
    tokens: list[str] = []
    for tok in _norm(tail).split():
        if _is_stop_token(tok):
            break
        tokens.append(tok)
    return _norm(" ".join(tokens)).strip(" -/")


def _merchant(opis: str) -> str:
    """Sprzedawca dla płatności kartą/BLIK/WEB — tekst po 'Lokalizacja:' do 'Nr ref:'."""
    m = re.search(r"Lokalizacja:\s*(.*?)\s*(?:Nr ref:|$)", opis)
    if not m:
        return ""
    name = m.group(1)
    name = re.sub(r"\s*\(mobile\)\s*$", "", name)
    name = re.sub(r"\s+PL\s*$", "", name)  # kraj
    tokens = _norm(name).split()
    while tokens and tokens[-1].lower().strip(".,") in CITIES:  # utnij miasto
        tokens.pop()
    return _norm(" ".join(tokens))


def _transfer_title(opis: str) -> str:
    """Tytuł przelewu = tekst przed numerem rachunku / markerami referencji."""
    t = opis
    m = NRB_RE.search(t)
    if m:
        t = t[:m.start()]
    for mk in (" OD:", "/OPT", "/OPF", " BID:", "Ref."):
        i = t.find(mk)
        if i >= 0:
            t = t[:i]
    t = re.split(r"\s+[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}", t)[0]  # utnij UUID referencji
    return _norm(t.strip("/ "))


def _derive_payee(op_type: str, opis: str) -> str:
    if "AUTOOSZCZĘDZANIE" in op_type:
        return "Autooszczędzanie"
    if "Lokalizacja:" in opis:
        return (_merchant(opis) or _norm(op_type))[:80]
    return (_counterparty(opis) or _transfer_title(opis) or _norm(op_type))[:80]


def _derive_notes(op_type: str, opis: str) -> str:
    if "AUTOOSZCZĘDZANIE" in op_type:
        return "Autooszczędzanie"
    if "Lokalizacja:" in opis:
        return _norm(op_type)
    return _transfer_title(opis) or _norm(op_type)


# ── Główna pętla parsowania ─────────────────────────────────────────────────

def _extract_meta(full_text: str) -> tuple[str, dict]:
    meta: dict = {}
    m = re.search(r"Nr rachunku/karty:\s*([\d  ]+)", full_text)
    account = _norm(m.group(1)) if m else ""
    m = re.search(r"Nr:\s*(\S+)", full_text)
    if m:
        meta["statement_no"] = m.group(1)
    m = re.search(rf"za okres\s*({DATE})\s*-\s*({DATE})", full_text)
    if m:
        meta["period"] = f"{m.group(1)}–{m.group(2)}"
        meta["period_from"] = m.group(1)
        meta["period_to"] = m.group(2)
        meta["single_day"] = m.group(1) == m.group(2)  # PKO miesięczny => False
    return account, meta


def _build(cur: dict) -> Transaction:
    opis = _norm(" ".join(cur["cont"]))
    tx = Transaction(
        booking_date=_to_date(cur["op_date"]),      # Data operacji -> data w Actual
        transaction_date=_to_date(cur["val_date"]),  # Data waluty
        description=_derive_notes(cur["type"], opis),
        payee=_derive_payee(cur["type"], opis),
        amount=_to_decimal(cur["amount"]),
        balance_after=_to_decimal(cur["balance"]),
    )
    # Numer rachunku kontrahenta (dla --exclude-acct: pomijanie transferów, które
    # obsługuje już import drugiego banku, np. Velo tworzy odbicie w PKO).
    tx.counterparty_acct = _last_nrb(opis)  # type: ignore[attr-defined]
    return tx


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
        if not s:
            continue
        if s.startswith("Saldo poprzednie"):
            opening = _last_amount(s)
            continue
        if s.startswith("Saldo końcowe"):
            closing = _last_amount(s)
            flush()
            break  # koniec transakcji — reszta to marketing
        if _is_boilerplate(s):
            continue
        m = START_RE.match(s)
        if m:
            flush()
            cur = {
                "op_date": m.group(1),
                "type": _norm(m.group(3)),
                "amount": m.group(4),
                "balance": m.group(5),
                "val_date": m.group(1),  # domyślnie = data operacji; nadpisze 1. kontynuacja
                "cont": [],
                "_val_set": False,
            }
        elif cur is not None:
            dm = DATE_RE.match(s)
            if dm and not cur["_val_set"]:
                cur["val_date"] = dm.group(0)      # Data waluty z pierwszej linii kontynuacji
                cur["_val_set"] = True
                rest = _norm(s[dm.end():])
                if rest:
                    cur["cont"].append(rest)
            else:
                cur["cont"].append(s)
    flush()
    return transactions, opening, closing


def parse(pdf_bytes: bytes, password: str = "") -> ParsedStatement:
    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password or "") as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    account, meta = _extract_meta(full_text)
    transactions, opening, closing = _parse_text(full_text)
    if opening is None:
        opening = (
            transactions[0].balance_after - transactions[0].amount
            if transactions else Decimal("0.00")
        )
    if closing is None:
        closing = transactions[-1].balance_after if transactions else opening

    return ParsedStatement(
        account_number=account,
        transactions=transactions,
        opening_balance=opening,
        closing_balance=closing,
        meta=meta,
    )


# ── CLI kalibracyjne / ręczny eksport ───────────────────────────────────────

def _write_actual_csv(path: str, txns: list[Transaction]) -> None:
    """CSV pod ręczny import w Actual: data,odbiorca,opis,kwota (+ saldo do kontroli)."""
    import csv

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Data", "Odbiorca", "Opis", "Kwota", "Saldo"])
        for t in txns:
            w.writerow([
                t.booking_date.isoformat(), t.payee, t.description,
                str(t.amount), str(t.balance_after),
            ])


def _opt(name: str) -> str | None:
    """Wartość flagi CLI, np. --csv plik / --from 2026-06-30."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python -m PKOBankIntegration.parse_pdf <plik.pdf> "
              "[--from RRRR-MM-DD] [--to RRRR-MM-DD] [--exclude-acct 1111,2222] [--csv <plik.csv>]")
        raise SystemExit(2)

    with open(sys.argv[1], "rb") as fh:
        stmt = parse(fh.read())

    # Filtr dat (booking_date, czyli kolumna „Data"). Przydatny gdy w Actual masz
    # już saldo startowe na jakiejś dacie — importujesz tylko to, co PO nim.
    lo = datetime.strptime(_opt("--from"), "%Y-%m-%d").date() if _opt("--from") else date.min
    hi = datetime.strptime(_opt("--to"), "%Y-%m-%d").date() if _opt("--to") else date.max
    sel_all = [t for t in stmt.transactions if lo <= t.booking_date <= hi]

    # Pomijanie transferów do kont obsługiwanych przez inny import (np. Velo sam
    # tworzy odbicie w PKO) — po końcówkach numerów rachunku kontrahenta.
    excl = [_norm_digits for s in (_opt("--exclude-acct") or "").split(",")
            if (_norm_digits := "".join(c for c in s if c.isdigit()))]
    dropped = [t for t in sel_all
               if excl and any(getattr(t, "counterparty_acct", "").endswith(s) for s in excl)]
    sel = [t for t in sel_all if t not in dropped]

    print(f"Rachunek: {stmt.account_number}  meta={stmt.meta}")
    for t in sel:
        print(f"  {t.booking_date} | {t.amount:>12} | saldo {t.balance_after:>12} | {t.payee[:32]:<32} || {t.description}")

    total = sum((t.amount for t in sel), Decimal("0"))
    if len(sel_all) == len(stmt.transactions) and not dropped:
        # cały wyciąg — walidacja saldo_pocz + Σ == saldo_końc
        print(f"Transakcji: {len(sel)}   Suma: {total}")
        print(f"Saldo początkowe: {stmt.opening_balance}   końcowe: {stmt.closing_balance}")
        expected = stmt.opening_balance + total
        ok = abs(expected - stmt.closing_balance) <= Decimal("0.01")
        print(f"Walidacja salda: {'OK' if ok else 'BŁĄD'} (pocz+suma={expected}, końc={stmt.closing_balance})")
    elif sel_all:
        # wycinek — pokaż kotwicę: saldo tuż przed pierwszą transakcją zakresu
        bal_before = sel_all[0].balance_after - sel_all[0].amount
        print(f"Do CSV: {len(sel)} transakcji   Suma (bez pominiętych): {total}")
        print(f"Saldo PRZED pierwszą ({sel_all[0].booking_date}): {bal_before}"
              f"  <-- musi = Twoje saldo startowe w Actual")
        print(f"Saldo PO ostatniej ({sel_all[-1].booking_date}): {sel_all[-1].balance_after}"
              f"  <-- konto dojdzie tu, gdy dołożysz też odbicia transferów z drugiego banku")
    else:
        print("Brak transakcji w podanym zakresie dat.")

    if dropped:
        print(f"Pominięto {len(dropped)} transfer(y) do wykluczonych kont (obsłuży je import drugiego banku):")
        for t in dropped:
            print(f"  {t.booking_date} | {t.amount:>12} | {t.payee[:40]}  (konto ...{getattr(t, 'counterparty_acct', '')[-8:]})")

    out = _opt("--csv")
    if out:
        _write_actual_csv(out, sel)
        print(f"CSV zapisany: {out}  ({len(sel)} transakcji)")
