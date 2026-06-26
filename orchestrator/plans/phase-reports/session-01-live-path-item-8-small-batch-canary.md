# Session 01 Live Path Item 8: Small Batch Canary

- Session: 01
- Phase: Live path item 8
- Owner: Workbench
- Feature IDs: AUTO-005, AUTO-004, PERSIST-001, PERSIST-002
- Migration Groups: MIG-008, MIG-013
- Status: complete
- Acceptance Evidence: Took a pre-run backup at `/tmp/openclaw-canary-backups/predquant-live-before-item8-small-batch-20260626T1445Z.sqlite3`, ran a live two-case canary with `--max-cases 2`, and audited the resulting live DB state. The harness returned `ok=true`, terminal status `auto005_max_cases_complete`, zero active runs, zero active leases, disabled control state, two released leases, two loop iterations, 26 completed stage records for the batch cases, zero v2 pipeline error events for the batch run, two new `forecast_decision_records` rows, and two new `market_predictions` rows.
- Checks Run: `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path orchestrator/scripts/data/predquant.sqlite3 --runner-mode calibration_debt_production --max-cases 2 --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --preflight-only --updated-by workbench --reason "2026-06-26 live small batch preflight" --metadata-json '{"live_path_item":"8","scope":"live_small_batch_preflight","max_cases":2}' --pretty`; `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path orchestrator/scripts/data/predquant.sqlite3 --runner-mode calibration_debt_production --max-cases 2 --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --apply --updated-by workbench --reason "2026-06-26 live two-case scoreable ADS canary" --metadata-json '{"live_path_item":"8","scope":"live_small_batch","max_cases":2}' --pretty`; read-only SQLite audit queries for the batch run.
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Record that the bounded AUTO-005 small-batch live canary path passed with max-case termination and no active work left behind.
- Blockers: None for bounded small-batch canary. The batch run was `ads-pipeline-run:5a4b56e9c605ee64b95529c24fee5ddff36e4cb77786ef7540253de2071508e8`; predictions `2` and `3` were written for markets `704026` and `825559` with probabilities `0.915` and `0.705`. Total live DB prediction count after this item is `3`.
- Commit SHA: see containing commit
