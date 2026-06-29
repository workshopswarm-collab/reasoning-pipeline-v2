# ADS v2 End-to-End Audit Remediation Plan

Date: 2026-06-28
Author: Workbench
Scope: Phase-by-phase implementation plan to remediate the ADS v2 live-runtime audit failures found during the clone-only strict canary run.

## Guiding Purpose

This plan is the operating map for turning ADS v2 from a partially wired canary path into a verified end-to-end forecasting pipeline. Its purpose is to keep remediation phased, testable, and non-duplicative: each phase should fix the next real blocker, preserve already-remediated source/retrieval safeguards, and prove progress with regression tests plus clone-only canaries before moving toward live cutover. The target end state is a pipeline where QDT defines meaningful research coverage, AMRG supplies only validated context, retrieval admits only certified pre-cutoff evidence, researchers classify bounded evidence without forecasting, SCAE remains the sole numeric forecast authority, and readiness reports reflect actual runtime health.

Source spec:
`/Users/agent2/.openclaw/media/inbound/autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md`

Observed audit run:

- Run id: `ads-pipeline-run:ebbbe0edf2abc9f07a17bc4c902994d0961a79945f2fbd18546d44a78a64d3d2`
- Case: `polymarket:572133`, "No one announced as next James Bond?"
- Clone DB: `/tmp/ads-e2e-audit.zRzjmY/predquant.sqlite3`
- Terminal failure: retrieval rejected selected evidence with `source_after_cutoff`
- Completed stages: case selection, evidence packet, policy context, related-market context, decomposition
- Not reached: researcher classification, verification, SCAE, synthesis, decision, training trace, replay record

## Executive Summary

The strict canary proved that the pipeline is not yet behaving as the v2 architecture intends. The decomposer model lane executed, but QDT quality was too template-shaped. AMRG admitted irrelevant related markets and did not run its intended model-assist lane. Retrieval failed before producing a certified packet. The researcher swarm did not deploy. SCAE passed its standalone tests but was not exercised on verified live evidence. Operator and readiness reports returned overly green statuses despite the true-runtime failure.

This plan fixes the pipeline by tightening the intelligence layer and the gates around it:

1. Make observability and readiness reflect true runtime health.
2. Replace shallow QDT "filled-in template specificity" with anatomy-based decomposition.
3. Fix AMRG candidate filtering and enable audited `gpt-5.4-high` AMRG model assist.
4. Fix retrieval temporal metadata handling, source certification, and live search/native research execution.
5. Ensure the researcher swarm actually deploys with `gpt-5.5-high` model-executed evidence when retrieval is sufficient.
6. Prove SCAE consumes verified classifications and remains the only numeric forecast authority.
7. Run strict clone canaries until all stages complete with manifest, model, and evidence provenance.

Permanent regression tests should stay in the repo. Phase-local scratch harnesses, cloned DBs, temp artifacts, and one-off debug outputs should be deleted after each phase.

## Current Repo Delta Review - 2026-06-29

Recent commits on `main` materially advanced the retrieval side of this plan and now cover the 21-item source/retrieval remediation tranche from the concurrent session:

- `eeb2a03` through `8da313b` wired retrieval providers, configured browser/search provider paths, added OpenAI/OpenClaw search transport coverage, proved `web_fetch` is URL fetch/extraction rather than search, and established a live browser-search canary path.
- `5cc89a8` through `e3ba9e0` added stricter canary evidence gates, pilot-vs-real retrieval separation, runtime proof lanes, live retrieval source-collation acceptance, and terminal acceptance/blocking checks.
- `166b49b` through `2d8e17d` improved RET-008 live retrieval breadth, source-time handling, empty-fetch failure behavior, direct URL/source authority limits, claim/source family validation, and source/claim family certification.
- `d7a2383`, `2c966b0`, and `fb36025` tightened Researcher Swarm assignment inputs, required bounded certified snippets, constrained researchers to certified evidence classification, and exposed terminal retrieval outcome state.

Plan amendments from this review:

- Phase 1 should distinguish non-scoreable canary diagnostics from release/cutover blockers. Missing retrieval/researcher/SCAE evidence may be a warning for explicitly non-scoreable canaries, but must be a blocker for release, scoreable, or cutover readiness.
- Phase 4 should no longer duplicate the completed source/retrieval implementation unless a regression test or live canary exposes a gap. Its default work is now verification, representative live-case evidence quality, native research when policy-enabled, metadata classifier policy, and canary evidence from more than the controlled search fixture.
- Native research is required to use `gpt-5.5-high` and OpenClaw OAuth when enabled or policy-required, but should not be treated as an unconditional blocker when browser/direct retrieval certifies sufficient evidence and policy records native research as disabled or unavailable.
- Phase 5 should treat bounded certified snippet/artifact access and the retrieval/researcher responsibility boundary as implemented regression requirements. New work should focus on integration with QDT outputs, live researcher execution proof, and SCAE-ready verification, not rebuilding the assignment contract.
- Phase 7 must run the live retrieval acceptance gate after each phase that changes QDT, AMRG, retrieval, researcher assignment, verification, or SCAE intake behavior. The gate must prove sufficient accepted evidence or a clean insufficiency/unanswerability blocker.

## Source/Retrieval 21-Item Cross-Reference - 2026-06-29

Status: implemented on `main` through `e3ba9e0`. During phase-by-phase remediation, do not reimplement these items unless the listed regression tests or clone canaries fail. If later QDT/AMRG/researcher changes alter the retrieval contract, extend the tests and acceptance gates rather than duplicating the already-landed source-discovery machinery.

| # | Completed item | Remediation commits | Plan verification point |
|---|---|---|---|
| 1 | True runs produced no real candidates | `eeb2a03`, `7ada77a`, `1303527`, `b766e32`, `8da313b`, `e3ba9e0` | Phase 4/7: canary must show nonzero candidate/fetch/admitted-evidence flow or a clean blocker. |
| 2 | Provider wiring/config was missing in earlier strict runs | `eeb2a03`, `7ada77a`, `b766e32`, `f632c5a` | Phase 4: production handler tests must prove configured provider and fail-closed behavior. |
| 3 | Search was not proven end-to-end | `8da313b`, `e3ba9e0` | Phase 7: live retrieval acceptance must pass, not just fixture-level search wiring. |
| 4 | `web_fetch` must not be treated as search | `2f8a208`, `75fdddb` | Phase 4: retrieval tests must preserve `web_fetch` as URL fetch/extraction only. |
| 5 | Direct URL discovery was too thin | `8cddae5`, `af0c808`, `9369e18` | Phase 4: direct URL capture remains first-class, but authority/freshness still validates deterministically. |
| 6 | Browser/direct/native/classifier proof lanes were unclear | `5cc89a8`, `fa0dd9e`, `52287cf`, `e3ba9e0` | Phase 1/4/7: reports expose distinct runtime counters and statuses. |
| 7 | Pilot retrieval could look healthier than real retrieval | `52287cf`, `e3ba9e0` | Phase 1/7: pilot metadata cannot satisfy true-runtime source proof. |
| 8 | Source time vs capture time confusion | `7729063`, `20971e2`, `9369e18` | Phase 4: source publication/update time, not fetch time, controls freshness. |
| 9 | Inferred source timestamps could over-credit freshness | `20971e2`, `9369e18`, `af0c808` | Phase 4: inferred or market-hint timestamps do not satisfy current-event freshness alone. |
| 10 | Missing fetched content must fail closed | `bf7031a`, `90ee368` | Phase 4: empty/no-content candidates cannot become admitted evidence. |
| 11 | Fetch/provider output could leak authority | `37f70a5`, `5ca54a1`, `a20a7b9` | Phase 4: provider claim/source hints remain assistive until validator-accepted. |
| 12 | Source-class hints were too trusted | `7750e73`, `b51cd08`, `af0c808` | Phase 4: deterministic resolver owns final source class/family. |
| 13 | Market URL counted as protected primary for real-world event | `af0c808` | Phase 4: market URLs can support rules/resolution mechanics, not external-event proof. |
| 14 | Source-family diversity could be overcounted | `166b49b`, `2d8e17d`, `e3ba9e0` | Phase 4/7: independent source family means publisher/API/service/wire/domain family, not page hash. |
| 15 | Duplicate/syndicated content needed stronger collapse | `166b49b`, `2d8e17d` | Phase 4: syndicated/duplicate families do not satisfy breadth. |
| 16 | Claim-family diversity could be too easy to satisfy | `a20a7b9`, `2d8e17d` | Phase 4: claim family comes from grounded normalized claims, not provider-supplied tuples alone. |
| 17 | Unknown metadata must remain `unknown_not_counted` | `2d8e17d`, `fb36025` | Phase 4/7: unknown source/claim/family fields block sufficiency when required. |
| 18 | Researchers could receive refs/hashes without enough text | `d7a2383` | Phase 5: assignments require bounded certified snippets/artifact access. |
| 19 | Retrieval vs researcher responsibility boundary needed hardening | `2c966b0`, `d7a2383` | Phase 5: researchers classify certified evidence; search expansion stays upstream and revalidated. |
| 20 | Structural unanswerability vs thin retrieval was implicit | `fb36025`, `e3ba9e0` | Phase 4/7: terminal retrieval outcome distinguishes certified insufficiency from thin unblocked advancement. |
| 21 | Search/source collation needed live acceptance test | `e3ba9e0` | Phase 7: live acceptance checks candidates, fetches, admitted evidence, non-market source families, protected-primary/freshness where required, and blocked status for unmet dimensions. |

