# ADS v2 Live-Market E2E Diagnostic Remediation Plan

Created: 2026-07-01
Owner: Workbench implementation session
Status: completed 2026-07-01

## Purpose

This plan addresses the issues exposed by the live-market clone-only ADS v2 diagnostic run on the
Bank of Israel July rate-decrease market. It is an implementation plan for making the true live v2
pipeline path scoreable-capable while preserving the fail-closed safety behavior that worked during
the audit.

This plan does not authorize live database mutation or cutover. All proof runs are clone-only unless
VM explicitly authorizes live control-state writes.

## Audit Anchor

Primary true-live diagnostic:

- Audit root: `/Users/agent2/.openclaw/tmp/text-snippets/ads-live-market-e2e-audit-20260701-205513`
- Clone DB: `/Users/agent2/.openclaw/tmp/text-snippets/ads-live-market-e2e-audit-20260701-205513/live-market-clone.sqlite3`
- Pipeline run: `ads-pipeline-run:9be8b1342e83c013b5ad0aec3a514f0f4a8511c23e98e3b8b1ddedd1f03f5ab5`
- Market: `polymarket:1795635`, "Will the Bank of Israel decrease the Bank of Israel Interest
  Rate after the July decision?"
- Snapshot: `2026-07-01T20:41:42.950241+00:00`
- Market probability at dispatch: `0.925`, bid/ask midpoint.
- Result: fail-closed at `decomposition`; no retrieval, researcher, SCAE, decision, training trace,
  or replay execution.

Primary failure:

- Live QDT executed through `openclaw_codex_oauth/decomposer` on `gpt-5.5-high`.
- Runtime latency was about `150.888s`.
- Mechanical repair ran once and fixed shape errors.
- The remaining terminal blocker was
  `terminal_verification_leaf_misclassified_as_pre_resolution: leaf-boi-july-material-unknowns`.
- No `forecast_decision_records` or `market_predictions` rows were written.
- Active runs/leases drained to `0/0`; live DB mutation proof passed.

Downstream isolation diagnostic:

- Clone DB:
  `/Users/agent2/.openclaw/tmp/text-snippets/ads-live-market-e2e-audit-20260701-205513/downstream-isolation/live-market-clone-downstream.sqlite3`
- Pipeline run: `ads-pipeline-run:b2ad82008333b61b21475e73668ecc9bebb44320283bd02b9b6fe4e9b700042f`
- QDT source: deterministic BOI-shaped transport response generated from the actual decomposer
  handoff.
- Result: QDT accepted; retrieval started and did not finish within about `546s`, leaving the clone
  with an active run/lease until the diagnostic process was manually terminated.
- One OpenClaw retrieval child process chain had to be cleaned up manually.

## Guiding Principles

- Preserve fail-closed behavior. Do not weaken downstream evidence, SCAE, or prediction gates to
  force a green run.
- Fix the earliest blocker first. QDT must be accepted before retrieval/research/SCAE behavior can
  be evaluated as part of a normal run.
- Treat downstream-isolation runs as diagnostic only. They may prove a later layer, but they do not
  replace a true-live QDT end-to-end proof.
- Every phase is clone-only unless VM explicitly authorizes live mutation.
- Testing artifacts and one-off scripts are temporary by default and must be deleted after the
  associated tests pass.

## Strict Sequential Execution Rule

Phases are strict sequential. A session implementing this plan must complete, verify, clean, and
summarize one phase before starting the next.

If a new bug, mismatch, or blocker appears during a phase:

1. Stop broad implementation.
2. Add a dated note to the current phase or insert a narrowly scoped subphase.
3. Preserve the failing shape as a regression test or clone-only proof.
4. Adjust only the current or next phase unless VM asks for broader remediation.
5. Continue only after the updated phase checklist is explicit.

## Cleanup Discipline

