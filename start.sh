#!/bin/bash
set -e

# Strefa czasowa (dla harmonogramu i logów). TZ pochodzi z Dockerfile/compose.
ln -sf "/usr/share/zoneinfo/${TZ:-Europe/Warsaw}" /etc/localtime
echo "${TZ:-Europe/Warsaw}" > /etc/timezone

touch /app/run.log

# Codziennie o 20:00 czasu warszawskiego. CRON_TZ wymusza strefę harmonogramu.
# Cron nie musi dziedziczyć env — run.py sam wczytuje /app/.env (python-dotenv).
echo "CRON_TZ=${TZ:-Europe/Warsaw}
0 20 * * * cd /app && /usr/local/bin/python run.py >> /app/run.log 2>&1
" | crontab -

cron
echo "Cron uruchomiony — wyciągi przetwarzane codziennie o 20:00 (${TZ:-Europe/Warsaw})."
# tail trzyma kontener przy życiu i pokazuje wynik w 'docker logs'.
tail -f /app/run.log
