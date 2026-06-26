# ADS v2 Storage Maintenance Agent Implementation Plan

Date: 2026-06-26
Author: Workbench
Scope: Phase-by-phase implementation plan for recency-biased ADS storage pruning, compression, and provenance preservation using the current Orchestrator storage architecture.

## Executive Summary

ADS currently has a conservative storage maintenance path: `maintain_ads_storage.py` calls `predquant.ads_storage_maintenance`, which can dry-run/apply deletes for old operational rows, checkpoint WAL, and optionally run `VACUUM`. That is a good base, but it only covers a few operational tables and does not yet manage artifact files, fetched evidence bodies, rejected retrieval candidates, market snapshot downsampling, or compressed archives.

The desired direction is:

- Strong bias toward recency for bulky operational and retrieval data.
- Permanent preservation of result provenance: predictions, forecast decisions, scorecards, prediction-time market baseline, resolution/scoring evidence, SCAE final ledger, replay/training minimal pointers, and enough evidence metadata to audit each scoreable forecast.
- Compression before deletion for material that may still be useful but should not stay hot.
- Dry-run-first operation with manifests, safety checks, and restore paths.
- Extension of the current `maintain_ads_storage.py` / `ads_storage_maintenance.py` path rather than a parallel cleanup system.

## Current State

Measured live state on 2026-06-26:

- `orchestrator/scripts/data`: about `6.8M`
- `predquant.sqlite3`: about `6.0M`
- `ads_artifacts`: about `820K`
- artifact files: `71`
- current DB freelist: `0` pages
- ADS predictions: `7`
- forecast decision records: `8`
- QDT decomposition run rows: `0`
- AMRG candidate set rows: `0`

Existing maintenance code:

- `orchestrator/scripts/bin/maintain_ads_storage.py`
- `orchestrator/scripts/predquant/ads_storage_maintenance.py`
- `orchestrator/scripts/predquant/ads_live_readiness.py`
- `orchestrator/scripts/tests/test_ads_storage_maintenance.py`

Existing prune scope:

- `v2_stage_execution_events`
- `v2_stage_status_snapshots`
- `v2_pipeline_error_events`
- `ads_pipeline_loop_iterations`

Existing protected areas are protected mostly by omission, not by an explicit provenance graph. The maintenance agent should make that protection explicit before it starts pruning real retrieval artifacts.

## Design Principles

1. **Never delete scoreable-result provenance**
   - Preserve `market_predictions`, `forecast_decision_records`, `evaluator_scorecards`, prediction-time `market_snapshots`, SCAE final ledger refs, score/replay refs, and minimal training trace pointers indefinitely.
2. **Delete or compress bulk, not meaning**
   - Raw fetched pages, rejected candidates, duplicate pages, old search dumps, temporary chunks, and scratch subagent logs are candidates for compression/pruning.
   - Canonical URLs, source family, claim family, extracted spans, hashes, publication timestamps, admission/rejection reasons, and sufficiency decisions should remain queryable.
3. **Recency wins unless provenance protects the object**
   - New/open/unresolved markets get hot retention.
   - Resolved/scored cases move to compressed/cold retention.
   - Unreferenced failed/scratch data expires quickly.
4. **Dry-run is the default**
   - Every apply operation must have a dry-run plan with row counts, file counts, bytes affected, protected-object counts, and reason codes.
5. **Compression is a first-class action**
   - The maintenance agent should support `compress`, `prune`, `downsample`, `checkpoint`, `vacuum`, and `verify` actions.
6. **Use existing architecture**
   - Extend `ads_storage_maintenance.py`, `maintain_ads_storage.py`, manifest tables, readiness checks, and operator reports.
   - Do not create a separate maintenance database or parallel artifact registry unless current manifests cannot represent compressed locations safely.

## Retention Classes

### Class A - Permanent Result Provenance

Never prune automatically:

- `market_predictions`
- `forecast_decision_records`
- `evaluator_scorecards`
- prediction-time `market_snapshots` referenced by predictions or scorecards
- resolution/outcome provenance and resolution payload hashes
- SCAE final probability ledger artifacts for scoreable predictions
- decision gate artifacts for scoreable predictions
- replay records needed to reproduce or audit scoreable predictions
- `training_trace_minimal_pointers`
- policy/model/code/prompt/input refs used by scoreable predictions
- CAL-001 evidence rows and scorecard refs

