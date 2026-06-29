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
- The audited live Victor Marx QDT showed a temporal-mode defect: several generated leaves asked whether he `won`, what the official winner announcement stated, or how the market would resolve after the primary. Those are terminal verification questions. For an unresolved market, QDT must instead prioritize what should be investigated before resolution to support a forecast.

## Amendment - Pre-Resolution Forecast Research Versus Terminal Verification

The QDT must distinguish forecasting research from settlement verification.

For unresolved markets, QDT should answer:

```text
What current, pre-cutoff evidence and unresolved drivers should researchers classify so SCAE can forecast whether the market's YES outcome will occur?
```

It should not primarily answer:

```text
What official result will eventually settle the market after the event has resolved?
```

Terminal result leaves are still allowed, but only as bounded contract/settlement context:

- They may describe the official source hierarchy and future settlement authority.
- They may define what later verification would require after resolution.
- They must not dominate the dispatchable leaf set for unresolved scoreable forecasts.
- They must not be treated as current evidence unless the source is already available before the forecast cutoff.

For example, an unresolved election market should produce leaves about ballot access, candidate viability, campaign strength, polling, endorsements, fundraising, field quality, rules, timing, base-rate context, negative checks, and material unknowns. A leaf like `Was Victor Marx the overall winner?` should be classified as terminal verification and either gated off before resolution or rewritten into a pre-resolution driver question.

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
- For unresolved markets, most dispatchable leaves must be pre-resolution forecast-research leaves, not post-resolution winner/result-verification leaves.
- Terminal verification leaves must be explicitly typed and gated so they cannot masquerade as current forecast evidence.
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
- `forecast_research_objective`
- `market_temporal_state`
- `coverage_dimensions`
- `research_factors`
- `contract_guard_leaf_ids`
- `material_question_leaf_ids`
- `terminal_verification_leaf_ids`
- `dispatchable_pre_resolution_leaf_ids`
- `required_leaf_ids_by_dimension`
- `overlap_groups`
- `unanswered_material_questions`
- `coverage_summary`

Extend each leaf with:

- `leaf_temporal_role`
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

Allowed `leaf_temporal_role` values:

- `pre_resolution_forecast_driver`: current evidence, drivers, catalysts, base-rate context, or negative checks that can inform a forecast before resolution.
- `current_status`: already-observable pre-cutoff state, such as ballot access, candidacy, eligibility, campaign activity, or current source status.
- `resolution_mechanics`: rules, source hierarchy, deadlines, settlement criteria, and admissibility constraints.
- `terminal_verification`: official result or final winner checks that are only dispatchable after the market has resolved, unless the result is already available before the forecast cutoff.
- `material_unknown`: explicitly missing or structurally unavailable information whose absence must be carried into SCAE as missingness, not silently ignored.

Pre-resolution dispatch policy:

- If `market_temporal_state` is `unresolved`, `terminal_verification` leaves are non-dispatchable unless `terminal_verification.already_observable_before_cutoff=true`.
- If `market_temporal_state` is `resolved_or_settlement_audit`, terminal verification leaves may become dispatchable for settlement validation, but that is not the normal scoreable forecast path.
- `research_coverage_check` fails when terminal verification leaves dominate unresolved-market QDT coverage.

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

For unresolved markets, instantiate the generic scaffold as pre-resolution research:

- `current_direct_evidence`: what is already known before cutoff, not the future final result.
- `key_drivers`: mechanisms that make the YES outcome more or less likely.
- `counterevidence_negative_checks`: disqualifiers, blockers, contradictions, withdrawals, eligibility failures, or adverse evidence.
- `timing_deadline_constraints`: what evidence can count before cutoff and how close the market is to resolution.
- `source_quality`: which current sources are credible enough for classification.
- `material_unknowns`: what remains unknown and how missingness should affect SCAE.

## Concrete Components That May Need Changing

Primary likely code changes:

- `decomposer/scripts/ads_decomposer/qdt.py`
  - add `leaf_temporal_role` validation
  - add `forecast_research_objective`, `market_temporal_state`, `terminal_verification_leaf_ids`, and `dispatchable_pre_resolution_leaf_ids`
  - detect result-verification-dominant QDTs for unresolved markets
  - ensure `research_coverage_check` fails when pre-resolution coverage is inadequate