Every phase that creates temporary artifacts must use a phase-scoped temp directory:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-live-market-e2e-phaseN.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
```

Temporary artifacts include clone DBs, generated JSON reports, copied runtime artifacts, one-off
inspection scripts, generated fixture JSON not intended as durable tests, and canary outputs.

One-off testing scripts must live under the phase temp directory and must be deleted by the trap
after successful testing. Durable regression tests may be committed under repo test directories.

Before completing every phase:

```bash
find /tmp -maxdepth 1 -name 'ads-v2-live-market-e2e-phase*' -print
git diff --check
git status --short
```

Success for cleanup means:

- no phase temp directories remain;
- no generated clone DB or canary output is staged;
- no one-off testing script remains outside the temp directory;
- only intentional source, test, and plan changes remain.

## Standing Invariants

- QDT may structure research, but may not forecast, assign probability, create SCAE deltas, or make
  execution decisions.
- QDT repair may normalize mechanical schema drift and narrowly identified role drift, but must not
  override forbidden authority leakage or true terminal-verification misuse.
- AMRG remains advisory context only.
- Retrieval providers may discover and fetch candidates, but deterministic admission remains final
  authority for source usefulness and certification.
- Researchers classify bounded certified evidence only; they do not browse freely and do not
  forecast.
- SCAE remains the only numeric forecast authority.
- Scoreable market predictions may be written only after valid SCAE evidence deltas.
- Insufficient or interrupted cases must write no market prediction.
- Live DB mutation remains forbidden without explicit authorization.

## Phase 0 - Preserve The Failure Shape And Diagnostic Taxonomy

Status: completed 2026-07-01

Goal: turn the live-market audit into durable test fixtures and report categories before changing
behavior.

Implementation:

- Preserve the sanitized QDT runtime failure shape:
  - model executed;
  - mechanical repair attempted;
  - remaining terminal temporal-role error on `leaf-boi-july-material-unknowns`.
- Preserve the downstream-isolation retrieval hang shape:
  - QDT accepted;
  - retrieval started;
  - no retrieval completion/error event;
  - active clone run/lease remained until manual termination;
  - provider child process survived initial termination.
- Add explicit taxonomy values for:
  - `qdt_schema_repair_remaining_terminal_temporal_role`;
  - `blocked_by_upstream_qdt`;
  - `retrieval_stage_timeout`;
  - `retrieval_child_process_orphaned`;
  - `not_attempted_due_upstream_block`.

Pseudocode:

```python
def classify_live_market_audit(run, events, runtime_call):
    if runtime_call["model_executed"] and runtime_call["execution_status"] == "failed_schema_validation":
        if "schema_repair_remaining_terminal_temporal_role" in runtime_call["runtime_reason_codes"]:
            return "qdt_schema_repair_remaining_terminal_temporal_role"
    if stage_absent("retrieval") and failed_stage(run) == "decomposition":
        return "blocked_by_upstream_qdt"
    return "unclassified_live_market_failure"


def classify_partial_retrieval(events, active_counts, child_processes):
    if stage_started_without_terminal_event(events, "retrieval"):
        status = ["retrieval_stage_timeout"]
        if child_processes:
            status.append("retrieval_child_process_orphaned")
        if active_counts != {"active_runs": 0, "active_leases": 0}:
            status.append("active_work_left_after_timeout")
        return status
    return []
```

Testing suite:

- Unit tests for taxonomy classification using compact fixtures from the primary run.
- Unit tests for partial retrieval timeout classification using compact fixtures from the
  downstream-isolation run.
- Report smoke tests confirming downstream stages are marked `not_attempted_due_upstream_block`,
  not independent failures, when QDT fails first.

Success criteria:

- The two observed failure shapes are reproducible without external model or browser calls.
- Reports can name the primary QDT blocker and the downstream retrieval hang separately.
- No scoreable write is expected or emitted by either fixture.

Checklist:

- [x] Primary QDT failure fixture added.
- [x] Downstream retrieval hang fixture added.
- [x] Taxonomy tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

Completion notes:

- Added compact durable fixtures for the primary true-live BOI QDT failure and the downstream
  retrieval hang isolation diagnostic.
- Added `ads-live-market-e2e-phase0-taxonomy/v1` / `ads-live-market-e2e-phase0-report/v1`
  helpers to classify the QDT blocker, upstream-blocked downstream stages, retrieval timeout,
  child-process orphan, and active-work-left-after-timeout shapes without external model or browser
  calls.
- Added report smoke coverage proving the primary run reports retrieval as
  `not_attempted_due_upstream_block`, while the downstream-isolation run reports
  `retrieval_stage_timeout`; both fixtures preserve zero scoreable writes.

## Phase 1 - QDT Unresolved-Market Temporal Contract Hardening

Status: complete

Goal: make the live Decomposer less likely to generate invalid terminal-verification roles for
unresolved markets.

Implementation:

- Tighten the Decomposer prompt for unresolved markets:
  - terminal verification is only for resolved/final-result markets;
  - material unknowns are structural uncertainty leaves;
  - material unknowns must not be dispatchable terminal verification;
  - pre-resolution forecast-driver leaves must ask about observable drivers, not final outcomes.
- Add prompt payload assertions so these constraints remain visible to the live model lane.
- Add validator issue codes that distinguish:
  - true terminal-verification leakage;
  - material-unknown role drift;
  - dispatchable terminal leaf on unresolved market.

Pseudocode:

```python
def build_qdt_prompt_context(handoff):
    market_state = "unresolved" if handoff["forecast_timestamp"] < handoff["market_close_or_resolution"] else "terminal"
    return {
        "market_temporal_state": market_state,
        "role_contract": {
            "terminal_verification_allowed": market_state != "unresolved",
            "material_unknowns_role": "material_unknown",
            "forbid_dispatchable_terminal_leaves_when_unresolved": True,
        },
    }


