# Session 01 Live Path Item 3: Cloned One-Case Canary

- Session: 01
- Phase: Live path item 3
- Owner: Workbench
- Feature IDs: AUTO-003, AUTO-004, AUTO-005, PERSIST-002, MIG-001, MIG-007, MIG-009
- Migration Groups: MIG-001, MIG-007, MIG-008, MIG-009
- Status: complete
- Acceptance Evidence: Recreated a clone of `orchestrator/scripts/data/predquant.sqlite3` at `/tmp/openclaw-canary-clones/predquant-item3-one-case-20260626.sqlite3` and ran a one-case scoreable ADS canary using forecast timestamp `2026-06-25T01:50:00+00:00`. The final run returned `ok=true`, terminal status `stopped_after_current_case`, completed all 13 ADS stages, released the lease, disabled the clone control state, wrote one `forecast_decision_records` row, and wrote one `market_predictions` row.
- Checks Run: `python3 orchestrator/scripts/bin/run_ads_one_case_canary.py --db-path /tmp/openclaw-canary-clones/predquant-item3-one-case-20260626.sqlite3 --runner-mode calibration_debt_production --forecast-timestamp 2026-06-25T01:50:00+00:00 --handler-factory predquant.ads_scoreable_canary_handlers:build_stage_handlers --apply --updated-by workbench --reason "2026-06-26 cloned DB one-case scoreable ADS canary" --metadata-json '{"live_path_item":"3","scope":"cloned_db_one_case","forecast_timestamp_basis":"latest_clone_snapshot"}' --pretty`; `python3 -m unittest orchestrator/scripts/tests/test_ads_case_contract.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_ads_handoff.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_ads_operational_canary.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_ads_pipeline_runner.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_prediction_provenance.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_training_trace.py orchestrator/scripts/tests/test_replay.py -v`
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Record that live DB clones exposed schema-drift surfaces not covered by in-memory greenfield tests.
- Blockers: Initial clone attempts failed at decision-stage persistence because the live DB had compact legacy `case_artifact_manifest` and training-trace table shapes. Fixed by running artifact manifest compatibility before the foundation migration and by adding a pre-operational compatibility pass for compact training-trace tables before `OPERATIONAL_SCHEMA`.
- Commit SHA: see containing commit