- `decomposer/scripts/ads_decomposer/model_runtime.py`
  - update the QDT prompt/request payload to demand pre-resolution forecast research for unresolved markets
  - forbid result-verification wording from becoming dominant except in `terminal_verification` leaves
- `decomposer/scripts/ads_decomposer/sufficiency_requirements.py`
  - derive sufficiency requirements from temporal role as well as purpose/priority
  - keep protected-primary requirements for source-of-truth leaves without forcing every forecast leaf into result verification
- `decomposer/scripts/bin/run_decomposition.py`
  - pass market temporal state, forecast cutoff, close/resolution timing, and scoreable/unresolved context into the decomposition request
- `decomposer/scripts/tests/test_qdt.py`
  - add fixtures for unresolved election/candidate markets where winner/result leaves must fail unless typed as gated terminal verification
  - add positive fixtures with campaign-strength, ballot-access, polling/reporting, blocker, timing, and missingness leaves
- `decomposer/scripts/tests/test_runtime_decomposition.py`
  - assert live/fixture runtime output includes temporal roles and passes pre-resolution coverage checks
- `researcher-swarm/scripts/researcher_swarm/assignments.py`
  - compile only dispatchable pre-resolution leaves for unresolved forecast runs
  - preserve terminal verification leaves as non-dispatchable context until settlement mode
- `researcher-swarm/scripts/tests/test_assignments.py`
  - prove terminal verification leaves do not become researcher assignments for unresolved markets
- `orchestrator/scripts/predquant/ads_production_readiness_handlers.py`
  - carry market temporal state into QDT input and preserve QDT temporal-role fields in stage artifacts
  - block classification/SCAE if QDT coverage passes schema but fails pre-resolution coverage
- `orchestrator/scripts/predquant/ads_operator_review.py` and `orchestrator/scripts/predquant/ads_live_readiness.py`
  - report result-verification-dominant QDTs as a true-runtime blocker for unresolved forecast canaries
- SCAE bridge/tests
  - treat `material_unknown` and missing pre-resolution driver coverage as missingness/invalidity inputs, not as zero evidence
  - reject scoreable forecast handoff when QDT only proves settlement mechanics or future result-verification requirements

## Evaluation And Cleanup Discipline

Each phase must include both durable regression tests and disposable evaluation artifacts.

Durable tests are normal repository tests and fixtures intentionally committed under existing test directories. Temporary evaluation artifacts are not durable and must be deleted after the phase evaluation completes.

Temporary artifacts include:

- clone SQLite databases
- canary JSON outputs
- generated QDT JSON not promoted into a permanent fixture
- scratch fixture builders
- one-off Python, shell, or jq scripts written only to conduct the evaluation
- temp logs, reports, and copied artifact directories

Temporary artifacts must be created under a phase-specific temp directory and removed with a cleanup trap:

```bash
TMPDIR="$(mktemp -d /tmp/ads-qdt-phase.XXXXXX)"
cleanup() {
  trash "$TMPDIR" 2>/dev/null || rm -rf "$TMPDIR"
}
trap cleanup EXIT

# Any one-off generated test script must live under "$TMPDIR".
# Do not create ad hoc test helpers in the repo unless they are intended
# to become durable regression tests.
```

Phase completion evidence should be a concise copied summary in the chat/session notes or a committed regression test, not retained scratch artifacts.

## Phase 0 - Baseline And Fixtures

Goal: make the current QDT weakness reproducible before changing contracts.

Status: completed on 2026-06-29. The durable regression suite now includes a Victor Marx-style unresolved election QDT that is dominated by terminal result-verification wording and recorded as an expected failure, plus a passing pre-resolution forecast-driver baseline for the same market shape.

Implementation:

1. Capture a fixture from the audited James Bond negative market.
2. Add focused invalid/valid QDT fixtures:
   - generic actor/announcement mad-lib leaves
   - resolution-checklist-only QDT with correct YES/NO mapping
   - unresolved election market whose leaves ask mainly whether the candidate won or what the official result announcement said
   - unresolved election market with valid pre-resolution forecast-driver leaves
   - grouped Polymarket child market with family ambiguity
   - valid research coverage graph for a negative semantic market
   - valid non-entertainment binary market