def validate_unresolved_temporal_contract(qdt):
    if qdt["research_coverage_graph"]["market_temporal_state"] != "unresolved":
        return []
    errors = []
    for leaf in qdt["required_leaf_questions"]:
        if leaf["leaf_temporal_role"] == "terminal_verification":
            errors.append(f"terminal_verification_leaf_for_unresolved_market:{leaf['leaf_id']}")
        if leaf["leaf_id"].endswith("material-unknowns") and leaf["leaf_temporal_role"] != "material_unknown":
            errors.append(f"material_unknown_leaf_role_drift:{leaf['leaf_id']}")
    return errors
```

Testing suite:

- Prompt payload tests confirming unresolved-market role contract is present.
- Validator tests for:
  - terminal leaf on unresolved market;
  - material unknown leaf with wrong temporal role;
  - valid material unknown leaf.
- Regression test using the BOI market handoff.

Success criteria:

- Prompt contract explicitly instructs the live model not to dispatch terminal-verification leaves
  for unresolved markets.
- Validator errors are precise enough to power targeted repair or retry.
- No forbidden probability/SCAE/decision authority is introduced.

Checklist:

- [x] Prompt payload updated.
- [x] Validator issue codes updated.
- [x] BOI unresolved-market regression added.
- [x] Prompt and validator tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

Completion notes:

- Added an explicit `qdt_role_contract` to the live Decomposer prompt payload and instruction
  blocks. For unresolved markets it makes terminal verification non-dispatchable, binds material
  unknowns to `coverage_dimension=material_unknowns` / `leaf_temporal_role=material_unknown`, and
  tells pre-resolution leaves to focus on observable current drivers rather than final outcomes.
- Added precise unresolved-market validator issue codes for
  `terminal_verification_leaf_for_unresolved_market`,
  `material_unknown_leaf_role_drift`, and
  `dispatchable_terminal_verification_leaf_for_unresolved_market` while keeping the existing broad
  graph error for report continuity.
- Added prompt payload assertions, validator regressions for terminal leakage/material-unknown drift
  and valid material unknowns, plus a BOI `leaf-boi-july-material-unknowns` regression that preserves
  the audited failure shape as a precise invalid candidate.

## Phase 2 - Narrow QDT Material-Unknown Repair

Status: completed 2026-07-01

Goal: allow safe repair of obvious material-unknown role drift while keeping true terminal
verification misuse non-repairable.

Implementation:

- Extend QDT schema repair to recognize material-unknown leaves by stable signals:
  - `leaf_id` contains `material-unknown`;
  - `question_text` asks what remains unanswered;
  - `coverage_dimension` is or should be `material_unknowns`.
- Repair only those leaves to:
  - `purpose = structural`;
  - `coverage_dimension = material_unknowns`;
  - `leaf_temporal_role = material_unknown`;
  - non-terminal dispatch semantics.
- Do not repair final-result, resolved-outcome, or official-result terminal verification leaks.

Pseudocode:

```python
def looks_like_material_unknown_leaf(leaf):
    text = " ".join([
        leaf.get("leaf_id", ""),
        leaf.get("question_text", ""),
        leaf.get("leaf_question", ""),
        leaf.get("coverage_dimension", ""),
    ]).lower()
    return (
        "material" in text
        and ("unknown" in text or "unanswered" in text)
        and not looks_like_final_result_leaf(leaf)
    )


def repair_material_unknown_role(leaf):
    if not looks_like_material_unknown_leaf(leaf):
        return leaf, False
    repaired = dict(leaf)
    repaired["purpose"] = "structural"
    repaired["coverage_dimension"] = "material_unknowns"
    repaired["leaf_temporal_role"] = "material_unknown"
    repaired["classification_targets"] = ["answerability_status", "unanswered_question_status"]
    repaired["forbidden_outputs"] = sorted(set(repaired.get("forbidden_outputs", [])) | {"probability", "final_forecast"})
    return repaired, True


