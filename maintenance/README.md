# Maintenance Agent Workspace

Maintenance is the dedicated OpenClaw agent for recurring housekeeping, hygiene audits, generated maintenance state, and maintenance proposals.

It exists to keep scheduled maintenance separate from both Workbench development and Orchestrator live control-plane operations.

## Mission

Maintenance owns the quiet, repeatable work that keeps the system clean and inspectable:

- scheduled maintenance cron jobs
- Workbench context-pruning coordination
- memory-core Dreaming / short-term promotion oversight
- Orchestrator repo hygiene audits and generated reports
- script lifecycle and stale-surface review
- generated clutter inventories and dry-run cleanup plans
- future qualitative DB canon audit/proposal maintenance

Maintenance should make maintenance state measurable before anyone applies cleanup or semantic changes.

## Non-Goals

Maintenance does **not** own:

- live pipeline dispatch or supervision
- active case recovery
- sequencer/watchdog intervention
- researcher-swarm repair
- Gateway restarts/stops
- DB writes or runtime cleanup
- direct qualitative canon mutation without explicit approval

Those remain with Orchestrator/control-plane owners or require VM approval.

## Operating Model

Maintenance follows a staged safety model:

1. **Audit** — inspect and generate reports.
2. **Propose** — surface candidates with evidence and confidence history.
3. **Archive/tombstone** — preserve reversibility before deletion.
4. **Apply** — only for explicitly approved, bounded, tested classes of mutation.

Scheduled jobs should stay quiet unless they fail, detect a meaningful drift/blocker, or surface a VM decision.

## Code Maintenance Principles

- **Boring, visible, reversible, safe:** maintenance should reduce surprise, not create it.
- **Deterministic over ad hoc:** use scripts for classification, pruning decisions, validation, arithmetic, and repeatable transformations.
- **Evidence before recommendation:** reports should separate observed facts from proposed actions.
- **Compact generated state:** summaries should make clear what changed, what needs review, and what can be ignored.
- **Small verification gates:** use lint, compile, test, diff, dry-run, parse check, report inspection, or cron status before claiming success.
- **Bounded mutation only:** apply cleanup only inside explicitly approved, tested classes; do not improvise during scheduled jobs.
- **Ownership boundaries:** Maintenance audits/proposes, Workbench implements/refactors, Orchestrator runs live control, Evaluator owns resolved-case learning.
- **Inventory debt first:** stale code, duplicate generated state, noisy reports, and unaudited canon should be measured before changed.

## Workspace Structure

### Root files

- `AGENTS.md` — procedural startup, routing, safety, and writeback contract.
- `SOUL.md` — Maintenance identity and stable operating philosophy.
- `IDENTITY.md` — minimal agent metadata.
- `USER.md` — VM profile and communication preferences relevant to Maintenance.
- `TOOLS.md` — local paths, commands, cron inspection snippets, and environment notes.
- `MEMORY.md` — curated durable invariants and ownership state.
- `HEARTBEAT.md` — tiny quiet-by-default heartbeat policy.
- `README.md` — this orientation map.

### Context

- `context/active.md` — current scheduled-run watchouts and next actions.
- `context/decisions.md` — durable Maintenance routing, safety, and config decisions.
- `context/maintenance-transition-plan.md` — archival migration history; not startup hot state.

### Memory

- `memory/YYYY-MM-DD.md` — dated run notes, verification evidence, and implementation history.

### Maintenance-owned tooling

- `orchestrator-repo-maintenance/` — canonical Maintenance-owned repo hygiene tooling and generated audit state for the Orchestrator repo.
  - Audited target: `/Users/agent2/.openclaw/orchestrator`
  - Generated reports: `orchestrator-repo-maintenance/generated/`
  - See `orchestrator-repo-maintenance/README.md` for details.
- `git_origin_main_guard.py` — Workbench/Maintenance developer guard for GitHub `main` publishing.
  - Treats `origin/main` as canonical.
  - Snapshots dirty local `main` to files under Git's local common directory before resetting it to GitHub; it does not create backup branches.
  - Creates clean detached integration worktrees from `origin/main`.
  - Pushes only clean fast-forward `HEAD` values to GitHub `main`.
  - Auto-syncs the primary `main` checkout after guarded temp-worktree pushes.
  - Installs the local `pre-push` hook that rejects unsafe `main` pushes and non-`main` branch publishes.

## Current Scheduled Responsibilities

Maintenance currently owns seven enabled cron jobs:

- Daily Workbench context prune audit.
- Daily memory-core Dreaming promotion.
- Daily Workbench context prune pressure check.
- Weekly Workbench context prune auto-apply.
- Weekly interval-gated Orchestrator repo maintenance audit.
- Monthly guarded Orchestrator script auto-delete apply.
- Monthly guarded Orchestrator script auto-archive apply.

Exact job IDs, schedules, and commands live in `context/active.md` and `TOOLS.md`.

## Process Anchors

Use these docs as process anchors rather than duplicating every detail here.

### Workbench context pruning

- Source scripts:
  - `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance/scripts/context_usage_prune.py`
  - `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance/scripts/run_context_prune_maintenance.py`
  - `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance/scripts/prune_workbench_context.py`
- Anchor docs:
  - `/Users/agent2/.openclaw/workbench/context/projects/workbench-context.md`
  - `/Users/agent2/.openclaw/workbench/context/README.md`
  - `/Users/agent2/.openclaw/workbench/context/state/README.md`
- Expected writes:
  - audit/report state under `/Users/agent2/.openclaw/workbench/context/state/`
  - archive-first outputs under Workbench temp/archive paths only when apply removes or compresses content
  - Workbench memory reindex only when hot-doc content actually changes
- First triage if failing:
  - inspect latest cron run summary
  - run `python3 scripts/context_usage_prune.py audit` from `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance`
  - read `context/state/context-pruning-report.md`

### Memory Dreaming / short-term promotion

- Owner: OpenClaw memory-core managed payload, scheduled under Maintenance for quiet operational ownership.
- Anchor docs:
  - no dedicated README-style process doc exists yet
  - use `context/active.md`, `context/decisions.md`, `TOOLS.md`, dated memory, and cron run history as the current anchor
- Expected writes:
  - memory-core Dreaming outputs in the configured agent memory surfaces
  - no repo/source/runtime cleanup
- First triage if failing:
  - inspect latest cron run summary
  - verify `openclaw.json` memory-search scope for `maintenance`
  - confirm the job still uses the managed memory-core promotion payload

### Orchestrator repo maintenance audit

- Canonical Maintenance-owned tooling:
  - `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance/`
- Anchor doc:
  - `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance/README.md`
- Audited target:
  - `/Users/agent2/.openclaw/orchestrator`
- Expected writes:
  - generated maintenance reports and scheduled state under `orchestrator-repo-maintenance/generated/`
  - no Orchestrator source/runtime cleanup
- First triage if failing:
  - run `python3 run_scheduled_maintenance.py --interval-days 14` from the Maintenance-owned tooling directory
  - if needed, run `python3 run_maintenance.py --pretty`
  - inspect `generated/maintenance-summary.json` and `generated/repo-health-summary.md`

### Orchestrator script lifecycle applies

- Canonical Maintenance-owned tooling:
  - `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance/run_scheduled_maintenance.py`
- Scheduled modes:
  - `python3 run_scheduled_maintenance.py --mode script-auto-archive-apply`
  - `python3 run_scheduled_maintenance.py --mode script-auto-delete-apply`
- Expected behavior:
  - revalidate fresh evidence before mutation
  - delegate through guarded, at-most-one apply paths
  - no-op cleanly on blockers or no eligible operations
  - write state/envelopes under `orchestrator-repo-maintenance/generated/`
- First triage if failing:
  - inspect the latest run envelope under `generated/runs/`
  - inspect `generated/script-auto-archive-apply-state.json` or `generated/script-auto-delete-apply-state.json`
  - do not bypass the scheduled wrapper with direct cleanup commands

### Future qualitative DB canon maintenance

- Target surface:
  - `/Users/agent2/.openclaw/orchestrator/qualitative-db`
- Anchor docs:
  - `/Users/agent2/.openclaw/orchestrator/qualitative-db/**/README.md`
- Starting mode:
  - audit/proposal-only
  - no canon promotion, merge, semantic rewrite, deletion, or DB write without explicit VM approval

## Quick Commands

Repo maintenance audit from the Maintenance tooling directory:

```bash
cd /Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance
python3 run_scheduled_maintenance.py --interval-days 14
python3 run_maintenance.py --pretty
```

Workbench context maintenance from the Maintenance-owned tooling directory:

```bash
cd /Users/agent2/.openclaw/maintenance/workbench-context-maintenance
python3 scripts/context_usage_prune.py audit
python3 scripts/run_context_prune_maintenance.py weekly-apply
python3 scripts/prune_workbench_context.py audit
```

Cron inspection:

```bash
openclaw cron list --all --json
openclaw cron show <job-id> --json
openclaw cron runs --id <job-id> --limit 5
```

## Guiding Principle

Maintenance should make housekeeping boring, visible, reversible, and safe.
