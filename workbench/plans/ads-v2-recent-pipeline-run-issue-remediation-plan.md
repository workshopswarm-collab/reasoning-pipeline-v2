# ADS v2 Recent Pipeline Run Issue Remediation Plan

Created: 2026-07-01
Owner: Workbench implementation session
Scope: strict sequential implementation plan for the issues observed in the latest clone-only ADS v2 pipeline runs.

## Audit Anchor

Recent observed clone-only runs:

- `ads-pipeline-run:91b2dec9dbd614dd21f35510d3df9c1b9dfcaa799d8c552023ce1bd943cd672d`
  - Case: `polymarket:1795635`, Bank of Israel July rate decrease.
  - Result: all 13 stages completed safely, but strict criteria failed on QDT quality, retrieval acceptance, and researcher execution.
  - Main intelligence findings: live QDT executed but failed `source_quality` coverage; retrieval produced activity but no meaningful snippets, claim families, freshness, source-family breadth, or protected-primary satisfaction; native research executed but produced no candidate URLs; AMRG was safe but weak and unconsumed.
- `ads-pipeline-run:d8328ad59497b07c2393efaf68f12a73b883a7737e7afb704c692ede010ca671`
  - Case: `polymarket:1795635`, Bank of Israel July rate decrease.
  - Result: stopped after 4 stages at decomposition.
  - Main issue: live `gpt-5.5-high` QDT output failed schema/semantic validation with invalid purposes, unknown required evidence purposes, missing `structural_validation.answerability_status`, invalid leaf condition scope, and terminal verification misclassified as pre-resolution.
- `ads-pipeline-run:fe10d36bfbb21ab10d2144d1804fa4cb4deb9a57fab3b488070b000402619eca`
  - Case: `polymarket:1919561`, RBNZ July OCR increase.
  - Result: stopped after 4 stages at decomposition.
  - Main issue: live `gpt-5.5-high` QDT output repaired once, then still failed `analyst_consensus_leaf_wrong_temporal_role`.

Safety behavior across the recent runs was correct: clone-only mode, no market prediction writes, active runs and leases drained to 0/0, pipeline control returned disabled, and unsafe downstream authority did not fire.

## Guiding Principle

Do not make downstream gates permissive to manufacture a pass. The fix path is to make upstream intelligence and retrieval produce valid, certified inputs while preserving strict deterministic validation and authority boundaries.

This plan is strict sequential. A session implementing it must complete, verify, clean, and summarize each phase before starting the next phase. If new bugs or mismatches appear, update this plan with a dated phase note before continuing.

## Standing Invariants

- QDT may decompose and structure research, but may not forecast probability, fair value, SCAE deltas, or execution decisions.
- Decomposer live model execution and QDT artifact acceptance are distinct states and must be reported distinctly.
- QDT repair may fix mechanical schema drift, but must not override semantic blockers or forbidden authority leakage.
- Retrieval may discover, fetch, normalize, and admit evidence, but deterministic validators remain final authority for source class, source family, claim family, temporal safety, breadth, and sufficiency.
- Native research and source-metadata classifier assists may propose candidate URLs or parsing hints only.
- AMRG is context/advisory only unless a separate explicit policy change makes model assist required.
- Researchers classify bounded certified evidence only; they do not browse freely and do not forecast.
- Verification must emit SCAE-ready deltas before SCAE can produce a valid scoreable forecast.
- SCAE remains the only numeric forecast authority.
- Non-scoreable or insufficient cases must write no market prediction.
- All proof runs in this plan are clone-only until VM explicitly authorizes live mutation.

## Adaptive Execution Rule

At the start of every phase:

1. Fetch and confirm local `main` is aligned with `origin/main`.
2. Re-run the smallest baseline check relevant to the phase.
3. Confirm the previous phase checklist still passes.
4. Record any newly observed blocker in this plan or a dated adjacent note.
5. Adjust only the current or next phase scope unless VM asks for a broader rewrite.

At the end of every phase:

1. Run targeted tests.
2. Run the phase clone proof when required.
3. Delete temporary artifacts and one-off scripts.
4. Run `git diff --check`.
5. Verify `git status --short` contains only intentional source, test, or plan changes.
6. Evaluate the phase checklist before marking the phase complete.

Temporary artifacts include clone DBs, generated JSON reports, ad hoc inspection scripts, copied runtime artifacts, generated fixture JSON not intended as permanent tests, and one-off test harnesses.