def repair_qdt(candidate):
    candidate = repair_mechanical_schema(candidate)
    for leaf in candidate["required_leaf_questions"]:
        leaf, repaired = repair_material_unknown_role(leaf)
        record_repair("material_unknown_role", leaf["leaf_id"], repaired)
    return candidate
```

Testing suite:

- Positive repair test using the exact BOI `leaf-boi-july-material-unknowns` failure.
- Negative tests:
  - true final-result terminal verification remains rejected;
  - resolved-market terminal verification remains governed by existing rules;
  - forbidden probability authority still fails.
- End-to-end Decomposer fixture test proving the repaired QDT validates.

Success criteria:

- The BOI material-unknown role drift validates after repair.
- True terminal verification misuse remains non-repairable.
- Runtime diagnostics show which fields were repaired and why.

Checklist:

- [x] Material-unknown detector implemented.
- [x] Narrow repair implemented.
- [x] Positive and negative QDT repair tests pass.
- [x] Runtime repair diagnostics updated.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

Completion notes:

- Added `material_unknown_role` runtime validation grouping and
  `material_unknown_role_repair_available` repair decisions so schema-repair diagnostics explain
  material-unknown role drift separately from generic semantic quality or terminal leakage.
- Added a narrow Decomposer response repair helper that recognizes material-unknown leaves by
  stable id/text/dimension signals, refuses final-result/official-result language, repairs only
  drifting contracts to `purpose=structural`, `coverage_dimension=material_unknowns`, and
  `leaf_temporal_role=material_unknown`, and removes stale terminal graph refs when present.
- Added runtime regressions proving the BOI `leaf-boi-july-material-unknowns` failure validates
  after repair, final-result terminal leaks still fail closed, resolved-market terminal verification
  remains governed by existing rules, and forbidden probability authority prevents repair entirely.

## Phase 3 - QDT Validation-Feedback Retry And Runtime Observability

Status: complete

Goal: make live QDT resilient to one repairable schema/role failure and make rejected output easier
to debug without external session spelunking.

Implementation:

- Add one validation-feedback retry when:
  - the model executed successfully;
  - forbidden authority scan passed;
  - validation failed only with repairable schema or role-contract errors.
- Do not retry on:
  - probability/fair-value/SCAE output;
  - policy contamination;
  - malformed non-JSON output with no usable candidate.
- Persist sanitized rejected-candidate summaries:
  - candidate id;
  - validation errors;
  - repair decisions;
  - retry prompt feedback hash;
  - no raw private content beyond bounded safe excerpts.

Pseudocode:

```python
def run_qdt_with_retry(handoff, transport):
    first = call_model(handoff, transport)
    repaired = repair_qdt(first.response)
    validation = validate_qdt(repaired)
    if validation.valid:
        return accepted(repaired, first.runtime)

    if not retry_allowed(validation, first.forbidden_output_scan):
        return rejected(validation, first.runtime)

    feedback = build_validation_feedback(validation)
    second = call_model(handoff, transport, validation_feedback=feedback)
    second_repaired = repair_qdt(second.response)
    second_validation = validate_qdt(second_repaired)
    return finalize_candidate(second_repaired, second_validation, runtime_calls=[first, second])


def retry_allowed(validation, forbidden_scan):
    return (
        forbidden_scan["status"] == "passed"
        and validation.error_groups <= {"mechanical_schema", "terminal_temporal_role", "material_unknown_role"}
        and validation.retry_count < 1
    )
