# Session 05 SCAE Calibration and Conditional Reconciliation

- Session: 05
- Phase: Cutover SCAE calibration, prior, and conditional fixture/blocker reconciliation
- Owner: Session 5
- Feature IDs: `SCAE-002`, `SCAE-010`, `SCAE-011`, `SCAE-012`, `SCAE-013`, `CAL-001`
- Migration Groups: `MIG-007`, `MIG-010`
- Fixture IDs: `FIX-008`, `FIX-009`, `FIX-024`
- Blocker IDs: `BLK-010`, `BLK-011`, `BLK-016`
- Status: `FIX-008`, `FIX-009`, and `FIX-024` passing; listed blockers passed.
- Acceptance Evidence: SCAE prior fixtures prove invalid markets fall back to a materialized structural/base-rate prior, stale/thin market priors receive a reliability ceiling, fresh/liquid priors receive a reliability floor, and old public evidence receives market assimilation discounting so priced information is not double-counted. SCAE ledger and interval fixtures prove active calibration-debt tail caps, minimum interval width, debt-adjusted production probability aliasing, low-size execution authority, watch-only structural-unanswerability authority, and fail-closed non-identity/beta post-ledger calibration. SCAE conditional fixtures require explicit condition-scoped prior metadata and reject reuse of the selected unconditional market prior inside branch priors. CAL-001 fixtures prove first-100 trace completeness alone cannot clear debt, unscored or missing scorecard evidence blocks clearance, and clearance requires scored Brier evidence plus tail, regime, protected-component, and pointer-stability gates.
- Matrix Reconciliation: Marked `FIX-008`, `FIX-009`, and `FIX-024` `passing`; marked `BLK-010`, `BLK-011`, and `BLK-016` `passed`. `BLK-018`, `CAL-002`, `CAL-003`, `CAL-004`, `CAL-005`, and `MIG-011` remain Session 6 maturity scope and are not advanced by this reconciliation.
- Checks Run: focused `PYTHONPATH=SCAE/scripts python3 -m unittest SCAE/scripts/tests/test_scae_prior.py SCAE/scripts/tests/test_scae_policy.py SCAE/scripts/tests/test_scae_intervals.py SCAE/scripts/tests/test_scae_ledger.py SCAE/scripts/tests/test_scae_conditional.py` PASS; focused `python3 -m unittest orchestrator.scripts.tests.test_cal001_calibration_debt` PASS; `PYTHONPATH=SCAE/scripts python3 -m unittest discover -s SCAE/scripts/tests` PASS; `python3 -m unittest discover -s orchestrator/scripts/tests` PASS; `python3 -m unittest discover -s orchestrator/plans/tests` PASS; `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 `CAL-003`/`CAL-004`/`CAL-005` blockers; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. `CAL-001` and `MIG-010` are already `ready_for_integration`; Session 6 maturity rows remain `not_started`.
- Shared Map/Matrix Updates Requested: none beyond the fixture and blocker row updates.
- Blockers: none for this batch.
- Newly Unblocked Rows: none.
- Commit SHA: pending at report authoring.
