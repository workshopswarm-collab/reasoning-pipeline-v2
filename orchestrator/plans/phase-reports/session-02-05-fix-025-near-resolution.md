# Sessions 02/05 FIX-025 Near-Resolution Market Shrinkage

- Session: 02/05
- Phase: Cutover fixture reconciliation
- Owner: Sessions 2 and 5
- Feature IDs: `MODEL-001`, `SCAE-003`
- Migration Groups: none
- Fixture IDs: `FIX-025`
- Blocker IDs: none
- Status: `FIX-025` passing.
- Acceptance Evidence: Tuning-profile tests prove a near-resolution market receives the `near_resolution` regime tag and can apply `conservative_close_to_resolution_overlay` only when an active promoted overlay pointer is present; the same pointer does not apply to an `open_window` market. SCAE prior tests prove a source-grade contradiction signal blocks the fresh/liquid reliability floor and records `contradiction_signal_present`, while an ordinary instant spread-spike warning candidate is handled as ordinary uncertainty through the stale/thin reliability ceiling without a contradiction flag.
- Matrix Reconciliation: Marked `FIX-025` `passing`. No blocker row advanced from this fixture alone. `FIX-019`, `FIX-027`, `FIX-028`, `BLK-004`, and `BLK-018` remain open.
- Checks Run: focused `python3 -m unittest orchestrator.scripts.tests.test_tuning_profile orchestrator.scripts.tests.test_evidence_packet` PASS; focused `PYTHONPATH=SCAE/scripts python3 -m unittest SCAE/scripts/tests/test_scae_prior.py` PASS; `python3 -m unittest discover -s orchestrator/scripts/tests` PASS; `PYTHONPATH=SCAE/scripts python3 -m unittest discover -s SCAE/scripts/tests` PASS; `python3 -m unittest discover -s orchestrator/plans/tests` PASS; `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 `CAL-003`/`CAL-004`/`CAL-005` blockers; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. Covered feature rows are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: none beyond the fixture row update.
- Blockers: none for this phase.
- Newly Unblocked Rows: none.
- Commit SHA: pending at report authoring.
