# Session 01 FIX-039: Runtime Script Placement Static Scan

- Session: 01 Foundation, Contracts, and Control Plane
- Phase: Wave B fixture/blocker evidence
- Owner: Session 1, with Session 3/4/5 path ownership inputs
- Feature IDs: `FND-001`, `FND-005`
- Migration Groups: none
- Fixture IDs: `FIX-039`
- Blocker IDs: `BLK-032`
- Status: `FIX-039` implemented; `BLK-032` blocked pending missing planned runtime paths.
- Acceptance Evidence: Added `orchestrator/scripts/predquant/script_placement.py` and `orchestrator/scripts/bin/check_ads_script_placement.py`. The scan parses the canonical script placement map, requires every planned runtime path to live under its declared owner root, fails closed on missing planned paths, owner mismatches, duplicate path declarations, unknown owner roots, or malformed map rows, and emits a JSON `ads-script-placement-scan/v1` report with `fixture_id=FIX-039` and `blocker_id=BLK-032`.
- Current Scan Result: `python3 orchestrator/scripts/bin/check_ads_script_placement.py --report-only --pretty` checked 96 planned paths. It found no owner mismatches, no duplicate path declarations, and no unknown owner roots. It found 30 missing planned paths, so `live_cutover_ready=false` and `BLK-032` remains blocked rather than passed.
- Checks Run: `python3 -m unittest orchestrator.scripts.tests.test_script_placement` PASS (4 tests); `python3 orchestrator/scripts/bin/check_ads_script_placement.py --report-only --pretty` PASS as report-only with expected failed scan status due missing paths; `python3 orchestrator/scripts/bin/check_ads_script_placement.py --pretty` returned the expected nonzero fail-closed status for current missing paths; `git diff --check` PASS; `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `python3 -m unittest discover -s orchestrator/scripts/tests` PASS (155 tests); `PYTHONPATH=SCAE/scripts python3 -m unittest discover -s SCAE/scripts/tests` PASS (97 tests); `PYTHONPATH=decomposer/scripts python3 -m unittest discover -s decomposer/scripts/tests` PASS (43 tests); `PYTHONPATH=researcher-swarm/scripts python3 -m unittest discover -s researcher-swarm/scripts/tests` PASS (132 tests).
- Shared Inventory Updates Requested: none.
- Shared Map/Matrix Updates Requested: Mark `FIX-039` `implemented`, not `passing`. Mark `BLK-032` `blocked` with the missing-path debt noted. Correct the Wave B requirements sentence so `FIX-048` is included. Keep all missing-path owning feature rows at their existing inventory status until their runtime paths are implemented, removed, or explicitly future-scoped. Keep `BLK-016` semantically unchanged while fixing its Markdown table pipe defect.
- Blockers: Closing `BLK-032` requires implementing, removing, or explicitly future-scoping the 30 missing planned paths currently reported by the scanner. This phase does not implement decomposer, researcher-swarm, or SCAE runtime entrypoints.
- Newly Unblocked Rows: None. The scanner now gives concrete evidence for subsequent Session 3/4/5 path cleanup and prevents silent placement drift.
- Commit SHA: pending at report authoring.