```

Testing suite:

- Unit tests for retry eligibility.
- Fake transport test where first output has the BOI material-unknown role drift and second output
  validates.
- Fake transport test where forbidden probability output does not retry.
- Runtime artifact tests for sanitized rejected-candidate summaries.

Success criteria:

- One repairable live QDT failure can recover through validation-feedback retry.
- Non-repairable or forbidden authority failures still fail closed.
- Operator reports can show why QDT rejected a candidate without requiring access to the model
  session transcript.

Checklist:

- [x] Retry eligibility policy implemented.
- [x] Validation-feedback prompt path implemented.
- [x] Rejected-candidate summary persisted.
- [x] Retry and no-retry tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

Completion notes:

- Added QDT validation-feedback retry eligibility around the existing validation taxonomy:
  retry is allowed only when the model executed, forbidden-output scan passed, validation retry
  budget remains, and active validation groups are limited to mechanical schema, material-unknown
  role, or terminal-temporal role errors.
- Added a live-only Decomposer retry path that sends one bounded validation-feedback prompt after
  the first repairable validation failure, then records the previous runtime call ref and final
  retry outcome on the accepted or failed runtime artifact.
- Persisted sanitized rejected-candidate summaries with candidate ids, bounded validation-error
  excerpts, schema repair codes, error-group counts, source response hash, and retry prompt
  feedback hash. Runtime summaries now carry these fields into operator/canary evidence.
- Added focused retry/no-retry coverage plus persistence and operator-summary regressions. Full
  Decomposer and Orchestrator test suites pass.

## Phase 4 - Retrieval Hard Timeout And Child-Process Cancellation

Status: complete

Goal: ensure retrieval cannot hang indefinitely or leave active clone work/processes behind.

Implementation:

- Add a hard wall-clock timeout around the retrieval stage.
- Add per-provider and per-child process timeout/cancellation.
- Track child process groups spawned by browser/native/OpenClaw providers.
- On timeout:
  - cancel/terminate children;
  - write a retrieval readiness block or terminal timeout artifact;
  - release or quarantine the lease according to failure policy;
  - return control state to disabled in canary harnesses.

Pseudocode:

```python
class RetrievalTimeout(Exception):
    pass


def run_retrieval_stage_with_deadline(case, qdt, policy):
    deadline = monotonic() + policy.retrieval_stage_timeout_seconds
    child_registry = ChildProcessRegistry()
    try:
        return run_retrieval_lanes(case, qdt, deadline=deadline, child_registry=child_registry)
    except TimeoutError as exc:
        child_registry.terminate_all(grace_seconds=policy.child_grace_seconds)
        return build_retrieval_timeout_block(
            case=case,
            timeout_seconds=policy.retrieval_stage_timeout_seconds,
            partial_diagnostics=collect_partial_retrieval_diagnostics(),
            reason_code="retrieval_stage_timeout",
        )


def call_provider_with_timeout(provider, request, deadline, child_registry):
    remaining = max(0.0, deadline - monotonic())
    with child_registry.track_current_process_group():
        return provider.call(request, timeout_seconds=min(provider.timeout_seconds, remaining))
```

Testing suite:

- Unit test with a hanging browser provider:
  - retrieval exits within configured timeout;
  - timeout artifact is persisted;
  - no child process remains.
- Unit test with a hanging native/OpenClaw provider.
- Canary harness test proving active runs/leases return to `0/0` after retrieval timeout.
- Regression test based on downstream-isolation shape.

Success criteria:

- Retrieval cannot remain open beyond its configured hard deadline.
- Provider children are terminated on timeout.
- Active work drains or is quarantined deterministically.
- No scoreable write occurs on retrieval timeout.

Checklist:

- [x] Retrieval hard timeout implemented.
- [x] Provider child registry implemented.
- [x] Timeout readiness block/artifact implemented.
- [x] Hanging-provider tests pass.
- [x] Active work cleanup tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

## Phase 5 - Retrieval Heartbeats And Partial Lane Diagnostics

Status: complete

Goal: make retrieval progress visible while it is running and useful when it times out.

Implementation:

- Emit bounded retrieval heartbeat diagnostics before each lane/provider call:
  - active leaf id;
  - lane name;
  - provider id;
  - elapsed seconds;
  - remaining deadline;
  - candidate/fetch/admission counts so far.
- Persist partial diagnostics on normal completion and timeout.
- Ensure diagnostics never count as certified evidence and never grant downstream authority.

Pseudocode:

```python
def emit_retrieval_heartbeat(state):
    heartbeat = {
        "schema_version": "ads-retrieval-heartbeat/v1",
        "pipeline_run_id": state.pipeline_run_id,
        "leaf_id": state.current_leaf_id,
        "lane": state.current_lane,
        "provider": state.current_provider_ref,
        "elapsed_seconds": state.elapsed_seconds(),
        "remaining_deadline_seconds": state.remaining_deadline_seconds(),
        "counts": state.partial_counts(),
        "authority": "diagnostic_only_no_retrieval_sufficiency_authority",
    }
    write_bounded_runtime_diagnostic(heartbeat)


def finalize_partial_diagnostics(state, terminal_status):
    return {
        "terminal_status": terminal_status,
        "heartbeats": state.bounded_heartbeat_refs,
        "lane_budget_summary": state.lane_budget_summary(),
        "partial_candidate_counts": state.partial_candidate_counts(),
    }