Use a phase-scoped temp directory for one-off artifacts:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-recent-run-remediation-phaseN.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
```

Before completing each phase:

```bash
find /tmp -maxdepth 1 -name 'ads-v2-recent-run-remediation-phase*' -print
git diff --check
git status --short
```

Success for cleanup means no phase temp directories remain, no generated canary output or clone DB is staged, and no one-off testing script remains outside the temp directory.

## Phase 0 - Baseline Reproduction And Failure Taxonomy

Status: complete

Goal: preserve the current failure shapes as reproducible tests and report categories before changing behavior.

Implementation:

- Add compact regression fixtures or test builders for:
  - BOI live QDT schema/semantic drift.
  - RBNZ analyst-consensus temporal-role drift.
  - BOI full-stage structured insufficiency with retrieval activity but no certified evidence.
- Add report taxonomy for:
  - `live_qdt_call_executed_output_rejected`
  - `live_qdt_call_executed_output_accepted`
  - `qdt_fixture_or_deterministic_path`
  - `retrieval_source_populated_but_not_certified`
  - `native_research_executed_no_candidates`
- Preserve existing fail-closed behavior while adding diagnostics.

Pseudocode:

```python
def classify_qdt_runtime_state(runtime_calls, accepted_qdts):
    live_calls = [
        call for call in runtime_calls
        if call["mode"] == "live"
        and call["fixture_mode"] is False
        and call["model_call_performed"] is True
    ]
    accepted_live_qdts = [
        qdt for qdt in accepted_qdts
        if qdt["adapter_mode"] == "decomposer_model_runtime_live"
        and qdt["resolved_model_id"] == "gpt-5.5-high"
    ]
    if accepted_live_qdts:
        return "live_qdt_call_executed_output_accepted"
    if live_calls:
        return "live_qdt_call_executed_output_rejected"
    return "qdt_fixture_or_deterministic_path"


def classify_recent_run_failure(report):
    qdt_state = classify_qdt_runtime_state(
        report["model_runtime_evidence"]["runtime_results"],
        report["model_runtime_evidence"]["qdt_results"],
    )
    retrieval = report["retrieval_runtime_evidence"]
    return {
        "qdt_runtime_state": qdt_state,
        "retrieval_state": (
            "retrieval_source_populated_but_not_certified"
            if retrieval["source_populated_count"] and not retrieval["live_acceptance_ok"]
            else "retrieval_not_source_populated"
        ),
        "native_state": (
            "native_research_executed_no_candidates"
            if retrieval["native_research_model_executed_count"]
            and retrieval.get("native_candidate_url_count", 0) == 0
            else "native_research_not_executed_or_useful"
        ),
    }
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_real_runtime_canary
python3 -m unittest scripts.tests.test_ads_operator_review
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 scripts/bin/report_ads_real_runtime_canary.py --help >/dev/null
python3 scripts/bin/report_ads_operator_review.py --help >/dev/null
git diff --check
```

Clone proof:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-recent-run-remediation-phase0.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --allow-non-scoreable \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --require-researcher-model-executed \
  --metadata-json '{"audit_id":"ads-v2-recent-run-phase0","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary-output.json" || true
```

Success criteria:

- Current QDT rejection and retrieval insufficiency shapes are represented in permanent tests or compact fixtures.
- Reports distinguish live model execution from accepted QDT artifact persistence.
- No downstream gate is loosened.
- Clone proof remains safe and writes no market prediction when insufficient.
- All temp artifacts are deleted.

Checklist:

- [x] BOI QDT schema/semantic drift regression exists.
- [x] RBNZ analyst-consensus drift regression exists.
- [x] Full-stage retrieval insufficiency regression exists.
- [x] Runtime taxonomy appears in report surfaces.
- [x] Clone proof is safe and drain is clean.
- [x] Temp artifacts and one-off scripts removed.
- [x] Targeted tests and `git diff --check` pass.

Completion note, 2026-07-01:

- Added `ads-recent-run-failure-taxonomy/v1` to real-runtime canary reporting and current-audit gap summaries. It distinguishes live QDT call execution from accepted QDT persistence, source-populated retrieval that is not certified, and native research execution with zero candidate URLs.
- Added focused Phase 0 regression fixtures for BOI live QDT schema/semantic rejection, RBNZ analyst-consensus temporal-role rejection, and BOI source-populated retrieval with no certified evidence. Operator review now reports live QDT output rejection separately from deterministic/fixture QDT paths.
- Clone proof run `ads-pipeline-run:492ac85fa7c3be30115c1973827d7e375563532054112bd7cc6e818f6cbb3f22` failed closed at `retrieval_live_acceptance_requirements`, wrote zero market predictions, and drained active work to 0/0. Its taxonomy reported `live_qdt_call_executed_output_accepted`, `retrieval_source_populated_but_not_certified`, and `native_research_executed_no_candidates`.
- Verification passed: targeted real-runtime/operator/operational canary tests, report CLI help checks, `py_compile` for changed modules/tests, cleanup check for phase temp directories, and `git diff --check`.

## Phase 1 - Live QDT Schema Contract Hardening

Status: completed 2026-07-01

Goal: make live Decomposer outputs reliably conform to `question-decomposition/v1` without relaxing validation.

Implementation:

- Update the Decomposer prompt/runtime input contract to include:
  - exact allowed `purpose` enum values;
  - exact allowed `required_evidence_purposes`;
  - exact allowed `leaf_condition_scope`;
  - required `structural_validation.answerability_status`;
  - allowed `leaf_temporal_role` values;
  - examples of terminal verification leaves that must not dispatch pre-resolution.
- Add a compact schema crib generated from code constants so prompt and validator do not drift.
- Add fixture tests using the two failed output shapes.
- Keep forbidden output scanning before any schema acceptance.

Pseudocode:

```python
def build_qdt_schema_crib():
    return {
        "allowed_purposes": sorted(ALLOWED_PURPOSES),
        "allowed_required_evidence_purposes": sorted(ALLOWED_REQUIRED_EVIDENCE_PURPOSES),
        "allowed_condition_scopes": sorted(ALLOWED_CONDITION_SCOPES),
        "allowed_leaf_temporal_roles": sorted(ALLOWED_LEAF_TEMPORAL_ROLES),
        "required_leaf_fields": sorted(REQUIRED_LEAF_FIELDS),
        "terminal_verification_rule": (
            "Post-resolution official-result checks must use terminal_verification "
            "and must not be counted as pre-resolution dispatch leaves."
        ),
    }


def build_decomposer_prompt(case_contract, policy_context, amrg_context):
    schema_crib = build_qdt_schema_crib()
    return render_prompt(
        case_contract=case_contract,
        policy_context=policy_context,
        amrg_context=amrg_context,
        schema_crib=schema_crib,
        forbidden_outputs=QDT_FORBIDDEN_AUTHORITY_FIELDS,
    )
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_model_runtime
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
git diff --check
```

Clone proof:

Run one clone-only BOI canary. It may still fail later on retrieval, but it must not stop at decomposition for schema enum drift.

Success criteria:

- BOI and RBNZ QDT schema-drift fixtures fail before the fix and pass after.
- Live QDT prompt includes canonical enum and required-field guidance derived from code.
- Decomposer still rejects forbidden authority fields.
- Clone proof reaches retrieval or later, unless a different explicit fail-closed QDT semantic blocker appears and is documented.
- No temp artifacts remain.

Checklist:

- [x] Prompt/runtime schema crib implemented.
- [x] BOI invalid enum/missing-field fixture covered.
- [x] RBNZ consensus-role fixture covered.
- [x] Full decomposer tests pass.
- [x] Clone proof no longer fails on basic QDT schema drift.
- [x] Temp artifacts and one-off scripts removed.

Completion note, 2026-07-01:

- Added `decomposer-qdt-schema-crib/v1`, generated from QDT validator constants, to the Decomposer prompt payload and live OpenClaw prompt contract.
- Hardened mechanical live-output repair for purpose aliases, invalid condition scopes, invalid temporal roles, missing `structural_validation.answerability_status`, analyst-consensus role drift, and malformed `research_sufficiency_requirements` values while keeping forbidden-output scanning ahead of schema acceptance.
- Added focused fixtures for BOI enum/missing-field drift, RBNZ analyst-consensus role drift, malformed sufficiency contracts, and prompt/schema-crib parity.
- Clone proof run `ads-pipeline-run:7021276fdab6a019923947b8cba20eac0327f8b6adbc613e59b52ecf3cd5e7de` executed live QDT via OpenClaw, repaired once, passed forbidden-output scan, validated the output schema, and accepted the QDT. The clone-only canary completed all 13 stages, drained active work to 0/0, wrote zero market predictions, and reported remaining criteria failures at QDT end-to-end quality, retrieval live acceptance, and researcher runtime verification.
- Verification passed: `python3 -m unittest scripts.tests.test_qdt`, `python3 -m unittest scripts.tests.test_model_runtime`, `python3 -m unittest scripts.tests.test_runtime_decomposition`, full decomposer discovery, `python3 -m unittest scripts.tests.test_ads_operational_canary`, temp-artifact cleanup check, and `git diff --check`.

## Phase 2 - QDT Repair Resilience And Semantic Failure Separation

Status: completed 2026-07-01

Goal: make QDT repair useful for mechanical schema drift while preserving semantic fail-closed behavior.

Implementation:

- Split validation errors into:
  - forbidden authority errors;
  - mechanical schema errors;
  - semantic research-quality errors;
  - terminal temporal-role errors.
- Permit one bounded repair pass for mechanical schema errors even when semantic errors also exist.
- After repair, preserve remaining semantic blockers as terminal if still present.
- Record durable diagnostics:
  - mechanical errors before repair;
  - semantic errors before repair;
  - repaired fields;
  - remaining errors after repair;
  - repair skipped reason, if skipped.

Pseudocode:

```python
def classify_qdt_validation_errors(errors):
    groups = {
        "forbidden_authority": [],
        "mechanical_schema": [],
        "semantic_quality": [],
        "terminal_temporal_role": [],
    }
    for error in errors:
        if "forbidden" in error or "authority" in error:
            groups["forbidden_authority"].append(error)
        elif any(token in error for token in [
            "purpose is invalid",
            "required_evidence_purposes contains unknown purpose",
            "answerability_status is required",
            "leaf_condition_scope is invalid",
            "missing ",
        ]):
            groups["mechanical_schema"].append(error)
        elif "terminal_verification_leaf_misclassified" in error:
            groups["terminal_temporal_role"].append(error)
        else:
            groups["semantic_quality"].append(error)
    return groups


def should_attempt_schema_repair(groups, repair_budget):
    if groups["forbidden_authority"]:
        return False, "forbidden_authority_not_repairable"
    if repair_budget <= 0:
        return False, "repair_budget_exhausted"
    if groups["mechanical_schema"]:
        return True, "mechanical_schema_repair_available"
    return False, "no_mechanical_schema_errors"
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_model_runtime
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
git diff --check
```

Success criteria:

- Mixed mechanical plus semantic failures attempt one repair pass.
- Forbidden authority failures still do not repair.
- Remaining semantic failures remain terminal and visible.
- Repair diagnostics are present in runtime artifacts and reports.
- No duplicate QDT artifacts or runtime calls are persisted after repair.

