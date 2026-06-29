# VeloBankIntegration

Moduł banku **Velo** dla orchestratora `run.py`.

## Konfiguracja

1. Hasło do PDF wyciągów: ustaw `VELO_PDF_PASSWORD` w `.env`.
2. Mapowanie kont: skopiuj `accounts.example.json` → `accounts.json` (gitignored) i
   uzupełnij: klucz = końcówka numeru rachunku z wyciągu, wartość = nazwa Twojego
   konta w Actual (dowolna, jaką ustawiłeś w Actual).
3. Foldery IMAP na koncie śmieciowym (stałe w `bank.py`):
   - `velo-billing` — nowe maile (nieprzeczytane),
   - `velo-billing-processed` — maile po udanym imporcie.
4. Dodaj `velo` do `ENABLED_BANKS` w `.env`.

## Pliki

- `bank.py` — metadane banku + delegacja do parsera.
- `parse_pdf.py` — parser PDF wyciągu Velo → `ParsedStatement`.
- `accounts.example.json` — wzór mapowania (numer → nazwa konta w Actual).
