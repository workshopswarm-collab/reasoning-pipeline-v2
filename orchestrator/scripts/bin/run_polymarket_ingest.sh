#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

OUTPUT_FILE="${1:-filtered_markets.json}"
DB_PATH="${PREDQUANT_SQLITE_PATH:-data/predquant.sqlite3}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

"$PYTHON_BIN" bin/init_sqlite_db.py --db-path "$DB_PATH"
"$PYTHON_BIN" bin/cleanup_expired_markets.py --db-path "$DB_PATH"
"$PYTHON_BIN" bin/sync_polymarket_resolutions.py --db-path "$DB_PATH"
"$PYTHON_BIN" bin/fetch_polymarket_markets.py --output "$OUTPUT_FILE"
"$PYTHON_BIN" bin/push_filtered_markets.py --input "$OUTPUT_FILE" --db-path "$DB_PATH"
"$PYTHON_BIN" bin/cleanup_expired_markets.py --db-path "$DB_PATH"
"$PYTHON_BIN" bin/sync_polymarket_resolutions.py --db-path "$DB_PATH"
