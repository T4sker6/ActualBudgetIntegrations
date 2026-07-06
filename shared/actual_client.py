"""Klient Actual Budget: otwarcie budżetu, idempotentny import transakcji.

Deduplikacja: każdej transakcji nadajemy deterministyczny imported_id, a do
reconcile_transaction przekazujemy rosnącą listę already_matched. Dzięki temu
ponowne przetworzenie tego samego (lub nakładającego się) wyciągu nie tworzy dubli
— bezpieczny retry po błędzie i katch-up po dniach offline.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from typing import Iterator

from actual import Actual
from actual.queries import get_account, reconcile_transaction

from .config import Config
from .models import Transaction


class AccountNotFoundError(Exception):
    """Konto o danej nazwie nie istnieje w budżecie Actual."""


def imported_id(bank: str, account_number: str, tx: Transaction) -> str:
    """Stabilny identyfikator transakcji (do deduplikacji między uruchomieniami)."""
    raw = f"{bank}|{account_number}|{tx.booking_date.isoformat()}|{tx.amount}|{tx.balance_after}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class ActualClient:
    def __init__(self, actual: Actual):
        self._actual = actual
        self._added: list = []  # already_matched dla całej sesji

    @property
    def session(self):
        return self._actual.session

    def import_transactions(
        self, bank: str, account_name: str, account_number: str, transactions: list[Transaction]
    ) -> int:
        """Importuje transakcje na wskazane (istniejące) konto Actual. Zwraca liczbę dodanych."""
        account = get_account(self.session, account_name)
        if account is None:
            raise AccountNotFoundError(
                f"Konto '{account_name}' nie istnieje w budżecie Actual — załóż je ręcznie."
            )
        before = len(self._added)
        for tx in transactions:
            result = reconcile_transaction(
                self.session,
                date=tx.booking_date,
                account=account,
                payee=tx.payee,
                notes=tx.description,
                category=None,
                amount=tx.amount,
                imported_id=imported_id(bank, account_number, tx),
                cleared=True,
                already_matched=self._added,
            )
            self._added.append(result)
        return len(self._added) - before

    def commit(self) -> None:
        self._actual.commit()


@contextmanager
def open_actual(cfg: Config) -> Iterator[ActualClient]:
    """Otwiera budżet Actual raz na przebieg (kontekst zamyka połączenie)."""
    with Actual(
        base_url=cfg.actual_base_url,
        password=cfg.actual_password,
        encryption_password=cfg.actual_encryption_password,
        file=cfg.actual_file,
        cert=True if cfg.actual_verify_ssl else False,  # False = pomiń weryfikację (self-signed HTTPS)
    ) as actual:
        actual.download_budget()
        yield ActualClient(actual)