## Phase-by-Phase Verification Rule

Before starting a phase, classify whether the phase changes QDT, AMRG, retrieval/source collation, researcher assignment, verification, SCAE intake, or reporting/readiness. For any area covered by the 21-item cross-reference, first run or inspect the listed regression surface and treat passing behavior as already implemented.

After each phase:

- Run that phase's targeted unit tests.
- If the phase changes QDT/AMRG outputs that feed retrieval, retrieval itself, researcher assignment inputs, verification, or SCAE intake, also run `orchestrator/scripts/tests/test_ads_operational_canary.py` and inspect the live retrieval acceptance fields.
- If the phase changes only reporting/readiness, run the reporting/readiness tests plus the smallest canary report fixture that proves missing evidence still fails closed.
- Record whether the phase preserved, extended, or regressed each relevant 21-item fix. Only implement new retrieval/source changes when this check identifies a concrete failing behavior.

## Non-Negotiable Runtime Invariants

- SCAE is the only production numeric forecast authority.
- Decomposer QDT and researcher NLI classification use `gpt-5.5-high` through OpenClaw Codex OAuth lanes.
- AMRG model assist uses the intended AMRG lane, default `gpt-5.4-high`, through OpenClaw Codex OAuth.
- Native research candidate discovery uses `gpt-5.5-high` when enabled and available.
- Small source metadata classifier assist uses the bounded OpenAI OAuth-routed lane only when configured and validator-accepted.
- Models may assist decomposition, relationship review, retrieval discovery, metadata parsing, and evidence classification. They may not author probabilities, market fair values, SCAE deltas, or execution decisions.
- The decomposition tree/factor graph is a research orchestration and coverage model, not an inference model. It compiles investigation scope, assignments, classified findings, and coverage status; SCAE remains the only component that converts verified findings into numeric probability.
- Retrieval must distinguish source publication/update/authored times from capture times. Capture after forecast cutoff is allowed only as a retrieval act; post-cutoff source facts are not evidence for the forecast-time state.
- Operator/readiness reports must fail closed when true runtime canary evidence is missing, stages fail, researcher models do not execute, or SCAE does not receive verified evidence for a scoreable run.
- Operator/readiness severity may be lower for explicitly non-scoreable canary runs only when the reports clearly preserve the blocked/non-scoreable status and do not claim release or scoreable readiness.

## Documentation Review Protocol

Run this before changing model/OAuth/runtime code in any phase.

Required local docs and contracts:

- `orchestrator/plans/autonomous-decomposition-swarm-implementation-plan.md`
- `orchestrator/plans/autonomous-decomposition-swarm-session-02-evidence-policy-amrg.md`
- `orchestrator/plans/autonomous-decomposition-swarm-session-03-decomposer-retrieval.md`
- `orchestrator/plans/autonomous-decomposition-swarm-session-05-scae-decision-evaluator.md`
- `orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json`
- `orchestrator/plans/autonomous-decomposition-swarm-script-placement-map.md`
- `decomposer/AGENTS.md`
- `researcher-swarm/AGENTS.md`
- `SCAE/AGENTS.md` if present, otherwise `SCAE/README.md`
- `orchestrator/AGENTS.md` and `orchestrator/TOOLS.md`

OpenClaw/OAuth implementation surfaces to inspect:

- `decomposer/scripts/ads_decomposer/model_runtime.py`
- `decomposer/scripts/ads_decomposer/handoff.py`
- `researcher-swarm/scripts/researcher_swarm/model_context.py`
- `researcher-swarm/scripts/researcher_swarm/openclaw_runtime.py`
- `researcher-swarm/scripts/researcher_swarm/browser_provider.py`
- `researcher-swarm/scripts/researcher_swarm/retrieval.py`
- `orchestrator/scripts/predquant/amrg.py`
- `orchestrator/scripts/predquant/ads_retrieval_transport.py`

Official OpenAI documentation review is only required if a phase changes a direct OpenAI HTTP fallback or OpenAI tool schema. The preferred live route is OpenClaw OAuth. Do not bypass OpenClaw OAuth for v2 runtime lanes unless VM explicitly approves a direct OpenAI integration change.

Documentation review checklist:

- [ ] Confirm model lane ids, default model ids, provider routes, and `oauth_route_required=true`.
- [ ] Confirm no new component invents a probability-authoring model path.
- [ ] Confirm OpenClaw OAuth route payloads are auditable: prompt hash, input artifact hash, output artifact hash, resolved model id, provider route, latency, execution status.
- [ ] Confirm runtime failures record structured reason codes and do not masquerade as readiness success.

## Phase 0 - Baseline Reproduction and Audit Harness

Goal: make the current failure reproducible, bounded, and easy to compare after each phase.

Concrete implementation:

- Add or update a local audit runbook in the plan itself, not a long-lived runtime script unless repeated manual steps become error-prone.
- Capture a fresh clone-only strict canary baseline before code changes.
- Record all critical refs in one temp directory:
  - DB clone path
  - canary output JSON
  - handoff report JSON
  - real-runtime canary report JSON
  - operator review JSON
  - readiness report JSON
- Ensure live DB is not mutated except for explicit preflight/read-only checks.

Pseudocode:

```text
tmpdir = mktemp("/tmp/ads-v2-remediation-baseline.XXXXXX")
cp live_predquant_db tmpdir/predquant.sqlite3
run strict one-case canary against tmpdir/predquant.sqlite3
run handoff report against run_id
run real-runtime canary report against run_id
run operator review against run_id
run live readiness against clone DB
write compact baseline summary into phase notes
delete tmpdir after summary is committed to the plan or phase report
```