Checklist:

- [x] Validation error classifier implemented.
- [x] Mixed-error repair test added.
- [x] Forbidden-authority no-repair test still passes.
- [x] Repair diagnostics surfaced.
- [x] Full decomposer tests pass.
- [x] Temp artifacts and one-off scripts removed.

Completion note, 2026-07-01:

- Added `model-runtime-schema-repair-diagnostic/v1` records to model-runtime calls and model execution context. Diagnostics now include pre-repair error groups/counts, repair decision or skipped reason, bounded repaired JSON paths, and remaining post-repair errors/groups/counts.
- Added QDT validation error grouping for `forbidden_authority`, `mechanical_schema`, `semantic_quality`, and `terminal_temporal_role`. Aggregate validator errors can populate multiple groups, so wrapped candidate-rejection messages still expose mixed mechanical/semantic failures.
- Updated schema repair gating to attempt one repair when mechanical schema errors are present, even if semantic/terminal errors are also present. Forbidden-authority validation errors still skip repair, and remaining semantic/terminal errors fail closed after repair.
- Threaded schema repair diagnostics into real-runtime canary model-runtime evidence so reports can surface repair decisions.
- Verification passed: `python3 -m unittest scripts.tests.test_model_runtime`, `python3 -m unittest scripts.tests.test_runtime_decomposition`, `python3 -m unittest scripts.tests.test_qdt`, full decomposer discovery, `python3 -m unittest scripts.tests.test_ads_real_runtime_canary`, `python3 -m unittest scripts.tests.test_ads_operational_canary`, temp-artifact cleanup check, and `git diff --check`.

## Phase 3 - QDT Coverage Semantics And Source Quality Mapping

Status: completed 2026-07-01

Goal: fix the mismatch where a source-quality/cutoff leaf exists but `source_quality` coverage still fails.

Implementation:

- Audit QDT coverage dimension computation.
- Define the exact leaf properties that satisfy `source_quality`:
  - `coverage_dimension == "source_quality"`; or
  - `purpose == "source_of_truth"` with source timestamp, publisher authority, cutoff admissibility, and decision calendar fields.
- Add explicit diagnostics when a source-quality-like leaf does not count.
- Add BOI fixture asserting `leaf-source-quality-calendar-cutoff` satisfies or precisely fails `source_quality`.

Pseudocode:

```python
def leaf_satisfies_source_quality(leaf):
    fields = set(leaf.get("required_evidence_fields") or [])
    source_quality_fields = {
        "source_timestamp",
        "publisher_authority",
        "cutoff_admissibility",
    }
    if leaf.get("coverage_dimension") == "source_quality":
        return True, []
    if leaf.get("purpose") == "source_of_truth" and source_quality_fields <= fields:
        return True, []
    return False, [
        "missing_coverage_dimension_source_quality",
        *missing_field_reasons(source_quality_fields, fields),
    ]


def compute_required_coverage(qdt):
    observed = set()
    diagnostics = []
    for leaf in qdt["required_leaf_questions"]:
        if leaf_satisfies_source_quality(leaf)[0]:
            observed.add("source_quality")
        else:
            diagnostics.append(source_quality_diagnostic(leaf))
        observed |= other_coverage_dimensions(leaf)
    return observed, diagnostics
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
git diff --check
```

Clone proof:

Run one BOI clone-only canary. Success for this phase means QDT either passes source-quality coverage or fails with a precise new source-quality diagnostic that directly identifies the missing field/role.

Success criteria:

- `source_quality` coverage is deterministic and test-covered.
- The BOI source-quality/cutoff leaf is no longer silently ignored.
- QDT does not pass if source-quality coverage is genuinely absent.
- Clone proof reaches retrieval when QDT is otherwise valid.
- No temp artifacts remain.

Checklist:

- [x] Source-quality satisfaction rule implemented.
- [x] Missing source-quality diagnostics implemented.
- [x] BOI coverage regression added.
- [x] Decomposer tests pass.
- [x] Clone proof validates intended behavior.
- [x] Temp artifacts and one-off scripts removed.

Completion note, 2026-07-01:

- Added deterministic source-quality satisfaction semantics for QDT coverage graphs. A leaf now contributes `source_quality` when it explicitly declares `coverage_dimension == "source_quality"` or when it is a `source_of_truth` leaf with `source_timestamp`, `publisher_authority`, `cutoff_admissibility`, and a decision-calendar evidence field.
- Coverage graph construction now preserves the leaf's primary dimension while allowing qualifying source-of-truth calendar/cutoff leaves to add supplemental `source_quality` coverage. Unresolved pre-resolution coverage validation and candidate scoring use the same effective coverage dimensions.
- Added `source_quality_diagnostics` and `source_quality_like_leaf_not_counted` reason codes for source-quality-like leaves that do not qualify. Diagnostics identify the exact missing field or role, including `missing_source_quality_field:cutoff_admissibility` and `missing_source_quality_decision_calendar_field`.
- Added BOI regressions for `leaf-source-quality-calendar-cutoff`: one accepted fixture proves the source-of-truth calendar/cutoff leaf satisfies `source_quality`; one rejected fixture proves precise missing-field diagnostics when cutoff/calendar evidence is absent.
- Clone proof: a BOI clone-only canary was run on a temporary DB copy with only external market `1795635` eligible and metadata `{"audit_id":"ads-v2-recent-run-phase3","live_db_mutation":"clone_only"}`. The broader postflight still failed on existing live-runtime/retrieval criteria, but clone-only safety held (`active_runs=0`, `active_leases=0`, protected write deltas all `0`) and the report did not list missing source-quality coverage (`qdt_missing_coverage_dimensions: []`). A transport-response variant using `leaf-source-quality-calendar-cutoff` was also attempted and stopped after exceeding the bounded proof window in later live stages; no phase temp directories or canary processes remained.
- Verification passed: `python3 -m unittest scripts.tests.test_qdt`, `python3 -m unittest scripts.tests.test_runtime_decomposition`, full decomposer discovery, `python3 -m unittest scripts.tests.test_ads_operational_canary`, `git diff --check`, and temp-artifact/process cleanup checks.

## Phase 4 - Runtime Reporting And Operator Review Accuracy

Status: planned

Goal: make reports accurately distinguish live model execution, output rejection, deterministic/fixture fallback, and accepted QDT artifacts.

Implementation:

- Add QDT runtime counters:
  - `qdt_live_model_call_attempted_count`
  - `qdt_live_model_call_executed_count`
  - `qdt_live_output_schema_rejected_count`
  - `qdt_live_output_accepted_count`
  - `qdt_fixture_or_deterministic_count`
- Update real-runtime canary gate details to show attempted/executed/rejected/accepted states.
- Update operator alert wording:
  - use `live_qdt_output_rejected` when live model executed but no QDT artifact was accepted;
  - reserve `true_production_deterministic_qdt` for actual deterministic/fixture paths.
- Preserve current readiness blocking behavior.

Pseudocode:

```python
def qdt_runtime_counters(runtime_calls, qdt_results):
    live_calls = [
        call for call in runtime_calls
        if call["mode"] == "live" and call["fixture_mode"] is False
    ]
    accepted_live = [
        qdt for qdt in qdt_results
        if qdt["adapter_mode"] == "decomposer_model_runtime_live"
    ]
    rejected_live = [
        call for call in live_calls
        if call["execution_status"] in {
            "failed_schema_validation",
            "failed_forbidden_output",
            "failed_forbidden_output_after_repair",
        }
    ]
    return {
        "qdt_live_model_call_attempted_count": len(live_calls),
        "qdt_live_model_call_executed_count": count(call["model_call_performed"] for call in live_calls),
        "qdt_live_output_schema_rejected_count": len(rejected_live),
        "qdt_live_output_accepted_count": len(accepted_live),
    }


def qdt_operator_alert(qdt):
    if qdt["qdt_live_output_schema_rejected_count"] > 0 and qdt["qdt_live_output_accepted_count"] == 0:
        return "live_qdt_output_rejected"
    if qdt["qdt_fixture_or_deterministic_count"] > 0:
        return "true_production_deterministic_qdt"
    return None
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_real_runtime_canary
python3 -m unittest scripts.tests.test_ads_operator_review
python3 -m unittest scripts.tests.test_ads_live_readiness
python3 -m unittest scripts.tests.test_ads_operational_canary
git diff --check
```

Success criteria:

- Failed live QDT schema calls report as live rejected, not deterministic.
- Deterministic/fixture paths still report as deterministic.
- Readiness stays blocked when no accepted QDT exists.
- Operator remediation text points to Decomposer output repair/contract, not handler selection, for live-rejected outputs.

Checklist:

- [ ] Runtime counters added.
- [ ] Operator alert split implemented.
- [ ] Regression tests cover live-rejected and deterministic paths.
- [ ] Readiness behavior unchanged.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 5 - Retrieval Meaningful Evidence, Claim Families, And Freshness Certification

Status: planned

Goal: make retrieval produce certified, classification-usable evidence rather than admitted short chunks that cannot support researcher dispatch.

Implementation:

- Require admitted evidence counted for sufficiency to include:
  - bounded meaningful snippet text;
  - source metadata resolution;
  - source family;
  - claim candidate;
  - claim family resolution when claim breadth is required;
  - freshness proof when freshness is required.
- Ensure short chunks can remain diagnostic but cannot satisfy sufficiency.
- Add leaf-level diagnostics for exactly why each leaf is uncertified.
- Tune elapsed-budget behavior so later leaves get explicit skipped-budget diagnostics and do not silently starve.

Pseudocode:

```python
def evidence_counts_for_sufficiency(evidence):
    return (
        evidence["admission_status"] == "admitted"
        and len(evidence.get("bounded_snippet", "")) >= MIN_CLASSIFICATION_SNIPPET_CHARS
        and evidence.get("source_metadata_ref")
        and evidence.get("source_family_id")
        and (
            not evidence.get("claim_family_required")
            or evidence.get("claim_family_id")
        )
        and (
            not evidence.get("freshness_required")
            or evidence.get("freshness_status") == "fresh"
        )
    )


def certify_leaf(leaf, evidence_refs):
    usable = [ref for ref in evidence_refs if evidence_counts_for_sufficiency(ref)]
    blockers = []
    if len(usable) < leaf["min_admitted_evidence"]:
        blockers.append("admitted_evidence_count")
    if not has_required_source_classes(leaf, usable):
        blockers.append("required_source_class_missing")
    if not has_required_claim_families(leaf, usable):
        blockers.append("claim_family_diversity")
    if not freshness_satisfied(leaf, usable):
        blockers.append("freshness")
    return build_leaf_certificate(leaf, usable, blockers)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest scripts.tests.test_assignments
python3 -m unittest scripts.tests.test_verification
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_operator_review
git diff --check
```

