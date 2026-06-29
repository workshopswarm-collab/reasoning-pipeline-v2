# ADS v2 QDT Remediation Plan

Date: 2026-06-29
Author: Workbench
Scope: Standalone plan for remediating QDT quality without duplicating the active retrieval/source-finding workstream.

Parent plan:
`/Users/agent2/.openclaw/workbench/plans/ads-v2-audit-remediation-end-to-end-plan.md`

Primary implementation surface:

- `decomposer/scripts/ads_decomposer/qdt.py`
- `decomposer/scripts/bin/run_decomposition.py`
- `decomposer/scripts/ads_decomposer/handoff.py`
- `decomposer/scripts/ads_decomposer/persistence.py`
- `decomposer/scripts/tests/test_qdt.py`
- `decomposer/scripts/tests/test_runtime_decomposition.py`
- Orchestrator QDT wake/persistence/reporting tests only where integration evidence is needed

## Executive Summary

QDT remediation is separate from search/source remediation.

The retrieval workstream should discover, fetch, admit, certify, and package evidence. QDT should define what needs to be investigated and how those findings should be classified. QDT is a research orchestration and coverage compiler, not a search engine, not a researcher, and not a forecast model.

Current QDT has a useful runtime/provenance/safety shell: model lane metadata, forbidden probability scans, persistence, and structural validation. The remaining gap is semantic quality. The audited live QDT was still too template-shaped and could pass specificity checks because old fixture leaf ids were absent. It did not yet express a market-resolution contract plus a market-specific research coverage graph.

The corrected chain is:

```text
decomposition -> research assignments -> classified findings -> verified feature ledger -> SCAE probability
```

QDT owns the first two links only:

- market-resolution contract
- research coverage graph
- per-leaf evidence requirements, classification targets, and sufficiency criteria
- no probabilities, fair values, numeric weights, SCAE deltas, decisions, or forecasts

## Current Status

Implementation update, 2026-06-29:

- The stricter QDT contract, research coverage graph, semantic specificity checks, and downstream `research_priority` compatibility are implemented in the active ADS v2 remediation changes.
- This document remains as the focused QDT design record; the parent end-to-end plan is the current coordination and verification map.

Known current strengths:

- Decomposer runtime can record `gpt-5.5-high` model execution.
- QDT artifacts can carry model provenance.
- Forbidden probability/fair-value fields are rejected in existing validators.
- QDT persistence rows are present and tested.
- Runtime fixture tests prove the current shell can emit question-specific leaves.

Known current gaps:

- `question_specificity_check` is still too shallow; absence of old fixture leaf ids is not semantic proof.
- QDT does not yet require `market_resolution_contract`.
- QDT does not yet require `research_coverage_graph`.
- Leaves do not yet consistently include `specificity_evidence`, `classification_targets`, `evidence_requirements`, `sufficiency_criteria`, `missingness_interpretation`, or `forbidden_outputs`.
- Candidate scoring still favors purpose coverage and weight labels rather than research coverage quality.
- The audited James Bond market should produce meaningful casting/process/rumor/blocker/timing/source-quality leaves, not only official-status/direct-evidence/rules leaves.

## Coordination Boundaries

This plan should not duplicate the active search/retrieval implementation work.

QDT may specify:

- what each leaf is asking
- why it matters for the market
- what evidence classes are required
- what values/relation/direction the researcher should classify
- what counts as sufficient, insufficient, contradicted, or structurally unavailable
- what AMRG context may be used as a hint or strict validated anchor

QDT must not specify:

- actual search execution
- URL fetching or browser/provider behavior
- source-family or claim-family final admission
- source timestamp admission
- researcher free-browsing behavior
- numeric probability, fair value, SCAE delta, or forecast decision

Retrieval owns source discovery, fetch/capture, deterministic admission, breadth certification, and packet assembly. Researchers receive bounded certified evidence/snippet refs and classify assigned leaves only. SCAE remains the only numeric forecast authority.

