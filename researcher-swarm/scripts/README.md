# ADS Researcher Swarm Scripts

This folder is the runtime script surface for ADS Researcher Swarm. It owns retrieval,
leaf-research preparation, and downstream classification/verification helpers.

## Folder Contract

- `bin/`: runnable entrypoints, kept thin.
- `researcher_swarm/`: importable Python package for retrieval, subagent coordination, classification, coverage proofs, verification, and sufficiency reconciliation.
- `migrations/`: researcher-swarm-owned persistence migrations if needed.
- `tests/`: focused tests for leaf research, classification, coverage, and verification behavior.
- `data/`: local fixture data only.
- `.runtime-state/`: generated reports, locks, heartbeats, and transient outputs.
- `requirements.txt`: Python dependencies for this script bundle.

## Implemented Surface

- `researcher_swarm/retrieval.py`: `RET-001` retrieval packet schema and deterministic query planning.
- `researcher_swarm/retrieval_quality.py`: `RET-003` deterministic retrieval quality slice/report scoring over `retrieval-packet/v1`.
- `researcher_swarm/model_preflight.py`: `RET-007` report-only local embedding/reranker preflight and resource-cap diagnostics.
- `researcher_swarm/classification.py`: `CLS-001` fail-closed researcher NLI classification prompt contract rendering over finalized `retrieval-packet/v1` dispatch artifacts; `CLS-002` deterministic `researcher-sidecar/v2` builder/validator with recursive no-probability enforcement, leaf coverage checks, coverage proof checks, sufficiency certificate refs, digest refs, and model execution context metadata checks.
- `researcher_swarm/classification_matrix.py`: `CLS-003` materializes schema-valid `researcher-sidecar/v2` artifacts into classification, provenance, and CLS-003 support-only coverage proof slices with deterministic matrix digests.
- `researcher_swarm/supplemental.py`: `CLS-004` normalizes raw supplemental citation refs into deterministic `normalized-supplemental-evidence/v1` records with source, claim-family, temporal, access, degraded, protected-primary, and matrix-join boundaries.
- `researcher_swarm/coverage.py`: `CLS-005` builds deterministic evidence-review coverage proof bundles over CLS-002 sidecars, CLS-003 matrix rows, CLS-006 assignments, CLS-008 audits, and RET-008 certificates with fail-closed assignment, review, requirement, and no-authority checks.
- `researcher_swarm/model_context.py`: `MODEL-003` deterministic metadata-only researcher leaf NLI model lane resolution for `gpt-5.5-high`.
- `researcher_swarm/assignments.py`: `CLS-006` compact `leaf-research-assignment/v1` builder/validator for RET-008 dispatchable QDT leaves, carrying refs, digests, context-isolation refs, model context, sidecar output contract, and budget caps without embedding QDT leaf blobs, evidence bodies, probabilities, fair values, intervals, or decision recommendations.
- `researcher_swarm/isolation.py`: `CLS-008` compact prelaunch `researcher-context-isolation/v1` audit builder/validator for fresh context, visible-ref allowlists, forbidden-ref scans, peer-output exclusion, allowed shared schema/prompt refs, launch blocking, and deterministic audit digests without spawning subagents.
- `researcher_swarm/verification.py`: `VER-001` direction verification slices and `VER-002` evidence-quality verification slices over materialized CLS-003 rows, with no SCAE ledger writes, model calls, or production forecasts.
- `bin/build_retrieval_packet.py`: builds a schema-only `retrieval-packet/v1` from a validated QDT.

## Expected Future Entrypoints

- `bin/run_researcher_swarm.py`
- `bin/spawn_leaf_researchers.py`
- `bin/run_native_gpt_research.py`
- `bin/run_browser_retrieval.py`
- `bin/run_source_metadata_classifier.py`
- `bin/build_retrieval_breadth_profile.py`
- `bin/run_retrieval_expansion.py`
- `bin/validate_retrieval_breadth.py`
- `bin/validate_researcher_sidecars.py`
- `bin/reconcile_research_sufficiency.py`

Later `RET-*`, `CLS-*`, and `VER-*` rows add retrieval execution, provenance validation, breadth certification, context isolation launch behavior, escalation logic, and verification behavior.
