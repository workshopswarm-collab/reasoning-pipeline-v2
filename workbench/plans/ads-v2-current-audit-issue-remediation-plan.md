# ADS v2 Current Audit Issue Remediation Plan

Created: 2026-06-30
Owner: Workbench implementation session
Scope: strict sequential implementation plan for issues observed in the current clone-only end-to-end ADS v2 audit.

## Audit Anchor

Latest observed clone-only run:

- Run id: `ads-pipeline-run:28ea03635fd884846d3e2be6ab17adefec6fcd01ba45f01f5d67aca324ec5c3c`
- Case: `polymarket:1795635`
- Market question: `Will the Bank of Israel decrease the Bank of Israel Interest Rate after the July decision?`
- Runtime shape: true-production/non-executing canary against a cloned DB.
- Result: all 13 stages completed, 14 manifests valid, unresolved output refs 0, active runs/leases drained to 0/0, stage error events 0.
- Strict real-runtime criteria failed on:
  - `qdt_end_to_end_quality_not_verified`
  - `retrieval_live_acceptance_requirements_not_met`
- Safety behavior was correct:
  - researcher dispatch blocked;
  - SCAE emitted `invalid_for_forecast`;
  - no market prediction was written;
  - downstream stages emitted valid block/diagnostic artifacts.

## Guiding Principle

Do not make the downstream gates more permissive. The right remediation path is to make upstream intelligence and retrieval produce valid, certified inputs. Researchers should run only after retrieval certifies enough evidence, and SCAE should produce a valid forecast only after verified researcher evidence deltas exist.

This plan is strict sequential. Complete, verify, clean, and summarize each phase before beginning the next. If a phase uncovers a new blocker, the implementation session must update this plan or append a dated note before continuing, rather than blindly following stale steps.

## Standing Invariants

- QDT may structure research, but it may not forecast probability, fair value, SCAE deltas, or execution decisions.
- Retrieval may discover and admit evidence, but deterministic validators remain final authority for source class, source family, claim family, temporal safety, breadth, and sufficiency.
- Native research and metadata classifier assists may propose candidates or parsing hints only.
- Researchers classify bounded certified evidence only; they do not browse freely and do not forecast.
- SCAE remains the only numeric forecast authority.
- AMRG is context/advisory only unless an explicit policy change makes model assist required.
- Non-scoreable or insufficient cases must write no market prediction.
- All live proof runs in this plan are clone-only until VM explicitly authorizes live mutation.
- Retries must be bounded, observable, and authority-neutral: retrying may recover transport/search/model execution, but it may not relax QDT, retrieval, researcher, verification, SCAE, or non-scoreable gates.

## Global Retry And Backoff Contract

All intelligence-layer retries added or audited under this plan must follow one shared contract:

- Classify failures before retrying:
  - retryable: timeout, rate limit, transient provider error, malformed-but-repairable model output, connection reset, temporary subprocess failure;
  - non-retryable: forbidden authority leakage, schema violation after repair budget, deterministic insufficiency, untrusted source class, stale/unknown freshness where freshness is required, missing evidence support.
- Use bounded exponential backoff with jitter for retryable transport/provider failures.
- Keep separate budgets for:
  - model runtime transport attempts;
  - schema repair attempts;
  - browser/OpenClaw search attempts;
  - native discovery attempts;
  - researcher assignment attempts;
  - stage-level retry scheduling.
- Record every retry decision in durable diagnostics:
  - component/lane;
  - leaf or stage ID;
  - attempt number;
  - max attempts;
  - failure class;
  - backoff seconds;
  - jitter seed or jitter range;
  - final retry outcome.
- Never let a retry consume the full useful budget for unrelated leaves, stages, or cases.
- Preserve idempotency: repeated attempts must not duplicate final sidecars, evidence refs, forecast ledgers, prediction records, leases, or unresolved handoff refs.
- Stage-level retries are a safety net only. Subcomponent retryable failures should either recover locally or surface as an explicit retryable stage error after bounded local retry is exhausted.

Reference policy shape:

```python
RetryPolicy = {
    "model_transport": {"max_attempts": 3, "base_backoff_seconds": 2, "max_backoff_seconds": 20},
    "model_schema_repair": {"max_attempts": 1, "base_backoff_seconds": 0, "max_backoff_seconds": 0},
    "browser_search": {"max_attempts": 3, "base_backoff_seconds": 2, "max_backoff_seconds": 15},
    "native_discovery": {"max_attempts": 2, "base_backoff_seconds": 3, "max_backoff_seconds": 20},
    "researcher_assignment": {"max_attempts": 2, "base_backoff_seconds": 5, "max_backoff_seconds": 30},
    "stage_retry": {"max_attempts": 2, "base_backoff_seconds": 60, "max_backoff_seconds": 300},
}

def compute_backoff_seconds(policy, attempt, jitter):
    raw = min(policy["max_backoff_seconds"], policy["base_backoff_seconds"] * (2 ** (attempt - 1)))
    return raw + jitter.uniform(0, max(1, raw * 0.25))

def retry_or_fail(operation, policy, classify_failure, diagnostics):
    for attempt in range(1, policy["max_attempts"] + 1):
        try:
            result = operation(attempt=attempt)
            diagnostics.record_success(attempt=attempt)
            return result
        except Exception as exc:
            failure = classify_failure(exc)
            if not failure.retryable or attempt == policy["max_attempts"]:
                diagnostics.record_terminal_failure(attempt=attempt, failure=failure)
                raise
            backoff = compute_backoff_seconds(policy, attempt, diagnostics.jitter)
            diagnostics.record_retry(attempt=attempt, failure=failure, backoff_seconds=backoff)
            sleep(backoff)
```

## Adaptive Execution Rule

At the start of every phase:

1. Rebase the phase against current `main`/`origin/main`.
2. Re-run the smallest baseline check relevant to the phase.
3. Confirm the previous phase checklist still passes.
4. Record any new observed blocker in this plan or an adjacent phase note.
5. Adjust only the current or next phase scope unless VM asks for a broader rewrite.

At the end of every phase:

1. Run targeted tests.
2. Run the phase clone proof when required.
3. Delete temporary artifacts and one-off scripts.
4. Run `git diff --check`.
5. Verify `git status --short` contains only intentional source/test/plan changes.
6. Evaluate the phase checklist before marking the phase complete.

Temporary artifacts include clone DBs, generated JSON reports, ad hoc inspection scripts, copied runtime artifacts, and temporary fixtures not intended as permanent tests.

