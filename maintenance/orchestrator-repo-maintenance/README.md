# Orchestrator Repo Maintenance

This directory is Maintenance's canonical home for deterministic hygiene tooling and generated audit state for the Orchestrator codebase.

Target repository: `/Users/agent2/.openclaw/orchestrator`
Maintenance workspace: `/Users/agent2/.openclaw/maintenance`

The goal is to make codebase health measurable before cleanup or refactors. Tools here are conservative and non-mutating by default: they refresh generated maintenance reports under this directory and do not delete, archive, rewrite, or repair Orchestrator source/runtime files.

## Files

- `script_classifier.py` — deterministic script lifecycle classifier for the Orchestrator repo.
- `script-lifecycle-overrides.json` — human-reviewed annotations for intentional manual tools, review deadlines, and cleanup candidates.
- `run_maintenance.py` — single refresh command for maintenance outputs.
- `run_scheduled_maintenance.py` — interval gate for OpenClaw cron/launchd; runs maintenance only when due.
- `com.openclaw.orchestrator.maintenance.plist.template` — optional launchd template for daily checks with a 14-day run interval; not installed by default.
- `codebase-dependency-map.md` — authored/current dependency and cleanup map for Orchestrator.
- `generated/` — generated maintenance outputs. These files are safe to regenerate.

## Generated outputs

- `generated/script-classification.json` — machine-readable script classification inventory.
- `generated/script-classification.md` — human-readable script classification report.
- `generated/clutter-inventory.json` — machine-readable generated/runtime clutter inventory with cleanup policy categories.
- `generated/clutter-inventory.md` — human-readable clutter inventory.
- `generated/maintenance-summary.json` — summary emitted by `run_maintenance.py`.
- `generated/maintenance-summary.previous.json` — previous summary snapshot used for drift comparison.
- `generated/maintenance-drift.json` — machine-readable drift report comparing the latest run against the previous summary.
- `generated/maintenance-drift.md` — human-readable drift report.
- `generated/repo-health-summary.json` — machine-readable repo health scorecard.
- `generated/repo-health-summary.md` — human-readable repo health scorecard.
- `generated/cleanup-plan.json` — dry-run cleanup/archive plan for clutter and script lifecycle review candidates.
- `generated/cleanup-plan.md` — human-readable dry-run cleanup/archive plan.
- `generated/scheduled-maintenance-*` — interval state, logs, scheduled history, and candidate stability history.

## Refresh

```bash
cd /Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance
python3 run_maintenance.py --pretty
```

Set `ORCHESTRATOR_REPO_ROOT=/path/to/orchestrator` only if auditing a non-default checkout.

## Optional biweekly scheduling

Use the scheduler wrapper when a periodic diagnostic is wanted:

```bash
cd /Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance
python3 run_scheduled_maintenance.py --interval-days 14
```

The wrapper records state in `generated/scheduled-maintenance-state.json` and skips cleanly until the interval has elapsed. Use `--force` for a manual proof run.

For OpenClaw cron, schedule the Maintenance agent to run the wrapper from this directory. For launchd, the template in this directory runs daily and lets the wrapper enforce the 14-day cadence because launchd does not express “every two weeks” directly.

Successful scheduled runs append compact trend records to `generated/scheduled-maintenance-history.jsonl` and update candidate stability evidence in `generated/scheduled-maintenance-candidate-history.json` / `.md`. This helps identify candidates that are repeatedly stable over time, ranks them by advisory confidence score, and lists the exact next verification checks needed. Stability is advisory; high-confidence archive/removal still requires lifecycle approval and verification checks.

## Scope rules

- This directory is for codebase maintenance and audit state, not live pipeline runtime state.
- Do not classify files as unused solely because they lack inbound static references.
- Manual repair/backfill tools should be treated as review candidates until their historical data/state class is proven obsolete.
- Lifecycle overrides document human intent; they do not override classifier evidence or delete files.
- Drift reports should be reviewed before cleanup or large refactors.
- Repo health scores are advisory maintenance signals, not release gates.
- Generated/runtime clutter under source script trees should be inventoried before cleanup.
- Clutter cleanup policies are advisory only; `run_maintenance.py` never deletes files.
- Cleanup plans are dry-run only; high-confidence script archive/removal requires explicit lifecycle approval plus verification checks.
- A continuous automatic loop is not required for high-confidence classification; repeated deterministic runs provide drift evidence, while operator/external-use checks must be recorded in `script-lifecycle-overrides.json`.
