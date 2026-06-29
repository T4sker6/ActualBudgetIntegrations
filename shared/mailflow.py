"""Operacje IMAP na koncie śmieciowym: pobranie nieprzeczytanych, oznaczenie, przeniesienie.

Używa imap-tools. Gmail udostępnia etykiety jako foldery IMAP; `move` realizuje
COPY do etykiety docelowej + skasowanie ze źródłowej (przeniesienie między etykietami).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from imap_tools import AND, MailBox, MailMessage, MailMessageFlags

from .config import Config


@contextmanager
def open_mailbox(cfg: Config) -> Iterator[MailBox]:
    """Otwiera połączenie IMAP (kontekst zamyka je automatycznie)."""
    mailbox = MailBox(cfg.imap_host)
    mailbox.login(cfg.imap_user, cfg.imap_app_password)
    try:
        yield mailbox
    finally:
        mailbox.logout()


def fetch_unseen(mailbox: MailBox, folder: str) -> list[MailMessage]:
    """Pobiera WSZYSTKIE nieprzeczytane maile z folderu do pamięci.

    Pełna materializacja (list(...)) + mark_seen=False chroni przed unieważnieniem
    UID, gdy w trakcie pętli przenosimy maile do innego folderu.
    """
    mailbox.folder.set(folder)
    return list(mailbox.fetch(AND(seen=False), mark_seen=False, bulk=True))


def mark_processed(mailbox: MailBox, folder: str, uid: str, processed_folder: str) -> None:
    """Oznacza maila jako przeczytanego i przenosi do folderu 'processed'.

    Wywoływane tylko po pełnym sukcesie przetworzenia maila.
    """
    mailbox.folder.set(folder)
    mailbox.flag(uid, MailMessageFlags.SEEN, True)
    mailbox.move(uid, processed_folder)