Allowed maintenance:

- gzip or zstd compression of large JSON artifacts if manifest resolution remains hash-safe.
- migration from full training trace materialization to minimal pointer plus protected artifact refs, after verification.

### Class B - Audit-Required Evidence

Keep compact form long-term:

- admitted evidence metadata
- admitted evidence canonical URL
- source family and source class
- claim family and atomic claim
- publication/update timestamp
- extracted supporting/opposing spans
- evidence chunk/span hashes
- admission reason
- sufficiency certificate refs
- verification refs

Allowed maintenance:

- compress full fetched page bodies after hot window.
- delete full fetched page bodies after cold window if compact admitted spans and hashes are preserved.
- keep enough content to prove what was classified, not necessarily the entire source page forever.

### Class C - Recency-Biased Operational Data

Prune after configured retention unless linked to a protected result:

- stage execution events
- stage status snapshots
- pipeline loop iterations
- pipeline error events after summarized into failure groups
- non-scoreable readiness/canary manifests
- failed run scratch logs
- transient stdout/stderr/bounded logs

### Class D - Rejected Or Duplicate Retrieval Bulk

Short retention:

- rejected candidate pages
- duplicate content bodies
- search result dumps
- native GPT candidate-discovery raw outputs
- crawler/browser attempt bodies that did not admit evidence
- leaf subagent scratch notes not referenced by accepted sidecars

Keep compact metadata:

- attempted URL
- final/canonical URL
- source family
- rejection reason
- content hash when available
- fetch status
- attempted_at timestamp

### Class E - Market Snapshot Time Series

Downsample with protected anchors:

- always preserve snapshots linked to predictions, forecast decisions, scorecards, resolution checks, and calibration reports.
- keep recent high-resolution snapshots for open markets.
- downsample older snapshots for closed/resolved markets into hourly/daily windows.
- preserve enough baseline data to compare prediction performance against market at prediction time and resolution time.

## Default Retention Policy

Initial defaults should be conservative and configurable:

| Object class | Hot retention | Cold/compact retention | Automatic deletion |
| --- | ---: | ---: | ---: |
| Class A result provenance | forever | forever | never |
| Admitted evidence full page body | 180 days after market resolution/scoring | compact spans/hashes forever | full body after 365 days if compact form verified |
| Rejected retrieval body | 14 days | compact metadata 180 days | body after 14 days, metadata after 180 days |
| Duplicate retrieval body | 7 days | compact metadata 90 days | body after 7 days, metadata after 90 days |
| Search result dump | 30 days | query/result hashes 180 days | raw dump after 30 days |
| Native GPT candidate-discovery raw response | 30 days | candidate URL metadata 180 days | raw response after 30 days |
| Leaf subagent scratch logs | 30 days | sidecar/tool summary 365 days | scratch after 30 days |
| Stage execution/status events | 90 days | summarized counts/failure groups 365 days | detailed rows after 90 days |
| Pipeline error events | 180 days | failure pattern group forever | detailed rows after 180 days |
| Open-market snapshots | 30 days full cadence | hourly after 30 days | unprotected dense rows after downsample |
| Closed/resolved market snapshots | 14 days full cadence after resolution | hourly/daily aggregates 365 days | unprotected dense rows after downsample |
| Non-scoreable canary artifacts | 30 days | summary manifest 365 days | bulky artifacts after 30 days |

The maintenance agent must not delete any row/file referenced by a protected provenance graph, even if the retention window says it is eligible.

## Phase 0 - Baseline Inventory And Safety Envelope

Goal: make current storage measurable before pruning expands.

Modify:

- `orchestrator/scripts/predquant/ads_storage_maintenance.py`
- `orchestrator/scripts/bin/maintain_ads_storage.py`
- `orchestrator/scripts/tests/test_ads_storage_maintenance.py`

Tasks:

1. Extend `build_storage_maintenance_plan()` to inventory:
   - DB size,
   - WAL/SHM size,
   - table row counts,
   - approximate table bytes via `dbstat` when available,
   - artifact directory size,
   - artifact file count,
   - largest artifact files,
   - backup directory size when configured.