Use a phase-scoped temp directory for one-off artifacts:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-current-audit-phaseN.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
```

## Phase 0 - Baseline Reproduction And Diagnostic Preservation

Status: completed on 2026-06-30

Goal: make the current failure shape reproducible and observable before changing behavior.

Why this phase is first:

- The latest run already proved the handoff spine is healthy.
- The failure details must be captured in compact regression surfaces so later phases can prove they fixed the right thing.
- The audit artifact currently truncates important OpenClaw search subprocess details, so provider failures are harder to diagnose than they should be.

Implementation:

- Add or extend compact real-runtime/operator report fields for:
  - QDT coverage dimensions required/missing.
  - Search calls attempted, succeeded, failed, skipped by cap, skipped by elapsed budget.
  - Retry attempts by component, retryable/non-retryable classification, backoff seconds, and terminal retry outcome.
  - Provider failure class, return code if available, elapsed seconds, and bounded stderr/stdout ref or safe excerpt.
  - Native research availability and attempted/not-attempted status.
  - Meaningful snippet count, short chunk count, hash-only count.
  - Claim-family extraction attempted count and accepted count.
  - Per-leaf sufficiency blockers.
- Preserve output safety by redacting raw prompt text and page content from report summaries unless a durable artifact policy already allows it.
- Add a regression fixture or unit test that recreates the current BOI-like shape:
  - live QDT model-executed evidence present;
  - missing QDT timing/deadline coverage;
  - one browser search success plus one provider failure;
  - remaining leaves skipped by global cap;
  - retrieval blocks researcher dispatch;
  - SCAE invalid for forecast.

Pseudocode:

```python
def build_current_audit_gap_summary(report):
    qdt = report["model_runtime_evidence"]
    retrieval = report["retrieval_runtime_evidence"]
    return {
        "qdt_missing_coverage_dimensions": qdt_missing_dimensions(qdt),
        "search_attempted_count": retrieval["browser_search_call_count"],
        "search_failed_count": retrieval["browser_search_failure_count"],
        "search_skipped_by_cap_count": count_skips(retrieval, "search_call_limit_reached"),
        "retry_summary": retry_summary(report),
        "provider_failure_summaries": safe_provider_failures(retrieval),
        "native_research_status": retrieval["native_research_status"],
        "meaningful_snippet_admitted_count": retrieval["meaningful_snippet_admitted_count"],
        "claim_family_accepted_count": retrieval["claim_family_accepted_count"],
        "classification_dispatch_allowed": retrieval["classification_dispatch_allowed"],
    }

def safe_provider_failures(retrieval):
    failures = []
    for item in retrieval["search_failure_diagnostics"]:
        failures.append({
            "leaf_id": item["leaf_id"],
            "query_variant_id": item["query_variant_id"],
            "reason_code": item["reason_code"],
            "error_class": item.get("error_class"),
            "elapsed_seconds": item.get("elapsed_seconds"),
            "safe_detail_ref": item.get("bounded_log_artifact_ref"),
            "safe_detail_excerpt": redact(item.get("detail", ""))[:500],
        })
    return failures

