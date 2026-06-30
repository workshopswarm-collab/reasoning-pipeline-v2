# ADS v2 End-to-End Audit Remediation Plan

Date: 2026-06-30
Author: Workbench
Scope: Current active remediation plan for ADS v2 after cross-referencing the original audit plan, the post-push audit, the existing repo, and completed remediation through Phase 3 AMRG assist policy signoff.

## Guiding Purpose

This plan exists to finish turning ADS v2 from a partially wired canary path into a verified end-to-end forecasting pipeline. It should now focus only on unresolved or unproven work. Already-remediated QDT, retrieval/source, researcher, verification, SCAE, and readiness safeguards should be protected by tests and clone-only canaries, not reimplemented.

The target end state is a pipeline where QDT defines useful pre-resolution research coverage, AMRG supplies only validated context, retrieval admits only certified pre-cutoff evidence, researchers classify bounded evidence without forecasting, SCAE remains the sole numeric forecast authority, and readiness reports cannot be mistaken for cutover readiness unless strict runtime evidence supports that claim.

## Source And Audit Anchors

Source spec:

`/Users/agent2/.openclaw/media/inbound/autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md`

Original strict audit run:

- Run id: `ads-pipeline-run:ebbbe0edf2abc9f07a17bc4c902994d0961a79945f2fbd18546d44a78a64d3d2`
- Case: `polymarket:572133`, "No one announced as next James Bond?"
- Clone DB: `/tmp/ads-e2e-audit.zRzjmY/predquant.sqlite3`
- Terminal failure: retrieval rejected selected evidence with `source_after_cutoff`
- Completed stages: case selection, evidence packet, policy context, related-market context, decomposition
- Not reached: researcher classification, verification, SCAE, synthesis, decision, training trace, replay record

Post-push audit after `7fbaffc Complete ADS v2 remediation phases`:

- Run id: `ads-pipeline-run:f483c681d7c2a6efac3b58035b4657222051f8ae20282e6d9e6e17eeca188478`
- Case: `polymarket:1795635`, Bank of Israel July interest-rate decrease market
- Result: all stages completed, but strict canary failed with `retrieval_live_acceptance_requirements_not_met` and `researcher_model_runtime_not_verified`
- Important detail: researcher dispatch was correctly blocked because retrieval was uncertified, so the remaining issue was not "force researchers to run"; it was "prove certified retrieval on representative live cases or stop with a precise blocker"

Current commit evidence reviewed:

- QDT remediation: `9ed3b24`, `bb03c09`, `857cc2e`, `b962d9f`, `987f767`, `dd692d7`, `2b38419`
- One-shot ADS remediation: `7fbaffc`
- Phase 2 retrieval proof: `032d438`
- Phase 3 AMRG signoff: `012a3db`
- Retrieval/source 21-item tranche: `eeb2a03` through `e3ba9e0`
- Researcher assignment contract hardening: `d7a2383`, `2c966b0`, `dd692d7`
- Controlled retrieval-to-SCAE proof: `2b38419`
- Earlier ADS architecture phases: `37049a1` through `901cf3d`

## Current Implementation Ledger

The following items are implemented and removed from active implementation scope. Future work should only touch them when a regression test or clone-only canary shows a concrete failure.

