# ActualBudgetIntegration

Automatyczne wciąganie dziennych wyciągów bankowych (z maila) do
[Actual Budget](https://actualbudget.org/). Wielobankowe i konfigurowalne —
włączasz tylko te banki, których używasz.

## Jak to działa

1. Bank wysyła raz dziennie maila z wyciągami w załącznikach `.zip` (jeden PDF na
   konto; każdy PDF chroniony statycznym hasłem).
2. Reguła na głównym Gmailu **forwarduje** tego maila na osobne konto „śmieciowe".
3. Reguła na koncie śmieciowym nadaje etykietę per bank (np. `velo-billing`).
4. Skrypt (`run.py`, cron raz dziennie) loguje się przez **IMAP** do konta
   śmieciowego, bierze nieprzeczytane maile, dla każdego: rozpakowuje PDF →
   parsuje → waliduje salda → importuje do Actual (bez duplikatów) → przenosi maila
   do `…-processed`.
5. O wyniku każdego maila przychodzi **powiadomienie na Discord** (✅ / ❌ z opisem
   błędu). Gdy homelab był offline kilka dni, przetwarzane są wszystkie zaległe
   maile — każdy z osobnym powiadomieniem.

Przy błędzie mail **zostaje nieprzeczytany** i jest ponawiany następnego dnia.
Deduplikacja w Actual (po `imported_id`) sprawia, że ponowne przetworzenie nie
tworzy duplikatów.

## Struktura

```
run.py                  # orchestrator: czyta ENABLED_BANKS, przetwarza maile
shared/                 # kod wspólny dla wszystkich banków
  config.py             # wczytanie/walidacja .env
  models.py             # Transaction, ParsedStatement, kontrakt Bank
  mailflow.py           # IMAP (fetch / oznacz / przenieś)
  extract.py            # zip → PDF
  actual_client.py      # import do Actual + deduplikacja
  statements.py         # walidacja salda, mapowanie kont, CSV
  notify.py             # webhook Discord
VeloBankIntegration/    # bank Velo (parser + mapowanie kont)
PKOBankIntegration/     # szablon-szkielet kolejnego banku
```

## Konfiguracja

1. Skopiuj `.env.example` → `.env` i uzupełnij (IMAP, Discord, Actual, hasła PDF).
2. Dla każdego włączonego banku: w jego katalogu skopiuj `accounts.example.json` →
   `accounts.json` i uzupełnij mapowanie (końcówka numeru rachunku → nazwa konta
   w Actual; nazwę konta ustawiasz w Actual dowolnie).
3. Ustaw `ENABLED_BANKS` w `.env` (np. `velo` lub `velo,pko`).

`.env` i `accounts.json` są w `.gitignore` i `.dockerignore` — nie trafiają do
repo ani do obrazu.

### Konfiguracja poczty (jednorazowo)

- Główny Gmail: filtr „od banku / z wyciągiem" → przekaż na konto śmieciowe.
- Konto śmieciowe: włącz IMAP + 2FA, wygeneruj App Password; filtr → etykieta
  `velo-billing` (Pomiń Odebrane); utwórz etykietę `velo-billing-processed`.

## Uruchomienie (Docker)

```bash
docker compose up --build -d      # cron odpala run.py codziennie o 20:00 Europe/Warsaw
docker compose logs -f            # podgląd
docker compose exec bank-actual python run.py   # ręczne uruchomienie (test)
```

Bez Dockera: `pip install -r requirements.txt && python run.py`.

## Dodanie własnego banku

1. Skopiuj `PKOBankIntegration` jako szablon → `<Nazwa>BankIntegration`.
2. Zaimplementuj `parse_pdf.parse()` (PDF + hasło → `ParsedStatement`).
3. Ustaw w `bank.py`: `name`, foldery IMAP, `pdf_password_env`.
4. Dodaj wpis do `BANK_MODULES` w `run.py` i `<bank>` do `ENABLED_BANKS`.
5. Utwórz `<Bank>/accounts.json` i hasło PDF w `.env`.