Commands:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --require-researcher-model-executed \
  --allow-non-scoreable \
  --skip-existing-ads-predictions \
  --metadata-json '{"audit_id":"ads-v2-remediation-baseline","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary-output.json"
```

Tests:

- No new permanent tests required in Phase 0.
- Use only phase-local temp DBs and JSON outputs.
- Delete temp DBs and JSON outputs after extracting the baseline summary.

Success criteria:

- [ ] Current failure is reproducible or a new failure is captured with the same report set.
- [ ] No scoreable predictions or production forecasts are written to live DB.
- [ ] The baseline explicitly records whether QDT, AMRG, retrieval, researcher, and SCAE runtime signals were observed.
- [ ] Temporary phase artifacts are deleted or moved into an intentional phase report.

## Phase 1 - Truthful Observability, Readiness, and Duration Accounting

Goal: readiness and operator tools must expose true failures before deeper component fixes begin.

Audit findings addressed:

- Operator review returned `review_passed` despite retrieval failure and zero researcher/SCAE evidence.
- Live readiness returned `ready` despite missing strict canary evidence.
- Stage `duration_ms` was `0` for long-running stages.

Concrete implementation:

- Update `orchestrator/scripts/bin/report_ads_operator_review.py` or its backing module so true-production stage failure, zero admitted evidence, missing researcher model execution, and missing SCAE ledger are blockers for release, cutover, scoreable readiness, or scoreable forecast paths. Explicit non-scoreable canaries may report these as warnings only when the run is clearly blocked/non-scoreable and cannot be mistaken for release readiness.
- Update `orchestrator/scripts/bin/check_ads_live_readiness.py` or backing module to distinguish base infrastructure health from true v2 cutover readiness.
- Update stage event writing in the pipeline runner so `duration_ms` is computed from start/end event timestamps or monotonic timers.
- Add a machine-readable `true_runtime_cutover_status` field:
  - `ready`
  - `blocked_stage_failure`
  - `blocked_missing_retrieval_cert`
  - `blocked_missing_researcher_model_execution`
  - `blocked_missing_scae_ledger`
  - `blocked_missing_strict_canary`

Pseudocode:

```python
def classify_operator_status(run):
    blockers = []
    if run.terminal_status in {"failed", "stage_failed"}:
        blockers.append("true_runtime_stage_failed")
    if run.retrieval_packet_count == 0 or run.admitted_evidence_count == 0:
        add_release_blocker_or_non_scoreable_warning("true_production_zero_admitted_evidence_refs")
    if run.requires_researcher_model and run.researcher_model_executed_count == 0:
        add_release_blocker_or_non_scoreable_warning("researcher_model_runtime_not_verified")
    if run.valid_forecast_expected and run.scae_ledger_count == 0:
        blockers.append("scae_ledger_not_verified")
    return "review_failed" if blockers else "review_passed"

def write_stage_completed(stage_attempt):
    duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
    write_event(stage="...", event="stage_completed", duration_ms=duration_ms)
```

Tests:

- Add regression tests under `orchestrator/scripts/tests/`.
- Include fixtures for:
  - retrieval failed with zero evidence
  - researcher model missing
  - SCAE missing for valid forecast
  - successful full run
  - duration computed from nonzero timestamps
- Keep permanent regression tests.
- Delete temp DB clones and ad hoc JSON outputs after test runs.

Commands:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest \
  scripts.tests.test_ads_live_readiness \
  scripts.tests.test_ads_operator_review \
  scripts.tests.test_ads_pipeline_runner \
  scripts.tests.test_ads_stage_logging
```

Success criteria:

- [ ] A failed true-runtime canary cannot produce `review_passed`.
- [ ] Readiness cannot return v2 cutover `ready` when strict canary evidence is missing.
- [ ] Non-scoreable canary warnings cannot satisfy release/cutover readiness.
- [ ] Nonzero stage duration is recorded for decomposer/retrieval stages.
- [ ] Existing live-readiness tests pass.
- [ ] Temporary validation files are deleted.

## Phase 2 - QDT Quality: Replace Template Specificity with a Research Coverage Graph

Goal: QDT must decompose a market into bounded research coverage that tells the system what to investigate, what evidence is required, and what each researcher must classify. It should not be a resolution lookup checklist, and it should not generate generic source/timing/reporting leaves with pasted market nouns. It is not an inference model.

Design correction:

The tree/factor graph is a research orchestration and coverage model. The deterministic compiler is not compiling:

```text
tree -> probability
```

It is compiling:

```text
decomposition -> research assignments -> classified findings -> verified feature ledger -> SCAE probability
```

Runtime contracts must avoid language that implies the graph itself owns probabilistic inference. Prefer:

- `research_factor`
- `coverage_dimension`
- `leaf_question`
- `evidence_requirement`
- `classification_target`
- `unanswered_material_question`

The graph answers: what must we investigate to understand this market holistically? It does not answer: what is the probability?

QDT has two jobs, and the current artifact only approximated the first one.

1. Contract guard: identify what outcome is being forecast, the YES/NO mapping, deadline, authority, family/sibling context, and evidence admissibility rules.
2. Research coverage graph: instantiate generic coverage dimensions into market-specific leaf questions, evidence requirements, classification targets, and sufficiency criteria.

Only a small minority of leaves should be contract guard leaves. Most leaves should be research-factor or coverage-dimension leaves that give researchers something meaningful to classify and give verification/SCAE a compact classified findings ledger. QDT may define leaf questions, expected value types, evidence requirements, classification targets, overlap risks, and material unknowns. It must not assign probabilities, numeric weights, magnitudes, fair values, Bayesian/log-odds structure, or final SCAE deltas.

Use a small generic scaffold, not a hardcoded taxonomy of market categories. Reasonable generic coverage dimensions include:

- resolution mechanics
- current direct evidence
- key drivers
- counterevidence and negative checks
- timing and deadline constraints
- source quality
- related-market or base-rate context, if available
- material unknowns

The decomposer instantiates those dimensions into market-specific research questions. The compiler validates shape, coverage, budgets, and forbidden fields; it should not require a giant table of elections, CPI, sports, crypto, central banks, court cases, or similar categories.

Deterministic compiler duties:

1. Take the decomposer's proposed branches and leaves.
2. Validate depth, budgets, required fields, and forbidden fields.
3. Normalize each leaf into a stable research assignment.
4. Deduplicate overlapping questions.
5. Attach evidence requirements and sufficiency criteria.
6. Spawn bounded researcher assignments after retrieval sufficiency is certified.
7. Collect classifications.
8. Verify coverage, contradictions, and unresolved material questions.
9. Emit a compact classified findings ledger for SCAE.

Audit findings addressed:

- Leaf questions were template-shaped:
  - official announcement
  - no actor chosen status
  - actor identity
  - timing window
  - credible reporting consensus
  - official/reporting alignment
- The validator marked specificity as passed because generic fixture leaf ids were absent.
- Candidate scoring rewarded purpose coverage and weight labels, not semantic novelty, market-specific coverage, or answerability.

Concrete implementation:

- Extend the QDT output contract with a required `market_resolution_contract` object:
  - `yes_no_mapping`
  - `resolution_subject`
  - `resolution_authority`
  - `contract_deadline`
  - `forecast_cutoff`
  - `platform_family_context`
  - `ambiguous_terms`
  - `disqualifying_evidence_types`
  - `source_hierarchy`