3. Capture the persisted Victor Marx live QDT shape as a regression fixture:
   - invalid when most dispatchable leaves are terminal verification or official-result checks
   - valid only after rewritten into pre-resolution forecast drivers plus separately gated terminal verification leaves
4. Preserve the current runtime/provenance tests so the transport shell does not regress.

Pseudocode:

```python
def build_phase0_fixture_matrix():
    return [
        invalid("generic_actor_announcement_madlib.json"),
        invalid("resolution_checklist_only.json"),
        invalid("unresolved_election_result_verification_dominant.json"),
        valid("unresolved_election_pre_resolution_forecast_research.json"),
        valid("negative_semantic_market_research_graph.json"),
    ]

def test_phase0_baseline_documents_current_gap():
    for fixture in build_phase0_fixture_matrix():
        result = validate_question_decomposition(load_fixture(fixture.path))
        assert result.status == fixture.expected_status
        assert_expected_reason_codes(result, fixture.expected_reason_codes)
```

Tests:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt scripts.tests.test_runtime_decomposition
```

Success criteria:

- Current validator weakness is represented by at least one failing or xfail-style fixture before the implementation change.
- Result-verification-dominant unresolved-market QDT is represented by a failing or xfail-style fixture before the implementation change.
- Fixtures do not rely on live network calls.
- No temp generated QDT artifacts remain after the test run.

## Phase 1 - Contract Expansion

Goal: make the target QDT shape explicit and machine-checkable.

Implementation:

1. Add required `market_resolution_contract` validation.
2. Add required `research_coverage_graph` validation.
3. Add per-leaf required fields for specificity, evidence requirements, classification targets, sufficiency, missingness, overlap, and forbidden outputs.
4. Add required temporal-role fields:
   - `research_coverage_graph.market_temporal_state`
   - `research_coverage_graph.forecast_research_objective`
   - `research_coverage_graph.terminal_verification_leaf_ids`
   - `research_coverage_graph.dispatchable_pre_resolution_leaf_ids`
   - per-leaf `leaf_temporal_role`
5. Decide whether to keep `question-decomposition/v1` with stricter required fields or bump schema. Prefer a clean current-state contract unless compatibility with existing persisted artifacts is explicitly required.
6. Update persistence so new fields are preserved in artifact JSON and any extracted rows needed by downstream stages.

Pseudocode:

```python
def validate_qdt_contract(qdt):
    require_object(qdt, "market_resolution_contract")
    require_object(qdt, "research_coverage_graph")
    graph = qdt["research_coverage_graph"]
    require_enum(graph, "market_temporal_state", {"unresolved", "resolved_or_settlement_audit"})
    require_list(graph, "terminal_verification_leaf_ids")
    require_list(graph, "dispatchable_pre_resolution_leaf_ids")

    leaves = {leaf["leaf_id"]: leaf for leaf in qdt["required_leaf_questions"]}
    for leaf in leaves.values():
        require_enum(leaf, "leaf_temporal_role", ALLOWED_TEMPORAL_ROLES)
        require_object(leaf, "classification_targets")
        require_object(leaf, "sufficiency_criteria")
        reject_forbidden_outputs(leaf)

    for leaf_id in graph["terminal_verification_leaf_ids"]:
        assert leaves[leaf_id]["leaf_temporal_role"] == "terminal_verification"
    if graph["market_temporal_state"] == "unresolved":
        for leaf_id in graph["dispatchable_pre_resolution_leaf_ids"]:
            assert leaves[leaf_id]["leaf_temporal_role"] != "terminal_verification"