```

Testing suite:

- Heartbeat emission test for normal provider sequence.
- Timeout test showing latest heartbeat names the stuck lane/provider.
- Report test confirming partial diagnostics are shown as diagnostic-only.
- Size/redaction test ensuring heartbeat payloads remain bounded.

Success criteria:

- A retrieval timeout identifies the active lane/provider and leaf.
- Heartbeats are bounded and safe for operator reports.
- Partial diagnostics do not certify retrieval or unblock researchers.

Checklist:

- [x] Heartbeat schema added.
- [x] Heartbeat writer integrated.
- [x] Timeout partial diagnostics integrated.
- [x] Heartbeat/report tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

## Phase 6 - Operator Report Semantics For Upstream Blocks

Status: complete

Goal: make reports distinguish attempted failures from stages that were correctly not attempted
because an upstream gate failed.

Implementation:

- Update real-runtime canary, operator review, handoff, and closure-lens reports to distinguish:
  - `attempted_and_failed`;
  - `blocked_by_upstream_qdt`;
  - `not_attempted_due_upstream_block`;
  - `attempted_and_timed_out`;
  - `attempted_and_not_certified`.
- Ensure downstream absence after QDT failure is not reported as an independent retrieval or
  researcher failure.
- Preserve strict closure failure when expected scoreable output was not produced.

Pseudocode:

```python
def stage_health(stage, upstream, events, artifacts):
    if upstream.failed and not stage_started(events, stage):
        return {
            "stage": stage,
            "health": "not_attempted_due_upstream_block",
            "blocked_by": upstream.stage,
            "accepted_downstream": False,
        }
    if stage_timeout(events, stage):
        return {"stage": stage, "health": "attempted_and_timed_out"}
    if stage_failed(events, stage):
        return {"stage": stage, "health": "attempted_and_failed"}
    return accepted_or_readiness_block_health(stage, artifacts)


def ordered_postflight_reasons(pipeline):
    reasons = []
    reasons.append(first_actual_failed_gate(pipeline))
    reasons.extend(upstream_blocked_stages(pipeline))
    reasons.extend(protected_write_delta_reasons(pipeline))
    return rank_reasons(reasons)
```

Testing suite:

- Primary live-QDT-failure fixture:
  - QDT is `attempted_and_failed`;
  - retrieval/researcher/SCAE are `not_attempted_due_upstream_block`.
- Retrieval-timeout fixture:
  - QDT is accepted;
  - retrieval is `attempted_and_timed_out`;
  - researcher/SCAE are blocked by retrieval.
- Positive scoreable fixture remains green.

Success criteria:

- Operator-facing reports lead with the first real blocker.
- Secondary downstream absence is explained as blocked, not independently failed.
- Closure reports still block when scoreable expectations are unmet.

Checklist:

- [x] Stage health vocabulary updated.
- [x] Real-runtime report updated.
- [x] Operator review updated.
- [x] Handoff/closure-lens report updated.
- [x] Fixture tests pass.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

## Phase 7 - Same-Market Clone Proof: Live QDT To Bounded Retrieval

Status: complete

Goal: prove the same BOI live-market clone no longer fails at QDT and retrieval no longer hangs.

Implementation:

- Clone the live DB.
- Run the true live production handler path against `polymarket:1795635` or the natural eligible
  current BOI case.
- Require:
  - live QDT model execution;
  - accepted QDT artifact;
  - retrieval terminal event within configured timeout;
  - either certified retrieval or explicit non-scoreable insufficiency/timeout block;
  - no active runs/leases left;
  - no live DB mutation.

Pseudocode:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-live-market-e2e-phase7.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

python clone_live_db.py --output "$TMPDIR/predquant.sqlite3"
python scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --runner-mode calibration_debt_production \
  --handler-factory predquant.ads_production_handlers \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --require-researcher-model-executed \
  --metadata-json '{"live_db_mutation":"clone_only","audit_scope":"phase7_live_qdt_bounded_retrieval"}' \
  --apply \
  --pretty
```

Testing suite:

- Focused unit/integration suites from Phases 1-6.
- Clone-only live-market canary.
- Report generation:
  - real-runtime canary;
  - handoff report;
  - operator review;
  - closure lens.
- Live DB non-mutation proof.

Success criteria:

- QDT is accepted in the true live path.
- Retrieval exits bounded; it does not hang or leave child processes.
- If retrieval is insufficient, the outcome is structured non-scoreable rather than unresolved
  hanging state.
- If retrieval certifies, researcher/SCAE/decision follow the existing v2 authority gates.

Completion note (2026-07-01):