Clone proof:

Run one BOI clone-only canary. Success for this phase can be either certified retrieval or a more precise structured insufficiency report, but not admitted evidence with `meaningful_snippet_admitted_count = 0` when fetches returned usable content.

Success criteria:

- Short chunks do not certify sufficiency.
- Meaningful snippets can certify sufficiency when metadata, family, claim, and freshness are valid.
- Leaf blockers are precise and complete.
- No researcher dispatch occurs unless all required leaves certify or are structurally unanswerable.
- No temp artifacts remain.

Checklist:

- [ ] Meaningful evidence sufficiency gate implemented.
- [ ] Claim-family certification covered.
- [ ] Freshness/protected-primary certification covered.
- [ ] Per-leaf blocker diagnostics covered.
- [ ] Retrieval and orchestrator tests pass.
- [ ] Clone proof validates intended behavior.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 6 - Native Research Candidate Discovery Usefulness

Status: planned

Goal: make native research produce useful candidate URLs or precise failure diagnostics without gaining evidence authority.

Implementation:

- Capture per-call native research diagnostics:
  - trigger reason;
  - prompt/case leaf refs;
  - model execution status;
  - output parse status;
  - candidate URL count;
  - validation rejection reasons.
- Add one bounded repair pass for malformed native output if it is safe and authority-clean.
- Keep native output limited to candidate URL, canonical URL hint, source type hint, leaf/query provenance, and reason.
- Route every native candidate through deterministic fetch/admission before it can affect evidence.

Pseudocode:

```python
def run_native_candidate_discovery(leaf, query_context, policy):
    diagnostic = start_native_diagnostic(leaf)
    response = native_runtime.call(
        lane="native_research_candidate_discovery",
        input=build_native_candidate_prompt(leaf, query_context),
    )
    diagnostic.model_executed = response.model_executed
    parsed = parse_native_candidates(response.payload)
    if not parsed.ok and parsed.repairable:
        parsed = repair_native_candidates(response.payload, parsed.errors)
        diagnostic.repair_attempted = True
    candidates = []
    for candidate in parsed.candidates:
        if native_candidate_is_authority_clean(candidate):
            candidates.append(normalize_native_candidate(candidate, leaf))
        else:
            diagnostic.rejections.append(candidate.rejection_reason)
    diagnostic.candidate_url_count = len(candidates)
    return candidates, diagnostic
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
git diff --check
```

Clone proof:

Run a clone-only canary with native discovery enabled. Success means native research either contributes at least one deterministic-fetchable candidate URL or emits per-call failure diagnostics that identify why no candidate was usable.

Success criteria:

- Native research candidate output remains authority-bounded.
- Per-call diagnostics explain failures.
- Malformed but safe output can be repaired once.
- Native candidates only affect evidence after deterministic fetch/admission.
- No temp artifacts remain.

Checklist:

- [ ] Native per-call diagnostics implemented.
- [ ] Native repair path covered.
- [ ] Authority-bound candidate validation covered.
- [ ] Positive native-candidate fixture covered.
- [ ] Clone proof validates useful candidate or precise failure.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 7 - AMRG Ranking, Filtering, And QDT Consumption Proof

Status: planned

Goal: make AMRG useful as context by improving candidate relevance and making QDT consumption observable, while preserving advisory boundaries.

Implementation:

- Improve AMRG candidate scoring so direct sibling/complement markets outrank broad entity matches.
- Add negative filters for weak macro/entity-only candidates unless they share:
  - same institution;
  - same decision date/window;
  - same market family;
  - direct complement relation;
  - explicit resolution anchor overlap.
- Update QDT prompt contract to instruct:
  - consume relevant AMRG hints by ref;
  - ignore irrelevant hints with reason codes;
  - never use AMRG hints for probability, sufficiency, or SCAE deltas.
- Add operator report counters:
  - consumed hint count;
  - ignored hint count by reason;
  - high-relevance candidate count;
  - weak-context-only candidate count.

Pseudocode:

```python
def score_amrg_candidate(target, candidate):
    score = 0
    if same_market_family(target, candidate):
        score += 50
    if is_direct_complement(target, candidate):
        score += 40
    if same_institution(target, candidate):
        score += 25
    if same_decision_window(target, candidate):
        score += 20
    if broad_entity_only(target, candidate):
        score -= 30
    return score


def qdt_amrg_consumption_slice(hint, qdt):
    refs = find_hint_refs_in_branches_or_leaves(hint, qdt)
    if refs:
        return {
            "hint_ref": hint["hint_ref"],
            "effect_status": "consumed_context_only_no_authority",
            "consumed_by_branch_ids": refs.branch_ids,
            "consumed_by_leaf_ids": refs.leaf_ids,
        }
    return {
        "hint_ref": hint["hint_ref"],
        "effect_status": "not_consumed_context_only_no_authority",
        "ignored_reason_codes": classify_ignored_hint(hint, qdt),
    }
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_amrg_context
python3 -m unittest scripts.tests.test_amrg_vector
python3 -m unittest scripts.tests.test_ads_operator_review
python3 -m unittest scripts.tests.test_ads_operational_canary

cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
git diff --check
```

