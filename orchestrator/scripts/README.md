# OpenClaw Pipeline Runtime Scripts

This folder is the dedicated runtime script surface for `.openclaw` pipeline work owned by Orchestrator.
It contains the Quant Pipeline market intake and Brier scoring modules without bringing in the whole v2 forecasting pipeline.

## Pipeline Runtime Home

Going forward, all `.openclaw` pipeline runtime scripts belong under `/Users/agent2/.openclaw/orchestrator/scripts`.
This is the single home for Orchestrator-run pipeline intake, controls, maintenance, scoring, reporting, and related runtime utilities.
Do not scatter new pipeline runtime scripts across other `.openclaw` folders; add them here and file each item into the appropriate location from the folder contract below.

## Folder Contract

- `bin/`: runnable entrypoints, one-shot jobs, maintenance commands, and shell wrappers.
- `predquant/`: importable Python source for intake, storage, scoring, resolution sync, and shared helpers.
- `migrations/`: ordered SQLite schema migrations and foundation dependencies.
- `data/`: local SQLite databases and other durable data files.
- `.runtime-state/`: generated reports, heartbeats, logs, locks, and transient market payloads.
- `requirements.txt`: Python dependencies for this bundle.
- `ingest_polymarket_market_snapshots.py` and `check_pipeline_health.py`: root compatibility shims for existing launchd plists.

Root files should stay minimal. New runnable scripts belong in `bin/`; new reusable logic belongs in `predquant/`.

## Script Index

| Path | Purpose | Typical use |
| --- | --- | --- |
| `ingest_polymarket_market_snapshots.py` | Launchd-compatible shim for the automated intake cycle. | Existing scheduled job; delegates to `bin/ingest_polymarket_market_snapshots.py`. |
| `check_pipeline_health.py` | Launchd-compatible shim for SQLite market pipeline health. | Existing scheduled job; delegates to `bin/check_pipeline_health.py`. |
| `bin/ingest_polymarket_market_snapshots.py` | One-shot intake runner: initialize SQLite, close expired markets, sync resolutions, fetch markets, store snapshots, and write reports. | Main automated market intake entrypoint. |
| `bin/check_pipeline_health.py` | Report database health, snapshot freshness, scoring gaps, and resolution sync freshness. | Scheduled healthcheck and manual diagnostics. |
| `bin/run_polymarket_ingest.sh` | Shell wrapper for the full intake flow using the smaller CLI commands. | Manual batch run or local debugging. |
| `bin/init_sqlite_db.py` | Initialize or migrate the local SQLite database. | Setup and migration checks. |
| `bin/fetch_polymarket_markets.py` | Fetch and filter Polymarket Gamma API markets into a JSON payload. | Inspect or stage source market data. |
| `bin/push_filtered_markets.py` | Load a filtered market JSON payload into SQLite and record snapshots. | Manual ingestion after fetch. |
| `bin/cleanup_expired_markets.py` | Mark expired open markets closed according to end-time controls. | Maintenance before and after intake. |
| `bin/sync_polymarket_resolutions.py` | Pull final Polymarket outcomes and score settled predictions. | Resolution sync and Brier scoring. |
| `bin/record_market_prediction.py` | Record a pipeline probability against the latest stored market snapshot. | Store predictions from the forecasting pipeline. |
| `bin/record_prediction_with_snapshot.py` | Atomically store a source market payload and the pipeline prediction made from it. | Prediction-time provenance capture. |
| `bin/settle_market_outcome.py` | Manually settle a market and score its predictions. | Override or backfill outcomes when source sync is insufficient. |
| `bin/report_brier_scores.py` | Summarize pipeline Brier scores against prediction-time market baselines. | Accuracy reporting. |
| `bin/ingest_market.py` | Compatibility wrapper for the SQLite store ingestion CLI. | Legacy/manual single-market ingestion path. |

## Source Index