| Area | Current status | Evidence |
|---|---|---|
| QDT pre-resolution forecast shape | Implemented. QDT now distinguishes unresolved forecast research from terminal result verification, gates terminal leaves, scores candidate quality, and bridges dispatchable leaves into researcher assignments. | Commits `9ed3b24` through `2b38419`; tests in `decomposer/scripts/tests/test_qdt.py`, `decomposer/scripts/tests/test_runtime_decomposition.py`, and `orchestrator/scripts/tests/test_ads_operational_canary.py`. |
| QDT assignment bridge | Implemented. Researcher assignments use `dispatchable_pre_resolution_leaf_ids`, carry `qdt_leaf_contract`, and fail closed on missing classification targets, sufficiency criteria, or pre-resolution driver coverage. | Commit `dd692d7`; `researcher-swarm/scripts/tests/test_assignments.py`. |
| 21 source/retrieval fixes | Implemented. Provider wiring, browser/search transport, web-fetch boundary, direct URL capture, source freshness, fail-closed empty content, market URL authority limits, source/claim family certification, and live acceptance gates are in the repo. | Commits `eeb2a03` through `e3ba9e0`; `orchestrator/scripts/tests/test_ads_retrieval_transport.py`, `researcher-swarm/scripts/tests/test_retrieval.py`, `orchestrator/scripts/tests/test_ads_operational_canary.py`. |
| Researcher evidence boundary | Implemented. Researchers classify bounded certified evidence and do not free-browse or forecast. Assignments require snippets/artifact refs, not blind hashes. | Commits `d7a2383`, `2c966b0`, `dd692d7`; assignment and verification tests. |
| Controlled retrieval-to-SCAE positive path | Implemented as a controlled canary fixture. The test proves nonzero search candidates, fetches, admitted evidence, retrieval acceptance, researcher model execution, valid SCAE forecast, evidence deltas, and prediction persistence. | Commit `2b38419`; `test_true_production_search_runtime_canary_proves_retrieval_to_scae_inputs`. |
| SCAE authority boundary | Implemented. Invalid/non-scoreable ledgers cannot write scoreable predictions, and valid forecasts require SCAE evidence delta refs. | `SCAE/scripts/tests`, `orchestrator/scripts/tests/test_ads_operational_canary.py`, `check_ads_non_scae_authority.py`. |
| AMRG weak-context and advisory-output boundaries | Implemented at contract level. AMRG assist packets/provenance reject probability, SCAE delta, QDT selection, promotion, citation/source outputs, and deterministic validation remains final authority. | `orchestrator/scripts/predquant/amrg.py`, `orchestrator/scripts/tests/test_amrg_context.py`. |
| AMRG optional-policy readiness signal | Implemented for the current default policy. Readiness already reports `assist_not_requested_by_policy` when `default_requested=false`; active work is policy proof/sign-off, not rebuilding the AMRG assist lane. | `orchestrator/scripts/predquant/ads_live_readiness.py`, `orchestrator/scripts/tests/test_ads_live_readiness.py`. |
| Canary/report harnesses | Implemented. Existing scripts should be reused for clone-only proof and compact reports; do not add another harness unless a specific missing summary blocks Phase 2 or Phase 5 proof. | `orchestrator/scripts/bin/run_ads_one_case_canary.py`, `report_ads_real_runtime_canary.py`, `report_ads_handoffs.py`, `report_ads_operator_review.py`, `check_ads_live_readiness.py`. |
| QDT coverage repair truthfulness | Implemented. Repair-required coverage summaries and repair-needed unanswered material questions now fail `research_coverage_check`, while explicit structural unanswerability remains allowed. Candidate scoring penalizes repair-required coverage. | Phase 1 change; `decomposer/scripts/tests/test_qdt.py`, `test_runtime_decomposition.py`, full decomposer discovery, and `orchestrator/scripts/tests/test_ads_operational_canary.py`. |
| Representative retrieval blocker proof | Implemented for Phase 2. Two clone-only representative runs reached live retrieval with real candidates/fetches, failed strict acceptance on specific source/freshness/protected-primary/admitted-evidence dimensions, and blocked researcher dispatch with `acceptance_unmet_not_blocked_count=0`. | Phase 2 change; run `ads-pipeline-run:9f5fe6d27a39163ef2a2ec95b5c29fc536643b015dc0c8386463ff2e748e87dd` for Bank of Israel decrease and run `ads-pipeline-run:a863dbde06f469d22a53d2407dc9c7309d9c14a060adfa394af334050a21dbc1` for RBNZ increase. |
| AMRG assist policy signoff | Implemented for Phase 3. AMRG dependency readiness now exposes a first-class assist policy signoff, the readiness report surfaces it, and the readiness CLI can prove optional, required-missing, and required-validated modes without adding a new AMRG lane. | Phase 3 change; `orchestrator/scripts/tests/test_amrg_context.py`, `test_ads_live_readiness.py`, `test_ads_operator_review.py`, and `scripts/bin/check_ads_live_readiness.py --help`. |
| Readiness semantics and cwd-safe tests | Implemented for Phase 4. Live readiness top-level `status` now reports `blocked_true_runtime_cutover` when true-runtime cutover is blocked even if general readiness checks pass, while `general_issue_status` and `base_infrastructure_status` preserve the narrower health signals. The documented orchestrator test discovery command now passes from `orchestrator/`. | Phase 4 change; `orchestrator/scripts/tests/test_ads_live_readiness.py`, `test_decision_gate.py`, `test_synthesis_annotation.py`, and full orchestrator discovery from both repo root and `orchestrator/`. |