2. Add `--json-output` path for writing durable dry-run plans.
3. Add `storage-maintenance-plan/v2` schema with:
   - scan timestamp,
   - retention policy id/hash,
   - protected provenance summary,
   - candidate rows/files by class,
   - estimated bytes reclaimable,
   - action plan.
4. Add live-readiness integration that can warn/block on:
   - DB WAL size,
   - artifact dir size,
   - overdue maintenance,
   - retention candidate growth.

Acceptance:

- Dry-run reports current DB/artifact sizes without deleting anything.
- Tests prove missing `dbstat` support degrades gracefully.

## Phase 1 - Protected Provenance Graph

Goal: explicitly identify rows and artifacts that must never be pruned.

Modify:

- `ads_storage_maintenance.py`
- `ads_handoff_resolver.py` if manifest traversal helpers should be reused
- scoring/replay helper modules only if needed for refs

Tasks:

1. Build `collect_protected_provenance_graph(db_path)` that starts from:
   - `market_predictions`,
   - `forecast_decision_records`,
   - `evaluator_scorecards`,
   - prediction-linked market snapshots,
   - replay/training trace refs,
   - CAL-001 scorecard refs.
2. Traverse:
   - `case_artifact_manifest`,
   - `artifact_manifest`,
   - stage `output_artifact_refs`,
   - validation refs,
   - replay refs,
   - scorecard refs.
3. Mark protected object refs with reasons:
   - `scoreable_prediction`,
   - `scorecard_evidence`,
   - `prediction_time_baseline`,
   - `scae_final_authority`,
   - `replay_minimal_pointer`,
   - `cal001_evidence`.
4. Add a dry-run invariant:
   - no apply plan may delete a protected row or protected file.

Acceptance:

- Test creates a prediction with linked snapshot, forecast decision, artifact, and scorecard; maintenance refuses to delete all referenced items even when old.

## Phase 2 - Artifact Classification And Manifest Compatibility

Goal: classify artifacts by retention class without breaking strict manifest resolution.

Modify:

- `case_artifact_manifest` migration or metadata writer
- `artifact_manifest` migration or metadata writer
- `ads_storage_maintenance.py`
- manifest resolver tests

Tasks:

1. Add retention metadata to artifact manifests, either as columns or manifest metadata:
   - `retention_class`,
   - `provenance_role`,
   - `scoreable_protected`,
   - `content_encoding`,
   - `original_sha256`,
   - `stored_sha256`,
   - `original_size_bytes`,
   - `stored_size_bytes`,
   - `compression_algorithm`,
   - `compression_at`,
   - `prunable_after`,
   - `delete_after`,
   - `retention_reason`.
2. Backfill current artifacts conservatively:
   - final forecast/decision/SCAE/replay/training refs -> Class A,
   - question decomposition, retrieval, verification, sidecars for scoreable cases -> Class B,
   - non-scoreable/canary scratch -> Class C/D depending artifact type.
3. Update strict manifest resolution so compressed artifacts can still be verified:
   - verify stored file hash,
   - decompress when needed,
   - verify original payload hash after decompression,
   - keep existing absolute-path/digest safety.

Acceptance:

- Existing uncompressed artifacts still resolve.
- A compressed artifact resolves to the original payload and validates both stored and original hashes.

## Phase 3 - Compression Engine

Goal: reduce bulk while preserving auditability.

Modify:

- `ads_storage_maintenance.py`
- `maintain_ads_storage.py`
- manifest resolver

Tasks:

1. Add `compress` action:
   - default to stdlib `gzip` for zero new dependency,
   - optionally support `zstd` only if dependency and deployment policy are added explicitly.
2. Compress eligible JSON/Markdown/text artifacts:
   - raw fetched pages,
   - large retrieval packets,
   - native research raw responses,
   - subagent scratch outputs,
   - old non-scoreable canary artifacts.
3. Never compress by overwriting blindly:
   - write compressed sibling file first,
   - fsync/close,
   - compute compressed hash,
   - verify decompressed original hash,
   - update manifest metadata,
   - only then remove original if policy allows.
4. Add `--compress-only`, `--min-compress-bytes`, and `--compression-algorithm`.
5. Add compression report:
   - files scanned,
   - files compressed,
   - bytes before/after,
   - skipped protected,
   - skipped too small,
   - verification failures.

Acceptance:

- Compression dry-run predicts savings.
- Apply compresses eligible files and preserves resolver access.
- Failed compression leaves original untouched.