- Replace any proposed `forecast_factor_graph` runtime field with a required `research_coverage_graph` object:
  - `target_event_description`
  - `coverage_dimensions`
  - `research_factors`
  - `contract_guard_leaf_ids`
  - `material_question_leaf_ids`
  - `required_leaf_ids_by_dimension`
  - `overlap_groups`
  - `unanswered_material_questions`
  - `coverage_summary`
- Extend each leaf with `specificity_evidence`:
  - `market_rule_clause_refs`
  - `case_contract_field_refs`
  - `why_this_must_be_investigated`
  - `not_a_template_reason`
  - `expected_answer_type`
- Extend each leaf with research assignment fields:
  - `coverage_dimension`
  - `research_factor`
  - `leaf_question`
  - `evidence_requirements`
  - `classification_targets`
  - `sufficiency_criteria`
  - `overlap_risk_with_leaf_ids`
  - `missingness_interpretation`
  - `forbidden_outputs`
- Add a semantic specificity and coverage validator:
  - reject if leaf questions match known template skeletons above a similarity threshold
  - reject if no leaf covers YES/NO mapping for semantically negative markets
  - reject if family/sibling context is unknown but market payload suggests grouped Polymarket family
  - reject if ambiguous terms from market description are not decomposed
  - reject if a leaf can be reused across unrelated markets by swapping entity names
  - reject if most leaves are contract/source/timing lookup leaves rather than material research leaves
  - reject if the generic coverage scaffold is not instantiated into market-specific questions
  - reject if `research_coverage_graph.required_leaf_ids_by_dimension` omits required dimensions without an `unanswered_material_question`
  - reject if overlapping leaf questions are not deduplicated or explicitly grouped
  - reject if leaves cannot be mapped to classification targets and verified findings without another model inventing the structure later
  - reject if any decomposer field or leaf field asks for probability, odds, numeric weight, Bayesian edge, log-odds delta, fair value, trade decision, or final forecast
- Update decomposer prompt in `decomposer/scripts/ads_decomposer/model_runtime.py` to demand analysis-first research decomposition and explicit rejection of mad-lib leaves.
- The corrected decomposer contract text should include: "Produce a bounded research decomposition that maximizes coverage of material uncertainty. Do not estimate probability. Do not assign weights. Do not make a final forecast. Emit leaf questions, purposes, evidence requirements, classification targets, and sufficiency criteria."
- Update `decomposer/scripts/bin/run_decomposition.py` so `question_specificity_check` and `research_coverage_check` are computed, not hard-coded as passed.
- Update `decomposer/scripts/ads_decomposer/qdt.py` candidate scoring to penalize template similarity and reward coverage diversity, market specificity, answerability, independence clarity, and clean classified-findings ledger readiness.

Suggested QDT fields:

```json
{
  "market_resolution_contract": {
    "yes_no_mapping": {
      "yes_means": "No qualifying actor announcement by the market deadline",
      "no_means": "A qualifying actor announcement occurred by the market deadline",
      "mapping_confidence": "requires_case_contract_confirmation"
    },
    "ambiguous_terms": [
      {"term": "above actor", "resolution_question": "what actor row or market family member does this refer to?"}
    ],
    "source_hierarchy": ["Amazon MGM official press", "007.com official", "authorized producer/studio statement", "credible reporting fallback"]
  },
  "research_coverage_graph": {
    "target_event_description": "qualifying next Bond actor announcement before the market deadline",
    "coverage_dimensions": [
      "resolution_mechanics",
      "current_direct_evidence",
      "key_drivers",
      "counterevidence_negative_checks",
      "timing_deadline_constraints",
      "source_quality",
      "related_market_or_base_rate_context",
      "material_unknowns"
    ],
    "contract_guard_leaf_ids": ["leaf-contract-yes-no-family"],
    "material_question_leaf_ids": [
      "leaf-casting-process-stage",
      "leaf-named-candidate-commitment",
      "leaf-official-announcement-readiness",
      "leaf-publicity-window-pressure",
      "leaf-negative-production-blockers",
      "leaf-rumor-vs-confirmation-quality"
    ],
    "required_leaf_ids_by_dimension": {
      "resolution_mechanics": ["leaf-contract-yes-no-family"],
      "current_direct_evidence": ["leaf-named-candidate-commitment"],
      "key_drivers": ["leaf-casting-process-stage", "leaf-official-announcement-readiness"],
      "counterevidence_negative_checks": ["leaf-negative-production-blockers"],
      "timing_deadline_constraints": ["leaf-publicity-window-pressure"],
      "source_quality": ["leaf-rumor-vs-confirmation-quality"]
    }
  }
}
```

Pseudocode:

```python
def validate_qdt_research_coverage(qdt, evidence_packet):
    contract = qdt["market_resolution_contract"]
    coverage = qdt["research_coverage_graph"]
    errors = []

    if not contract.get("yes_no_mapping"):
        errors.append("missing_yes_no_mapping")

    if is_negative_market_title(evidence_packet.title) and not leaf_covers_negative_mapping(qdt):
        errors.append("negative_market_mapping_not_decomposed")

    required_dimensions = required_generic_coverage_dimensions(qdt, evidence_packet)
    covered_dimensions = set(coverage.get("required_leaf_ids_by_dimension", {}).keys())
    unanswered = coverage.get("unanswered_material_questions", [])
    missing_dimensions = required_dimensions - covered_dimensions
    if missing_dimensions and not unanswered:
        errors.append("required_coverage_dimension_missing")

    guard_leaf_ids = set(coverage.get("contract_guard_leaf_ids", []))
    material_leaf_ids = set(coverage.get("material_question_leaf_ids", []))
    if len(material_leaf_ids) < minimum_material_leaf_count(qdt["leaf_budget_decision"]):
        errors.append("insufficient_material_leaf_count")
    if len(guard_leaf_ids) >= len(material_leaf_ids):
        errors.append("resolution_checklist_dominates_research_coverage")

    for leaf in qdt["required_leaf_questions"]:
        similarity = template_similarity(leaf["question_text"], GENERIC_QDT_SKELETONS)
        if similarity > 0.82 and not leaf_has_resolution_specific_payload(leaf):
            errors.append(f"{leaf['leaf_id']}:template_mad_lib_leaf")
        if not leaf.get("specificity_evidence", {}).get("why_this_must_be_investigated"):
            errors.append(f"{leaf['leaf_id']}:missing_research_purpose")
        if not leaf.get("classification_targets"):
            errors.append(f"{leaf['leaf_id']}:missing_classification_targets")
        if not leaf.get("evidence_requirements"):
            errors.append(f"{leaf['leaf_id']}:missing_evidence_requirements")
        if contains_forbidden_probability_field(leaf):
            errors.append(f"{leaf['leaf_id']}:forbidden_probability_or_weight_field")

    if evidence_packet_suggests_market_family(evidence_packet) and not contract.get("platform_family_context"):
        errors.append("market_family_context_not_analyzed")

    if has_unmerged_duplicate_leaf_questions(qdt["required_leaf_questions"]):
        errors.append("overlapping_leaf_questions_not_deduplicated")

    return errors
```

Better QDT shape for the audited James Bond market:

Contract guard leaves:

- What exactly does YES/NO mean for the "No one announced as next James Bond?" market, including whether YES is the absence of a qualifying announcement and whether "above actor" implies a market-family child?
- Which source hierarchy and deadline rules determine whether a claim is a qualifying announcement rather than rumor, speculation, or post-cutoff evidence?

Research factor / coverage leaves:

- What is the current stage of the Bond casting process before the forecast cutoff: open search, shortlist, screen tests, negotiations, offer, contract, finalized selection, or authorized announcement-ready?
- Is there evidence that any named candidate has moved from rumor into a commitment-stage state, such as offer negotiation, contract talks, official screen test reporting, or producer/studio confirmation?
- Are Amazon MGM, Eon, 007.com, or authorized producers signaling announcement readiness through press scheduling, franchise events, production milestones, or coordinated media windows before the deadline?
- Are there negative production/casting blockers, such as no finalized script/director/timeline, producer statements that casting is not imminent, or credible reporting that the search remains unresolved?
- How strong is the evidence quality split between speculative celebrity/media rumor and trade/official reporting that would normally precede or accompany a real casting announcement?
- Given the time remaining until the deadline, what timing/deadline constraints materially affect whether a qualifying announcement could be observed before cutoff?
- Are the relevant claim families independent, or are they syndicated repetitions of the same rumor source that should be collapsed before SCAE sees the ledger?
- What material questions remain unanswered after retrieval, and are they answerable through additional source discovery or structurally unavailable before the forecast cutoff?

Example leaf shape:

```json
{
  "leaf_id": "leaf:resolution-condition:source-of-truth",
  "leaf_type": "research_factor",
  "coverage_dimension": "resolution_mechanics",
  "research_factor": "resolution_condition_and_authority",
  "question_text": "What source will resolve this market, and what exact condition must be observed?",
  "purpose": "resolution_mechanics",
  "classification_targets": [
    "condition_met_status",
    "source_reliability",
    "ambiguity_risk"
  ],
  "evidence_requirements": [
    "primary_resolution_source",
    "market_rules"
  ],
  "sufficiency_criteria": {
    "required_source_classes": ["official_or_primary", "market_rules_or_resolution_source"],
    "required_value_fields": ["resolution_condition", "resolution_authority"],
    "unanswerability_allowed": true
  },
  "forbidden_outputs": ["probability", "trade_decision", "fair_value", "numeric_weight"]
}
```

Researcher contract correction:

Researchers receive only assigned leaf context and certified evidence/snippet refs. Their contract should say: "Answer only your assigned leaf. Classify evidence direction, strength, confidence, quality, and extracted values. Flag insufficiency, contradictions, and unanswered material questions. Do not forecast."

Tests:

- Add QDT quality tests in `decomposer/scripts/tests/test_qdt.py` and `test_runtime_decomposition.py`.
- Include fixtures:
  - James Bond negative semantic market
  - grouped Polymarket child market
  - generic actor/announcement mad-lib output, expected rejection
  - resolution-checklist-only output, expected rejection even when YES/NO mapping is correct
  - valid research coverage graph output, expected acceptance
  - leaf with missing `why_this_must_be_investigated`, expected rejection
  - leaf with missing `classification_targets`, expected rejection
  - leaf with probability, weight, Bayesian edge, log-odds delta, fair value, or forecast output, expected rejection
- Keep permanent regression tests because this is a core quality gate.
- Delete any temporary generated QDT artifact files after test completion.

Commands:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/wake_decomposer.py --help >/dev/null
```

Success criteria:

- [ ] Generic filled-in template leaves are rejected.
- [ ] Resolution-checklist-only QDT outputs are rejected.
- [ ] The audited James Bond market produces contract guard leaves plus research-factor leaves for casting stage, named candidate commitment, announcement readiness, blockers, rumor quality, timing constraints, claim-family independence, and material unknowns.
- [ ] Leaves include evidence requirements, classification targets, sufficiency criteria, and forbidden outputs.
- [ ] `question_specificity_check.status` and `research_coverage_check.status` can fail with actionable reason codes.
- [ ] QDT artifacts still include model provenance for `gpt-5.5-high`.
- [ ] No QDT output includes probabilities, numeric weights, probabilistic dependencies, SCAE deltas, fair values, or forecast decisions.

## Phase 3 - AMRG Relationship Quality and Model Assist

Goal: AMRG must not inject unrelated markets into QDT, and the intended AMRG intelligence lane must execute when policy requires it.

Audit findings addressed:

- AMRG selected unrelated markets as `entity_match` for the James Bond market.
- The candidates included Russian territorial-control markets, Colorado primaries, Tesla deliveries, and prediction-market legislation.
- QDT consumed those AMRG refs.
- AMRG model assist was not requested, despite the v2 intended model-assisted path.

Concrete implementation:

- Fix deterministic candidate filtering in `orchestrator/scripts/predquant/amrg.py`:
  - use canonical named-entity extraction with stopword and generic-term removal
  - require at least one high-salience shared entity or explicit market-family relation
  - require domain compatibility unless relationship type is explicitly cross-domain and weak
  - treat shared dates, common verbs, countries, "will", "by June 30", and platform boilerplate as non-entities
  - cap weak context effects to retrieval-query hints only; never promote weak unrelated edges into QDT branch usage
- Add AMRG model assist:
  - resolve `amrg_model_assist` from `autonomous-decomposition-swarm-model-lane-policy.json`
  - require `default_model_id == "gpt-5.4-high"`
  - require `provider_route == "openclaw_codex_oauth/amrg"`
  - require `oauth_route_required == true`
  - send compact candidate pairs only
  - model returns relationship classification and rationale, not evidence or probabilities
  - deterministic validator remains final authority
- Update QDT handoff so AMRG context defaults to `weak_context_only=true` unless strict anchor status is validated.

Pseudocode:

```python
def deterministic_amrg_filter(target, candidate):
    target_entities = salient_entities(target)
    candidate_entities = salient_entities(candidate)
    shared = target_entities & candidate_entities

    if not shared and not same_platform_family(target, candidate):
        return reject("no_salient_shared_entity")

    if target.domain != candidate.domain and not explicit_cross_domain_relation(target, candidate):
        return weak_or_reject("domain_mismatch")

    if only_generic_overlap(target, candidate):
        return reject("generic_overlap_only")

    return candidate_context_hint(shared_entities=shared)

def run_amrg_model_assist(candidate_pairs):
    lane = resolve_model_lane("amrg_model_assist")
    assert lane.model == "gpt-5.4-high"
    assert lane.provider_route == "openclaw_codex_oauth/amrg"
    response = openclaw_oauth_call(lane, compact_candidate_pairs(candidate_pairs))
    return validate_amrg_assist_response(response)
```

Tests:

- Add regression tests under `orchestrator/scripts/tests/test_amrg_context.py` or a new focused AMRG quality test.
- Fixtures:
  - James Bond target vs Russia market, expected reject
  - James Bond target vs Tesla deliveries, expected reject
  - two members of same Polymarket event family, expected strict family relation
  - same named actor across markets, expected weak/strong based on timing and source
  - AMRG model lane missing or wrong model, expected closed failure
  - AMRG model response invalid, expected deterministic fallback with no promotion
- Keep permanent regression tests.
- Delete phase-local temp model response JSONs.

Commands:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest \
  scripts.tests.test_amrg_context \
  scripts.tests.test_amrg_vector
python3 scripts/bin/report_amrg_context.py --help >/dev/null
```

Success criteria:

- [ ] Unrelated James Bond AMRG candidates are rejected or remain non-promotable weak diagnostics.
- [ ] AMRG model assist executes through `openclaw_codex_oauth/amrg` when policy requires it; if policy leaves `default_requested=false`, injected or unavailable runtime status must be explicit and non-promoting.
- [ ] AMRG assist records `model_executed=true`, model id, route, prompt/input/output hashes, and latency.
- [ ] QDT cannot consume weak/generic AMRG refs as if they were meaningful anchors.
- [ ] AMRG never produces forecast probabilities.

## Phase 4 - Retrieval Temporal Isolation, Source Metadata, and Search Intelligence