## What Is Still Not Implemented Or Not Yet Proven

These are the only active plan items.

1. The final representative clone-only batch has not been run after the Phase 4 readiness/test cleanup. End-to-end remediation should not be declared complete until that batch has no unexpected failures and at least one scoreable success.

## Non-Negotiable Runtime Invariants

- SCAE is the only production numeric forecast authority.
- Decomposer QDT and researcher leaf classification use `gpt-5.5-high` through OpenClaw Codex OAuth lanes.
- AMRG model assist uses the intended AMRG lane, default `gpt-5.4-high`, through OpenClaw Codex OAuth when policy requests it.
- Native research candidate discovery uses `gpt-5.5-high` when enabled and available.
- Source metadata classifier assist is bounded, optional unless policy requires it, and validator-accepted before it affects final metadata.
- Models may assist decomposition, relationship review, retrieval discovery, metadata parsing, and evidence classification. They may not author probabilities, fair values, SCAE deltas, or execution decisions.
- The decomposition tree is a research orchestration and coverage model, not an inference model.
- Retrieval must distinguish source publication/update/authored times from capture times.
- Market platform URLs may support market rules or resolution mechanics, but not external-event proof.
- Unknown source class, source family, claim family, or source time remains `unknown_not_counted` when sufficiency depends on it.
- Researchers classify certified evidence only. Search expansion stays upstream and any supplemental evidence must be revalidated.
- Readiness reports must fail closed for cutover when strict runtime canary evidence is missing, retrieval is uncertified, researcher models do not execute when dispatch is allowed, or SCAE lacks verified evidence deltas for a scoreable forecast.

## Phase 1 - QDT Coverage Repair Truthfulness

Status: completed. Preserve this as regression coverage while continuing with Phase 2.

Goal: QDT quality checks must not report coverage passed when the research coverage graph says required coverage still needs repair.

Why this remains:

- The post-push audit found `research_coverage_graph.coverage_summary.status = requires_repair` while `research_coverage_check.status = passed`.
- Current QDT code computes coverage failures from validation errors, but does not directly turn `coverage_summary.status == "requires_repair"` or repair-needed unanswered material questions into a failed coverage check.

Implementation:

- Update `decomposer/scripts/ads_decomposer/qdt.py`.
- In `compute_qdt_quality_checks()`, inspect `research_coverage_graph.coverage_summary`.
- If summary status is `requires_repair`, fail `research_coverage_check` with `research_coverage_requires_repair`.
- If `unanswered_material_questions` contains repair-needed required dimensions, fail with `unanswered_material_questions_require_repair` unless the artifact explicitly marks the question structurally unanswerable before cutoff.
- Preserve legitimate structural unanswerability, but do not label it as coverage-ready unless it is explicit, bounded, and non-dispatchable.
- Ensure candidate scoring rejects or heavily penalizes repair-required QDT outputs for live unresolved markets.

Pseudocode:

```python
def coverage_repair_reason_codes(qdt):
    graph = qdt.get("research_coverage_graph") or {}
    summary = graph.get("coverage_summary") or {}
    reasons = []

    if summary.get("status") == "requires_repair":
        reasons.append("research_coverage_requires_repair")

    for item in graph.get("unanswered_material_questions") or []:
        if item.get("status") in {"requires_repair", "requires_decomposer_repair"}:
            if item.get("unanswerability_type") != "structurally_unavailable_before_cutoff":
                reasons.append("unanswered_material_questions_require_repair")

    return sorted(set(reasons))

def compute_qdt_quality_checks(qdt, evidence_packet=None):
    validation = validate_question_decomposition(qdt, evidence_packet=evidence_packet)
    coverage_errors = coverage_errors_from(validation)
    coverage_errors.extend(coverage_repair_reason_codes(qdt))
    return failed_coverage_check(coverage_errors) if coverage_errors else passed_coverage_check()
```