## Phase 4 - Recency-Biased Artifact Pruning

Goal: delete old bulk files while keeping result provenance.

Modify:

- `ads_storage_maintenance.py`
- `maintain_ads_storage.py`
- artifact manifest/resolver helpers

Tasks:

1. Add `prune-artifacts` action with dry-run default.
2. Candidate classes:
   - rejected retrieval bodies older than 14 days,
   - duplicate retrieval bodies older than 7 days,
   - raw search dumps older than 30 days,
   - native GPT candidate raw responses older than 30 days,
   - subagent scratch logs older than 30 days,
   - non-scoreable canary bulky artifacts older than 30 days.
3. Before deletion, require:
   - object not in protected provenance graph,
   - compact metadata exists,
   - content hash recorded,
   - deletion reason recorded,
   - dry-run plan reviewed or `--apply` explicitly passed.
4. Delete files through a two-step policy:
   - default move to a trash/quarantine directory with manifest tombstone,
   - permanent deletion only after quarantine TTL or explicit `--purge-quarantine`.
5. Add `artifact_tombstone` or equivalent metadata:
   - deleted path,
   - artifact ref,
   - hash,
   - size,
   - deletion reason,
   - deleted_at,
   - maintenance_run_id.

Acceptance:

- A protected scoreable artifact is not deleted.
- An old rejected candidate body can be pruned while compact rejection metadata remains queryable.

## Phase 5 - Market Snapshot Downsampling

Goal: prevent `market_snapshots` from dominating long-term DB growth while preserving prediction baselines.

Modify:

- `sqlite_store.py` only if helper queries are needed
- `ads_storage_maintenance.py`
- scoring/reporting tests

Tasks:

1. Protect snapshots linked to:
   - `market_predictions`,
   - scorecards,
   - resolution sync/scoring events,
   - calibration diagnostics.
2. Add `market_snapshot_retention_plan`:
   - open markets: keep full cadence for 30 days,
   - older open-market snapshots: hourly representative rows,
   - closed/resolved markets: keep full cadence for 14 days after resolution,
   - older closed/resolved snapshots: hourly for 90 days, daily for 365 days.
3. Preserve prediction-time market baseline:
   - linked snapshot row,
   - bid/ask/yes/last/current price fields,
   - raw payload hash,
   - observed_at timestamp.
4. Optionally move old raw snapshot payloads to compressed cold artifacts if row-level raw payload grows.
5. Add `--downsample-market-snapshots` action.

Acceptance:

- Downsampling never deletes prediction-linked snapshots.
- Brier report still has prediction and market baseline inputs after downsampling.

## Phase 6 - DB Row Pruning And Summarization

Goal: expand current operational row pruning safely.

Modify:

- `DEFAULT_RETENTION_TABLES`
- `ads_storage_maintenance.py`
- tests

Tasks:

1. Keep existing retention for:
   - `v2_stage_execution_events`,
   - `v2_stage_status_snapshots`,
   - `v2_pipeline_error_events`,
   - `ads_pipeline_loop_iterations`.
2. Add summary-before-delete for:
   - pipeline errors,
   - repeated stage failures,
   - canary run summaries,
   - storage maintenance history.
3. Add candidate tables only after protected provenance graph exists:
   - non-scoreable run stage logs,
   - stale active-work snapshots,
   - transient healthcheck snapshots,
   - old non-scoreable canary manifests.
4. Refuse to prune rows attached to scoreable prediction runs unless compact replay/trace provenance exists.

Acceptance:

- Old non-scoreable operational rows prune.
- Scoreable run trace rows are preserved until minimal replay pointer verification passes.

## Phase 7 - Maintenance Agent CLI And Scheduling

Goal: make maintenance an operator-safe routine, not an ad hoc cleanup command.

Modify:

- `maintain_ads_storage.py`
- possibly new `run_ads_storage_maintenance_agent.py` wrapper if the CLI becomes too large
- launchd/cron config only after explicit operational approval

Tasks:

1. Add subcommands:
   - `audit`,
   - `compress`,
   - `prune`,
   - `downsample`,
   - `checkpoint`,
   - `vacuum`,
   - `verify`,
   - `apply-plan`.
