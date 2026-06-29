# PKOBankIntegration (szkielet)

Szablon modułu banku — **parser nie jest jeszcze zaimplementowany**. Służy jako
wzór do dodania własnego banku.

## Jak uruchomić

1. Zaimplementuj `parse()` w `parse_pdf.py` (PDF + hasło → `ParsedStatement`),
   wzorując się na `VeloBankIntegration/parse_pdf.py`.
2. Ustaw w `bank.py`: `imap_folder`, `processed_folder`, `pdf_password_env`.
3. Skopiuj `accounts.example.json` → `accounts.json` i uzupełnij mapowanie.
4. Ustaw `PKO_PDF_PASSWORD` w `.env` i dodaj `pko` do `ENABLED_BANKS`.

Dopóki parser zgłasza `NotImplementedError`, nie dodawaj `pko` do `ENABLED_BANKS`.
