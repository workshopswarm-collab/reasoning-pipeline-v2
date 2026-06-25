# Session 05 Phase 4: SCAE-006 Cross-Leaf Dependence

- Session: 05 SCAE, Synthesis/Decision Handoff, and Evaluator Spine
- Phase: 4
- Owner: Session 5
- Feature IDs: `SCAE-006`
- Migration Groups: `MIG-007`
- Status: ready_for_integration pending coordinator inventory reconciliation
- Acceptance Evidence: Implemented deterministic candidate-only cross-leaf dependence guard in `/Users/agent2/.openclaw/SCAE/scripts/scae/netting.py`. The guard consumes SCAE-005 cluster netting slices, groups resolved claim families across leaves through a shared-claim union so repeated force is not additive, maps ambiguous or unresolved claim-family equivalence to a conservative ambiguity union instead of independent corroboration, emits source-family diagnostics, and records mechanism-family tags as dependence/interval diagnostics that cannot increase evidence strength. Outputs remain candidate-only and explicitly do not write SCAE ledger rows, probability fields, forecasts, research, live LLM calls, branch sub-ledgers, interval builders, or persistence.
- Checks Run: `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --feature-id SCAE-006 --mode runtime_integration --report-only` PASS; `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `python3 -m unittest discover -s orchestrator/scripts/tests` PASS (115 tests); `PYTHONPATH=SCAE/scripts python3 -m unittest discover -s SCAE/scripts/tests` PASS (48 tests); focused `PYTHONPATH=SCAE/scripts python3 -m unittest SCAE/scripts/tests/test_scae_netting.py` PASS (12 tests).
- Shared Inventory Updates Requested: Mark `SCAE-006` `ready_for_integration` with acceptance evidence summarizing the deterministic cross-leaf dependence bundle, shared-claim union, conservative ambiguous-claim handling, mechanism-family diagnostic-only semantics, and no ledger/probability/forecast authority. After this reconciliation, `SCAE-007` and `SCAE-011` should become dependency-ready.
- Shared Map/Matrix Updates Requested: No direct shared map edits requested. `BLK-005` and `BLK-024` now have SCAE-006 implementation evidence but should not be marked passed until their owning fixture/static validations are reconciled.
- Blockers: No implementation blocker for `SCAE-006`. Downstream rows remain inventory-blocked until `SCAE-006` is reconciled to `ready_for_integration`; later SCAE rows remain out of scope for this phase.
- Commit SHA: Detached local commit pending from base `fee022606207b8b9d677c7b1f434f87b3d0d0ef9`; final local commit SHA will be reported by Session 5 after commit.
