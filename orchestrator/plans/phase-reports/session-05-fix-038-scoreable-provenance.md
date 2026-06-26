# Session 05 FIX-038: Scoreable Forecast Provenance

- Session: 05
- Phase: Cutover fixture/blocker reconciliation
- Owner: Session 5, with Session 1/2 case-contract and runner evidence
- Feature IDs: `PERSIST-002`, `SCORE-001`
- Migration Groups: `MIG-008`, `MIG-010`
- Fixture IDs: `FIX-038`
- Blocker IDs: `BLK-031`
- Status: `FIX-038` passing; `BLK-031` passed.
- Acceptance Evidence: Added the focused SCAE persistence fixture `test_scae_market_prediction_bridge_scores_against_prediction_time_market_baseline`. The fixture seeds a real intake market and prediction-time snapshot, builds an `ads-case-contract/v1`, writes the SCAE `production_forecast_prob` through the PERSIST-002 `write_scae_market_prediction()` bridge, then resolves the same market through SCORE-001 `write_resolution_score()`. It verifies the settled market updates one scoreable prediction, creates one evaluator scorecard, records prediction Brier, market Brier, scoring version, resolution payload hash, case-contract snapshot ID, prediction-time market probability, and prediction-time market probability method on the `market_predictions` row, and verifies the scorecard mirrors the prediction row and snapshot provenance.
- Matrix Reconciliation: Marked `FIX-038` `passing` and `BLK-031` `passed`.
- Checks Run: focused `PYTHONPATH=SCAE/scripts python3 -m unittest SCAE.scripts.tests.test_scae_persistence.ScaePersistenceTest.test_scae_market_prediction_bridge_scores_against_prediction_time_market_baseline` PASS; `PYTHONPATH=SCAE/scripts python3 -m unittest discover -s SCAE/scripts/tests` PASS; `python3 -m unittest discover -s orchestrator/scripts/tests` PASS; `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `python3 -m unittest discover -s orchestrator/plans/tests` PASS; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. `PERSIST-002` and `SCORE-001` are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: none; fixture and blocker rows reconciled.
- Blockers: none for `FIX-038` / `BLK-031`. `MIG-010` remains tracked in the schema map until the coordinator explicitly reconciles the existing `market_predictions` plus `evaluator_scorecards` scoring spine against the dedicated migration row.
- Newly Unblocked Rows: none.
- Commit SHA: pending at report authoring.
