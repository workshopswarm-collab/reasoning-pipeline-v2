# ADS Phase Report Convention

This directory is the conflict-safe handoff surface for asynchronous ADS worker sessions.

## Why This Exists

The shared inventory, schema-name map, blocker matrix, fixture matrix, and script-placement map are coordinator-owned coordination files. When Sessions 2-5 run concurrently, direct edits to those shared files can conflict or accidentally mark dependencies ready before review.

Component sessions should write phase reports here instead of editing shared coordination files when:

- Their change would touch a row owned by another session.
- They need Session 1 to reconcile shared inventory, blocker, fixture, schema-name, or script-placement state.
- They have acceptance evidence for their own component but concurrent shared-file edits would be risky.

Session 1 or the coordinator reconciles phase reports into shared files after review.

## File Naming

Use one Markdown file per completed or blocked phase:

```text
plans/phase-reports/session-0N-phase-M-short-slug.md
```

Examples:

```text
plans/phase-reports/session-02-phase-1-case-contract.md
plans/phase-reports/session-03-phase-2-retrieval-packet-blocked.md
```

## Required Fields

Every phase report must include:

```markdown
# Session 0N Phase M: Short Name

- Session:
- Phase:
- Owner:
- Feature IDs:
- Migration Groups:
- Status:
- Acceptance Evidence:
- Checks Run:
- Shared Inventory Updates Requested:
- Shared Map/Matrix Updates Requested:
- Blockers:
- Commit SHA:
```

## Reconciliation Rules

- A component session may update rows it owns when it can do so without conflict and with acceptance evidence.
- If a shared coordination edit would collide with other active sessions, write a phase report instead.
- Session 1/coordinator reviews reports and updates shared inventory/maps/matrices in a separate reconciliation commit.
- Rows may move to `ready_for_integration` or `done` only when acceptance evidence is present.
- Runtime integration gates still require upstream rows to be `ready_for_integration`, `done`, or explicitly waived.