Goal: retrieval must produce certified evidence packets when good pre-cutoff evidence exists, reject contaminated sources precisely, and use the intended search/intelligence layer.

Current status after recent commits:

- Implemented for the 21-item source/retrieval remediation tranche listed above. Recent commits now prove browser-search source discovery in canary tests, separate pilot metadata from real retrieval proof, expose direct/browser/native/metadata-classifier runtime proof lanes, reject empty fetched content, omit post-cutoff source evidence, harden source/claim family breadth certification, and add live retrieval acceptance checks.
- The phase should continue to require real-case canary evidence, because controlled fixtures can prove the path without proving enough live source quality across representative markets.
- Native research remains a policy-enabled lane, not an unconditional requirement when browser/direct retrieval is sufficient and native status is explicitly disabled or unavailable.
- Phase 4 implementation work should be limited to gaps revealed by tests, representative clone canaries, or later QDT/AMRG contract changes. Otherwise this phase is a verification checkpoint, not a second implementation pass.

Audit findings addressed:

- Retrieval failed on `source_after_cutoff` before writing a retrieval packet.
- Source/capture metadata likely conflated retrieval capture time or HTTP metadata with source publication time.
- Browser search was active, but native research was not verified.
- Search breadth looked too thin for high-certainty leaves.

Concrete implementation and regression requirements:

- In `researcher-swarm/scripts/researcher_swarm/browser_provider.py` and `retrieval.py`:
  - never treat HTTP `Date` as source publication/update time
  - classify HTTP `Date` and fetch time as capture metadata only
  - treat HTTP `Last-Modified` as `source_updated_at_candidate`, not authoritative publication time unless page-bound metadata supports it
  - extract visible page dates into explicit candidates with confidence and source span refs
  - require deterministic temporal resolver to choose one of:
    - `source_time_pre_cutoff`
    - `source_time_post_cutoff`
    - `source_time_unknown_not_counted`
    - `capture_time_post_cutoff_allowed`
- In `orchestrator/scripts/predquant/ads_retrieval_transport.py`:
  - filter temporally invalid candidates before `selected_evidence`
  - persist rejected candidate diagnostics rather than failing the whole stage on one contaminated selected item
  - fail the leaf only when no sufficient admissible evidence or structural unanswerability proof remains
- Increase retrieval breadth for high-certainty leaves:
  - direct official/protected-primary URLs first
  - bounded OpenClaw OAuth web search
  - site-specific searches for official domains
  - contradiction and negative checks
  - optional native research candidate discovery through `gpt-5.5-high`
- Add a strict runtime signal that native research and browser search are distinguishable:
  - `browser_search_executed`
  - `native_research_model_executed`
  - `metadata_classifier_assist_executed`
  - `direct_url_capture_executed`

Pseudocode:

```python
def classify_source_times(fetch_result, cutoff):
    capture = fetch_result["captured_at"]
    source_candidates = []

    for meta_name in ("article:published_time", "datePublished", "published_at"):
        if fetch_result.meta.get(meta_name):
            source_candidates.append(candidate(meta_name, fetch_result.meta[meta_name], confidence="high"))

    if fetch_result.http_last_modified:
        source_candidates.append(candidate("http_last_modified", fetch_result.http_last_modified, confidence="low_update_only"))

    # HTTP Date is not a source time.
    capture_time = capture

    resolved = resolve_visible_or_structured_source_time(source_candidates)
    if resolved is None:
        return TemporalStatus("source_time_unknown_not_counted", capture_time=capture_time)
    if resolved >= cutoff:
        return TemporalStatus("source_time_post_cutoff", rejected=True)
    return TemporalStatus("source_time_pre_cutoff", accepted=True)

def select_evidence(candidates, sufficiency):
    admissible = [c for c in candidates if c.temporal_status == "source_time_pre_cutoff"]
    rejected = [c for c in candidates if c not in admissible]
    write_rejected_candidate_slices(rejected)
    if sufficient(admissible, sufficiency):
        return build_retrieval_packet(admissible)
    return structural_unanswerability_or_leaf_block(admissible, rejected)
```

Tests:

- Existing regression tests now cover much of this list in `researcher-swarm/scripts/tests/test_retrieval.py`, `orchestrator/scripts/tests/test_ads_retrieval_transport.py`, `orchestrator/scripts/tests/test_ads_operational_canary.py`, and `orchestrator/scripts/tests/test_ads_production_handlers.py`.
- Add new tests only for uncovered gaps introduced by later phase work.
- Fixtures:
  - HTTP `Date` after cutoff with article published before cutoff, expected accept
  - HTTP `Last-Modified` after cutoff but visible article date before cutoff, expected accept with warning
  - article published after cutoff, expected reject candidate but not crash the packet builder
  - only unknown source time for source-of-truth leaf, expected insufficient or structural unanswerability
  - direct official URL search path, expected before broad search
  - native research lane configured, expected `model_executed=true`
  - source metadata classifier assist unavailable, expected conservative non-blocking fallback
- Keep permanent regression tests.
- Delete temp fetched HTML fixtures only if generated dynamically; keep curated minimal fixtures in tests.

Commands:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest \
  scripts.tests.test_ads_retrieval_transport \
  scripts.tests.test_ads_operational_canary \
  scripts.tests.test_ads_production_handlers
