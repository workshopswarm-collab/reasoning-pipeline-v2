# Session 01 Live Path Item 6: Live One-Case Canary

- Session: 01
- Phase: Live path item 6
- Owner: Workbench
- Feature IDs: AUTO-003, AUTO-004, PERSIST-001, PERSIST-002
- Migration Groups: MIG-008, MIG-013
- Status: complete
- Acceptance Evidence: Took a pre-run backup at `/tmp/openclaw-canary-backups/predquant-live-before-item6-one-case-20260626T144254Z.sqlite3` and ran one live scoreable ADS canary against `orchestrator/scripts/data/predquant.sqlite3`. The harness returned `ok=true`, terminal status `stopped_after_current_case`, completed all 13 ADS stages, wrote one `forecast_decision_records` row, wrote one `market_predictions` row, released the case lease, and disabled pipeline control in postflight.
- Checks Run: `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path orchestrator/scripts/data/predquant.sqlite3 --runner-mode calibration_debt_production --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --apply --updated-by workbench --reason "2026-06-26 live one-case scoreable ADS canary" --metadata-json '{"live_path_item":"6","scope":"live_db_one_case"}' --pretty`
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Record that the first live scoreable canary write path has passed with bounded one-case execution and automatic postflight disable.
- Blockers: None for one-case live canary. Result run `ads-pipeline-run:7202f10437b346fca0a119d07e205cfeb268ae86f7e976741a48f94592f2c82a`, lease `ads-case-lease:cf41d10fb66a2dfc16f708d6748c2b930d64a8996f67c30cb17f6835f9c39938`, forecast decision `forecast-decision-089c1374f38b85abdd4d6e07`; protected deltas were `forecast_decision_records=1`, `market_predictions=1`, `scae_ledger_outputs=0`.
- Commit SHA: see containing commit
