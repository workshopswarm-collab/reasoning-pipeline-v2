# Session 02 FIX-037: Existing Intake To ADS Case Contract

- Session: 02 Evidence Packet, Policy Context, and AMRG
- Phase: Wave B fixture/blocker reconciliation
- Owner: Session 2, with Session 5 forecast provenance dependency awareness
- Feature IDs: `CASE-001`, `CASE-002`, `CTX-001`, `MIG-012`
- Migration Groups: `MIG-012`
- Fixture IDs: `FIX-037`
- Blocker IDs: `BLK-030`
- Status: `FIX-037` passing; `BLK-030` passed.
- Acceptance Evidence: Existing case-contract tests prove real SQLite `markets` and `market_snapshots` rows materialize into `ads-case-contract/v1`; the selected pre-forecast snapshot is the latest safe snapshot, not an older or post-forecast row; `intake_source` records source table names, market row ID, snapshot row ID, source payload hash, ingestion runner, and schema version; `prediction_time_market_baseline` records snapshot age, max age policy, market probability, and probability method; raw input refs include source row IDs and payload hash; artifact manifests and handoff records are persisted idempotently; stale, lookahead, and missing snapshots block with explicit reason codes before evidence packet construction.
- Checks Run: `python3 -m unittest orchestrator.scripts.tests.test_ads_case_contract` PASS (9 tests); `python3 -m unittest discover -s orchestrator/scripts/tests` PASS (156 tests); `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. The owned case-contract rows are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: Mark `FIX-037` `passing` and `BLK-030` `passed`.
- Blockers: none for `FIX-037` / `BLK-030`.
- Newly Unblocked Rows: `BLK-030` is no longer a live-cutover blocker.
- Commit SHA: pending at report authoring.