```

Tests:

- Missing contract object is rejected.
- Missing coverage graph is rejected.
- Missing per-leaf classification targets is rejected.
- Missing per-leaf evidence requirements is rejected.
- Missing per-leaf sufficiency criteria is rejected.
- Missing per-leaf temporal role is rejected.
- `terminal_verification_leaf_ids` containing leaves not typed as `terminal_verification` is rejected.
- `dispatchable_pre_resolution_leaf_ids` containing terminal verification leaves is rejected for unresolved markets.
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
4. Detect terminal-verification domination for unresolved markets:
   - most dispatchable leaves ask whether the event `won`, `resolved`, `happened`, or what the final official result says
   - result-verification leaves are not typed as `terminal_verification`
   - terminal verification leaves are included in `dispatchable_pre_resolution_leaf_ids`
   - current forecast-driver dimensions are absent or waived without material-unknown entries
5. Detect missing semantic requirements:
   - negative-market YES/NO mapping not decomposed
   - market-family ambiguity not represented
   - ambiguous terms not decomposed
   - missing current direct evidence or counterevidence dimensions without unanswered-material-question entry
   - unresolved forecast market lacks material leaves for current evidence, drivers, negative checks, source quality, timing, and missingness

Pseudocode:

```python
RESULT_VERIFICATION_PATTERNS = [
    r"\bwon\b",
    r"\boverall winner\b",
    r"\bofficial result\b",
    r"\bfirst official announcement\b",
    r"\bresolved?\b",
]

def compute_research_coverage_check(qdt):
    graph = qdt["research_coverage_graph"]
    leaves = qdt["required_leaf_questions"]
    dispatchable = [leaf_by_id(qdt, leaf_id) for leaf_id in graph["dispatchable_pre_resolution_leaf_ids"]]

    terminal_like = [
        leaf for leaf in dispatchable
        if regex_any(RESULT_VERIFICATION_PATTERNS, leaf["leaf_question"] + " " + leaf.get("question_text", ""))
        or leaf["leaf_temporal_role"] == "terminal_verification"
    ]

    missing_dimensions = required_pre_resolution_dimensions(qdt) - covered_dimensions(dispatchable)
    if graph["market_temporal_state"] == "unresolved" and terminal_like:
        if len(terminal_like) / max(1, len(dispatchable)) >= TERMINAL_DOMINATION_THRESHOLD:
            fail("terminal_verification_dominates_unresolved_forecast_qdt")
    if missing_dimensions:
        fail("missing_pre_resolution_forecast_dimensions", missing_dimensions)
    if graph["coverage_summary"]["status"] == "requires_repair":
        fail("coverage_summary_requires_repair")
    return passed()
```

Tests:

- Generic actor/announcement mad-lib rejected.
- Resolution-checklist-only QDT rejected even with correct YES/NO mapping.
- Unresolved election QDT dominated by `who won` or `official winner announcement` leaves rejected.
- Unresolved election QDT with terminal verification leaves included in pre-resolution dispatch set rejected.
- Unresolved election QDT with ballot/campaign/polling/reporting/blocker/timing/missingness leaves accepted.
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

3. Add unresolved-market temporal instructions:

```text
If the market is unresolved at forecast time, prioritize pre-resolution forecast research. Ask what current evidence, drivers, blockers, source quality, timing constraints, and missing information should be classified before cutoff. Do not make official-result or final-winner verification the dominant dispatchable leaf set. Put future settlement/result checks in terminal_verification leaves and mark them non-dispatchable before resolution unless already observable before the source cutoff.
```

4. Tell the model to separate:
   - contract guard leaves
   - material research-factor leaves
   - material unknowns
   - overlap groups
   - terminal verification leaves
   - dispatchable pre-resolution leaves
5. Add schema repair only for shape normalization, not for semantic invention.
6. Keep OpenClaw OAuth lane provenance intact for `gpt-5.5-high`.

Pseudocode:

```python
def build_decomposer_prompt(handoff):
    temporal_state = classify_market_temporal_state(
        forecast_timestamp=handoff["forecast_timestamp"],
        close_timestamp=handoff.get("close_timestamp"),
        resolution_status=handoff.get("resolution_status"),
    )
    return {
        "schema_version": "decomposer-qdt-request/v1",
        "market_temporal_state": temporal_state,
        "source_cutoff_timestamp": handoff["source_cutoff_timestamp"],
        "instruction_blocks": [
            NO_PROBABILITY_AUTHORITY,
            PRE_RESOLUTION_FORECAST_RESEARCH_INSTRUCTIONS,
            TERMINAL_VERIFICATION_GATING_INSTRUCTIONS,
            REQUIRED_OUTPUT_SCHEMA,
        ],
    }