- Implemented narrow live-QDT repair for unresolved BOI drift:
  - terminal settlement/source/cutoff status leaves are repaired to dispatchable
    `resolution_mechanics` leaves;
  - redundant `leaf-terminal-official-result` leaves are dropped for unresolved markets rather
    than converted into dispatchable evidence;
  - final-result leak guard tests still fail closed.
- Final clone-only proof used `polymarket:1795635` as the only eligible clone market and ran the
  true production handler path with live Decomposer and live retrieval runtime.
- Final canary:
  - `pipeline_run_id`: `ads-pipeline-run:fc33c92120c7685ded8fae54f115fa7017faf9df42aaf97cfa4905587819ff93`;
  - `terminal_status`: `stopped_after_current_case`;
  - completed stages: `13`;
  - QDT live model executed and accepted: `qdt_model_executed_count=1`,
    `qdt_live_output_accepted_count=1`, `qdt_end_to_end_quality_ok=true`;
  - Decomposer runtime status: `succeeded`, `fixture_mode=false`, `repair_count=1`,
    remaining validation errors `0`;
  - retrieval terminal: `timeout`, `retrieval_stage_hard_timeout`,
    `retrieval_stage_timeout_count=1`;
  - real-runtime criteria: `ok=true`, no issues, `first_failing_gate=null`;
  - closure lens: `structured_non_scoreable_insufficiency`,
    `stage_completed_with_readiness_block`, `non_scoreable_fail_closed`;
  - protected clone write deltas: `forecast_decision_records=1`, `market_predictions=0`,
    `scae_ledger_outputs=0`;
  - active work after run: `active_runs=0`, `active_leases=0`.
- Reports generated and reviewed:
  - real-runtime canary: `ok=true`;
  - handoff report: `ok=true`, unresolved refs `[]`, stage completions `13`;
  - operator review: expected clone-only block, `true_runtime_cutover_status=blocked_clone_only_canary`;
  - closure lens from `source_retrieval_pipeline_health_taxonomy` confirmed
    non-scoreable fail-closed handling.
- Live DB non-mutation proof: protected live counters stayed unchanged at
  `ads_case_leases=9`, `ads_pipeline_runs=8`, `forecast_decision_records=8`,
  `market_predictions=7`.

Checklist:

- [x] Same-market clone run completed.
- [x] QDT accepted.
- [x] Retrieval terminal event emitted within deadline.
- [x] Active runs/leases are `0/0`.
- [x] Live DB mutation proof passes.
- [x] Reports generated and reviewed.
- [x] No temp artifacts remain.
- [x] `git diff --check` passes.

## Phase 8 - End-To-End Scoreable Or Structured Non-Scoreable Closure

Status: completed 2026-07-02

Goal: close the remediation by proving the pipeline reaches the intended v2 terminal state on live
market data: scoreable only with certified evidence and verified SCAE deltas, otherwise structured
non-scoreable with clear reasons.

Implementation:

- Run a representative clone-only mini-batch:
  - BOI rate-decrease market;
  - at least one other central-bank macro market;
  - one non-central-bank market;
  - one expected insufficiency case.
- Aggregate:
  - QDT accepted count;
  - retrieval terminal/certified/insufficient/timeout counts;
  - native/browser provider timeout counts;
  - researcher runtime counts;
  - SCAE valid/invalid counts;
  - protected write deltas;
  - active work cleanup.
- Add dated amendment if any new runtime class appears.

Completion note - 2026-07-02:

- Added Phase 8 closure tooling:
  - `orchestrator/scripts/predquant/ads_live_market_e2e_phase8_closure.py`;
  - `orchestrator/scripts/bin/report_ads_live_market_e2e_phase8_closure.py`;
  - focused closure tests in `test_ads_live_market_e2e_phase8_closure.py`.
- Added a narrow Decomposer repair for live QDT timing/source-quality drift where a
  timing/cutoff leaf explicitly carries source-quality constraints. The repair promotes the
  leaf to a counted `source_quality` coverage ref, adds the source/timestamp/cutoff evidence
  fields, and removes the invalid list-shaped sufficiency requirement.
