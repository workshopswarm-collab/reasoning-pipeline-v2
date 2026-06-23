# TOOLS.md - Maintenance Local Notes

Skills define shared tool behavior. This file is Maintenance's local environment cheat sheet.

## Canonical Paths

- Maintenance workspace: `/Users/agent2/.openclaw/maintenance`
- Maintenance context: `/Users/agent2/.openclaw/maintenance/context`
- Orchestrator repo maintenance tooling/state: `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance`
- Orchestrator repo audited target: `/Users/agent2/.openclaw/orchestrator`
- Orchestrator repo maintenance generated reports: `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance/generated`
- Workbench workspace: `/Users/agent2/.openclaw/workbench`
- Workbench context pruning scripts: `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance/scripts`
- OpenClaw config: `/Users/agent2/.openclaw/openclaw.json`
- OpenClaw cron jobs file: `/Users/agent2/.openclaw/cron/jobs.json`

## Repo Maintenance Commands

Run from `/Users/agent2/.openclaw/maintenance/orchestrator-repo-maintenance`:

```bash
python3 run_scheduled_maintenance.py --interval-days 14
python3 run_maintenance.py --pretty
python3 script_classifier.py --pretty
```

`ORCHESTRATOR_REPO_ROOT` may override the audited target repo for tests or alternate checkouts.

## Workbench Context Maintenance Commands

Run from `/Users/agent2/.openclaw/maintenance/workbench-context-maintenance`:

```bash
python3 scripts/context_usage_prune.py audit
python3 scripts/run_context_prune_maintenance.py weekly-apply
python3 scripts/prune_workbench_context.py audit
```

These Maintenance-owned scripts audit/mutate the Workbench target at `/Users/agent2/.openclaw/workbench`; Workbench should not retain local context-management script copies.

## Cron Inspection

```bash
openclaw cron list --all --json
openclaw cron show <job-id> --json
openclaw cron runs --id <job-id> --limit 5
```

Current scheduled maintenance jobs should be owned by `agentId=maintenance` and use `agent:maintenance:*` session keys.

## Safety Notes

- Do not restart/stop Gateway without explicit VM permission.
- Cron rewiring is live behavior; review current jobs before changing them.
- Launchd templates are not installed unless VM explicitly approves installation.
- Qualitative DB pruning/promotions must start as audit/proposal-only.
- Generated cleanup plans are dry-run only unless VM approves a specific apply step.
