# OpenClaw Pipeline Runtime Scripts

This folder is the dedicated runtime script surface for `.openclaw` pipeline work owned by Orchestrator.
It contains the Quant Pipeline market intake and Brier scoring modules without bringing in the whole v2 forecasting pipeline.

## Pipeline Runtime Home

Going forward, all `.openclaw` pipeline runtime scripts belong under `/Users/agent2/.openclaw/orchestrator/scripts`.
This is the single home for Orchestrator-run pipeline intake, controls, maintenance, scoring, reporting, and related runtime utilities.
Do not scatter new pipeline runtime scripts across other `.openclaw` folders; add them here and file each item into the appropriate location from the folder contract below.

## Agent Roles

- Workbench is the development surface. Use Workbench for implementation, edits, refactors, docs, script design, tests, and cleanup work across `.openclaw`.
- Orchestrator is the functionality and execution surface. Use Orchestrator for live pipeline runtime behavior, scheduled jobs, intake, controls, scoring, reporting, and operational execution.
- Maintenance is the repository maintenance surface. Use Maintenance for repo hygiene, dependency upkeep, routine checks, cleanup, and non-feature maintenance tasks.

Keep development work, live execution, and repo maintenance distinct. Runtime scripts still live in this folder, but Workbench should make changes to them as development work; Orchestrator should run them as operational behavior; Maintenance should keep the repository healthy around them.

## Folder Contract

- `bin/`: runnable entrypoints, one-shot jobs, maintenance commands, and shell wrappers.
- `predquant/`: importable Python source for intake, storage, scoring, resolution sync, and shared helpers.
- `migrations/`: ordered SQLite schema migrations and foundation dependencies.
- `tests/`: focused regression tests for the runtime script bundle.
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
| `bin/run_golden_fixture.py` | Run the ADS v2 golden fixture registry/result harness in fixture or runtime-dependency-check mode. | Fixture-first integration checks for Session 1-owned foundation contracts. |
| `bin/run_ads_pipeline_loop.py` | Run the AUTO-001 ADS pipeline runner contract skeleton. | Safe control-plane check; refuses start while disabled and never selects cases or persists forecasts. |
| `bin/set_ads_pipeline_enabled.py` | Enable or disable the durable AUTO-006 ADS pipeline control switch. | Manual operator control for whether new runner starts and case leases are allowed. |
| `bin/get_ads_pipeline_control.py` | Inspect the durable AUTO-006 ADS pipeline control row. | Manual diagnostics for enablement, desired runner mode, disable action, reason, metadata, and acknowledgement. |

## Source Index

| Path | Responsibility |
| --- | --- |
| `predquant/brier.py` | Probability validation, market probability extraction, and Brier scoring helpers. |
| `predquant/polymarket_intake.py` | Polymarket Gamma API fetch/filter logic. |
| `predquant/pipeline.py` | Load filtered markets into SQLite. |
| `predquant/polymarket_resolution.py` | Source-backed Polymarket resolution sync. |
| `predquant/sqlite_store.py` | SQLite schema, market snapshot storage, prediction recording, settlement, and Brier persistence. |
| `predquant/foundation_schema.py` | Foundation schema dependency used by `sqlite_store.py`. |
| `predquant/golden_fixtures.py` | Golden fixture matrix parser, starter fixture specs, fail-closed validation harness, and fixture registry/result writers. |
| `predquant/ads_pipeline_runner.py` | AUTO-001 pipeline control-state, run identity, stage-order, no-live-autostart, and non-executing runner skeleton helpers. |
| `predquant/ads_case_selector.py` | AUTO-002 eligible-case selection plus disabled-gated case lease and idempotency helpers over intake rows. |
| `predquant/ads_pipeline_control.py` | AUTO-006 durable manual pipeline enablement, inspection, and acknowledgement helpers. |
| `migrations/001_foundation_persistence_and_artifacts.sql` | Ordered schema migration required by this bundle. |
| `migrations/006_golden_fixture_harness.sql` | Typed golden fixture registry and result tables for ADS v2 fixture-first integration. |
| `migrations/008_pipeline_runner_contract.sql` | AUTO-001 `ads_pipeline_runs`/`ads_pipeline_control_state` and AUTO-002 `ads_case_leases` schema. |
| `tests/test_prediction_provenance.py` | Regression coverage for prediction provenance, idempotent recording, stale snapshots, and Brier scoring metadata. |

## Adding Future Scripts

Use this layout when adding new work:

- Add all `.openclaw` pipeline runtime scripts under `/Users/agent2/.openclaw/orchestrator/scripts`, then place each file according to the folder contract.
- Put executable scripts in `bin/` with a clear verb phrase, such as `sync_source_name.py`, `report_metric_name.py`, or `cleanup_resource_name.py`.
- Put shared logic in `predquant/` first, then keep `bin/` scripts thin: parse arguments, call library functions, print JSON or concise status.
- Keep generated files out of source folders. Durable data goes in `data/`; reports, logs, heartbeats, locks, and temporary payloads go in `.runtime-state/`.
- Keep launchd-facing root files as compatibility shims only. If a scheduled job needs a new root path, document why in this README.
- Prefer JSON output for scripts that will be consumed by Orchestrator or health checks.
- For new schema changes, add a numbered migration under `migrations/` and make initialization idempotent.
- Add focused tests under `tests/` for any runtime path that changes persistence, scheduling, provenance, scoring, or cleanup behavior.
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

The canonical prediction-engine write path is `bin/record_prediction_with_snapshot.py`.
Use it when the prediction engine has just fetched market data and made a prediction from that exact source payload:

```bash
python3 bin/record_prediction_with_snapshot.py \
  --file market-payload.json \
  --probability 0.62 \
  --prediction-run-id RUN_ID \
  --forecast-artifact-id FORECAST_ARTIFACT_ID \
  --case-key CASE_KEY \
  --case-id CASE_ID \
  --dispatch-id DISPATCH_ID \
  --engine-stage prediction-engine \
  --input-artifact-path artifacts/input.json \
  --input-artifact-sha256 INPUT_SHA256 \
  --prediction-artifact-path artifacts/prediction.json \
  --prediction-artifact-sha256 PREDICTION_SHA256 \
  --db-path data/predquant.sqlite3
```

This atomic path stores the market snapshot, the pipeline probability, the prediction-time market baseline, and the case/run/artifact provenance in one transaction. `prediction_run_id` and `forecast_artifact_id` are unique idempotency keys: a retry with the same values returns the existing prediction when the payload matches, and fails if the probability/source identity changed.

The recorder rejects prediction writes when the market snapshot is after the prediction timestamp or older than `--max-snapshot-age-seconds` (default: 3600 seconds). Keep the default unless the prediction engine has an explicit policy for a wider freshness window.

`bin/record_market_prediction.py` remains available for manual or legacy forecasts against an already-ingested market:

```bash
python3 bin/record_market_prediction.py \
  --external-market-id MARKET_ID \
  --probability 0.62 \
  --prediction-run-id RUN_ID \
  --forecast-artifact-id FORECAST_ARTIFACT_ID \
  --db-path data/predquant.sqlite3
```

At prediction time, the recorder derives the market baseline probability from bid/ask midpoint, then yes price, then last price/current price. When the market resolves, `settle_market_outcome.py` or `sync_polymarket_resolutions.py` updates `market_predictions` with:

- `prediction_brier`: pipeline probability vs final outcome.
- `market_brier`: prediction-time market baseline probability vs final outcome.
- `scoring_version`, `scored_at`, `scoring_resolution_payload_hash`, and `scoring_resolution_source`: scoring provenance for repeatable benchmark interpretation.

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
