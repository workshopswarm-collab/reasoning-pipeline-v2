# Session 01 Live Path Item 5: Live DB Preflight

- Session: 01
- Phase: Live path item 5
- Owner: Workbench
- Feature IDs: AUTO-003, AUTO-004, PERSIST-002
- Migration Groups: MIG-008
- Status: complete
- Acceptance Evidence: Took a backup at `/tmp/openclaw-canary-backups/predquant-live-before-item5-refresh-20260626T144043Z.sqlite3`, refreshed live intake with the existing Polymarket ingester, then ran live DB preflight only. Preflight returned `ok=true`, zero active runs, zero active leases, protected forecast/prediction counts at zero, and one eligible case.
- Checks Run: `python3 orchestrator/scripts/bin/ingest_polymarket_market_snapshots.py --db-path orchestrator/scripts/data/predquant.sqlite3 --apply --output /tmp/openclaw-canary-backups/item5-ingest-output-20260626T144043Z.json --report-file /tmp/openclaw-canary-backups/item5-ingest-report-20260626T144043Z.json --pretty`; `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path orchestrator/scripts/data/predquant.sqlite3 --runner-mode calibration_debt_production --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --preflight-only --updated-by workbench --reason "2026-06-26 live ADS preflight after intake refresh" --metadata-json '{"live_path_item":"5","scope":"live_db_preflight","intake_refresh":"2026-06-26T14:41:17Z"}' --pretty`
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Record that live preflight requires a current intake refresh when the DB snapshot age exceeds the default case-selection freshness window.
- Blockers: None for live preflight. Intake refresh loaded 16 markets, grew snapshots from 2,730 to 2,746, resolved market `648378` with zero prediction updates, and left `market_predictions=0`. The preflight-selected live case was market `679583`, case `case-475481988df99fa7630b18e2`, snapshot `2733`, observed at `2026-06-26T14:41:17.217985+00:00`, with snapshot age `24.148372` seconds.
- Commit SHA: see containing commit