Testing:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
```

New permanent tests:

- QDT with `coverage_summary.status=requires_repair` fails `research_coverage_check`.
- QDT with repair-needed `unanswered_material_questions` fails unless explicitly structurally unavailable before cutoff.
- Valid unresolved pre-resolution QDT still passes.
- Candidate selection does not select a repair-required QDT over a coverage-ready candidate.

Cleanup:

- Keep only permanent unit tests.
- Delete any generated QDT JSON artifacts, scratch scripts, temp DBs, or one-off debug outputs after extracting the summary.

Success criteria:

- Live QDT cannot be both `requires_repair` and `research_coverage_check.status=passed`.
- Repair-required QDT blocks before retrieval dispatch or is rejected during candidate selection.
- Existing QDT phase-6 regressions still pass.

## Phase 2 - Representative Live Retrieval Acceptance

Status: completed as representative live insufficiency proof. Preserve the tests and clone-run pattern as regression coverage while continuing with Phase 3.

Goal: prove retrieval acceptance on representative real clone-only cases, or produce a precise insufficiency/unanswerability blocker without unblocked downstream advancement.

Why this remains:

- The 21 source/retrieval implementation items are complete.
- The controlled search canary proves the positive path.
- The post-push real clone canary still failed live acceptance with zero independent non-market source families, zero freshness satisfaction, and zero protected-primary satisfaction.

Phase result:

- `ads-pipeline-run:9f5fe6d27a39163ef2a2ec95b5c29fc536643b015dc0c8386463ff2e748e87dd`, Bank of Israel decrease market:
  - QDT model executed, retrieval reached live runtime, and external source discovery was proven.
  - Retrieval found `6` real candidates, made `10` fetch attempts, and admitted `3` evidence refs.
  - Strict acceptance remained false because freshness, protected-primary, independent non-market source family, source/claim family diversity, and related breadth dimensions were unmet.
  - `classification_dispatch_allowed=false`, `blocked_when_acceptance_unmet_count=1`, and `acceptance_unmet_not_blocked_count=0`.
- `ads-pipeline-run:a863dbde06f469d22a53d2407dc9c7309d9c14a060adfa394af334050a21dbc1`, RBNZ increase market:
  - QDT end-to-end quality passed, retrieval reached live runtime, and external source discovery was proven.
  - Retrieval found `6` real candidates and made `10` fetch attempts, but admitted `0` evidence refs.
  - Strict acceptance remained false because admitted evidence, freshness, protected-primary, independent non-market source family, and source/claim family breadth were unmet.
  - `classification_dispatch_allowed=false`, `blocked_when_acceptance_unmet_count=1`, and `acceptance_unmet_not_blocked_count=0`.
- Phase 2 therefore closes as a blocker-proof phase, not as scoreable positive proof. The remaining need for at least one `scoreable_success` stays in Phase 5.

Implementation note:

- During Phase 2, live QDT execution exposed two pre-retrieval runtime-shape bugs that would have prevented representative retrieval proof:
  - Declarative `forbidden_outputs` values such as `probability` and `fair_value` were incorrectly treated as active forbidden model outputs.
  - Model-supplied `related_market_context_usage.usage_status` enum drift could block QDT materialization even though the handoff contains deterministic AMRG usage state.
- Both are fixed as deterministic runtime/schema handling. This is not a relaxation of retrieval acceptance.

Implementation:

- Do not rebuild the completed retrieval machinery unless a test exposes a failing dimension.
- Reuse the existing clone-only canary and report scripts. Do not add a new harness unless the existing scripts cannot produce the compact per-case retrieval acceptance summary needed for this phase.
- Run representative eligible markets that exercise:
  - official/protected-primary sources
  - independent secondary source families
  - source-time extraction
  - market-family or grouped-market context
  - clear insufficiency/unanswerability when sources are unavailable before cutoff
- If a representative case fails, diagnose the exact unmet dimensions before changing code:
  - no search candidates
  - fetch failure
  - empty fetched text
  - unknown source time
  - protected primary missing
  - source family collapse
  - claim family unknown
  - direct URL/source authority mismatch
  - policy-disabled native research or classifier assist
- If a representative clone run proves search is starved across required leaves and current diagnostics are insufficient, extend the existing retrieval diagnostics with per-critical-leaf budget accounting and status fields rather than relaxing acceptance.

Pseudocode:

```python
for case in representative_cases:
    result = run_clone_canary(case, require_real_runtime_canary_criteria=True)
    retrieval = result.report["retrieval_runtime_evidence"]

    if retrieval["live_acceptance_ok"]:
        assert retrieval["classification_dispatch_allowed"]
        continue

    assert retrieval["acceptance_unmet_not_blocked_count"] == 0
    assert result.blocker in {
        "retrieval_live_acceptance_requirements_not_met",
        "retrieval_structurally_unanswerable",
        "retrieval_insufficient_evidence",
    }
    write_compact_diagnostics(case, retrieval["acceptance_unmet_dimension_codes"])
