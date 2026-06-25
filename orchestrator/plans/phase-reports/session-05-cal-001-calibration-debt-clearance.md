# Session 05 CAL-001: Calibration-Debt Clearance Gates

- Session: 05
- Phase: Calibration-debt-clearance hard gates
- Owner: Session 5
- Feature IDs: `CAL-001`
- Migration Groups: `MIG-010`
- Status: `ready_for_integration` for `CAL-001`; `MIG-010` reconciled to existing `market_predictions` plus `evaluator_scorecards` surfaces.
- Acceptance Evidence: Added `orchestrator/scripts/predquant/calibration_debt.py` with `build_calibration_debt_clearance_report()`, a non-authoritative CAL-001 report contract that requires first-100 trace completeness, SCORE-001 scored prediction/evaluator scorecard evidence, tail-slice diagnostics, regime diagnostics, protected component diagnostics, and pointer-stability evidence before setting `clears_calibration_debt=true`. Missing or failed gates produce explicit blocked status. The report carries Session 6 handoff refs but forbids production forecast writes, SCAE probability rewrites, calibration policy promotion, and base policy rewrites.
- Checks Run: Focused `python3 -m unittest orchestrator.scripts.tests.test_cal001_calibration_debt` PASS at report authoring. Full requested checks will be reported by the worker handoff after final validation.
- Shared Inventory Updates Requested: Mark `CAL-001` `ready_for_integration` with the acceptance evidence above. `CAL-002` becomes dependency-ready for Session 6 maturity work, but this slice does not implement or mark `CAL-002`, `CAL-003`, `CAL-004`, or `CAL-005` ready.
- Shared Map/Matrix Updates Requested: Reconcile `MIG-010` away from a mandatory dedicated `outcome_scoring_records` migration for CAL-001. Existing `market_predictions` fields plus `evaluator_scorecards` provide resolved outcome, Brier, market-baseline Brier, Brier edge, log-loss, reliability bucket, resolution provenance, scorecard refs, and explicit no-authority flags sufficient for CAL-001 gates. Do not advance `FIX-024`, `BLK-010`, or `BLK-018` from this inventory update alone unless the coordinator accepts the focused CAL-001 tests as fixture/blocker evidence.
- Blockers: No CAL-001 implementation blocker. `FIX-024`, `BLK-010`, and `BLK-018` remain matrix-level reconciliation decisions. Session 6 `CAL-*` maturity rows and `MIG-011` remain out of scope.
- Expected Reconciliation Effects: `CAL-001` and `MIG-010` should become ready. `CAL-002` is newly dependency-unblocked for Session 6. No SCAE production probability, forecast persistence, decision, live execution, calibration candidate, policy pointer, rollback, or Session 6 maturity behavior changes.
- Commit SHA: Pending at report authoring; final local commit SHA will be reported by the worker handoff.
