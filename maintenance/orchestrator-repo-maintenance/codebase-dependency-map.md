# Orchestrator Codebase Dependency Map

_Last updated: 2026-04-28_

This is a first-pass static map of the active Orchestrator repository execution surfaces, with emphasis on script dependency edges, stale/manual utilities, and redundancy risks. It is intentionally conservative: absence of in-repo references is a review signal, not proof that a manual repair tool is safe to delete.

## Top-level execution surfaces

### Launchd / automation control plane

- `scripts/run_sequential_market_pipeline.py` — main sequencer loop for one-case-at-a-time market pipeline execution.
- `scripts/watch_pipeline.py` — watchdog / repair loop.
- `scripts/check_pipeline_health.py` — health and reporting audit.
- `scripts/watch_decided_market_prices.py` — decided-market price watcher for material changes.
- `scripts/pipeline_automation_actions.py` — shared side-effect/action layer used by the automation plane.

Primary edge pattern:

```text
launchd / cron / operator
  -> scripts/run_sequential_market_pipeline.py / watch_pipeline.py / check_pipeline_health.py
  -> scripts/pipeline_automation_actions.py
  -> stage-specific role scripts
```

### Researcher swarm

Planner entrypoints:

- `runtime/researchers-swarm-subagents/planner/scripts/select_next_market.py`
- `runtime/researchers-swarm-subagents/planner/scripts/select_refresh_case.py`
- `runtime/researchers-swarm-subagents/planner/scripts/create_research_run.py`
- `runtime/researchers-swarm-subagents/planner/scripts/dispatch_case_research.py`

Runtime / recovery entrypoints:

- `runtime/researchers-swarm-subagents/runtime/scripts/manual_batch_controller.py`
- `runtime/researchers-swarm-subagents/runtime/scripts/prepare_and_launch_headless_telegram_dispatch.py`
- `runtime/researchers-swarm-subagents/runtime/scripts/run_telegram_swarm_runtime_loop.py`
- `runtime/researchers-swarm-subagents/runtime/scripts/reconcile_swarm_stage.py`
- `runtime/researchers-swarm-subagents/runtime/scripts/resume_swarm_stage.py`
- `runtime/researchers-swarm-subagents/runtime/scripts/reconcile_research_run_completion.py`

Key edges:

```text
pipeline_automation_actions.py
  -> manual_batch_controller.py / prepare_and_launch_headless_telegram_dispatch.py
  -> dispatch_case_research.py
  -> internal/bootstrap_telegram_topics.py
  -> internal/openclaw_sessions_send.mjs
```

### Synthesis

- `runtime/synthesis-subagent/runtime/scripts/kickoff_synthesis_after_swarm.py`
- `runtime/synthesis-subagent/runtime/scripts/launch_synthesis_if_ready.py`
- `runtime/synthesis-subagent/runtime/scripts/run_synthesis_executor.py`

Key edges:

```text
pipeline_automation_actions.py
  -> kickoff_synthesis_after_swarm.py / launch_synthesis_if_ready.py
  -> run_synthesis_executor.py
```

### Decision-Maker

- `decision-maker/runtime/scripts/run_decision_maker.py`
- `decision-maker/runtime/scripts/run_light_refresh_update.py`
- `decision-maker/runtime/scripts/reconcile_decision_stage.py`
- `decision-maker/runtime/scripts/finalize_decision_stage.py`

Key edges:

```text
pipeline_automation_actions.py
  -> run_decision_maker.py / run_light_refresh_update.py
  -> planner helpers:
       select_decision_inputs.py
       decide_verification_mode.py
       build_targeted_verification_pack.py
       build_decision_prompt.py
  -> validate_decision_packet.py / render_decision_packet.py / persist_forecast_decision.py
  -> bootstrap_decision_telegram_lane.py
  -> openclaw_sessions_send.mjs
```

Current default model/thinking setting:

- `run_decision_maker.py`: `openai-codex/gpt-5.5` / `xhigh`, with env overrides `DECISION_MAKER_MODEL` and `DECISION_MAKER_THINKING`.
- `handoff_to_decision_maker.py`: `openai-codex/gpt-5.5` / `xhigh`.
- Repo `.env` has `DECISION_MAKER_MODEL=openai-codex/gpt-5.5` and `DECISION_MAKER_THINKING=xhigh` set locally.

### Evaluator / recursive learning / causal-LMD

Main maintenance entrypoints:

- `evaluator/runtime/scripts/run_resolved_case_learning_sync.py`
- `evaluator/runtime/scripts/run_evaluator_learning_maintenance_cycle.py`
- `evaluator/runtime/scripts/run_lmd_causal_maintenance_cycle.py`

The top-level `evaluator/` tree is the canonical implementation owner.

Key edges:

```text
pipeline_automation_actions.py
  -> sync_polymarket_market_resolutions.py
  -> run_resolved_case_learning_sync.py
  -> run_lmd_causal_maintenance_cycle.py

run_evaluator_learning_maintenance_cycle.py
  -> materialize_analysis_factor_ledger.py
  -> aggregate_learning_patterns.py
  -> materialize_evaluator_performance_brief.py
  -> materialize_market_prediction_slices.py
  -> materialize_market_prediction_trajectories.py
  -> materialize_market_prediction_performance_scorecard.py
  -> materialize_market_prediction_spine_quality_audit.py
  -> materialize_factor_impact_analysis.py
  -> materialize_evaluator_index_triage.py
  -> materialize_learning_artifact_manifest.py

run_lmd_causal_maintenance_cycle.py
  -> post-treatment feedback / causal graph maintenance
  -> occurrence compiler / bridge / shadow feedback
  -> family policy and lifecycle reports
  -> Phase 11 retrieval learning/reporting
```

