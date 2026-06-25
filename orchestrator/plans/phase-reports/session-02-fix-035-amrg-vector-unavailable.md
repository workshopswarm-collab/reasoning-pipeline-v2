# Session 02 FIX-035: AMRG Vector Source Unavailable

- Session: 02 Evidence Packet, Policy Context, and AMRG
- Phase: Wave B fixture/blocker reconciliation
- Owner: Session 2
- Feature IDs: `AMRG-001`, `AMRG-009`, `MIG-005`
- Migration Groups: `MIG-005`
- Fixture IDs: `FIX-035`
- Blocker IDs: `BLK-029`
- Status: `FIX-035` passing; `BLK-029` passed.
- Acceptance Evidence: Existing AMRG vector tests prove the local embedding lane resolves to provider `ollama`, route `ollama/local`, model `BAAI/bge-base-en-v1.5`, and download command `ollama pull BAAI/bge-base-en-v1.5`; unavailable model/route/index paths write `amrg_vector_candidate_source_unavailable` diagnostics with `non_blocking=true`; unavailable index snapshots carry the diagnostic; deterministic related-market candidates continue when vector diagnostics are present; vector-neighbor candidates, when available, are capped, vector-only, and weak-context-only.
- Checks Run: `python3 -m unittest orchestrator.scripts.tests.test_amrg_vector` PASS (7 tests); `python3 -m unittest orchestrator.scripts.tests.test_amrg_context` PASS (25 tests); `python3 -m unittest discover -s orchestrator/scripts/tests` PASS (156 tests); `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. The owned AMRG feature rows are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: Mark `FIX-035` `passing` and `BLK-029` `passed`.
- Blockers: none for `FIX-035` / `BLK-029`.
- Newly Unblocked Rows: `BLK-029` is no longer a live-cutover blocker.
- Commit SHA: pending at report authoring.