```

Success criteria:

- [ ] Post-cutoff capture time no longer invalidates pre-cutoff source evidence.
- [ ] True post-cutoff source publication remains rejected.
- [ ] Rejected retrieval candidates are diagnostic slices, not opaque fatal crashes.
- [ ] Retrieval packet can be produced for a live case with admissible evidence.
- [ ] Browser search, direct URL capture, and native research execution are separately visible in canary reports.
- [ ] Native research candidate discovery uses `gpt-5.5-high` and OpenClaw OAuth when enabled or policy-required.
- [ ] If native research is disabled or unavailable, reports preserve that status and prove browser/direct retrieval was sufficient before dispatch.
- [ ] Live retrieval acceptance reports `live_acceptance_ok=true` for sufficient evidence or blocks cleanly with `acceptance_unmet_not_blocked_count=0`.
- [ ] No completed 21-item source/retrieval fix is duplicated unless a regression first identifies a concrete failing behavior.

## Phase 5 - Researcher Swarm Deployment and Model-Executed Classification

Goal: once retrieval certifies evidence, Orchestrator must deploy the researcher swarm and prove intended model execution.

Current status after active changes:

- Implemented in recent commits for the assignment-contract portion. `d7a2383` requires bounded certified snippet/artifact access for assigned evidence, and `2c966b0` constrains researchers to certified evidence classification.
- Phase 5 now verifies integration with QDT leaf contracts, retrieval sufficiency, live researcher model execution, sidecar persistence, and SCAE-ready verification. Do not rebuild the assignment contract unless its regression tests fail or a later QDT schema change requires an explicit extension.

Audit findings addressed:

- Researcher swarm did not run because retrieval failed.
- The strict canary could not verify `researcher_leaf_nli_classification` model execution.
- Runtime reports need stronger proof of sidecars, isolation, coverage, and verification.

Concrete implementation and regression requirements:

- In `orchestrator/scripts/predquant/ads_production_readiness_handlers.py` and `wake_researcher_swarm.py`:
  - ensure retrieval sufficiency certificate opens classification dispatch
  - fail closed if classification dispatch is expected but no researcher runtime bundle appears
  - require minimum configured researcher assignments for scoreable cases
- In `researcher-swarm/scripts/researcher_swarm/assignments.py`:
  - each leaf or compatible leaf bundle gets an explicit assignment packet
  - include QDT leaf text, coverage dimension, research factor, evidence requirements, classification targets, sufficiency requirements, evidence refs, source cutoff, allowed context, and prohibited context
  - require each assigned certified evidence ref to include bounded snippet/artifact access, including snippet ref, content artifact ref, text hash, char range, excerpt length, and excerpt policy
  - fail closed when certified retrieval evidence lacks bounded snippet/artifact access
  - include explicit `forbidden_outputs` from the compiled leaf assignment, including probability, fair value, numeric weight, trade decision, SCAE delta, and final forecast
- In `researcher-swarm/scripts/researcher_swarm/openclaw_runtime.py` and `classification.py`:
  - resolve `researcher_leaf_nli_classification`
  - require `resolved_model_id == "gpt-5.5-high"`
  - require `provider_route == "openclaw_codex_oauth/researcher-swarm"`
  - require `model_executed=true` for live classification
  - record prompt/input/output hashes and forbidden-output scan status
  - enforce researcher prompt text: "Answer only your assigned leaf. Classify evidence direction, strength, confidence, quality, and extracted values. Flag insufficiency, contradictions, and unanswered material questions. Do not forecast."
- Enforce 5-researcher intent:
  - either five independent researcher classifications for the case, or a documented policy exception when fewer leaves exist and each critical leaf has the required redundancy
  - no researcher may see future/post-cutoff evidence
  - no researcher may produce probabilities, fair values, numeric weights, SCAE deltas, trade decisions, or final forecasts

Pseudocode:

```python
def deploy_researcher_swarm(retrieval_packet, qdt):
    if retrieval_packet.classification_dispatch_status != "allowed":
        return block("retrieval_sufficiency_not_certified")

    assignments = build_assignments(qdt.leaves, retrieval_packet.evidence)
    require_bounded_certified_snippets(assignments)
    if requires_five_researchers(qdt) and len(assignments) < 5:
        assignments = add_redundant_critical_leaf_assignments(assignments, target_count=5)

    bundle = []
    for assignment in assignments:
        runtime = run_openclaw_researcher(assignment, lane="researcher_leaf_nli_classification")
        assert runtime.model_executed is True
        assert runtime.resolved_model_id == "gpt-5.5-high"
        bundle.append(validate_sidecar(runtime.output))

    return build_classification_bundle(bundle)
```

Tests:

- Existing tests now cover the certified snippet and certified-evidence boundary in several of these files. Add tests only for uncovered integration gaps in:
  - `researcher-swarm/scripts/tests/test_assignments.py`
  - `researcher-swarm/scripts/tests/test_openclaw_runtime.py`
  - `researcher-swarm/scripts/tests/test_classification.py`
  - `researcher-swarm/scripts/tests/test_sidecar.py`
  - `researcher-swarm/scripts/tests/test_verification.py`
  - `orchestrator/scripts/tests/test_ads_operational_canary.py`
- Fixtures:
  - retrieval certified, expected researcher deployment
  - retrieval uncertified, expected no deployment and structured blocker
  - wrong model id, expected rejection
  - OAuth route missing, expected rejection
  - model output includes probability, expected forbidden-output rejection
  - five-researcher coverage required, expected coverage proof
  - certified evidence missing bounded snippet/artifact access, expected fail-closed assignment rejection
- Keep permanent regression tests.
- Delete temp sidecar bundles from scratch directories after validation.

Commands:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest \
  scripts.tests.test_assignments \
  scripts.tests.test_openclaw_runtime \
  scripts.tests.test_classification \
  scripts.tests.test_coverage \
  scripts.tests.test_escalation \
  scripts.tests.test_isolation \
  scripts.tests.test_sidecar \
  scripts.tests.test_persistence \
  scripts.tests.test_supplemental \
  scripts.tests.test_verification

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 scripts/bin/wake_researcher_swarm.py --help >/dev/null
```

Success criteria:

- [ ] Certified retrieval opens researcher dispatch.
- [ ] Live researcher classification records `model_executed=true`.
- [ ] Runtime model id is `gpt-5.5-high`.
- [ ] Runtime provider route is `openclaw_codex_oauth/researcher-swarm`.
- [ ] Researcher outputs include classification/evidence values only, no probabilities.
- [ ] Coverage proof shows the intended researcher count or a policy-valid exception.
- [ ] Assigned evidence includes bounded certified snippet/artifact access and does not expose raw unbounded source bodies.
- [ ] Verification artifacts are ready for SCAE intake.
- [ ] Regression tests still reject assignments that lack certified snippets or attempt researcher-side search expansion.

## Phase 6 - Verification and SCAE Integration

Goal: SCAE must consume verified researcher classifications from the live pipeline and remain the only numeric forecast authority.

Audit findings addressed:

- SCAE was not reached during the strict canary.
- SCAE tests passed from repo root but failed from inside `SCAE/` due to cwd-sensitive CLI test paths.
- Calibration debt is correctly blocked but live evidence-to-ledger integration remains unproven.

Concrete implementation:

- Fix SCAE CLI cwd sensitivity:
  - compute repo paths relative to script location or accept explicit `--repo-root`
  - update tests to run from repo root and SCAE cwd
- In `researcher-swarm/scripts/researcher_swarm/verification.py`:
  - ensure verifier emits SCAE-ready direction/evidence-quality slices only after sufficiency reconciliation
- In `SCAE/scripts/scae/evidence.py` and `ledger.py`:
  - enforce that each delta candidate traces to verified classifications and admitted evidence refs
  - reject uncertified, thin, post-cutoff, or unverified evidence
- In `orchestrator/scripts/bin/kick_scae.py`:
  - fail closed if verification bundle is missing
  - write explicit no-ledger blocker when input is insufficient
- In `orchestrator/scripts/predquant/model_provenance_trace.py`:
  - ensure decomposer/researcher model calls are traceable, while SCAE records deterministic/no-model provenance

Pseudocode:

```python
def build_scae_inputs(verification_bundle):
    if not verification_bundle.sufficiency_reconciled:
        return block("research_sufficiency_not_reconciled")

    deltas = []
    for classification in verification_bundle.classifications:
        if not classification.verified or not classification.evidence_ref:
            continue
        deltas.append(map_verified_classification_to_delta(classification))

    if not deltas:
        return block("no_verified_scae_delta_inputs")

    return run_scae_ledger(deltas, deterministic=True, model_calls_forbidden=True)
```

Tests:

- Add or update SCAE tests:
  - cwd-independent CLI invocation
  - uncertified evidence rejected
  - verified classification maps to ledger delta
  - no model provenance for SCAE
  - forecast persistence only uses SCAE production probability
- Keep permanent regression tests.
- Delete temp ledger JSONs and cloned DBs after test runs.

Commands:

```bash
cd /Users/agent2/.openclaw
python3 -m unittest discover -s SCAE/scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/SCAE
python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_model_provenance_trace
python3 scripts/bin/check_ads_non_scae_authority.py
```

Success criteria:

- [ ] SCAE CLI tests pass from repo root and SCAE cwd.
- [ ] SCAE rejects unverified or uncertified evidence.
- [ ] SCAE ledger records deterministic/no-model authority.
- [ ] Forecast persistence uses only `production_forecast_prob` from SCAE.
- [ ] Calibration debt remains blocked until scorecard criteria are met.

## Phase 7 - End-to-End Strict Canary and Handoff Closure

Goal: prove the entire v2 intended path works on a clone DB, with model calls, retrieval, researcher swarm, verifier, SCAE, synthesis, decision, trace, and replay.