def repair_model_output(candidate, validation_errors):
    if only_shape_errors(validation_errors):
        return normalize_schema_shape(candidate)
    raise QDTValidationError("semantic repair must not invent forecast coverage")
```

Tests:

- Fixture-mode response can satisfy new contract.
- Live-transport test still records `fixture_mode=false`, `model_executed=true`, and `resolved_model_id=gpt-5.5-high`.
- Schema repair does not add probabilistic fields or silently convert invalid semantic output into valid output.
- Prompt fixture for an unresolved election does not produce a dispatchable set dominated by final-winner/result-verification questions.

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
- pre-resolution forecast-driver coverage for unresolved markets
- proper segregation of terminal verification leaves
- validated AMRG strict-anchor usage when available

Penalize:

- template similarity
- resolution-checklist domination
- result-verification domination on unresolved markets
- terminal verification leaves marked as dispatchable pre-resolution
- ungrounded AMRG refs
- excessive leaf count without independent material value
- missing classification targets
- leaves that cannot produce a verified findings ledger

Pseudocode:

```python
def score_qdt_candidate(qdt):
    checks = run_qdt_checks(qdt)
    if checks.status != "passed":
        return reject(checks.reason_codes)
    score = 0
    score += coverage_diversity_points(qdt)
    score += market_specificity_points(qdt)
    score += pre_resolution_driver_points(qdt)
    score += missingness_clarity_points(qdt)
    score -= template_similarity_penalty(qdt)
    score -= resolution_checklist_domination_penalty(qdt)
    score -= terminal_verification_domination_penalty(qdt)
    score -= unsupported_amrg_penalty(qdt)
    return score
```

Tests:

- A valid but shallow checklist candidate loses to a richer coverage candidate.
- A result-verification-heavy unresolved-market candidate loses to a pre-resolution forecast-research candidate.
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
   - leaf temporal role
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
   - unresolved forecast runs dispatch only pre-resolution forecast-driver/current-status/resolution-mechanics/material-unknown leaves allowed by policy
   - terminal verification leaves remain context or settlement-mode assignments only
3. Do not let QDT demand free browsing by researchers.
4. Do not let QDT require raw source bodies in assignment packets.
5. Ensure SCAE receives missingness/coverage metadata when pre-resolution driver leaves are insufficient, rather than receiving a thin result-verification packet as if it were forecast evidence.

Pseudocode:

```python
def compile_leaf_assignments(qdt, retrieval_packet):
    graph = qdt["research_coverage_graph"]
    leaf_ids = graph["dispatchable_pre_resolution_leaf_ids"]
    assignments = []
    for leaf_id in leaf_ids:
        leaf = leaf_by_id(qdt, leaf_id)
        if graph["market_temporal_state"] == "unresolved":
            assert leaf["leaf_temporal_role"] != "terminal_verification"
        assignments.append({
            "leaf_id": leaf_id,
            "leaf_question": leaf["leaf_question"],
            "leaf_temporal_role": leaf["leaf_temporal_role"],
            "classification_targets": leaf["classification_targets"],
            "evidence_requirements": leaf["evidence_requirements"],
            "certified_snippet_refs": certified_refs_for_leaf(retrieval_packet, leaf_id),
            "forbidden_outputs": leaf["forbidden_outputs"],
        })
    if not assignments and graph["market_temporal_state"] == "unresolved":
        raise AssignmentError("missing_dispatchable_pre_resolution_leaf_assignments")
    return assignments