## Non-Negotiable QDT Invariants

- QDT is a research coverage artifact, not an inference model.
- QDT emits no probability-like, fair-value, forecast, SCAE-delta, or decision authority fields.
- Most leaves should be material research-factor leaves, not contract/source/timing checklist leaves.
- Contract guard leaves are allowed but should not dominate the graph.
- AMRG context is advisory unless a strict anchor is deterministically validated.
- Weak AMRG refs may become retrieval hints, not QDT selection/repair or forecast authority.
- QDT output must be useful to Retrieval, Researcher Swarm, Verification, and SCAE without requiring a later model to invent the missing structure.

## Target Artifact Shape

Add a required `market_resolution_contract` object:

- `yes_no_mapping`
- `resolution_subject`
- `resolution_authority`
- `contract_deadline`
- `forecast_cutoff`
- `platform_family_context`
- `ambiguous_terms`
- `disqualifying_evidence_types`
- `source_hierarchy`

Add a required `research_coverage_graph` object:

- `target_event_description`
- `coverage_dimensions`
- `research_factors`
- `contract_guard_leaf_ids`
- `material_question_leaf_ids`
- `required_leaf_ids_by_dimension`
- `overlap_groups`
- `unanswered_material_questions`
- `coverage_summary`

Extend each leaf with:

- `coverage_dimension`
- `research_factor`
- `leaf_question`
- `specificity_evidence`
- `evidence_requirements`
- `classification_targets`
- `sufficiency_criteria`
- `overlap_risk_with_leaf_ids`
- `missingness_interpretation`
- `forbidden_outputs`

Keep or map existing fields only when they remain useful:

- `question_text` can remain as display text, but `leaf_question` should be the normalized assignment question.
- Existing `purpose` can map to `coverage_dimension` or `research_factor`; it should not remain the only semantic field.
- Existing `research_sufficiency_requirements` should either derive from or validate against `sufficiency_criteria`.

## Generic Coverage Scaffold

Use generic dimensions, not a giant market taxonomy:

- `resolution_mechanics`
- `current_direct_evidence`
- `key_drivers`
- `counterevidence_negative_checks`
- `timing_deadline_constraints`
- `source_quality`
- `related_market_or_base_rate_context`
- `material_unknowns`

The decomposer must instantiate these into market-specific leaves. Missing dimensions are acceptable only when recorded as explicit `unanswered_material_questions` or policy-valid waivers.

## Phase 0 - Baseline And Fixtures

Goal: make the current QDT weakness reproducible before changing contracts.

Implementation:

1. Capture a fixture from the audited James Bond negative market.
2. Add focused invalid/valid QDT fixtures:
   - generic actor/announcement mad-lib leaves
   - resolution-checklist-only QDT with correct YES/NO mapping
   - grouped Polymarket child market with family ambiguity
   - valid research coverage graph for a negative semantic market
   - valid non-entertainment binary market
3. Preserve the current runtime/provenance tests so the transport shell does not regress.