Clone proof:

Run one BOI clone-only canary. Success means the BOI no-change sibling is ranked high and either consumed by QDT as context or ignored with a precise reason; weak off-topic candidates are not promoted.

Success criteria:

- AMRG candidate ranking prefers relevant sibling/complement markets.
- QDT consumption or ignore status is observable.
- AMRG does not create evidence, probability, QDT selection, or SCAE authority.
- Operator report makes AMRG usefulness visible.
- No temp artifacts remain.

Checklist:

- [ ] Candidate scoring updated.
- [ ] Weak-candidate filtering covered.
- [ ] QDT AMRG consumption contract covered.
- [ ] Operator counters added.
- [ ] Clone proof validates relevant sibling handling.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 8 - Researcher Runtime Positive Dispatch And Verification Proof

Status: planned

Goal: prove researcher execution and verification on certified bounded evidence, without relaxing retrieval gates.

Implementation:

- Add or reuse a controlled certified-retrieval fixture that creates:
  - dispatchable QDT leaves;
  - certified bounded evidence descriptors;
  - source metadata refs;
  - claim family refs;
  - leaf sufficiency certificates.
- Prove researcher assignment creation only occurs when `classification_dispatch_allowed = true`.
- Prove researcher sidecars are model-backed, authority-clean, and leaf-scoped.
- Prove verification consumes researcher sidecars and emits SCAE-ready evidence delta refs only when direction/quality checks pass.

Pseudocode:

```python
def build_researcher_assignments(retrieval_packet):
    if not retrieval_packet["research_sufficiency_summary"]["all_required_leaves_certified"]:
        return readiness_block("blocked_until_certified_retrieval")
    assignments = []
    for leaf in retrieval_packet["leaf_retrieval_results"]:
        assignments.append({
            "leaf_id": leaf["leaf_id"],
            "bounded_evidence_refs": leaf["certified_bounded_evidence_refs"],
            "forbidden_context_refs": FORBIDDEN_RESEARCHER_CONTEXT_REFS,
            "authority": "classification_only_no_probability",
        })
    return assignments


def verify_researcher_sidecar(sidecar):
    if sidecar_contains_forbidden_authority(sidecar):
        return quarantine("policy_violation_quarantine")
    if not sidecar_has_bounded_evidence_lineage(sidecar):
        return blocked("missing_bounded_evidence_lineage")
    return scae_ready_delta_ref(sidecar)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_assignments
python3 -m unittest scripts.tests.test_verification
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_production_handlers
git diff --check
```

Success criteria:

- Researcher dispatch is blocked when retrieval is uncertified.
- Researcher dispatch runs when retrieval is certified in the controlled fixture.
- Researcher sidecars contain bounded evidence lineage and no authority leakage.
- Verification emits SCAE-ready deltas only for valid sidecars.
- No temp artifacts remain.

Checklist:

- [ ] Certified retrieval positive fixture exists.
- [ ] Blocked dispatch test passes.
- [ ] Positive researcher dispatch test passes.
- [ ] Authority leakage quarantine test passes.
- [ ] Verification-to-SCAE-ready delta test passes.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 9 - SCAE Valid Forecast Positive Path And Authority Guard

Status: planned

Goal: prove SCAE can produce a valid forecast from verified evidence-delta refs and remains the only numeric forecast authority.

Implementation:

- Use verified SCAE-ready delta refs from Phase 8.
- Require SCAE valid forecast ledgers to have nonzero accepted delta refs.
- Keep invalid/insufficient research ledgers as `invalid_for_forecast`.
- Prove non-SCAE stages cannot write forecast probability, fair value, SCAE delta, or market prediction authority.

Pseudocode:

```python
def build_scae_ledger(prior, verified_delta_refs):
    if not verified_delta_refs:
        return {
            "forecast_validity_status": "invalid_for_forecast",
            "scoreable_forecast_output": False,
            "scae_evidence_delta_ref_count": 0,
        }
    ledger = apply_scae_delta_refs(prior, verified_delta_refs)
    return {
        "forecast_validity_status": "valid_for_forecast",
        "scoreable_forecast_output": True,
        "scae_evidence_delta_ref_count": len(verified_delta_refs),
        "non_scae_probability_inputs": [],
        "forecast_authority_policy": "scae_only",
        **ledger,
    }


def decision_gate(scae_ledger, runner_mode):
    if scae_ledger["forecast_validity_status"] != "valid_for_forecast":
        return non_actionable("blocked_invalid_scae_forecast")
    if runner_mode == "non_executing_canary":
        return clone_only_prediction_persistence(scae_ledger)
    return require_live_authorization_before_persistence()
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/SCAE
python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_production_handlers
python3 scripts/bin/check_ads_non_scae_authority.py
git diff --check
```