```

Testing:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Clone-only test command template:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-retrieval.XXXXXX)"
cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"
cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --allow-non-scoreable \
  --skip-existing-ads-predictions \
  --metadata-json '{"audit_id":"ads-v2-retrieval-acceptance","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary-output.json"
```

Cleanup:

- Extract only the compact summary needed for the phase record.
- Delete `$TMPDIR`, cloned DBs, generated JSON reports, and any one-off scripts.

Success criteria:

- At least one representative clone-only case reaches `live_acceptance_ok=true` and `classification_dispatch_allowed=true`, or the phase explicitly documents why no eligible case can currently satisfy acceptance.
- Insufficient cases block cleanly with `acceptance_unmet_not_blocked_count=0`.
- No market prediction is written for non-scoreable or insufficient cases.
- Existing source/retrieval 21-item safeguards remain green.

## Phase 3 - AMRG Assist Policy And Runtime Proof

Status: completed as optional-policy signoff proof. Preserve the signoff/report tests and continue with Phase 4.

Goal: remove any remaining ambiguity around AMRG model assist by proving the current optional policy is visible end to end, or by proving live execution only if VM explicitly changes the policy to require it.

Why this remains:

- AMRG assist contracts, provenance validation, and optional-policy readiness status exist.
- The policy currently has `default_requested=false`, so live assist execution is not required and should not be claimed.

Phase result:

- The current policy remains optional with `default_requested=false`; Phase 3 did not add a new AMRG adapter, lane, or trigger path.
- `amrg_dependency_readiness.assist_policy_signoff` now makes the distinction explicit:
  - optional not requested: `signoff_status=optional_not_requested`, `model_execution_claim=not_claimed`
  - required but missing/failed: `signoff_status=required_assist_missing_or_failed`, readiness blocks with `amrg_assist_failed`
  - required and validated: `signoff_status=required_assist_validated`, execution is accepted only for advisory-validated assist
- Readiness and AMRG operator reports expose the model lane, resolved model, OAuth route, runtime agent, and advisory-only authority for signoff.
- The readiness CLI accepts AMRG assist policy/status inputs so the existing operator command can prove optional or required behavior without a new proof harness.

Implementation:

- Default path: keep the existing optional policy and verify reports expose `assist_not_requested_by_policy` without treating it as a blocker.
- Do not create a new AMRG adapter, lane, or policy branch during this phase unless VM explicitly decides AMRG assist is required for cutover.
- If VM changes policy to required, use the existing AMRG assist lane and provenance machinery to prove execution through `openclaw_codex_oauth/amrg`.
- If required, ensure live provenance records:
  - `model_executed=true`
  - `model_lane_id=amrg_model_assist`
  - `resolved_model_id=gpt-5.4-high`
  - `provider_route=openclaw_codex_oauth/amrg`
  - advisory-only status
- Preserve hard boundaries:
  - no probability
  - no fair value
  - no SCAE delta
  - no QDT selection or repair
  - no promotion authority
  - no source/citation/evidence authority

Pseudocode:

```python
def amrg_assist_required(candidate_set, policy):
    # Under the current policy this returns False; do not add new trigger modes
    # unless the policy is explicitly changed.
    if policy["default_requested"]:
        return True
    if policy.get("request_for_ambiguous_promotable_edges"):
        return candidate_set.has_ambiguous_promotable_edges()
    return False

def maybe_run_amrg_assist(candidate_set, policy):
    if not amrg_assist_required(candidate_set, policy):
        return {"status": "assist_not_requested_by_policy", "model_executed": False}

    output = invoke_amrg_model_assist(candidate_set)
    validate_amrg_model_assist_output(output)
    return advisory_only_provenance(output)
```

Testing:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_amrg_context
python3 -m unittest scripts.tests.test_ads_live_readiness
python3 -m unittest scripts.tests.test_ads_operator_review
python3 scripts/bin/report_amrg_context.py --help >/dev/null
```

Clone-only proof:

- Optional policy: run readiness/operator reports and confirm they expose `assist_not_requested_by_policy` and do not claim live assist execution.
- Required policy: run a clone canary with AMRG candidate context and confirm `amrg_model_assist_provenance.model_executed=true`.

Cleanup:

- Delete generated AMRG packet/output JSONs after extracting compact proof.
- Keep only permanent fixtures/tests.

Success criteria:

- AMRG assist status is no longer ambiguous.
- Optional mode remains a proof/sign-off step and does not block cutover merely because assist was not requested.
- Required mode records model execution and blocks when it fails.
- AMRG assist cannot promote related markets or become probability/evidence/QDT authority.

## Phase 4 - Readiness Semantics And Cwd-Safe Tests

Status: completed. Preserve this as regression coverage while continuing with Phase 5.

Goal: make the existing human-facing readiness report impossible to misread, and make documented test commands pass from their documented working directory.

Why this remains:

- `true_runtime_cutover_status` and `true_runtime_cutover_ready` exist.
- `build_live_readiness_report()` still sets top-level `status` from general `issues`, so it can say `ready` while `true_runtime_cutover_ready=false`.
- Running orchestrator tests from `/Users/agent2/.openclaw/orchestrator` currently fails two tests because they invoke repo-root-relative paths:
  - `orchestrator/scripts/bin/run_decision_gate.py`
  - `orchestrator/scripts/bin/run_synthesis_annotation.py`

Phase result:

- `build_live_readiness_report()` now distinguishes:
  - top-level `status`, which reports `blocked_true_runtime_cutover` whenever true-runtime cutover is blocked and no general issue would otherwise make the report `blocked`
  - `general_issue_status`, which preserves the previous general-issue readiness signal
  - `base_infrastructure_status`, which remains the health/infrastructure signal
- Non-scoreable readiness guard paths can still have `ok=true` when general checks pass, but the report can no longer be read as true-runtime cutover-ready while `true_runtime_cutover_ready=false`.
- The decision-gate and synthesis-annotation CLI tests now resolve script paths from `Path(__file__).resolve().parents[1] / "bin"` instead of repo-root-relative strings.
- Full orchestrator test discovery passes from both `/Users/agent2/.openclaw` and `/Users/agent2/.openclaw/orchestrator`.

Implementation:

- Update the existing readiness JSON and CLI display so top-level status reflects cutover blocking in cutover/readiness contexts.
- Preserve base infrastructure status separately:
  - `base_infrastructure_status`
  - `true_runtime_cutover_status`
  - `true_runtime_cutover_ready`
  - `overall_status` or top-level `status`
- Suggested status behavior:
  - if base infrastructure is healthy but true runtime cutover is blocked, show `status=blocked_true_runtime_cutover`
  - if only non-cutover diagnostics are requested, preserve a clear diagnostic/non-scoreable status
- Fix cwd-sensitive tests by computing CLI paths from `Path(__file__).resolve().parents[1] / "bin" / ...`.
- Add a regression that the documented orchestrator discovery command passes from `orchestrator/`.

Pseudocode:

```python
def report_status(base_issues, true_runtime_cutover_status, context):
    if true_runtime_cutover_status != "ready" and context in {"cutover", "scoreable_live", "operator"}:
        return "blocked_true_runtime_cutover"
    if base_issues:
        return "blocked"
    return "ready"