### Quant DB / scoring

- `quant-db/scripts/sync_polymarket_market_resolutions.py`
- `quant-db/scripts/market_probability.py`
- `quant-db/scripts/score_brier.py`
- `quant-db/scripts/persist_brier_history.py`

Key edge:

```text
market_probability.py + spine migrations
  -> materialize_market_prediction_slices.py
  -> prediction_accuracy_metrics / evaluator learning artifacts
```

## Initial stale / unused / redundancy candidates

### High-confidence manual-or-stale candidates

These scripts have no non-generated in-repo direct filename references in the first static pass and expose repair/replay/backfill-style CLIs. Treat as review candidates before deletion.

- `runtime/researchers-swarm-subagents/planner/scripts/replay_research_difficulty_cases.py`
  - Help text: replays research-difficulty fixtures and summarizes output drift.
  - Likely status: evaluation harness / diagnostic utility.
- `runtime/researchers-swarm-subagents/runtime/scripts/sweep_stale_market_pipeline_state.py`
  - Help text: previews or applies stale market-state repairs.
  - Likely status: old bounded repair helper; do not delete until current sequencer/watchdog repair paths are checked.
- `runtime/synthesis-subagent/runtime/scripts/runrepairs/repair_structured_bundle_path.py`
  - Help text: repairs synthesis-stage structured bundle path to canonical sidecar bundle.
  - Likely status: one-off repair tool from a prior synthesis artifact migration.
- `quant-db/scripts/backfill_market_categories.py`
  - Help text: backfills `public.markets.category` and normalized metadata category via the shared category resolver.
  - Likely status: manual backfill utility; current resolver remains active through `score_brier.py`.
- `quant-db/scripts/repair_market_resolution_links.py`
  - Help text: repairs `public.market_resolutions` rows whose `market_id` accidentally stores a `case_key`.
  - Likely status: manual DB repair utility; deletion requires checking whether the bad data class is permanently impossible.

### Generated clutter under script trees

These are not source surfaces and should be excluded from codebase maps / script audits:

- `scripts/.runtime-state/**`
- `runtime/**/scripts/.runtime-state/**`
- `scripts/__pycache__/**`
- `runtime/**/__pycache__/**`
- `quant-db/scripts/__pycache__/**`
- `.DS_Store`

### Redundancy / ambiguity watchlist

Not deletion candidates yet, but worth mapping more carefully:

- Evaluator family lifecycle reporting surfaces:
  - `report_family_lifecycle_actions.py`
  - `report_family_lifecycle_action_manifests.py`
  - `report_family_lifecycle_remediation_manifests.py`
  - These are adjacent but currently called by `run_lmd_causal_maintenance_cycle.py`; ambiguity is conceptual, not dead code.
- Decision and synthesis stage status CLIs overlap operationally with reconciliation/finalization scripts. They may be useful operator read surfaces, but should be documented as read-only/status vs mutating/recovery entrypoints.
- Repair/backfill scripts are mixed into active script directories. A future cleanup should separate active automation entrypoints from manual repair/migration utilities, e.g. `scripts/repairs/` or role-local `runtime/scripts/repairs/` with README ownership notes.

## Inventory snapshot

Static script count across audited source surfaces, excluding generated/runtime directories:

- Current generated classifier scan: refresh with `run_maintenance.py --pretty`.
- Current canonical split:
  - `decision-maker`: canonical Decision-Maker implementation
  - `evaluator`: canonical Evaluator implementation
  - `maintenance`: maintenance tooling
  - `device-b`: canonical Device-B scripts/tests
  - `orchestrator/runtime`: canonical researcher/synthesis runtime components
  - `orchestrator/scripts`: Orchestrator control-plane scripts
  - `orchestrator/quant-db/scripts`: quant DB/scoring scripts

## Next verification steps

1. Add a deterministic dependency-map generator so this artifact can be regenerated and diffed instead of hand-maintained.
2. Classify script surfaces with frontmatter or a sidecar index:
   - `active_entrypoint`
   - `called_helper`
   - `manual_repair`
   - `migration_backfill`
   - `diagnostic_harness`
   - `test_only`
   - `deprecated_candidate`
3. For each high-confidence candidate, verify:
   - no launchd/cron references,
   - no README/operator docs references,
   - no external shell history or TaskFlow references if relevant,
   - safe dry-run behavior,
   - whether the underlying bad data/state class can still recur.
4. Move confirmed manual repair utilities into an explicit repair namespace before deletion, unless VM wants a more aggressive cleanup.

## Deterministic classifier generator

Added 2026-04-28:

- Generator: `maintenance/script_classifier.py`
- JSON output: `maintenance/generated/script-classification.json`
- Markdown output: `maintenance/generated/script-classification.md`

The generator classifies script-like files under `scripts/`, `roles/`, `quant-db/scripts/`, and `qualitative-db/scripts/` using deterministic evidence only: path/name rules, known active entrypoints, launchd references, direct text references, and Python import references. It intentionally treats no-reference/manual utilities as review candidates rather than automatically unused code.

Latest generated summary:

- Script-like files scanned: 329
- Active entrypoints: 33
- Called helpers: 156
- Report/materializer surfaces: 38
- Diagnostic/status surfaces: 21
- Tests: 64
- Manual repair surfaces: 10
- Migration/backfill surfaces: 5
- Deprecated candidates: 1
- Diagnostic harnesses with no inbound refs: 1
- Files over 500 lines: 56
- Files over 1000 lines: 11