Success criteria:

- SCAE valid forecast requires nonzero verified delta refs.
- SCAE invalid forecast remains fail-closed.
- Decision writes clone-only scoreable prediction only when valid and expected.
- Non-SCAE authority checks pass.
- No temp artifacts remain.

Checklist:

- [ ] Positive SCAE ledger test passes.
- [ ] Zero-delta invalid ledger test passes.
- [ ] Clone-only valid decision persistence test passes.
- [ ] Non-SCAE authority check passes.
- [ ] Temp artifacts and one-off scripts removed.

## Phase 10 - Representative Clone Batch And Closure

Status: planned

Goal: prove the intended current ADS v2 shape across representative clone-only cases after the intelligence-layer fixes.

Implementation:

- Run a representative clone-only batch containing at least:
  - BOI July rate-decrease case;
  - RBNZ July OCR case;
  - one protected-primary binary market;
  - one market-family/sibling-context case.
- Require:
  - zero unexpected failures;
  - at least one `scoreable_success`;
  - blocked cases write no market predictions;
  - active work drains after every run;
  - all handoffs resolve;
  - retry diagnostics remain bounded;
  - live-readiness remains honestly blocked for clone-only/cutover authorization.
- Generate Phase 9 aggregate report and closure report from saved temp reports, then delete temp artifacts.

Pseudocode:

```python
def run_representative_clone_batch(case_specs):
    results = []
    for spec in case_specs:
        with clone_db() as db:
            run = run_strict_canary(db, spec)
            report = build_real_runtime_report(db, run.pipeline_run_id)
            operator = build_operator_review(db, run.pipeline_run_id)
            assert report["active_work"] == {"active_runs": 0, "active_leases": 0}
            assert report["handoff_report"]["ok"] is True
            results.append(classify_phase9_case(report, operator, spec))
    aggregate = build_phase9_representative_batch_report(results)
    assert aggregate["unexpected_failure_count"] == 0
    assert aggregate["scoreable_success_count"] >= 1
    return aggregate
```

Testing suite:

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
python3 scripts/bin/report_ads_phase9_representative_batch.py --help >/dev/null
python3 scripts/bin/report_ads_current_audit_plan_closure.py --help >/dev/null
git diff --check
```

Clone proof:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-recent-run-remediation-phase10.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"

# Run representative cases with existing canary/report CLIs.
# Save per-case reports under "$TMPDIR".
# Build phase9 aggregate and closure reports under "$TMPDIR".
# Do not commit generated outputs.
```

Success criteria:

- Representative batch completes with zero unexpected failures.
- At least one case reaches true `scoreable_success`.
- Non-scoreable cases remain safely blocked with no market prediction write.
- Handoffs resolve, active work drains, and reports show clone-only metadata.
- Live readiness remains blocked unless VM separately authorizes live mutation/cutover.
- No temp artifacts remain.

Checklist:

- [ ] Full decomposer suite passes.
- [ ] Full researcher-swarm suite passes.
- [ ] SCAE suite passes.
- [ ] Full orchestrator suite passes.
- [ ] Authority/script/canonical checks pass.
- [ ] Representative clone batch has at least one `scoreable_success`.
- [ ] Zero unexpected failures.
- [ ] Live-readiness status is honest.
- [ ] Temp artifacts and one-off scripts removed.

## Cross-Phase Bug Accommodation Protocol

If any phase uncovers a new bug:

1. Stop at the smallest safe boundary.
2. Add a dated note to this plan with:
   - observed command or run id;
   - expected behavior;
   - actual behavior;
   - affected phase;
   - safety impact;
   - root-cause hypothesis;
   - plan adjustment;
   - new or updated tests;
   - cleanup requirements.
3. Decide whether the bug blocks the current phase, belongs inside the current phase, belongs in the next phase, or should be deferred.
4. Preserve fail-closed behavior while fixing.
5. Re-run the phase checklist after the adjustment.

Bug note template:

```markdown
### YYYY-MM-DD Phase N Bug Note - Short Title

- Run/command:
- Expected:
- Actual:
- Safety impact:
- Root cause hypothesis:
- Plan adjustment:
- New/updated tests:
- Cleanup requirements:
```

## Final Non-Negotiable Gate

Do not call this remediation complete until all of the following are true:

- Live QDT model execution is separately reported from QDT artifact acceptance.
- Live QDT schema/semantic drift is covered by regression tests.
- QDT repair can fix mechanical schema drift without overriding semantic blockers.
- `source_quality` coverage semantics are deterministic and tested.
- Retrieval sufficiency cannot be satisfied by short, hash-only, claimless, stale, or source-familyless evidence.
- Native research either contributes deterministic-fetchable candidate URLs or emits precise failure diagnostics.
- AMRG relevant sibling/complement candidates are ranked and consumption/ignore status is observable.
- Researchers execute only after certified retrieval.
- Verification emits SCAE-ready deltas before SCAE valid forecasts.
- SCAE valid forecasts require nonzero verified evidence-delta refs.
- Clone-only metadata is truthful in all reports.
- Representative clone batch has at least one true `scoreable_success` and zero unexpected failures.
- Non-scoreable cases write no market prediction.
- All temporary testing artifacts and one-off scripts are deleted.