| Path | Responsibility |
| --- | --- |
| `predquant/brier.py` | Probability validation, market probability extraction, and Brier scoring helpers. |
| `predquant/polymarket_intake.py` | Polymarket Gamma API fetch/filter logic. |
| `predquant/pipeline.py` | Load filtered markets into SQLite. |
| `predquant/polymarket_resolution.py` | Source-backed Polymarket resolution sync. |
| `predquant/sqlite_store.py` | SQLite schema, market snapshot storage, prediction recording, settlement, and Brier persistence. |
| `predquant/foundation_schema.py` | Foundation schema dependency used by `sqlite_store.py`. |
| `migrations/001_foundation_persistence_and_artifacts.sql` | Ordered schema migration required by this bundle. |

## Adding Future Scripts

Use this layout when adding new work:

- Add all `.openclaw` pipeline runtime scripts under `/Users/agent2/.openclaw/orchestrator/scripts`, then place each file according to the folder contract.
- Put executable scripts in `bin/` with a clear verb phrase, such as `sync_source_name.py`, `report_metric_name.py`, or `cleanup_resource_name.py`.
- Put shared logic in `predquant/` first, then keep `bin/` scripts thin: parse arguments, call library functions, print JSON or concise status.
- Keep generated files out of source folders. Durable data goes in `data/`; reports, logs, heartbeats, locks, and temporary payloads go in `.runtime-state/`.
- Keep launchd-facing root files as compatibility shims only. If a scheduled job needs a new root path, document why in this README.
- Prefer JSON output for scripts that will be consumed by Orchestrator or health checks.
- For new schema changes, add a numbered migration under `migrations/` and make initialization idempotent.
- Add every new runnable script to the Script Index in this README before considering the folder organized.

## Setup

```bash
cd /Users/agent2/.openclaw/orchestrator/scripts
python3 -m pip install -r requirements.txt
python3 bin/init_sqlite_db.py --db-path data/predquant.sqlite3
```

## Main Commands

```bash
python3 bin/fetch_polymarket_markets.py --output filtered_markets.json
python3 bin/push_filtered_markets.py --input filtered_markets.json --db-path data/predquant.sqlite3
python3 bin/record_market_prediction.py --external-market-id MARKET_ID --probability 0.62 --db-path data/predquant.sqlite3
python3 bin/sync_polymarket_resolutions.py --db-path data/predquant.sqlite3
python3 bin/report_brier_scores.py --db-path data/predquant.sqlite3 --pretty
```

The one-shot intake flow initializes SQLite, marks expired markets closed, syncs source-backed resolutions, fetches filtered Polymarket markets, stores snapshots, then repeats cleanup/resolution sync:

```bash
bin/run_polymarket_ingest.sh
```

The root-level launchd-compatible entrypoint does the same work and writes an optional heartbeat/report:

```bash
python3 ingest_polymarket_market_snapshots.py \
  --db-path data/predquant.sqlite3 \
  --report-file .runtime-state/polymarket-snapshot-ingester-heartbeat.json \
  --apply \
  --pretty
```

## Prediction and Brier Lifecycle

Record a pipeline forecast against an already-ingested market:

```bash
python3 bin/record_market_prediction.py \
  --external-market-id MARKET_ID \
  --probability 0.62 \
  --db-path data/predquant.sqlite3
```

At prediction time, the recorder stores the latest available market snapshot and derives the market baseline probability from bid/ask midpoint, then yes price, then last price/current price. When the market resolves, `settle_market_outcome.py` or `sync_polymarket_resolutions.py` updates `market_predictions` with both:

- `prediction_brier`: pipeline probability vs final outcome.
- `market_brier`: prediction-time market baseline probability vs final outcome.

Check current SQLite health:

```bash
python3 check_pipeline_health.py --db-path data/predquant.sqlite3 --pretty
```

Summarize scored forecasts:

```bash
python3 bin/report_brier_scores.py --db-path data/predquant.sqlite3 --pretty
```

`avg_brier_edge` is `avg_market_brier - avg_prediction_brier`; positive values mean the pipeline beat the prediction-time market baseline.

## Boundary

This bundle does not include the v2 decomposition, retrieval, classification, SCAE, calibration, UI, or agent runtime.
Those should stay in the main Quant Pipeline repo unless OpenClaw is explicitly being wired to run those stages.