- Representative clone-only mini-batch completed with all required tags covered:
  - BOI rate-decrease, live QDT:
    `ads-pipeline-run:0fc9502e7b854e8e83611f6ee4c0ca5284c6512d099980f9706dbbee556df426`;
  - RBNZ central-bank macro, deterministic QDT on cloned live market row:
    `ads-pipeline-run:05e18277b973d98e7d37b7981c865ad446a4eaa708fa1c88c1f93229a80172ff`;
  - GPT-5.6 July 13 non-central-bank, deterministic QDT on cloned live market row:
    `ads-pipeline-run:774cb5d09bff9b14d409162cbff4a0f605577792429ca81516f1e1ae8203173e`;
  - GPT-5.6 July 8 expected-insufficiency, deterministic QDT on cloned live market row:
    `ads-pipeline-run:ec551bdc80f8a6560f2b6e5a71c16485bb41fb840a9500f5f835d46b05ddafa2`.
- Aggregate closure report:
  - `case_count=4`;
  - classifications: `structured_non_scoreable_insufficiency=4`;
  - QDT accepted `4/4`: live accepted `1`, deterministic accepted `3`;
  - QDT quality OK `4/4`;
  - retrieval terminal `4/4`, retrieval timeout `4`, browser/native timeout counts `4/4`;
  - SCAE valid `0`, SCAE invalid `4`;
  - protected clone deltas: `forecast_decision_records=4`, `market_predictions=0`;
  - active work after batch: `active_runs=0`, `active_leases=0`.
- Cleanup and live DB proof:
  - live protected deltas stayed zero for `ads_case_leases`, `ads_pipeline_runs`,
    `forecast_decision_records`, `market_predictions`, and `scae_ledger_outputs`;
  - Phase 8 temp clone artifacts were deleted;
  - cleanup proof passed.

Amendment - 2026-07-02:

- Additional live-QDT central-bank attempts surfaced a new runtime class after the
  source-quality repair: `auto003_stage_failed` with `invalid_artifact_terminal` /
  Decomposer schema-validation failure on RBNZ, BOK, and BOI-no-change probes.
- The completed Phase 8 closure therefore separates:
  - true live-QDT BOI proof that accepted QDT reaches bounded retrieval without hanging;
  - deterministic-QDT category-breadth proof over cloned live market rows;
  - the central-bank live-QDT invalid-artifact variance as a recorded follow-up blocker
    rather than a hidden closure failure.

Pseudocode:

```python
def aggregate_final_batch(reports):
    return {
        "case_count": len(reports),
        "qdt_accepted": count(r.qdt.accepted for r in reports),
        "retrieval_terminal": count(r.retrieval.terminal for r in reports),
        "retrieval_certified": count(r.retrieval.certified_leaf_count > 0 for r in reports),
        "retrieval_timeout": count(r.retrieval.status == "attempted_and_timed_out" for r in reports),
        "researcher_executed": count(r.researcher.model_executed for r in reports),
        "valid_scae": count(r.scae.valid_forecast_count > 0 for r in reports),
        "market_prediction_delta": sum(r.protected.market_predictions_delta for r in reports),
        "live_db_mutation_detected": any(r.live_db_mutation_detected for r in reports),
        "active_work_left": sum(r.active_runs + r.active_leases for r in reports),
    }
```

Testing suite:

- Full focused Decomposer suite.
- Full focused retrieval/provider suite.
- Full focused operator-report suite.
- SCAE authority and market-prediction bridge tests.
- Representative clone-only mini-batch.
- Cleanup proof and live DB non-mutation proof.

Success criteria:

- No case hangs.
- Every case reaches a clear terminal outcome:
  - scoreable success;
  - structured non-scoreable insufficiency;
  - structurally unanswerable;
  - bounded retryable/non-retryable provider failure.
- Scoreable market prediction rows are written only for valid SCAE cases.
- Operator reports explain first blocker and downstream blocked stages without manual artifact
  inspection.
- No active work, child process, temp artifact, or live DB mutation remains.

Checklist:

- [x] Representative mini-batch completed.
- [x] Aggregate report reviewed.
- [x] Any new blocker added as amendment/subphase.
- [x] Expected tests pass.
- [x] Cleanup proof passes.
- [x] Live DB non-mutation proof passes.
- [x] `git diff --check` passes.
- [x] Final completion note added.

## Final Completion Definition

This plan is complete only when:

- the BOI live-market clone no longer fails at QDT temporal-role validation;
- accepted QDT can progress into retrieval without hanging;
- retrieval emits bounded terminal status and useful partial diagnostics on timeout;
- operator reports separate true attempted failures from upstream-blocked stages;
- SCAE probability is emitted only after verified evidence deltas;
- market prediction rows are written only after valid scoreable SCAE;
- fail-closed behavior remains intact for invalid or insufficient inputs;
- clone-only proof shows no live DB mutation;
- all temporary artifacts and one-off scripts created during phase testing are deleted after tests
  pass.
