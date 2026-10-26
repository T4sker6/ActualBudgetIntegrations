# PKOBankIntegration

Parser **miesięcznych** wyciągów PKO BP. PKO nie udostępnia wyciągów dziennych
mailem, więc ten moduł jest używany **ręcznie** (nie przez `run.py`): parsujesz
plik PDF, sprawdzasz saldo i eksportujesz CSV do ręcznego importu w Actual.

## Jak uruchomić

```bash
# wydruk kontrolny + walidacja salda
.venv/Scripts/python -m PKOBankIntegration.parse_pdf Wyciag_7_....pdf

# to samo + eksport CSV do importu w Actual
.venv/Scripts/python -m PKOBankIntegration.parse_pdf Wyciag_7_....pdf --csv pko.csv
```

CSV ma kolumny `Data,Odbiorca,Opis,Kwota,Saldo` (data ISO, kwota z kropką,
UTF-8 z BOM). Przy imporcie w Actual zmapuj `Data→date`, `Odbiorca→payee`,
`Opis→notes`, `Kwota→amount`; kolumnę `Saldo` (kontrolną) pomiń.

## Jak to działa

- Tekst z PDF (pdfplumber), parsowanie liniowe — patrz docstring w `parse_pdf.py`.
- Linia startowa transakcji = `Data operacji <id> <TYP> <kwota> <saldo>`,
  kolejna = `Data waluty <opis>` (+ kontynuacje). `Saldo poprzednie`/`Saldo końcowe`
  wyznaczają salda; `Saldo z/do przeniesienia` i stopki stron są pomijane.
- **payee**: sprzedawca (po `Lokalizacja:` dla kart/BLIK/WEB) albo kontrahent
  (nazwa po numerze rachunku dla przelewów), `Autooszczędzanie` dla autozapisu.
- **notes**: TYP operacji (karty) albo tytuł przelewu.
- Bezpiecznik: `saldo_pocz + Σ kwot == saldo_końc` (patrz `Walidacja salda: OK`).

## Uwaga

Nie dodawaj `pko` do `ENABLED_BANKS` w automatyzacji — wyciągi PKO są miesięczne,
a orchestrator importuje tylko wyciągi dzienne. `accounts.json` jest potrzebny
tylko gdyby kiedyś użyć `map_account`; do ręcznego CSV nie jest wymagany.
