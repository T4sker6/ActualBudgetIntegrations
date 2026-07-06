"""Orchestrator: dla każdego włączonego banku przetwarza nieprzeczytane wyciągi.

Uruchamiany raz dziennie przez cron. Czyta ENABLED_BANKS z .env, dla każdego banku
bierze nieprzeczytane maile z jego folderu IMAP i przetwarza je po kolei. Każdy mail
to osobna jednostka — własne powiadomienie na Discord (sukces/błąd). Błąd jednego
maila nie przerywa reszty; mail z błędem zostaje nieprzeczytany (retry następnego dnia).
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from imap_tools import MailMessage

from shared import notify
from shared.actual_client import ActualClient, open_actual
from shared.config import Config, ConfigError, load
from shared.extract import pdfs_from_message
from shared.mailflow import fetch_unseen, mark_processed, open_mailbox
from shared.models import Bank
from shared.statements import map_account, validate_balance, write_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("velo")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Nazwa w ENABLED_BANKS -> moduł banku (każdy eksponuje obiekt BANK)
BANK_MODULES = {
    "velo": "VeloBankIntegration.bank",
    "pko": "PKOBankIntegration.bank",
}


def load_bank(name: str) -> Bank:
    if name not in BANK_MODULES:
        raise ConfigError(f"Nieznany bank '{name}' w ENABLED_BANKS. Dostępne: {sorted(BANK_MODULES)}")
    module = importlib.import_module(BANK_MODULES[name])
    return module.BANK


def process_message(bank: Bank, msg: MailMessage, actual: ActualClient, cfg: Config) -> dict:
    """Przetwarza jednego maila: zip -> PDF -> parse -> walidacja -> CSV -> import. Zwraca summary."""
    password = cfg.pdf_password(bank.pdf_password_env)
    # Hasło chroni archiwum ZIP (ZipCrypto); przekazujemy je też do parsera PDF,
    # gdyby któryś bank szyfrował również sam PDF (pdfplumber zignoruje je dla jawnego PDF).
    pdfs = pdfs_from_message(msg, zip_password=password.encode("utf-8"))
    if not pdfs:
        raise ValueError("Mail nie zawiera żadnego PDF w załącznikach ZIP.")

    accounts_summary = []
    skipped = []
    for pdf in pdfs:
        stmt = bank.parse(pdf.data, password)
        # Olewamy wyciągi okresowe (miesięczne/półroczne) — pracujemy tylko na dziennych.
        if not stmt.meta.get("single_day", True):
            period = stmt.meta.get("period", "?")
            log.info("Pomijam wyciąg okresowy konta %s (okres %s).", stmt.account_number, period)
            skipped.append(period)
            continue
        validate_balance(stmt)
        write_csv(DATA_DIR, bank.name, stmt)
        account_name = map_account(bank.accounts_path, stmt.account_number)
        count = actual.import_transactions(
            bank.name, account_name, stmt.account_number, stmt.transactions
        )
        dates = [tx.booking_date for tx in stmt.transactions]
        date_range = f"{min(dates)}–{max(dates)}" if dates else "—"
        accounts_summary.append(
            {
                "account": stmt.account_number,
                "name": account_name,
                "count": count,
                "range": date_range,
                "closing": str(stmt.closing_balance),
                "statement": stmt.meta.get("statement_no", ""),
            }
        )

    if accounts_summary:
        actual.commit()  # atomowo po całym mailu; commit tylko gdy coś zaimportowano
    statement_no = accounts_summary[0]["statement"] if accounts_summary else ""
    return {
        "accounts": accounts_summary,
        "skipped": skipped,
        "subject": msg.subject,
        "statement": statement_no,
    }


def run() -> None:
    cfg = load()
    if not cfg.enabled_banks:
        log.info("ENABLED_BANKS puste — nic do zrobienia.")
        return
    banks = [load_bank(name) for name in cfg.enabled_banks]

    with open_mailbox(cfg) as mailbox, open_actual(cfg) as actual:
        for bank in banks:
            messages = fetch_unseen(mailbox, bank.imap_folder)
            log.info("Bank %s: %d nieprzeczytanych maili.", bank.name, len(messages))
            for msg in messages:
                try:
                    summary = process_message(bank, msg, actual, cfg)
                    mark_processed(mailbox, bank.imap_folder, msg.uid, bank.processed_folder)
                    notify.success(cfg.discord_webhook_url, bank.name, summary)
                    log.info("OK: %s / %s", bank.name, msg.subject)
                except Exception as error:  # noqa: BLE001 — błąd jednego maila nie ubija reszty
                    log.exception("Błąd przy mailu %s (%s)", msg.subject, bank.name)
                    try:
                        notify.failure(cfg.discord_webhook_url, bank.name, msg.subject, error)
                    except Exception:  # noqa: BLE001
                        log.exception("Nie udało się wysłać powiadomienia o błędzie.")


if __name__ == "__main__":
    try:
        run()
    except ConfigError as e:
        log.error("Błąd konfiguracji: %s", e)
        raise SystemExit(1)