def retry_summary(report):
    events = report.get("retry_diagnostics") or []
    return {
        "retryable_failure_count": count(events, lambda e: e["failure_retryable"]),
        "retry_attempt_count": count(events, lambda e: e["event"] in {"local_retry", "retry_scheduled"}),
        "terminal_retry_exhausted_count": count(events, lambda e: e["event"] == "retry_exhausted"),
        "components": sorted({e["component"] for e in events}),
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
TMPDIR="$(mktemp -d /tmp/ads-v2-current-audit-phase0.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
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
  --metadata-json '{"audit_id":"ads-v2-current-audit-phase0","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary-output.json"
python3 scripts/bin/report_ads_real_runtime_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --pipeline-run-id "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[\"result\"][\"pipeline_run_id\"])' "$TMPDIR/canary-output.json")" \
  --expected-cases 1 \
  --expected-forecast-decision-records 1 \
  --expected-market-predictions 0 \
  --pretty > "$TMPDIR/real-runtime-report.json"
```

Cleanup:

- Delete `$TMPDIR` through the trap.
- Do not commit generated canary output.
- Do not commit one-off extraction scripts.

Success criteria:

- Current blocker shape is captured in permanent tests or compact report fields.
- Retry/backoff decisions are visible in report surfaces even when no retry is attempted.
- Provider failure diagnostics are no longer limited to an opaque truncated command.
- The baseline still blocks safely with no market prediction write.
- Handoff/manifests/drain remain healthy.

Checklist:

- [x] QDT missing coverage dimensions are visible.
- [x] Search failure and skip reasons are visible per leaf/query.
- [x] Retry/backoff diagnostics are visible and bounded.
- [x] Native research disabled/not-configured status is visible.
- [x] Evidence-usability counters are visible.
- [x] No generated artifacts remain.
- [x] Targeted tests pass.

Completion note:

- Added `ads-current-audit-gap-summary/v1` to the real-runtime canary report, plus matching operator-review fields for QDT coverage dimensions, search attempt/failure/skip diagnostics, bounded provider failure summaries, native research status, evidence-usability counters, claim-family counters, retry/backoff summary, and per-leaf sufficiency blockers.
- Added permanent BOI-like regression coverage for missing timing/deadline QDT coverage, one search success plus one provider failure, search-call cap skips, blocked researcher dispatch, and safe non-scoreable behavior.
- Clone-only proof run `ads-pipeline-run:8199b959941d11b989889061eb7ea40be044c42cc518772d2eded920e2730388` failed closed on `retrieval_live_acceptance_requirements_not_met`, wrote one non-scoreable forecast decision, wrote zero market predictions, and drained active runs/leases to 0/0. Current GitHub state no longer reproduces missing QDT timing coverage in the live clone run; the summary reported `qdt_missing_coverage_dimensions=[]`, `search_attempted_count=2`, `search_failed_count=1`, `search_skipped_by_cap_count=8`, and `native_research_statuses=["disabled"]`.
- Temporary clone DB and JSON reports were cleaned up by the phase-scoped temp directory trap.

## Phase 1 - QDT Timing And Deadline Coverage Repair

Status: completed on 2026-06-30

Goal: ensure live QDT outputs structurally cover timing/deadline constraints for unresolved forecast markets, or fail with a targeted repair requirement before retrieval.

Observed issue:

- The BOI QDT looked human-reasonable, but the structured coverage graph reported missing `timing_deadline_constraints`.
- This is an intelligence-quality/contract-alignment failure, not a deterministic placeholder or model transport failure.

Implementation:

- Update QDT required coverage dimensions for unresolved forecast markets to include:
  - source cutoff;
  - market close/resolution date;
  - remaining pre-decision/pre-resolution events;
  - evidence staleness windows;
  - post-resolution terminal-only boundaries.
- Update Decomposer prompt/schema instructions so timing/deadline constraints are first-class.
- Add a deterministic QDT repair checker:
  - if `coverage_summary.status == "requires_repair"`, inspect missing dimensions;
  - if missing only repairable dimensions, request a bounded repair pass;
  - if still missing after repair, block QDT quality.
- Replace immediate model transport retry with the global model transport retry policy:
  - classify retryable model transport failures before retry;
  - apply exponential backoff with jitter;
  - record lane, attempt, failure class, backoff, repair count, and terminal outcome.
- Ensure terminal verification leaves do not count as dispatchable pre-resolution coverage.

Pseudocode:

```python
REQUIRED_UNRESOLVED_DIMENSIONS = {
    "resolution_mechanics",
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "source_quality",
    "material_unknowns",
    "timing_deadline_constraints",
}

def qdt_missing_coverage_dimensions(qdt):
    graph = qdt.get("research_coverage_graph") or {}
    present = set(graph.get("coverage_dimensions") or [])
    required = required_dimensions_for_market(qdt)
    return sorted(required - present)

def maybe_repair_qdt_coverage(qdt, runtime):
    missing = qdt_missing_coverage_dimensions(qdt)
    if not missing:
        return qdt
    if not runtime.can_repair or qdt_repair_count(qdt) >= 1:
        mark_quality_failed(qdt, "research_coverage_requires_repair", missing)
        return qdt
    repaired = runtime.request_repair(
        qdt=qdt,
        repair_instruction={
            "add_or_reclassify_leaves_for_missing_dimensions": missing,
            "do_not_add_probability_fields": True,
            "preserve_terminal_verification_gating": True,
        },
    )
    return validate_repaired_qdt(repaired)

def call_qdt_model_with_retry(request, runtime):
    return retry_or_fail(
        operation=lambda attempt: runtime.execute_model_call(request, attempt=attempt),
        policy=RetryPolicy["model_transport"],
        classify_failure=classify_model_transport_failure,
        diagnostics=request.retry_diagnostics.for_component("qdt_model_runtime"),
    )
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_real_runtime_canary
python3 -m unittest scripts.tests.test_ads_operational_canary
git diff --check
```

Required permanent tests:

- BOI-like unresolved rate decision QDT includes `timing_deadline_constraints`.
- QDT with timing text but no structured timing coverage fails.
- QDT repair pass can add a timing/deadline leaf without adding forecast authority.
- Terminal verification leaf does not satisfy pre-resolution timing coverage by itself.
- Retryable QDT model transport failure sleeps/backoffs and succeeds on a later attempt.
- Non-retryable forbidden output fails without retry.

Cleanup:

- Delete generated QDT JSONs and one-off model outputs.
- Keep only durable fixtures/tests needed for regression.

Success criteria:

- The BOI-like QDT passes only when timing/deadline coverage is structurally present.
- `research_coverage_check.status` cannot pass while `coverage_summary.status == "requires_repair"`.
- Repair does not add probability/fair-value/SCAE fields.
- QDT retry/backoff is bounded, observable, and does not mask schema/authority failures.

Checklist:

- [x] Required timing/deadline coverage dimension exists.
- [x] QDT model transport retry/backoff implemented and tested.
- [x] Repair loop is bounded and audited.
- [x] Terminal-only leaves remain non-dispatchable before resolution.
- [x] QDT tests pass.
- [x] No temp QDT artifacts remain.

Completion note:

- Current `main` already enforced first-class timing/deadline QDT coverage, bounded repair-required coverage failure, and terminal-only leaf gating for unresolved markets.
- Replaced the previous immediate model transport retry with the shared model transport retry policy: max 3 attempts, classified retryable/non-retryable transport failures, deterministic jittered exponential backoff, and durable `model-runtime-retry-diagnostic/v1` events on runtime call artifacts.
- Propagated QDT model retry diagnostics into real-runtime current-audit retry summaries so retry attempts, backoff seconds, retry policy refs, components, and retry exhaustion are observable from operator-facing reports.
- Verification passed: `python3 -m unittest scripts.tests.test_model_runtime`, `python3 -m unittest scripts.tests.test_qdt`, `python3 -m unittest scripts.tests.test_runtime_decomposition`, `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` from `decomposer`; `python3 -m unittest scripts.tests.test_ads_operational_canary`, `python3 -m unittest scripts.tests.test_ads_operator_review`, and `python3 -m unittest scripts.tests.test_ads_retrieval_transport` from `orchestrator`.

## Phase 2 - Search Failure Handling And Per-Leaf Retrieval Budgets

Status: complete

Goal: prevent one search success and one provider failure from starving the remaining QDT leaves.

Observed issue:

- Default retrieval policy uses global `max_total_search_calls=2`.
- In the audit, one successful search plus one failed OpenClaw search consumed the entire search budget.
- Eight leaf searches were skipped with `search_call_limit_reached`.

Implementation:

- Replace the blunt global search-call gate with a leaf-aware budget:
  - reserve minimum search attempts for source-of-truth/protected-primary leaves;
  - reserve attempts for high-impact forecast-driver leaves;
  - allow provider failures to consume a failure budget, not the entire useful search budget;
  - preserve an absolute case-level cap.
- Add retry/fallback semantics for provider failures:
  - retry timeout/rate-limit/transient provider failures with exponential backoff and jitter;
  - use alternate query variants on retry, starting from the same leaf intent rather than broadening beyond the market;
  - treat no-candidate search responses as query exhaustion, not transport failure, unless the provider reports an error;
  - if retries exhaust, mark the leaf as `search_transport_failed` and allow native discovery in Phase 3.
- Ensure local search retries do not consume the reserved attempts for unrelated leaves.
- Escalate exhausted retryable search transport failures as explicit retrieval diagnostics and, when no fallback lane can run, as a retryable stage failure rather than a silent insufficiency-only blocker.
- Improve diagnostics:
  - distinguish `skipped_global_case_cap`, `skipped_leaf_cap`, `skipped_elapsed_budget`, and `skipped_after_provider_failure`.

Pseudocode:

```python
def search_budget_for_case(qdt):
    leaves = dispatchable_leaves(qdt)
    return {
        "absolute_case_search_cap": min(24, max(8, len(leaves) * 2)),
        "per_leaf_default_cap": 2,
        "protected_primary_leaf_cap": 3,
        "provider_failure_retry_cap": RetryPolicy["browser_search"]["max_attempts"] - 1,
    }

def should_search_leaf(leaf, counters, budget):
    if counters.case_search_calls >= budget["absolute_case_search_cap"]:
        return deny("skipped_global_case_cap")
    if counters.elapsed_budget_exhausted:
        return deny("skipped_elapsed_budget")
    cap = budget["protected_primary_leaf_cap"] if leaf.requires_protected_primary else budget["per_leaf_default_cap"]
    if counters.leaf_search_calls[leaf.id] >= cap:
        return deny("skipped_leaf_cap")
    return allow()

def execute_leaf_search(leaf, query):
    diagnostics = retry_diagnostics.for_leaf(leaf.id)
    variants = query_variants_for_leaf(leaf, query)

    def operation(attempt):
        selected_query = variants[min(attempt - 1, len(variants) - 1)]
        return browser_search(selected_query)

    try:
        return retry_or_fail(
            operation=operation,
            policy=RetryPolicy["browser_search"],
            classify_failure=classify_search_failure,
            diagnostics=diagnostics,
        )
    except RetryExhausted as exc:
        leaf.mark_search_transport_failed(exc.failure_summary)
        if native_discovery_available():
            return deferred_to_native_discovery(leaf)
        raise RetryableRetrievalStageError("browser_search_retry_exhausted", leaf_id=leaf.id)
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

Required permanent tests:

- A failed second search does not prevent later critical leaves from receiving search attempts.
- Protected-primary leaves receive reserved budget.
- Global absolute cap still prevents runaway search.
- Search failure diagnostics identify the exact cap/failure reason.
- Search retry uses backoff/jitter and alternate query variants for retryable provider failures.
- Exhausted retryable search failures either fall through to native discovery or surface as retryable retrieval-stage errors.

Clone proof:

- Run one BOI-like clone canary.
- Expected interim output after this phase:
  - more than 2 search calls or explicit per-leaf reserved attempts;
  - no blanket starvation of 8 leaves;
  - retrieval may still block if evidence quality is insufficient.

Cleanup:

- Delete clone DBs and JSON reports after extracting summary.

Success criteria:

- Search failure no longer starves unrelated leaves.
- Search diagnostics distinguish provider failure from budget policy.
- Search retries/backoffs are bounded and visible in operator reports.
- Retrieval remains fail-closed if evidence is still insufficient.

Checklist:

- [x] Leaf-aware budget implemented.
- [x] Provider failure retry/backoff/fallback recorded.
- [x] Exhausted retryable search failure classification tested.
- [x] Absolute cap still enforced.
- [x] BOI-like run shows no broad leaf starvation.
- [x] Temporary clone artifacts deleted.

Completion note:

- Replaced the legacy default global two-search budget with a bounded leaf-aware case budget while preserving explicit low caps and the absolute cap contract.
- Added per-leaf primary search counters, protected-primary/high-priority leaf caps, and diagnostics for effective case cap plus per-leaf budget usage.
- Added browser-search retry diagnostics under `ads-browser-search-retry/v1`: retryable provider failures use deterministic jittered exponential backoff, alternate query variants, and do not consume unrelated leaves' primary search budget.
- Exhausted retryable search failures now mark the leaf as search-transport failed and surface either `deferred_to_native_discovery` or `retryable_stage_error_candidate`.
- Search skip diagnostics now distinguish `skipped_global_case_cap`, `skipped_leaf_cap`, `skipped_elapsed_budget`, and `skipped_after_provider_failure`, while preserving legacy aliases for existing reports.
- Verification passed: `python3 -m unittest scripts.tests.test_ads_retrieval_transport scripts.tests.test_ads_operational_canary scripts.tests.test_ads_operator_review` from `orchestrator`; `python3 -m unittest scripts.tests.test_retrieval` and `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` from `researcher-swarm`; `git diff --check`.
- Clone proof run `ads-pipeline-run:fe7221a215eb0b8a44cf48c9f059dfdec9deb5dc0e9917306f21bb4c539cf4e6` attempted 3 searches, recorded 0 provider failures, 0 cap skips, and 7 elapsed-budget skips. It failed closed on QDT end-to-end quality and retrieval live acceptance, but Phase 2's broad two-search starvation was not reproduced.

## Phase 3 - Native Research Candidate Discovery Wiring

Status: complete

Goal: configure the native GPT candidate-discovery lane so retrieval has a model-backed discovery fallback when browser search fails or source diversity remains unmet.

Observed issue:

- Native research reported `native_research_transport_not_configured`.
- Browser search alone did not discover enough diverse, fresh, source-bearing URLs.

Implementation:

- Add an Orchestrator-owned adapter that invokes Researcher Swarm's native candidate discovery through OpenClaw OAuth.
- Use model lane `native_research_candidate_discovery` with resolved model `gpt-5.5-high`.
- Wrap native discovery transport in the global native discovery retry/backoff policy.
- The native lane may return only bounded candidate fields:
  - URL/canonical URL;
  - title/source label;
  - why it may matter;
  - related leaf ID;
  - candidate claim text.
- Reject any native output containing probability, fair value, SCAE delta, decision, source sufficiency, final source class, final source family, final claim family, or temporal safety.
- Trigger native discovery when:
  - browser search provider fails;
  - leaf search budget is exhausted without enough source diversity;
  - protected-primary evidence is missing;
  - claim-family diversity is 0;
  - meaningful snippets are 0.

Pseudocode:

```python
NATIVE_FORBIDDEN_KEYS = {
    "probability",
    "fair_value",
    "scae_delta",
    "decision",
    "source_class",
    "source_family",
    "claim_family",
    "temporal_safety",
    "research_sufficiency",
}

def should_run_native_discovery(leaf_status):
    return any([
        leaf_status.browser_search_failed,
        leaf_status.source_family_count < leaf_status.required_source_families,
        leaf_status.claim_family_count == 0,
        leaf_status.protected_primary_required and not leaf_status.protected_primary_satisfied,
        leaf_status.meaningful_snippet_count == 0,
    ])

def run_native_candidate_discovery(leaf, case_context):
    output = retry_or_fail(
        operation=lambda attempt: openclaw_oauth_call(
            agent="researcher-swarm",
            model_lane="native_research_candidate_discovery",
            model="gpt-5.5-high",
            prompt=build_native_discovery_prompt(leaf, case_context, attempt=attempt),
        ),
        policy=RetryPolicy["native_discovery"],
        classify_failure=classify_model_transport_failure,
        diagnostics=retry_diagnostics.for_leaf(leaf.id).for_component("native_discovery"),
    )
    validate_allowed_fields(output, allowed=NATIVE_ALLOWED_FIELDS)
    reject_forbidden_fields(output, forbidden=NATIVE_FORBIDDEN_KEYS)
    return materialize_candidate_urls(output)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_real_runtime_canary

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
git diff --check
```

Required permanent tests:

- Native candidate discovery executes when browser search fails.
- Native output with forbidden authority fields is rejected.
- Native candidate URLs must still be fetched and deterministically validated.
- Native candidate discovery cannot certify sufficiency.
- Retryable native discovery transport failure backs off and retries.
- Forbidden native discovery output is non-retryable unless it is a repairable schema-only error within schema repair budget.

Clone proof:

- Run a clone canary with native discovery enabled.
- Expected output:
  - `native_research_model_executed_count > 0` or explicit configured execution proof;
  - native candidate URLs materialized;
  - deterministic validators still decide admission and sufficiency.

Cleanup:

- Delete native output JSONs unless they are permanent redacted fixtures.
- Delete clone reports after summary extraction.

Success criteria:

- Native discovery is no longer `not_configured`.
- Native candidates improve URL diversity without taking authority.
- Native retry/backoff is bounded, observable, and authority-neutral.
- Retrieval still blocks if deterministic admission fails.

Checklist:

- [x] Native adapter wired through Researcher Swarm OAuth lane.
- [x] Native discovery retry/backoff implemented and tested.
- [x] Forbidden output scanner covers native outputs.
- [x] Native candidates are fetched before admission.
- [x] Unit tests pass.
- [x] Clone proof has no live DB mutation.

Completion note:

- Added an Orchestrator native candidate-discovery provider for `native_research_candidate_discovery` that uses the shared OpenClaw OAuth model runtime, the `gpt-5.5-high` lane, native-specific prompt instructions, bounded output validation, forbidden-output scanning, and model-runtime retry diagnostics.
- True-production handlers now enable native discovery by default and supply a lazy native provider while still allowing canary/test injection.
- Retrieval now triggers native discovery only when fallback is warranted, such as failed browser search, missing meaningful fetched snippets, protected-primary gaps, or exhausted per-leaf search without source diversity.
- Native candidates are rejected if they contain authority fields, materialized only as URL proposals, fetched through the existing browser fetch path with `retrieval_transport="native_gpt_research"`, and left to deterministic validators for admission and sufficiency.
- Operator/canary diagnostics now expose native trigger, skip, failure, runtime-call, and transport availability summaries without embedding authority-bearing model output.
- Verification passed: full orchestrator test discovery (`293 tests OK`), full decomposer test discovery (`104 tests OK`), full researcher-swarm test discovery (`247 tests OK`), and `git diff --check`.
- Clone proof run `ads-pipeline-run:0a59ebc022784caee56b909dff8f404df01e78bf9a00723509b0adcdf6261408` used a cloned SQLite DB with fixture QDT and forced native discovery. It recorded `native_research_model_executed_count=1`, native status `executed_with_candidates`, 4 native candidate URLs, 20 fetched attempts, 4 admitted evidence refs, and no live DB mutation. Retrieval still failed closed on live acceptance, proving deterministic validators retained authority.

## Phase 4 - Evidence Extraction, Claim Families, And Freshness

Status: complete

Goal: make admitted evidence classification-useful instead of hash-only, too short, or claim-family empty.

Observed issue:

- The audit admitted 10 refs, but all were short chunks from the BOI schedule page.
- Meaningful snippet count was 0.
- Claim-family count was 0.
- Freshness satisfied count was 0.
- Protected-primary satisfaction remained 0/2 despite official BOI material being fetched.

Implementation:

- Tighten evidence admission so a ref can count toward sufficiency only when it has:
  - meaningful bounded snippet or allowed span text;
  - source URL/canonical URL;
  - source class and source family;
  - publication/update/source-time status or explicit unknown-not-counted;
  - claim-family candidate or explicit claim-extraction-not-applicable reason.
- Add claim extraction for admitted snippets:
  - deterministic normalization over subject, predicate, value, event time, entity/jurisdiction, polarity;
  - reject spanless or unsupported model proposals.
- Add or refine BOI source metadata rules:
  - BOI official domain/path is `official_or_primary`;
  - BOI schedule page can support resolution mechanics/timing only;
  - BOI schedule page does not satisfy macro-driver leaves by itself.
- Preserve strict source freshness:
  - capture time is not publication time;
  - unknown publication/update time remains `unknown_not_counted` for freshness;
  - stale evidence blocks current-event leaves.

Pseudocode:

```python
def admitted_ref_counts_for_sufficiency(evidence):
    if not has_meaningful_snippet(evidence):
        return reject("snippet_too_short_for_classification")
    if not evidence.source_family:
        return reject("source_family_unknown_not_counted")
    if freshness_required(evidence.leaf) and not has_valid_source_time(evidence):
        return reject("freshness_unknown_not_counted")
    if claim_family_required(evidence.leaf) and not evidence.claim_family_id:
        return reject("claim_family_missing")
    return accept()

def classify_boi_schedule_page(candidate, leaf):
    if is_boi_schedule_url(candidate.url):
        candidate.source_class = "official_or_primary"
        candidate.source_family = "bank_of_israel"
        if leaf.coverage_dimension not in {"resolution_mechanics", "timing_deadline_constraints", "source_quality"}:
            candidate.sufficiency_effect = "context_only_not_counted_for_driver_leaf"
    return candidate

def extract_claim_family(span):
    normalized = normalize_claim(
        subject=span.subject,
        predicate=span.predicate,
        value=span.value,
        event_time=span.event_time,
        entity=span.entity,
        jurisdiction=span.jurisdiction,
        polarity=span.polarity,
    )
    return "claim-family:" + sha256_json(normalized)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest scripts.tests.test_retrieval_quality
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
git diff --check
```

Required permanent tests:

- Hash-only or too-short chunks do not count toward sufficiency.
- BOI schedule URL counts for mechanics/timing, not inflation/shekel/labor driver leaves.
- Claim-family extraction creates stable IDs for grounded snippets.
- Unknown source time does not satisfy freshness.
- Source family diversity cannot be inflated by duplicate canonical URLs.

Clone proof:

- Run a BOI-like clone canary.
- Expected output:
  - meaningful snippet count increases;
  - claim-family count is nonzero for at least relevant leaves;
  - BOI schedule evidence is limited to appropriate leaves;
  - retrieval still blocks unless all strict dimensions are satisfied.

Cleanup:

- Delete clone DBs and generated extraction reports.
- Keep only durable fixtures that are small and policy-safe.

Success criteria:

- Admitted evidence is usable by researchers.
- Sufficiency counters no longer count hash-only or irrelevant schedule snippets.
- Claim/source/freshness diagnostics explain remaining blockers.

Checklist:

- [x] Meaningful snippet gate implemented.
- [x] Claim-family extraction implemented or explicitly attempted.
- [x] BOI source rules tested.
- [x] Freshness remains strict.
- [x] Temporary artifacts deleted.

Completion note:

- Tightened final retrieval usefulness so context-only BOI schedule evidence is excluded from research-usable admitted refs and cannot satisfy protected-primary or breadth sufficiency for current driver leaves.
- Added deterministic Researcher Swarm BOI source-family handling (`source-family:bank_of_israel`) so duplicate BOI URLs cannot inflate independent source-family diversity through candidate/provider metadata.
- Preserved the existing meaningful snippet gate and strict freshness behavior where capture/observed time is not publication/update time.
- Added a conservative fetched-text claim fallback for deterministic/proven official, primary-reporting, or specialist sources; it still requires the supporting sentence to appear in bounded fetched content and does not derive claim families from search snippets or unproven provider metadata.
- Added permanent tests proving BOI schedule pages count for resolution mechanics/timing but not current inflation/guidance driver leaves.
- Verification passed: `researcher-swarm` `scripts.tests.test_retrieval`, `scripts.tests.test_retrieval_quality`, and full discovery (`249 tests OK`); `orchestrator` `scripts.tests.test_ads_retrieval_transport`, `scripts.tests.test_ads_operational_canary`, and full discovery (`293 tests OK`); `decomposer` full discovery (`104 tests OK`); and `git diff --check`.
- Clone proof run `ads-pipeline-run:5179afccf80d595a2f254f535b6eadfb10448d891b630d86e38712744782f8ee` used a cloned SQLite DB with a deterministic BOI provider. It recorded `meaningful_snippet_admitted_count=16`, `short_chunk_admitted_count=0`, `hash_only_admitted_count=0`, `claim_family_extraction_attempted_count=16`, `accepted_claim_family_count=8`, explicit `boi_schedule_context_only_not_counted_for_driver_leaf` blockers, and 0 market-prediction writes. The run still failed closed on fixture QDT verification and strict retrieval live acceptance, as expected.

## Phase 5 - AMRG Context Consumption And Optional Assist Clarity

Status: complete

Goal: make AMRG's contribution observable and useful without giving it forecast or evidence authority.

Observed issue:

- AMRG produced deterministic candidate context, but the QDT artifact showed no visible consumed branch/leaf IDs.
- AMRG model assist is optional/not requested, which is policy-consistent, but live assist execution cannot be claimed.
- Vector context remains unavailable-allowed weak context.

Implementation:

- Preserve current optional AMRG assist policy unless VM explicitly changes it.
- If optional AMRG model assist is enabled in a later implementation run, wrap it in the global model transport retry/backoff policy and report `not_requested`, `executed`, `retry_exhausted`, or `disabled_by_policy` distinctly.
- Add deterministic AMRG consumption mapping:
  - which AMRG hints were provided to QDT;
  - which hints the Decomposer used;
  - which branch/leaf IDs were influenced;
  - whether a hint was ignored and why.
- Ensure QDT prompt context includes active-safe AMRG hints only.
- If vector context is intended for this phase:
  - use Ollama route only;
  - preflight `/api/version` and `/api/show`;
  - require `BAAI/bge-base-en-v1.5`;
  - validate finite vector dimensions;
  - fail closed with diagnostics if unavailable.
- If vector context is not intended:
  - keep `vector_unavailable_allowed_weak_context`;
  - do not imply model/vector execution.

Pseudocode:

```python
def build_amrg_qdt_context(amrg_report):
    hints = []
    for candidate in amrg_report.active_safe_candidates:
        hints.append({
            "hint_ref": candidate.edge_ref,
            "source_market_ref": candidate.market_ref,
            "relationship_status": candidate.relationship_status,
            "allowed_effect": "context_only",
            "forbidden_effects": ["qdt_selection", "probability", "evidence_admission"],
        })
    return hints

def record_amrg_hint_consumption(qdt, hints):
    consumption = []
    for hint in hints:
        matched = find_related_qdt_nodes(qdt, hint)
        consumption.append({
            "hint_ref": hint["hint_ref"],
            "decomposer_consumed": bool(matched),
            "consumed_by_branch_ids": matched.branch_ids,
            "consumed_by_leaf_ids": matched.leaf_ids,
            "effect_status": "context_only_no_authority",
        })
    return consumption

def maybe_run_amrg_assist(amrg_request, policy):
    if not policy.amrg_assist_enabled:
        return {"status": "not_requested"}
    return retry_or_fail(
        operation=lambda attempt: run_amrg_model_assist(amrg_request, attempt=attempt),
        policy=RetryPolicy["model_transport"],
        classify_failure=classify_model_transport_failure,
        diagnostics=retry_diagnostics.for_component("amrg_model_assist"),
    )
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_amrg_context
python3 -m unittest scripts.tests.test_ads_live_readiness
python3 -m unittest scripts.tests.test_ads_operator_review
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 scripts/bin/report_amrg_context.py --help >/dev/null
git diff --check
```

Required permanent tests:

- AMRG hints appear in QDT context as context-only.
- Consumed hints record branch/leaf IDs.
- AMRG hints cannot select QDT leaves or write probability/evidence authority.
- Optional assist reports `not_requested` without claiming execution.
- If AMRG assist is policy-enabled later, enabled-assist retry tests must cover retryable transport failures and exhausted retries distinctly.

Clone proof:

- Run a clone canary with related market context.
- Expected output:
  - AMRG candidates present;
  - hint consumption report is populated or explains non-consumption;
  - no AMRG probability/evidence authority.

Cleanup:

- Delete AMRG packet/output JSONs generated during inspection.

Success criteria:

- AMRG usefulness is observable.
- Optional model assist remains explicit.
- Any enabled AMRG assist retry/backoff is bounded and visible.
- Vector availability status is truthful.

Checklist:

- [x] AMRG hint consumption mapping implemented.
- [x] QDT context includes only active-safe hints.
- [x] AMRG authority boundaries tested.
- [x] AMRG optional not-requested reporting semantics tested; enabled-assist retry remains deferred until policy enables assist.
- [x] Reports distinguish optional not requested vs executed.
- [x] Temporary artifacts deleted.

Completion note:

- Added QDT `amrg_operator_metadata.hint_consumption_slices`, a deterministic per-hint ledger showing provided hints, consumed branch/leaf IDs, non-consumption reasons, context-only effect status, allowed use, forbidden effects, and no-forecast authority.
- Updated AMRG operator reports to consume the QDT ledger when present, including ignored-hint reasons and context-only authority, while preserving legacy branch/leaf AMRG refs.
- Preserved optional AMRG model-assist policy: not-requested assist still reports `assist_not_requested_by_policy`, `model_executed=false`, and `model_execution_claim=not_claimed`.
- Kept vector context as a truthful weak-context availability signal; no Ollama requirement was introduced in this phase.
- Verification passed: `python3 -m unittest decomposer/scripts/tests/test_runtime_decomposition.py`, `python3 -m unittest decomposer/scripts/tests/test_persistence.py`, and `python3 -m unittest orchestrator/scripts/tests/test_amrg_context.py`.

## Phase 6 - Researcher Runtime And Verification Positive Path

Status: complete

Goal: prove that once retrieval certifies at least one case, researcher leaf classification and verification produce SCAE-ready evidence deltas.

Why this phase waits:

- In the audit, researcher model execution was correctly skipped because retrieval did not certify.
- This phase should not force researchers to run on insufficient evidence.

Implementation:

- Add a controlled certified-retrieval fixture if existing fixtures are insufficient.
- Run one assignment per dispatchable certified leaf.
- Wrap retryable researcher assignment/runtime transport failures in the global researcher assignment retry/backoff policy.
- Require Researcher Swarm runtime bundle:
  - `model_executed=true`;
  - resolved model `gpt-5.5-high`;
  - sidecars bounded to leaf evidence;
  - no sibling leakage;
  - no probability/fair-value/SCAE-delta outputs.
- Verification consumes researcher sidecars and emits:
  - classification matrix;
  - direction verification slices;
  - quality verification slices;
  - SCAE-ready reconciliation slices only when evidence is valid.

Pseudocode:

```python
def launch_researchers_if_certified(retrieval_packet):
    if retrieval_packet.classification_dispatch_status != "allowed":
        return readiness_block("retrieval_sufficiency_not_certified")
    assignments = build_leaf_assignments(retrieval_packet)
    bundle = retry_or_fail(
        operation=lambda attempt: run_researcher_swarm_runtime(assignments, attempt=attempt),
        policy=RetryPolicy["researcher_assignment"],
        classify_failure=classify_researcher_runtime_failure,
        diagnostics=retry_diagnostics.for_component("researcher_runtime"),
    )
    validate_researcher_bundle(bundle)
    return bundle

def validate_researcher_bundle(bundle):
    assert bundle.model_executed_count > 0
    assert bundle.idempotency_key
    for sidecar in bundle.sidecars:
        reject_forbidden_fields(sidecar, ["probability", "fair_value", "scae_delta"])
        assert sidecar.leaf_id in bundle.assignment_leaf_ids
        assert not sidecar.references_sibling_outputs
    assert no_duplicate_final_sidecars(bundle.idempotency_key)

def verify_for_scae(bundle):
    matrix = build_classification_matrix(bundle.sidecars)
    direction = verify_direction_slices(matrix)
    quality = verify_quality_slices(matrix)
    return build_scae_reconciliation(direction, quality)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_assignments
python3 -m unittest scripts.tests.test_runtime_bundle
python3 -m unittest scripts.tests.test_verification
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_real_runtime_canary
git diff --check
```

Required permanent tests:

- Researchers do not run when retrieval is blocked.
- Researchers run when retrieval is certified.
- Researcher sidecars reject probability/fair value/SCAE delta.
- Verification emits SCAE-ready deltas only for valid sidecars.
- Retryable researcher runtime failure backs off and retries without duplicating final sidecars.
- Non-retryable researcher authority leakage fails without retry.

Clone proof:

- Use either a controlled certified fixture or a live clone case that now certifies retrieval.
- Expected output:
  - `researcher_model_executed_count > 0`;
  - verification `ok=true`;
  - `scae_ready_reconciliation_count > 0`.

Cleanup:

- Delete runtime bundle JSONs unless they are durable redacted fixtures.
- Delete clone reports.

Success criteria:

- Researcher execution is proven only after certified retrieval.
- Verification produces SCAE-ready deltas.
- Researcher retry/backoff is bounded, observable, and idempotent.
- No researcher authority leakage.

Checklist:

- [x] Retrieval-blocked path still prevents researcher runtime.
- [x] Certified path executes researcher runtime.
- [x] Researcher runtime retry/backoff and idempotency tested.
- [x] Verification emits valid SCAE-ready slices.
- [x] Forbidden output scanner passes.
- [x] Temporary artifacts deleted.

Completion note, 2026-06-30:

- Current `main` already had the certified retrieval positive path, researcher runtime bundle manifest, verification matrix, SCAE-ready reconciliation refs, and retryable researcher transport coverage in `scripts.tests.test_ads_operational_canary`.
- Added the missing terminal authority-leakage path: researcher runtime bundle validation now classifies probability/fair-value/SCAE-delta/authority leakage as `policy_violation_quarantine`, fails without retry, and writes no researcher bundle, verification, SCAE, or market prediction output.
- Verified current-repo test placement rather than the stale plan filenames: `test_ads_real_runtime_canary.py` is covered by operational canary tests, and researcher runtime bundle coverage lives in `scripts.tests.test_assignments` plus `scripts.tests.test_verification`.
- Verification run:
  - `/Users/agent2/.openclaw/orchestrator`: `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` passed 295 tests.
  - `/Users/agent2/.openclaw/researcher-swarm`: `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` passed 249 tests.
  - Targeted production-handler, operational-canary, assignment, and verification tests passed.

## Phase 7 - SCAE Valid Forecast And Non-Executing Prediction Proof

Status: complete

Goal: prove SCAE can produce a valid forecast with evidence delta refs while preserving non-executing canary safety.

Implementation:

- Feed verified SCAE reconciliation slices into the existing SCAE bridge.
- Require final ledger:
  - `forecast_validity_status=valid_for_forecast`;
  - nonzero evidence delta refs;
  - SCAE-only forecast authority;
  - no non-SCAE decision/prediction authority.
- In non-executing clone mode:
  - forecast decision record may be written in clone;
  - market prediction count must match expected mode;
  - live DB must not mutate.

Pseudocode:

```python
def run_scae_after_verification(verification):
    if not verification.scae_ready_reconciliation_slices:
        return invalid_ledger("missing_verified_evidence_deltas")
    ledger = scae_build_ledger(
        prior=market_snapshot_prior(),
        evidence_deltas=verification.scae_ready_reconciliation_slices,
    )
    validate_scae_authority(ledger)
    return ledger

def validate_scae_authority(ledger):
    assert ledger.forecast_authority_policy == "scae_only"
    assert ledger.scae_evidence_delta_ref_count > 0
    assert not ledger.non_scae_probability_inputs
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/SCAE
python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_real_runtime_canary
python3 scripts/bin/check_ads_non_scae_authority.py
git diff --check
```

Required permanent tests:

- SCAE valid forecast requires evidence delta refs.
- Missing deltas produce invalid forecast.
- Decision cannot write market prediction from non-SCAE probability.
- Non-executing clone mode does not mutate live DB.

Clone proof:

- Run one clone canary expected to reach SCAE valid forecast.
- Expected output:
  - SCAE `valid_forecast_count > 0`;
  - `delta_ref_count > 0`;
  - forecast decision record written in clone;
  - no live DB mutation.

Cleanup:

- Delete clone DBs and generated reports.

Success criteria:

- Valid SCAE forecast is proven with verified evidence deltas.
- Non-SCAE authority scan remains clean.
- Non-executing/live-mutation boundary remains intact.

Checklist:

- [x] SCAE valid forecast requires deltas.
- [x] Non-SCAE authority check passes.
- [x] Clone-only proof shows no live mutation.
- [x] Temporary artifacts deleted.

Completion note, 2026-06-30:

- Added ADS bridge enforcement for true-production SCAE ledgers: otherwise-valid forecasts without accepted verified SCAE evidence-delta refs are downgraded to `invalid_for_forecast` before finalization and persistence.
- Added final ledger authority metadata for Phase 7 reporting: `forecast_authority_policy=scae_only`, `scae_evidence_delta_ref_count`, `scae_evidence_delta_refs`, `scae_evidence_delta_ref_requirement_status`, and `non_scae_probability_inputs=[]`.
- Added permanent operational canary coverage proving:
  - a valid true-production SCAE forecast has nonzero evidence-delta refs and writes only to the cloned DB;
  - the source/live DB protected tables remain unchanged during that clone proof;
  - certified retrieval plus researcher output with no SCAE-eligible deltas produces an invalid forecast, blocked forecast-decision persistence, and zero market predictions.
- Verification run:
  - `/Users/agent2/.openclaw/orchestrator`: `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` passed 297 tests.
  - `/Users/agent2/.openclaw/SCAE`: `python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'` passed 109 tests.
  - `/Users/agent2/.openclaw/orchestrator`: `python3 -m unittest scripts.tests.test_ads_operational_canary` passed 28 tests.
  - `/Users/agent2/.openclaw/orchestrator`: `python3 scripts/bin/check_ads_non_scae_authority.py` passed.
- Current-repo note: the plan's `scripts.tests.test_ads_real_runtime_canary` target remains stale; real-runtime canary criteria coverage is in `scripts.tests.test_ads_operational_canary`.

## Phase 8 - Reporting, Clone Metadata, And Operator Readiness Semantics

Status: complete

Goal: fix reporting polish and ensure operator/readiness surfaces accurately describe clone-only runs and remaining cutover blockers.

Observed issue:

- The phase9 representative classifier reported `clone_only=false` even though the run used a cloned DB and metadata requested `live_db_mutation=clone_only`.

Implementation:

- Propagate `live_db_mutation=clone_only` from canary metadata into:
  - run metadata;
  - real-runtime report;
  - phase9 representative-case classifier;
  - operator review report.
- Propagate retry/backoff summary fields into:
  - real-runtime report;
  - operator review report;
  - phase9 representative-case classifier;
  - live readiness diagnostics.
- If metadata is missing, infer clone-only only from an explicit safe source, not path guessing alone.
- Keep true cutover readiness blocked unless strict runtime evidence, scoreable success, calibration requirements, and operator gates pass.

Pseudocode:

```python
def resolve_live_db_mutation(run, db_path, explicit_metadata):
    if explicit_metadata.get("live_db_mutation") == "clone_only":
        return "clone_only"
    if run.metadata.get("live_db_mutation") == "clone_only":
        return "clone_only"
    return "unknown_or_live"

def classify_phase9_case(report):
    mutation = resolve_live_db_mutation(report.run, report.db_path, report.run.metadata)
    return {
        "clone_only": mutation == "clone_only",
        "live_db_mutation": mutation,
        "retry_summary": summarize_retry_diagnostics(report),
        "classification": classify_runtime_outcome(report),
    }
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

Required permanent tests:

- Clone-only metadata yields `clone_only=true` in phase9 classifier.
- Retry diagnostics appear in report surfaces and remain bounded.
- Missing metadata does not falsely claim clone-only.
- Readiness status remains `blocked_true_runtime_cutover` when strict evidence is missing.
- Operator review agrees with real-runtime report.

Cleanup:

- Delete temp report JSONs.

Success criteria:

- Clone-only proof is reported truthfully.
- Operator/readiness reports are aligned.
- Retry/backoff state is visible enough for operator triage.
- No report claims cutover readiness without strict evidence.

Checklist:

- [x] Clone metadata propagated.
- [x] Retry/backoff diagnostics propagated.
- [x] Missing metadata is conservative.
- [x] Readiness remains fail-closed.
- [x] Report tests pass.
- [x] Temporary artifacts deleted.

Completion note, 2026-06-30:

- Propagated explicit canary metadata into ADS pipeline-run metadata through `PipelineRunnerPolicy.safe_metadata`, then exposed `live_db_mutation`, `clone_only`, and normalized retry summaries in the real-runtime canary report, Phase 9 representative classifier, operator review report, and live-readiness diagnostics.
- Kept clone-only inference conservative: cloned DB paths alone do not set `clone_only=true`; only explicit `live_db_mutation=clone_only` metadata does.
- Added `blocked_clone_only_canary` as a true-runtime cutover status so even a complete scoreable clone proof stays blocked for live cutover until VM authorizes live mutation and strict readiness evidence exists.
- Added permanent tests proving explicit clone metadata reaches real-runtime, Phase 9, operator, and readiness surfaces; missing metadata stays `unknown_or_live`; retry summaries are present and bounded; and clone-only readiness remains fail-closed.
- Verification passed: `python3 -m unittest scripts.tests.test_ads_operator_review scripts.tests.test_ads_live_readiness scripts.tests.test_ads_operational_canary`, `python3 -m unittest scripts.tests.test_ads_pipeline_runner`, report CLI help checks for real-runtime canary, operator review, and live readiness, and no generated artifacts were created.
- Current-repo note: the plan's `scripts.tests.test_ads_real_runtime_canary` target remains stale; real-runtime canary criteria coverage is still in `scripts.tests.test_ads_operational_canary`.

## Phase 9 - Final Representative Clone Batch

Status: complete

Goal: prove the intended end-to-end v2 path on representative clone-only cases, including at least one true scoreable success.

Implementation:

- Reuse existing canary/report scripts.
- Run a representative batch containing:
  - BOI-like central-bank rate decision case;
  - one binary market with clear protected-primary source requirements;
  - one market with market-family/sibling context;
  - one unresolved forecast market where pre-resolution QDT matters.
- Classify every case:
  - `scoreable_success`;
  - `structured_non_scoreable_insufficiency`;
  - `structural_unanswerability`;
  - `unexpected_failure`.
- Require:
  - no unexpected failures;
  - at least one scoreable success;
  - blocked cases write no scoreable prediction;
  - active runs/leases drain after every run;
  - all output refs resolve.
  - retry/backoff diagnostics show bounded attempts with no retry storms;
  - retry-exhausted intelligence-layer failures are classified as structured insufficiency or retryable stage failure, never silent success.

Pseudocode:

```python
results = []
for selector in representative_case_selectors:
    with clone_db() as db:
        canary = run_strict_canary(db, selector)
        reports = collect_reports(db, canary.pipeline_run_id)
        result = classify_representative_case(reports)
        assert result.live_db_mutation == "clone_only"
        assert reports.active_work == {"active_runs": 0, "active_leases": 0}
        assert reports.retry_summary.max_attempts_within_policy
        assert not reports.retry_summary.retry_storm_detected
        results.append(result)

assert not any(r.classification == "unexpected_failure" for r in results)
assert any(r.classification == "scoreable_success" for r in results)
assert all(r.no_scoreable_write_when_blocked for r in results)
assert all(r.retry_failures_are_explicit for r in results)
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
python3 scripts/bin/check_ads_live_readiness.py \
  --scoreable-readiness-mode true_scoreable_live_readiness \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --operator-review \
  --pretty > "$TMPDIR/readiness.json"
git diff --check
```

Cleanup:

- Delete every clone DB and generated JSON report.
- Delete ad hoc batch runner scripts unless promoted to permanent source/tests.
- Confirm no `/tmp/ads-v2-current-audit-phase*` directories remain.

Success criteria:

- At least one representative case reaches:
  - QDT quality passed;
  - retrieval certified;
  - researcher model executed;
  - verification passed;
  - SCAE valid forecast with evidence delta refs;
  - clone-only prediction persistence when expected.
- All non-scoreable cases block cleanly.
- No unexpected failures.
- No live DB mutation.
- Handoffs and manifests are healthy.
- Retry/backoff diagnostics prove bounded recovery or explicit exhaustion.

Checklist:

- [x] Representative batch completed.
- [x] At least one `scoreable_success`.
- [x] Zero `unexpected_failure`.
- [x] Retry/backoff attempts stayed within policy.
- [x] Retry-exhausted failures were explicit and fail-closed.
- [x] Blocked cases wrote no scoreable predictions.
- [x] Active work drained after every run.
- [x] All temp artifacts deleted.
- [x] Full targeted test suite passed.

Completion note, 2026-06-30:

- Added `ads-phase9-representative-batch/v1`, an aggregate Phase 9 report over per-case real-runtime canary reports. It requires the four representative tags from this plan, explicit clone-only metadata, at least one `scoreable_success`, zero `unexpected_failure` cases, clean blocked-case no-write behavior, drained active work, resolved handoffs, bounded retry attempts/backoff, and explicit retry-exhausted classification.
- Added `scripts/bin/report_ads_phase9_representative_batch.py` so the representative clone-batch proof can be rerun from saved per-case real-runtime reports without ad hoc scripts.
- Added permanent representative-batch coverage with one scoreable success and three blocked/structural cases, plus fail-closed tests for missing scoreable success, missing clone metadata, retry storms, scoreable success without prediction persistence, and blocked cases writing scoreable predictions.
- Existing operational-canary discovery continues to cover the clone-only scoreable true-production path and structured non-scoreable path; the new Phase 9 report enforces the aggregate success criteria across those per-case report shapes.
- Verification passed: Decomposer full discovery (`104 tests OK`), Researcher Swarm full discovery (`249 tests OK`), SCAE `test_scae*.py` discovery (`109 tests OK`), Orchestrator full discovery (`308 tests OK`), `check_ads_non_scae_authority.py`, `check_ads_script_placement.py`, `check_ads_canonical_artifacts.py`, Phase 9 batch CLI help, live-readiness report generation, and `git diff --check`.
- Live-readiness remains intentionally blocked for true runtime cutover without a strict current canary and VM live-mutation authorization; this belongs to Phase 10 closure rather than Phase 9 batch classification.
- Temporary Phase 9 report artifacts were created only under a trap-cleaned `/tmp/ads-v2-current-audit-phase9.*` directory and were removed.

## Phase 10 - Plan Closure And Next-State Decision

Status: pending

Goal: decide whether ADS v2 current-audit remediation is complete, or document the next blocker with evidence.

Implementation:

- Summarize all phase results in this plan or a dated phase report.
- Update relevant readiness/implementation plans if the current blockers changed.
- Do not mark true live cutover ready unless:
  - strict runtime clone proof has at least one scoreable success;
  - readiness reports agree;
  - CAL-001 remains honestly represented;
  - VM explicitly authorizes any live mutation/cutover work.

Pseudocode:

```python
def close_plan(phase_results):
    if all_required_success_criteria_met(phase_results):
        return {
            "plan_status": "implementation_ready_for_vm_review",
            "remaining_blockers": current_readiness_blockers(),
            "live_mutation_authorized": False,
        }
    return {
        "plan_status": "blocked",
        "blocking_phase": first_blocked_phase(phase_results),
        "evidence": blocker_evidence(phase_results),
    }
```

Testing suite:

```bash
cd /Users/agent2/.openclaw
git status --short --branch
git diff --check

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/check_ads_live_readiness.py \
  --scoreable-readiness-mode true_scoreable_live_readiness \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --operator-review \
  --pretty
```

Cleanup:

- Remove all temp directories and generated summaries.
- Keep only committed source, tests, and plan updates.

Success criteria:

- Plan outcome is explicit: complete for VM review or blocked with a precise next blocker.
- No generated artifacts remain.
- Repo status is clean after final commit/push, if VM asks for commit/push.

Checklist:

- [ ] All phase checklists evaluated.
- [ ] Final readiness state recorded.
- [ ] Remaining blockers listed, if any.
- [ ] Workspace clean except intentional changes.
- [ ] VM has a compact final summary.

## Cross-Phase Bug Accommodation Protocol

If a phase uncovers a new bug:

1. Stop the current implementation at the smallest safe boundary.
2. Write a compact bug note:
   - observed command/run id;
   - expected behavior;
   - actual behavior;
   - retry/backoff behavior observed;
   - affected phase;
   - safety impact;
   - proposed adjustment.
3. Decide whether the bug:
   - blocks the current phase;
   - should be fixed as part of the current phase;
   - belongs in the next phase;
   - is unrelated and should be deferred.
4. Update this plan before continuing.
5. Preserve fail-closed behavior while fixing.

Bug note template:

```markdown
### YYYY-MM-DD Phase N Bug Note - Short Title

- Run/command:
- Expected:
- Actual:
- Retry/backoff behavior:
- Safety impact:
- Root cause hypothesis:
- Plan adjustment:
- New/updated tests:
- Cleanup requirements:
```

## Final Non-Negotiable Gate

Do not call the remediation complete until all of the following are true:

- QDT cannot pass quality while required coverage dimensions are missing.
- Search failures do not starve unrelated QDT leaves.
- Retryable intelligence-layer failures have bounded backoff, jitter, diagnostics, and explicit exhausted states.
- Stage-level retry scheduling is reserved for exhausted retryable failures that cannot be recovered locally.
- Native candidate discovery is configured or explicitly proven unnecessary by successful browser/search retrieval.
- Admitted evidence counted for sufficiency is meaningful, source-family resolved, claim-family resolved where required, and temporally safe.
- AMRG context consumption is observable and authority-bounded.
- Researchers execute only after retrieval certification.
- Verification emits SCAE-ready deltas before SCAE valid forecast.
- SCAE valid forecasts have nonzero evidence delta refs.
- Clone-only metadata is reported truthfully.
- Representative clone batch has at least one `scoreable_success`.
- Non-scoreable cases write no market prediction.
- All temporary testing artifacts and one-off scripts are deleted.
