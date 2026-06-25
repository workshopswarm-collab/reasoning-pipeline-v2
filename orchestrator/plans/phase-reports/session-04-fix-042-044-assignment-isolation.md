# Session 04 FIX-042/FIX-044: Assignment And Isolation Evidence

- Session: 04 Researcher Classification and Verification
- Phase: Wave B fixture/blocker reconciliation
- Owner: Session 4
- Feature IDs: `CLS-006`, `CLS-008`, `CLS-002`, `CLS-005`, `MODEL-003`, `MIG-006`
- Migration Groups: `MIG-006`
- Fixture IDs: `FIX-042`, `FIX-044`
- Blocker IDs: `BLK-027`, `BLK-036`
- Status: `FIX-042` passing; `FIX-044` passing; `BLK-036` passed; `BLK-027` in progress.
- Acceptance Evidence: Existing assignment tests prove `leaf-research-assignment/v1` packets are compact machine artifacts with stable assignment IDs and digests, leaf refs and leaf digests, sufficiency requirement refs, required value/negative-check IDs, assigned evidence refs, output refs, budget caps, researcher model lane and prompt metadata, forbidden output fields, context allowlists, no peer context, and no embedded question text, full QDT leaf, evidence body, narrative payload, or probability/decision fields. Existing isolation tests prove fresh launch-allowed audits, independent primary/confirmation researcher audits, no visible peer sidecar overlap, and fail-closed rejection for sibling assignment refs, peer sidecars, peer outputs, aggregate summaries, SCAE refs, prediction/forecast/replay/scoring refs, outcome refs, and non-fresh contexts.
- Checks Run: `PYTHONPATH=researcher-swarm/scripts python3 -m unittest discover -s researcher-swarm/scripts/tests -p 'test_assignments.py'` PASS (5 tests); `PYTHONPATH=researcher-swarm/scripts python3 -m unittest discover -s researcher-swarm/scripts/tests -p 'test_isolation.py'` PASS (4 tests); `PYTHONPATH=researcher-swarm/scripts python3 -m unittest discover -s researcher-swarm/scripts/tests` PASS (132 tests); `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `git diff --check` PASS.
- Shared Inventory Updates Requested: none. The owned Session 4 rows are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: Mark `FIX-042` and `FIX-044` `passing`; mark `BLK-036` `passed`; move `BLK-027` to `in_progress` because assignment and isolation audit canonical-machine evidence is complete while full QDT, sidecar, and model-provenance scan evidence remains open.
- Blockers: `BLK-027` still needs the remaining canonical-machine evidence outside the assignment/isolation slice.
- Newly Unblocked Rows: `BLK-036` is no longer a live-cutover blocker.
- Commit SHA: pending at report authoring.
