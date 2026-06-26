# Session 01 Live Path Item 1: Scoreable Canary Handlers

- Session: 01
- Phase: Live path item 1
- Owner: Workbench
- Feature IDs: AUTO-003, AUTO-004, AUTO-005, PERSIST-002
- Migration Groups: MIG-008
- Status: complete
- Acceptance Evidence: Added `predquant.ads_scoreable_canary_handlers` and widened the operational canary harness from one-case only to bounded `max_cases` operation. The factory covers every ADS downstream stage, writes a PERSIST-001 forecast-decision record through the SCAE bridge at decision stage, and writes scoreable `market_predictions` rows when the selected snapshot contract is fresh.
- Checks Run: `python3 -m py_compile orchestrator/scripts/predquant/ads_operational_canary.py orchestrator/scripts/predquant/ads_scoreable_canary_handlers.py orchestrator/scripts/bin/run_ads_one_case_canary.py`; `python3 -m unittest orchestrator/scripts/tests/test_ads_operational_canary.py -v`; `python3 -m unittest orchestrator/scripts/tests/test_ads_pipeline_runner.py -v`
- Shared Inventory Updates Requested: None.
- Shared Map/Matrix Updates Requested: Note that a bounded scoreable canary factory now exists for live-path validation, but true specialist workspace adapters remain separate work.
- Blockers: The factory intentionally echoes the selected market snapshot baseline as the canary probability source. It verifies runner/control/persistence mechanics, not real SCAE forecast quality. A production live cutover still needs real stage adapters for evidence, policy context, related markets, decomposition, retrieval, classification, verification, SCAE, synthesis, decision, training trace, and replay record surfaces.
- Commit SHA: 01a77bf4d47b9681db02482d3288e157b7957a88