```

Testing:

```bash
cd /Users/agent2/.openclaw
python3 -m unittest discover -s orchestrator/scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 -m unittest \
  scripts.tests.test_ads_live_readiness \
  scripts.tests.test_ads_operator_review \
  scripts.tests.test_ads_pipeline_runner
```

Cleanup:

- Delete any temp CLI output JSONs.
- Do not leave cwd-test helper scripts behind unless they are permanent tests.

Success criteria:

- Readiness cannot be read as cutover-ready when strict runtime evidence is missing or blocked.
- Operator and readiness reports agree on true-runtime blocked status.
- Orchestrator tests pass from both repo root and `orchestrator/`.

## Phase 5 - Final Representative End-to-End Clone Batch

Goal: prove the intended v2 path after all remaining fixes with the existing canary/report scripts, then leave the workspace clean.

Implementation:

- Reuse the existing clone-only strict canary and report scripts against representative eligible cases:
  - one case similar to the prior Bank of Israel retrieval failure if still eligible
  - one binary market with clear protected-primary source requirements
  - one market with market-family/sibling context
  - one unresolved forecast market where pre-resolution QDT matters
- For each case, classify the result:
  - `scoreable_success`
  - `structured_non_scoreable_insufficiency`
  - `structural_unanswerability`
  - `unexpected_failure`
- Require no `unexpected_failure`.
- Require at least one `scoreable_success` before claiming the end-to-end scoreable path is resolved.
- Require non-scoreable cases to have no market prediction writes and clear blocker artifacts.

Pseudocode:

```python
results = []
for case_selector in representative_cases:
    tmpdir = make_clone()
    result = run_strict_canary(tmpdir.db, case_selector)
    reports = collect_reports(tmpdir.db, result.run_id)
    results.append(classify_end_to_end_result(reports))
    trash(tmpdir)

assert not any(r.kind == "unexpected_failure" for r in results)
assert any(r.kind == "scoreable_success" for r in results)
assert all(r.live_db_mutation == "clone_only" for r in results)
```

Testing:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/SCAE
python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/bin/check_ads_non_scae_authority.py
python3 scripts/bin/check_ads_script_placement.py
python3 scripts/bin/check_ads_canonical_artifacts.py
```

Cleanup:

- Delete clone DBs, generated canary outputs, handoff reports, operator reports, readiness reports, and one-off scripts after extracting the final summary.
- Do not commit generated test artifacts.

Success criteria:

- The batch has no unexpected failures.
- At least one case proves the full scoreable path: QDT quality, retrieval acceptance, researcher model execution, verification, SCAE valid forecast with evidence deltas, and prediction persistence.
- Any non-scoreable case blocks cleanly and writes no scoreable prediction.
- `main` and `origin/main` are clean and reconciled after the final implementation commit.

## Cross-Phase Verification Rule

Before starting a phase, classify whether it changes QDT, AMRG, retrieval/source collation, researcher assignment, verification, SCAE intake, or readiness/reporting.

After each phase:

- Run that phase's targeted unit tests.
- Run `git diff --check`.
- If the phase changes QDT, AMRG, retrieval, researcher assignment, verification, or SCAE intake, run `orchestrator/scripts/tests/test_ads_operational_canary.py`.
- If the phase changes readiness/reporting, run `scripts.tests.test_ads_live_readiness`, `scripts.tests.test_ads_operator_review`, and the smallest canary/report fixture proving blocked status stays visible.
- If clone DBs or JSON reports are generated, extract the compact phase summary and delete the artifacts before committing.

## Final Cutover Gate

Do not mark ADS v2 end-to-end remediation complete until all are true:

- QDT coverage cannot pass while the graph requires repair.
- Representative clone-only retrieval either certifies sufficient evidence or blocks cleanly.
- AMRG assist policy is explicit and proven according to that policy.
- Readiness top-level status cannot be misread as cutover-ready when true runtime cutover is blocked.
- Orchestrator test discovery passes from both repo root and `orchestrator/`.
- A final representative clone batch has no unexpected failures.
- At least one final batch case proves the full scoreable path end to end.
- Temporary testing artifacts and generated one-off scripts are deleted.
