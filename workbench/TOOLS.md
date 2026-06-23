# TOOLS.md - Local Notes

This file is for environment-specific implementation notes that are useful to Workbench.

Potential entries:
- repo locations
- preferred editing conventions
- project-specific commands
- local safety rules for risky file areas

## Environment notes

- Treat `.openclaw` as Workbench's primary development surface.
- High-caution areas: gateway/runtime config, bootstrap files, canonical memory, control-plane files, and Orchestrator's base workspace docs.
- Orchestrator's base workspace docs require express user permission before edits.
- Temporary snippet/debug text outputs belong under `tmp/text-snippets/`, not the Workbench top level.