Concrete implementation:

- Run strict clone-only canary against at least:
  - the audited James Bond market
  - one non-entertainment binary market
  - one market with clear family/sibling context, if present
- Require:
  - manifest handoffs
  - real runtime canary criteria
  - live retrieval acceptance criteria from `ads_real_runtime_canary.py`
  - researcher model executed
  - no unresolved refs
  - no SCAE ledger when evidence is insufficient, but explicit structured blocker
  - SCAE ledger when evidence is sufficient
  - native research execution only when enabled or policy-required; otherwise disabled/unavailable status is explicit and browser/direct retrieval sufficiency is proven
- Add a canary summary comparator that shows phase-over-phase improvements:
  - QDT semantic specificity status
  - AMRG accepted/rejected count and model-assist status
  - retrieval packet count and admitted evidence count
  - source-collation acceptance status, unmet dimension codes, and blocked/unblocked outcome
  - browser search/direct/native research execution or explicit disabled/unavailable status
  - independent non-market source family count
  - researcher sidecar count and model execution
  - bounded certified snippet coverage for researcher assignments
  - verifier slices
  - SCAE ledger count
  - forecast decision delta
  - readiness/operator statuses

Pseudocode:

```python
def assert_full_runtime_canary(report):
    assert report.qdt.model_executed
    assert report.qdt.semantic_specificity_status == "passed"
    assert report.amrg.unrelated_candidate_promotions == 0
    assert report.retrieval.packet_count >= 1
    assert report.retrieval.admitted_evidence_count >= min_required
    assert report.retrieval.live_acceptance_ok is True
    assert report.retrieval.acceptance_unmet_not_blocked_count == 0
    assert report.retrieval.independent_non_market_source_family_count >= min_required_non_market_families
    assert report.retrieval.native_research_ok_or_not_required
    assert report.researcher.model_executed_count >= required_researcher_count
    assert report.researcher.assigned_evidence_certified_snippet_coverage == "complete"
    assert report.verification.scae_ready is True
    assert report.scae.ledger_count == 1
    assert report.handoffs.unresolved_output_manifest_refs == []
    assert report.operator.status == "review_passed"
    assert report.readiness.true_runtime_cutover_status == "ready"
```

Tests:

- Permanent tests:
  - canary report classifier rejects missing model execution
  - handoff report rejects unresolved refs
  - readiness fails closed for missing SCAE/researcher/retrieval
  - live retrieval acceptance rejects unmet source-collation dimensions that advance unblocked
  - pilot/structured market metadata cannot satisfy real retrieval acceptance
- Phase-local tests:
  - cloned DB canary runs
  - JSON output comparison
  - temp artifact inspection
- Delete cloned DBs and phase-local JSONs after summary is captured.

Commands:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary

python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --require-researcher-model-executed \
  --skip-existing-ads-predictions \
  --metadata-json '{"audit_id":"ads-v2-remediation-final","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/final-canary-output.json"

python3 scripts/bin/report_ads_handoffs.py --db-path "$TMPDIR/predquant.sqlite3" --run-id "$RUN_ID" --pretty
python3 scripts/bin/report_ads_real_runtime_canary.py --db-path "$TMPDIR/predquant.sqlite3" --run-id "$RUN_ID" --require-researcher-model-executed --pretty
python3 scripts/bin/report_ads_operator_review.py --db-path "$TMPDIR/predquant.sqlite3" --run-id "$RUN_ID" --pretty
python3 scripts/bin/check_ads_live_readiness.py --db-path "$TMPDIR/predquant.sqlite3" --pretty
```

Success criteria:

- [ ] Full clone-only canary reaches terminal success for at least one scoreable sufficient-evidence case.
- [ ] If a case is structurally unanswerable, it ends with a clean structured blocker and no forecast write.
- [ ] Source/retrieval acceptance proves nonzero candidate/fetch/admitted-evidence flow, independent non-market source families, protected-primary/freshness where required, and no unblocked unmet dimensions.
- [ ] Pilot or structured market metadata does not satisfy real retrieval acceptance.
- [ ] QDT, AMRG assist when policy-required, native research when enabled or policy-required, researcher NLI, and SCAE deterministic paths all have expected provenance.
- [ ] Researcher assignment evidence access is bounded, hashed, and complete for every certified evidence ref.
- [ ] No unresolved manifest refs.
- [ ] Operator and readiness reports agree with actual runtime health.
- [ ] Live DB remains unmodified except for explicitly approved operations.

## Phase 8 - Cleanup, Documentation, and Live Cutover Decision

Goal: leave the workspace clean and make the live-cutover decision based on evidence, not optimism.

Concrete implementation:

- Update phase reports under `orchestrator/plans/phase-reports/` only if VM wants the remediation implementation recorded there.
- Update Workbench or Orchestrator memory only for durable decisions, not raw logs.
- Delete:
  - temp DB clones
  - scratch JSON outputs
  - generated debug HTML/text
  - one-off temp test harnesses
- Keep:
  - permanent regression tests
  - schema migrations
  - runtime implementation code
  - concise phase report or plan updates
- Produce a final live-cutover matrix:
  - QDT quality
  - AMRG quality
  - retrieval certification
  - researcher model execution
  - verifier/SCAE integration
  - operator/readiness honesty
  - protected forecast authority
  - calibration debt status

Pseudocode:

```text
for artifact in tmp_phase_artifacts:
    if artifact.is_temp and not referenced_by_phase_report:
        trash artifact

run all targeted tests
run strict clone canary
produce cutover recommendation:
    ready_for_clone_batch
    blocked_with_remaining_items
    not_ready_for_live
```

Commands:

```bash
cd /Users/agent2/.openclaw/workbench
git status --short

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/check_ads_script_placement.py
python3 scripts/bin/check_ads_canonical_artifacts.py
python3 scripts/bin/check_ads_non_scae_authority.py
```

Success criteria:

- [ ] No scratch clutter remains.
- [ ] Permanent regression tests cover each fixed bug.
- [ ] Final strict canary evidence is summarized.
- [ ] Live cutover is either explicitly approved as ready for clone batch, or blocked with concrete remaining failures.

## Cross-Phase Test Matrix

Run these before claiming end-to-end remediation is complete:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw
python3 -m unittest discover -s SCAE/scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/bin/check_ads_script_placement.py
python3 scripts/bin/check_ads_canonical_artifacts.py
python3 scripts/bin/check_ads_non_scae_authority.py
```

Expected end state:

- QDT rejects template mad-lib decomposition.
- AMRG rejects unrelated candidates and records model-assist provenance when used.
- Retrieval produces certified packets when admissible pre-cutoff evidence exists.
- Researcher swarm runs with audited `gpt-5.5-high` model execution.
- SCAE consumes only verified evidence and is the only numeric forecast authority.
- Operator/readiness reports fail closed until all true-runtime criteria are met.
- Strict clone canary completes the intended v2 path or produces a precise non-scoreable blocker.

## Open Questions for Implementation

- Should the v2 canary require exactly five researcher executions, or at least five when the QDT has enough independent critical leaves and otherwise a redundancy policy over critical leaves?
- Should AMRG model assist be mandatory for all non-empty candidate sets, or only when deterministic confidence falls in an ambiguous band?
- For source temporal metadata, what is the exact policy for pages with only `Last-Modified` and no visible publication date?
- Should grouped Polymarket family context be mandatory for all Polymarket cases, or only when the market payload exposes parent/sibling metadata?
- Should native research candidate discovery be a blocker for live cutover, or a required diagnostic that may fail closed while browser/direct retrieval still succeeds?