```

Tests:

- QDT leaves compile into assignment-compatible fields.
- Researcher assignment builder can consume a valid QDT without fallback invention.
- Missing classification targets or sufficiency criteria block assignment compilation.
- Terminal verification leaves do not compile into researcher assignments for unresolved scoreable forecast runs.
- Missing pre-resolution forecast-driver coverage blocks SCAE-ready handoff.

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
   - unresolved-market QDT dispatchable leaves are pre-resolution forecast-research leaves
   - terminal verification leaves, if present, are typed and gated
   - no forbidden probabilistic fields
   - retrieval receives meaningful leaf requirements
4. Use at least:
   - audited James Bond negative market
   - one non-entertainment binary market
   - one grouped/family Polymarket child market when available

Pseudocode:

```python
def run_qdt_end_to_end_clone_batch(case_selectors):
    results = []
    for selector in case_selectors:
        with temporary_clone_db(prefix="ads-qdt-e2e") as db_path:
            run_id = run_ads_canary(
                db_path=db_path,
                case_selector=selector,
                require_qdt_model_executed=True,
                require_qdt_specificity_passed=True,
                require_qdt_research_coverage_passed=True,
            )
            qdt = load_stage_artifact(db_path, run_id, stage="decomposition")
            assert qdt["model_execution_context"]["model_executed"] is True
            assert qdt["question_specificity_check"]["status"] == "passed"
            assert qdt["research_coverage_check"]["status"] == "passed"
            assert_pre_resolution_dispatchable_leaves(qdt)
            assert_terminal_verification_gated(qdt)
            assert_no_forbidden_forecast_fields(qdt)
            results.append(summarize_qdt_result(qdt))
    return results
```

Commands:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/wake_decomposer.py --help >/dev/null
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Temporary canary/evaluation wrapper scripts must be written only under `"$TMPDIR"` and removed by the cleanup trap. Do not leave generated helper scripts under `decomposer/scripts/bin`, `orchestrator/scripts/bin`, or `workbench/plans` unless they are intentionally promoted into durable implementation files.

Success criteria:

- Generic filled-in template leaves are rejected.
- Resolution-checklist-only QDT outputs are rejected.
- Result-verification-dominant unresolved-market QDT outputs are rejected.
- For unresolved markets, `research_coverage_check` fails if dispatchable leaves are mostly final-winner/result-verification questions.
- The audited James Bond market produces contract guard leaves plus material leaves for casting stage, named candidate commitment, announcement readiness, blockers, rumor quality, timing constraints, claim-family independence, and material unknowns.
- The Victor Marx-style election market produces pre-resolution leaves for ballot access/eligibility, campaign strength, field quality, polling/reporting/endorsements/fundraising where available, negative checks/blockers, timing, source quality, and material unknowns; official final-winner verification is present only as gated terminal verification.
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

## Evaluation Test Suite Matrix

Run this matrix as phases mature. Keep committed regression tests; delete generated evaluation artifacts and one-off runner scripts after each run.

Phase 0 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
```

Phase 1 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
```

Phase 2 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
```

Phase 3 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 scripts/bin/run_decomposition.py --help >/dev/null
```

Phase 4 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
```

Phase 5 suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_assignments
python3 -m unittest scripts.tests.test_isolation
```

Phase 6 suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_live_readiness
python3 -m unittest scripts.tests.test_ads_operator_review
```

Ephemeral clone-canary template:

```bash
TMPDIR="$(mktemp -d /tmp/ads-qdt-e2e.XXXXXX)"
cleanup() {
  trash "$TMPDIR" 2>/dev/null || rm -rf "$TMPDIR"
}
trap cleanup EXIT

cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"
cat > "$TMPDIR/run_qdt_e2e_check.py" <<'PY'
# One-off evaluation script. Must remain under TMPDIR and be deleted by trap.
PY

python3 "$TMPDIR/run_qdt_e2e_check.py"
```

Success condition for cleanup:

- `find /tmp -maxdepth 1 -name 'ads-qdt-*'` shows no stale phase directories from the run.
- `git status --short` shows no accidental generated test scripts or temp JSON artifacts.
- Only intentional source changes and durable regression tests remain.

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
- What maximum terminal-verification share should be allowed for unresolved markets before failing QDT coverage?
- Should `leaf_temporal_role` live only in QDT, or should it be persisted into downstream assignment and verification tables for audit/reporting?
- Should AMRG strict-anchor usage be represented only in `research_coverage_graph`, or also repeated at the leaf level?
- Should QDT semantic checks be deterministic-only, or may an advisory model critique be used after deterministic validation exists?
