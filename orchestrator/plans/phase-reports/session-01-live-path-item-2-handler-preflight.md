# Session 01 Live Path Item 2: Handler Preflight

- Session: 01
- Phase: Live path item 2
- Owner: Workbench
- Feature IDs: AUTO-003, AUTO-004, AUTO-005, PERSIST-002
- Migration Groups: MIG-008
- Status: blocked-by-intake-freshness
- Acceptance Evidence: Ran real-DB handler preflight only with `runner_mode=calibration_debt_production` and `predquant.ads_scoreable_canary_handlers:build_stage_handlers`. Handler coverage, active-run checks, and active-lease checks passed, but the preflight returned `ok=false` because no eligible ADS case was available under the current forecast timestamp and snapshot-age policy.
- Checks Run: `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path orchestrator/scripts/data/predquant.sqlite3 --runner-mode calibration_debt_production --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --preflight-only --updated-by workbench --reason "2026-06-26 ADS handler preflight only" --metadata-json '{"live_path_item":"2","scope":"handler_preflight_only"}' --pretty`
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Add an operational live-path prerequisite that current market intake must be refreshed before real-time scoreable canaries. As observed on 2026-06-26, the DB had 2,730 snapshots and 34 open markets, but `MAX(market_snapshots.observed_at)` was `2026-06-25T01:45:58.501485+00:00`, outside the one-hour default snapshot-age policy for a current forecast timestamp.
- Blockers: Live scoreable preflight cannot pass until market snapshots are refreshed or a cloned/historical canary intentionally supplies a forecast timestamp near the existing snapshots. No `market_predictions`, `forecast_decision_records`, or `scae_ledger_outputs` rows were written.
- Commit SHA: see containing commit