Tests:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt scripts.tests.test_runtime_decomposition
```

Success criteria:

- Current validator weakness is represented by at least one failing or xfail-style fixture before the implementation change.
- Fixtures do not rely on live network calls.
- No temp generated QDT artifacts remain after the test run.

## Phase 1 - Contract Expansion

Goal: make the target QDT shape explicit and machine-checkable.

Implementation:

1. Add required `market_resolution_contract` validation.
2. Add required `research_coverage_graph` validation.
3. Add per-leaf required fields for specificity, evidence requirements, classification targets, sufficiency, missingness, overlap, and forbidden outputs.
4. Decide whether to keep `question-decomposition/v1` with stricter required fields or bump schema. Prefer a clean current-state contract unless compatibility with existing persisted artifacts is explicitly required.
5. Update persistence so new fields are preserved in artifact JSON and any extracted rows needed by downstream stages.

Tests:

- Missing contract object is rejected.
- Missing coverage graph is rejected.
- Missing per-leaf classification targets is rejected.
- Missing per-leaf evidence requirements is rejected.
- Missing per-leaf sufficiency criteria is rejected.
- Forbidden outputs are rejected anywhere in the new fields.

Success criteria:

- A valid QDT has enough structure to compile leaf research assignments without another model inventing missing schema.
- Existing no-probability/no-SCAE-authority tests still pass.

## Phase 2 - Semantic Specificity And Coverage Validator

Goal: reject QDTs that are syntactically valid but semantically shallow.

Implementation:

1. Add a semantic validator that computes:
   - `question_specificity_check.status`
   - `question_specificity_check.reason_codes`
   - `research_coverage_check.status`
   - `research_coverage_check.reason_codes`
2. Detect template/mad-lib leaves:
   - reusable across unrelated markets by entity swap
   - generic official/direct/rules/timing leaves with no market-specific payload
   - duplicate or overlapping leaves not grouped
3. Detect resolution-checklist domination:
   - guard leaves outnumber or equal material leaves
   - most leaves only ask source/timing/status questions
4. Detect missing semantic requirements:
   - negative-market YES/NO mapping not decomposed
   - market-family ambiguity not represented
   - ambiguous terms not decomposed
   - missing current direct evidence or counterevidence dimensions without unanswered-material-question entry

Tests:

- Generic actor/announcement mad-lib rejected.
- Resolution-checklist-only QDT rejected even with correct YES/NO mapping.
- Negative market without explicit YES/NO semantic mapping rejected.
- Grouped market without family/child ambiguity handling rejected.
- Valid research coverage graph accepted.

Success criteria:

- `question_specificity_check.status` can fail with actionable reason codes.
- `research_coverage_check.status` can fail with actionable reason codes.
- The old "generic fixture leaf ids absent" condition is not sufficient for pass.

## Phase 3 - Prompt And Runtime Output Alignment

Goal: make model output naturally target the new contract.

Implementation:

1. Update the decomposition request/prompt payload to demand analysis-first research coverage.
2. Include explicit language:

```text
Produce a bounded research decomposition that maximizes coverage of material uncertainty. Do not estimate probability. Do not assign weights. Do not make a final forecast. Emit leaf questions, purposes, evidence requirements, classification targets, and sufficiency criteria.
```

3. Tell the model to separate:
   - contract guard leaves
   - material research-factor leaves
   - material unknowns
   - overlap groups
4. Add schema repair only for shape normalization, not for semantic invention.
5. Keep OpenClaw OAuth lane provenance intact for `gpt-5.5-high`.

Tests:

- Fixture-mode response can satisfy new contract.
- Live-transport test still records `fixture_mode=false`, `model_executed=true`, and `resolved_model_id=gpt-5.5-high`.
- Schema repair does not add probabilistic fields or silently convert invalid semantic output into valid output.

Success criteria:

- Runtime output is contract-aligned before QDT materialization.
- Failed semantic validation fails closed.

## Phase 4 - Candidate Scoring And Selection

Goal: select the best research coverage graph, not the most superficially complete schema.

Implementation:

Replace or extend QDT scoring to reward:

- coverage diversity
- market specificity
- answerability
- independence and overlap clarity
- clean mapping to classification targets
- clear missingness semantics
- material research-factor coverage
- validated AMRG strict-anchor usage when available

Penalize:

- template similarity
- resolution-checklist domination
- ungrounded AMRG refs
- excessive leaf count without independent material value
- missing classification targets
- leaves that cannot produce a verified findings ledger

Tests:

- A valid but shallow checklist candidate loses to a richer coverage candidate.
- A candidate with unknown AMRG refs is rejected or loses.
- A candidate with duplicated leaves is rejected or loses unless overlap groups are explicit.

Success criteria:

- Candidate selection audit explains why the selected QDT was preferred.
- Candidate scoring is deterministic and testable.

## Phase 5 - Downstream Assignment Contract Bridge

Goal: make QDT output line up with active Retrieval and Researcher Swarm contracts.

Implementation:

1. Compile each QDT leaf into a stable research assignment seed:
   - leaf id
   - leaf question
   - coverage dimension
   - research factor
   - evidence requirements
   - classification targets
   - sufficiency criteria
   - missingness interpretation
   - forbidden outputs
2. Ensure leaf assignment expectations are compatible with active bounded certified snippet work:
   - QDT asks for evidence classes and values
   - Retrieval admits and packages evidence/snippets
   - Researchers receive bounded certified snippets/artifact refs
3. Do not let QDT demand free browsing by researchers.
4. Do not let QDT require raw source bodies in assignment packets.

Tests:

- QDT leaves compile into assignment-compatible fields.
- Researcher assignment builder can consume a valid QDT without fallback invention.
- Missing classification targets or sufficiency criteria block assignment compilation.

Success criteria:

- Retrieval and Researcher Swarm can consume QDT leaves deterministically.
- QDT output has no hidden dependency on later model interpretation.

## Phase 6 - End-To-End QDT Proof

Goal: prove QDT quality independently and then inside the full canary.

Implementation:

1. Run focused Decomposer tests.
2. Run Orchestrator wake/decomposer smoke tests.
3. Run a clone-only canary that proves:
   - QDT model executed
   - QDT semantic specificity passed
   - QDT research coverage passed
   - no forbidden probabilistic fields
   - retrieval receives meaningful leaf requirements
4. Use at least:
   - audited James Bond negative market
   - one non-entertainment binary market
   - one grouped/family Polymarket child market when available

Commands:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/wake_decomposer.py --help >/dev/null
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Success criteria:

- Generic filled-in template leaves are rejected.
- Resolution-checklist-only QDT outputs are rejected.
- The audited James Bond market produces contract guard leaves plus material leaves for casting stage, named candidate commitment, announcement readiness, blockers, rumor quality, timing constraints, claim-family independence, and material unknowns.
- QDT artifacts include model provenance for `gpt-5.5-high`.
- QDT artifacts include actionable `question_specificity_check` and `research_coverage_check`.
- No QDT output includes probabilities, numeric weights, probabilistic dependencies, SCAE deltas, fair values, or forecast decisions.

## Implementation Order

Recommended order:

1. Phase 0 fixtures
2. Phase 1 contract expansion
3. Phase 2 semantic validator
4. Phase 3 prompt/runtime alignment
5. Phase 4 candidate scoring
6. Phase 5 assignment bridge
7. Phase 6 canary proof

This order lets the implementation fail for the right reasons before changing model prompting or candidate scoring.

## Concurrent Work Guidance

The other session can continue source/retrieval work while this plan proceeds if file ownership stays clear:

- QDT session owns `decomposer/scripts/ads_decomposer/qdt.py`, `decomposer/scripts/bin/run_decomposition.py`, and Decomposer QDT tests.
- Retrieval session owns `researcher-swarm/scripts/researcher_swarm/retrieval.py`, browser/provider code, retrieval transport, and breadth/admission tests.
- Shared touchpoints should be coordinated before edits:
  - `researcher-swarm/scripts/researcher_swarm/assignments.py`
  - `orchestrator/scripts/predquant/ads_production_readiness_handlers.py`
  - canary tests that assert both QDT and retrieval behavior

If coordination is not available, prefer adding QDT-focused tests and validators first, then let the retrieval session adapt to the new stable QDT contract.

## Open Questions

- Should the stricter QDT shape remain `question-decomposition/v1`, or should it become a new schema revision?
- Should `research_sufficiency_requirements` be derived from `sufficiency_criteria`, or should both remain required and cross-validated?
- What minimum material-leaf count should be required for compact markets?
- Should AMRG strict-anchor usage be represented only in `research_coverage_graph`, or also repeated at the leaf level?
- Should QDT semantic checks be deterministic-only, or may an advisory model critique be used after deterministic validation exists?
