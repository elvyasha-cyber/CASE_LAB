#!/usr/bin/env bash
# Плановый прогон для Linux/macOS (cron).
# Пример crontab: */10 * * * * /path/to/CASE_LAB/scripts/run_scheduled.sh >> /path/to/CASE_LAB/out/cron.log 2>&1

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Не найден .venv. Сначала создайте окружение и установите пакет." >&2
  exit 1
fi

"$ROOT/.venv/bin/python" -m case_lab live
