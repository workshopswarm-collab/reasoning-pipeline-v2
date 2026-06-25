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

Later `RET-*`, `CLS-*`, and `VER-*` rows add retrieval execution, provenance validation, breadth certification, researcher assignments, and verification behavior.
