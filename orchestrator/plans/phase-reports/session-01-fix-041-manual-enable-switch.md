# Session 01 FIX-041: Manual Pipeline Enable Switch

- Session: 01 Foundation, Contracts, and Control Plane
- Phase: Wave B fixture/blocker evidence
- Owner: Session 1
- Feature IDs: `AUTO-001`, `AUTO-002`, `AUTO-004`, `AUTO-006`, `MIG-013`
- Migration Groups: `MIG-013`
- Fixture IDs: `FIX-041`
- Blocker IDs: `BLK-034`
- Status: `FIX-041` passing; `BLK-034` passed.
- Acceptance Evidence: Added a consolidated `FIX-041` control-plane test proving a manually enabled fixture runner can acquire the next eligible lease, a stop-after-current request during the active decision stage disables new work, the active case completes and releases its lease, no second eligible case is leased, the pipeline run clears its active lease, the durable control state remains disabled, and the stop signal is acknowledged by the runner. Existing AUTO-006/AUTO-004 tests also prove the disabled default blocks runner start, disabling after candidate selection refuses a new lease, CLI enable/stop helpers persist durable control state, structured stop signals are stored, and safe-drain disable during an active case releases the active lease and records acknowledgement.
- Checks Run: `python3 -m unittest orchestrator.scripts.tests.test_ads_pipeline_control.AdsPipelineControlTest.test_manual_stop_after_current_during_active_run_acknowledges_and_blocks_next_lease` PASS (1 test); `python3 -m unittest orchestrator.scripts.tests.test_ads_pipeline_control` PASS (7 tests); `python3 -m unittest orchestrator.scripts.tests.test_ads_pipeline_runner` PASS (18 tests); `python3 -m unittest discover -s orchestrator/scripts/tests` PASS (156 tests); `python3 -m unittest discover -s orchestrator/plans/tests` PASS (13 tests); `python3 orchestrator/plans/check_dependency_gates.py` PASS; `python3 orchestrator/plans/check_dependency_gates.py --all --mode runtime_integration --report-only` PASS with expected Session 6 CAL blockers; `git diff --check` PASS.
- Shared Inventory Updates Requested: none. The owned AUTO rows are already `ready_for_integration`.
- Shared Map/Matrix Updates Requested: Mark `FIX-041` `passing` and `BLK-034` `passed`.
- Blockers: none for `FIX-041` / `BLK-034`.
- Newly Unblocked Rows: `BLK-034` is no longer a live-cutover blocker.
- Commit SHA: pending at report authoring.