2. Keep dry-run as default for every destructive or mutating action.
3. Add maintenance run records:
   - `maintenance_run_id`,
   - policy id/hash,
   - action,
   - actor,
   - started/completed timestamps,
   - candidate counts,
   - changed counts,
   - bytes reclaimed,
   - protected skips,
   - verification result.
4. Add scheduling policy:
   - daily audit,
   - weekly compress dry-run,
   - weekly apply compression if dry-run is clean,
   - monthly prune dry-run,
   - manual approval for first prune apply,
   - vacuum only after large deletes or DB bloat threshold.
5. Add `--max-bytes-to-delete`, `--max-files-to-delete`, and `--require-backup` guards.

Acceptance:

- Operator can run one command to see what would be compressed/pruned.
- Apply refuses without backup when deletion scope exceeds threshold.

## Phase 8 - Backup, Restore, And Verification

Goal: make maintenance reversible enough for live operations.

Modify:

- `ads_storage_maintenance.py`
- `maintain_ads_storage.py`
- backup helpers if they exist

Tasks:

1. Before destructive apply:
   - require SQLite backup or `VACUUM INTO` backup path,
   - write artifact deletion quarantine path,
   - write maintenance plan JSON.
2. Add `verify` action:
   - manifest path exists or tombstone exists,
   - protected provenance graph resolves,
   - compressed artifacts decompress and match original hash,
   - scorecard and Brier reports still run,
   - handoff reports for protected runs still resolve.
3. Add restore documentation:
   - restore SQLite backup,
   - restore quarantined files,
   - rerun verify.

Acceptance:

- A test maintenance run can prune a non-protected file, verify state, restore it from quarantine, and verify again.

## Phase 9 - Readiness And Operator Reporting

Goal: let live readiness account for storage health.

Modify:

- `ads_live_readiness.py`
- `check_ads_live_readiness.py`
- operator report CLIs

Tasks:

1. Add readiness blockers:
   - protected provenance graph cannot be built,
   - artifact resolver cannot read protected compressed artifact,
   - storage maintenance overdue beyond policy,
   - DB WAL above hard threshold,
   - artifact directory above hard threshold without a clean dry-run plan.
2. Add warnings:
   - rejected retrieval bodies above retention,
   - raw fetched page bytes above threshold,
   - market snapshots eligible for downsampling,
   - compression savings above threshold,
   - quarantine pending purge.
3. Add report sections:
   - hot storage,
   - cold compressed storage,
   - protected result provenance,
   - prunable bytes,
   - expected reclaimed bytes,
   - next recommended command.

Acceptance:

- Live readiness distinguishes "storage healthy", "maintenance recommended", and "storage blocks live run".

## Phase 10 - Rollout Plan

Goal: deploy safely in increasing scope.

Steps:

1. Land audit-only inventory.
2. Land protected provenance graph.
3. Run audit on live DB and compare protected object counts to known predictions/scorecards.
4. Land compression support and run dry-run only.
5. Compress a cloned DB/artifact tree.
6. Verify handoff reports, scoring reports, and manifest resolution on clone.
7. Compress live eligible non-protected artifacts.
8. Add artifact pruning in clone only.
9. Verify restore from quarantine.
10. Apply live pruning only for non-scoreable/rejected/duplicate data.
11. Add market snapshot downsampling in clone.
12. Apply live downsampling only after prediction-linked snapshot protection tests pass.
13. Add scheduled maintenance only after at least two successful manual live runs.

## Concrete First Implementation Slice

The smallest useful slice is:

1. Extend `build_storage_maintenance_plan()` with artifact directory inventory, table bytes, largest files, and policy id.
2. Add protected provenance graph for `market_predictions`, `forecast_decision_records`, `evaluator_scorecards`, linked snapshots, and manifest refs.
3. Add dry-run classification of artifact files into protected, compressible, prunable, and unknown.
4. Add tests proving prediction-linked snapshots and artifacts are protected.
5. Add live-readiness warning if prunable/compressible storage exceeds a threshold.

This gives us visibility and safety before any compression or deletion is enabled.

## Non-Goals

- Do not delete prediction, forecast decision, scorecard, or prediction-time market baseline rows.
- Do not delete admitted evidence metadata needed to audit a scoreable prediction.
- Do not replace existing manifests with a separate storage registry.
- Do not schedule destructive maintenance before manual dry-run/apply cycles are proven.
- Do not use compression that the manifest resolver cannot verify.
