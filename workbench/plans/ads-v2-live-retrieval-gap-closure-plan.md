# ADS v2 Live Retrieval Gap Closure Plan

Created: 2026-06-30

Purpose: close the remaining ADS v2 end-to-end blocker exposed by the clone-only live run
`ads-pipeline-run:e104d1ec2f1550dcb1a0a99c879613f7d9f8b75e59ac631544125d87d01a4d6d`.
The pipeline now has healthy stage handoffs and safe fail-closed behavior, but live retrieval still
does not produce enough fresh, diverse, meaningful, source-certified evidence to let researchers
execute and SCAE produce a valid forecast.

This plan is sequential. Each phase should be completed, tested, cleaned, committed, and pushed
before the next phase starts.

## Current Audit Findings

The one-run audit showed:

- The run completed all 13 stages and drained active leases/runs.
- QDT ran live on `gpt-5.5-high` and passed the current end-to-end quality gate.
- QDT generated 11 market-specific Bank of Israel leaves, 10 dispatchable pre-resolution leaves,
  and 1 terminal verification leaf gated out of dispatch.
- Retrieval failed strict acceptance:
  - `search_candidate_urls = 0`
  - `browser_search_status = executed_with_failures`
  - `native_research_status = disabled`
  - `metadata_classifier_assist_status = not_executed`
  - `direct_url_candidate_count = 2`
  - `fetched_attempt_count = 6`
  - `admitted_evidence_ref_count = 3`
  - `independent_non_market_source_family_count = 0`
  - `freshness_satisfied_count = 0 / 11`
  - `protected_primary_satisfied_count = 0 / 2`
- The admitted evidence was not classification-useful:
  - all admitted refs pointed to the same BOI schedule page;
  - each chunk was only 12 characters;
  - chunks used `excerpt_policy = hash_only`;
  - no claim-family candidates were extracted;
  - evidence did not count toward breadth.
- Targeted expansion attempts existed but were `planned_not_executed`.
- Researcher classification was correctly blocked with `retrieval_sufficiency_not_certified`.
- SCAE correctly produced `invalid_for_forecast` with 0 delta inputs and no market prediction write.
- AMRG behaved as deterministic context only: assist was optional/not requested, no model assist
  executed, no QDT selection/repair/probability/evidence authority was claimed.

## Non-Goals

- Do not create a second canary/report harness. Reuse:
  - `orchestrator/scripts/bin/run_ads_one_case_canary.py`
  - `orchestrator/scripts/bin/report_ads_real_runtime_canary.py`
  - `orchestrator/scripts/bin/report_ads_operator_review.py`
  - `orchestrator/scripts/bin/report_ads_handoffs.py`
  - `orchestrator/scripts/bin/check_ads_live_readiness.py`
- Do not relax evidence acceptance to manufacture a scoreable path.
- Do not let `web_fetch` become search. It remains URL fetch/extraction only.
- Do not give researchers browsing authority. Researchers classify bounded certified evidence only.
- Do not give QDT, AMRG, retrieval, or researchers probability/SCAE-delta authority.
- Do not persist generated clone DBs, one-off JSON summaries, or ad hoc test scripts.

## Cleanup Discipline

Every phase that creates temporary artifacts must use a phase-scoped temp directory:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-live-retrieval-phaseN.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
```

Temporary artifacts include:

- clone DBs
- canary JSON reports
- handoff/operator/runtime reports
- ad hoc inspection scripts
- copied runtime artifacts
- generated fixture JSON not intended as durable regression data

Durable regression tests may be committed under repo test directories. One-off test scripts must
live under the phase temp directory and be deleted by the trap. Before committing each phase:

```bash
find /tmp -maxdepth 1 -name 'ads-v2-live-retrieval-phase*' -print
git status --short
git diff --check
```

Success for cleanup: no phase temp directories remain, no accidental generated artifacts are staged,
and only intentional source/test/plan changes are committed.

## Phase 1 - Baseline And Runtime Diagnostics

Goal: make the current live retrieval failure mode reproducible with compact, machine-checkable
diagnostics before changing behavior.

Implementation:

- Add or extend tests around the current representative failure shape:
  - search executed but candidate URLs are zero;
  - targeted expansion attempts are planned but not executed;
  - admitted chunks are hash-only or too short;
  - retrieval blocks researcher dispatch;
  - SCAE remains invalid for forecast.
- Add compact report fields only if existing reports do not expose the needed counters:
  - `planned_not_executed_expansion_count`
  - `meaningful_snippet_admitted_count`
  - `hash_only_admitted_count`
  - `short_chunk_admitted_count`
  - `search_candidates_materialized_count`
  - `canonical_fetch_duplicate_count`

Pseudocode:

```python
def summarize_retrieval_gap(packet):
    expansions = packet["retrieval_expansion_attempts"]
    chunks = packet["evidence_chunks"]
    return {
        "planned_not_executed_expansion_count": count(
            e for e in expansions if e["attempt_status"] == "planned_not_executed"
        ),
        "meaningful_snippet_admitted_count": count(
            c for c in chunks
            if c["excerpt_policy"] != "hash_only" and c["excerpt_char_count"] >= 280
        ),
        "hash_only_admitted_count": count(
            c for c in chunks if c["excerpt_policy"] == "hash_only"
        ),
        "short_chunk_admitted_count": count(
            c for c in chunks if c["excerpt_char_count"] < 280
        ),
        "search_candidates_materialized_count": len(packet["search_candidate_urls"]),
    }
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operator_review
python3 -m unittest scripts.tests.test_ads_live_readiness
```

Clone proof command:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-live-retrieval-phase1.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --skip-existing-ads-predictions \
  --allow-non-scoreable \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --metadata-json '{"audit_id":"ads-v2-live-retrieval-phase1","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary.json" || true
```

Success criteria:

- The current retrieval insufficiency is reproducible without unexpected stage failure.
- Reports expose enough counters to distinguish:
  - no search candidates,
  - planned-but-not-executed expansion,
  - hash-only/short admitted content,
  - insufficient source/claim family breadth,
  - correct downstream block.
- No generated artifacts remain after the phase.

## Phase 2 - Execute Retrieval Expansion

Goal: targeted expansion must execute or produce an explicit exhausted/unavailable state. It must
not stop at `planned_not_executed` for leaves with thin or empty evidence.

Implementation:

- Locate the retrieval expansion planner/executor in existing retrieval code.
- For every leaf with unsatisfied requirements, execute bounded expansion attempts up to
  `max_targeted_expansion_attempts`.
- Route expansion through existing transports:
  - configured browser/search provider for search queries;
  - direct URL fetch for known URLs;
  - native candidate discovery when configured;
  - structured feeds only when already supported.
- If all transports are unavailable, record `expansion_exhausted_transport_unavailable`.
- If transports run but produce no admitted evidence, record `expansion_exhausted_no_admissible_candidates`.

Pseudocode:

```python
def resolve_leaf_retrieval(leaf, initial_candidates, transports):
    evidence = fetch_and_admit(initial_candidates, leaf)
    requirements = evaluate_sufficiency(leaf, evidence)

    attempts = []
    while requirements.unsatisfied and len(attempts) < leaf.max_expansion_attempts:
        query = build_targeted_query(leaf, requirements)
        transport = choose_transport(query, transports)
        if not transport.available:
            attempts.append(record_unavailable(query, transport))
            break

        candidates = transport.discover(query)
        fetched = fetch_candidates(candidates, leaf)
        admitted = admit_fetched_evidence(fetched, leaf)
        evidence.extend(admitted)
        attempts.append(record_executed(query, candidates, fetched, admitted))
        requirements = evaluate_sufficiency(leaf, evidence)

    if requirements.unsatisfied:
        return block_with_exhaustion_state(leaf, requirements, attempts, evidence)
    return certify_leaf(leaf, evidence, attempts)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Required new tests:

- Thin initial evidence causes executed expansion attempts.
- Empty initial evidence causes executed expansion attempts.
- Unavailable transports produce explicit unavailable/exhausted reason codes.
- `planned_not_executed` is not a final state for an unsatisfied required leaf.

Success criteria:

- Representative clone run has `planned_not_executed_expansion_count = 0` for required leaves.
- Each required leaf has either executed expansion attempts or a precise transport-unavailable state.
- Researcher dispatch remains blocked when sufficiency is still unmet.

## Phase 3 - Materialize Real Search Candidates

Goal: browser/search execution must produce search candidate URLs for forecast-driver leaves, or
must clearly report a search-provider failure that blocks sufficiency.

Implementation:

- Separate direct URL capture from search candidate discovery in runtime state.
- Ensure search query variants for QDT leaves are submitted to a configured search provider.
- Materialize results into `search_candidate_urls` with:
  - URL
  - canonical URL
  - query variant ref
  - leaf id
  - result rank
  - provider id
  - discovery timestamp
- Do not use `openclaw.web_fetch` as search.
- If browser search fails, record provider error class and do not report search as successful.

Pseudocode:

```python
def discover_search_candidates(leaf, query_variants, browser_provider):
    if not browser_provider.search_available:
        return SearchDiscoveryResult(
            status="search_transport_unavailable",
            candidates=[],
            blocks_sufficiency=True,
        )

    all_candidates = []
    for query in query_variants:
        result = browser_provider.search(query.text)
        if result.failed:
            record_search_failure(query, result.safe_error)
            continue
        all_candidates.extend(normalize_search_results(result.urls, leaf, query))

    return SearchDiscoveryResult(
        status="executed_with_candidates" if all_candidates else "executed_no_candidates",
        candidates=dedupe_candidates(all_candidates),
        blocks_sufficiency=not all_candidates,
    )
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
```

Required new tests:

- Browser search results populate `search_candidate_urls`.
- Direct URL fetches do not increment search candidate counts.
- Search failure marks sufficiency as blocked by search transport/candidate discovery.
- Search candidate URLs dedupe by canonical URL without losing leaf/query provenance.

Success criteria:

- Representative clone run shows nonzero `search_candidate_urls` for at least one required
  forecast-driver leaf, or a truthful provider-unavailable block.
- `browser_search_status` cannot be `executed_with_failures` while also hiding the failure from
  the strict acceptance result.

## Phase 4 - Require Meaningful Content And Claim Extraction

Goal: admitted evidence must be useful to researchers. Hash-only or tiny content may be retained as
diagnostic fetch evidence, but it must not satisfy research sufficiency.

Implementation:

- Introduce deterministic content-usefulness checks before evidence counts toward leaf sufficiency:
  - minimum snippet length;
  - non-hash-only excerpt policy;
  - accessible content artifact ref;
  - source text extract status;
  - claim extraction attempted for claim-bearing leaves.
- Keep raw body handling bounded. Do not expose unbounded pages to researchers.
- Add reason codes for rejected/thin evidence:
  - `hash_only_excerpt_not_research_usable`
  - `snippet_too_short_for_classification`
  - `content_artifact_missing`
  - `claim_extraction_not_attempted`

Pseudocode:

```python
def is_research_usable(evidence, chunk, leaf):
    if chunk.excerpt_policy == "hash_only":
        return reject("hash_only_excerpt_not_research_usable")
    if chunk.excerpt_char_count < leaf.minimum_snippet_chars:
        return reject("snippet_too_short_for_classification")
    if not chunk.content_artifact_ref:
        return reject("content_artifact_missing")
    if leaf.requires_claim_family and not evidence.claim_family_ids:
        return reject("claim_family_missing_not_counted")
    return accept_for_research()
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
python3 -m unittest scripts.tests.test_assignments

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Required new tests:

- Hash-only chunks are not counted toward research sufficiency.
- Short chunks are not counted toward research sufficiency.
- Bounded meaningful snippets are passed into researcher assignment contracts when certified.
- Claim-family-empty evidence blocks claim-family breadth requirements.

Success criteria:

- `meaningful_snippet_admitted_count > 0` for certified leaves.
- `hash_only_admitted_count` may be nonzero diagnostically, but hash-only evidence cannot certify
  research sufficiency.
- Researcher assignments receive certified snippet refs, not blind refs/hashes.

## Phase 5 - Source Metadata, Freshness, And Source-Class Semantics

Goal: source metadata rules must distinguish stable rule/schedule evidence from fresh current-event
evidence, and official BOI sources must count correctly for BOI facts without over-crediting market
platform pages.

Implementation:

- Reclassify freshness requirements by leaf role and required evidence field:
  - stable contract/rules/schedule leaves need official authenticity and version/source identity;
  - current status, guidance, inflation, market conditions, and analyst expectations need freshness;
  - terminal verification remains gated and should not dispatch for unresolved forecast runs.
- Classify BOI official pages as `official_or_primary` for BOI facts when deterministic domain/path
  rules support that classification.
- Keep Polymarket as `market_rules_or_resolution_source`, not official proof of the underlying
  real-world event.
- Do not infer source freshness from fetch time. Use publication/update semantics when available.
- Unknown source class/family/claim family remains `unknown_not_counted`.

Pseudocode:

```python
def freshness_policy_for_leaf(leaf, evidence_field):
    if leaf.leaf_temporal_role in {"resolution_mechanics"}:
        if evidence_field in {"contract_resolution_text", "official_decision_schedule"}:
            return FreshnessPolicy(require_fresh_publication=False, require_source_identity=True)
    if leaf.leaf_temporal_role in {
        "current_status",
        "pre_resolution_forecast_driver",
        "material_unknown",
    }:
        return FreshnessPolicy(require_fresh_publication=True, recency_window=leaf.recency_window)
    return FreshnessPolicy(require_fresh_publication=True)

def classify_source(url, leaf):
    if is_bank_of_israel_domain(url) and leaf.requires_boi_fact:
        return "official_or_primary"
    if is_polymarket_url(url):
        return "market_rules_or_resolution_source"
    return deterministic_source_class(url)
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary

cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval
```

Required new tests:

- Stable BOI schedule/rules evidence does not fail solely because `published_at` is unknown.
- Current BOI status/guidance/inflation leaves still require freshness.
- BOI official pages count as `official_or_primary` only for BOI facts.
- Polymarket URLs do not count as protected primary for underlying BOI facts.

Success criteria:

- Freshness failures are semantically correct by leaf type.
- Protected-primary requirements are satisfied only by true primary/official sources.
- The Bank of Israel representative run no longer fails stable schedule leaves for misapplied
  freshness, while still failing current-event leaves when fresh evidence is missing.

## Phase 6 - QDT Leaf Role And Sufficiency Requirement Refinement

Goal: QDT should not create semantically mismatched leaf roles or source requirements that make
retrieval impossible or misleading.

Implementation:

- Add validator/scoring rules for analyst/consensus/market-expectation leaves:
  - should be `pre_resolution_forecast_driver` or `source_quality`;
  - should not be `resolution_mechanics`;
  - should not require protected-primary unless asking for official survey data from a protected
    primary source.
- Add requirement templates for expectation/consensus leaves:
  - accepted source classes: `independent_secondary`, `expert_or_specialist`, and optionally
    `official_or_primary` when applicable;
  - no blanket protected-primary requirement.
- Ensure QDT scoring penalizes role/source requirement mismatches.

Pseudocode:

```python
def validate_leaf_role_semantics(leaf):
    if contains_any(leaf.research_factor, ["analyst", "consensus", "expectation", "survey"]):
        if leaf.leaf_temporal_role == "resolution_mechanics":
            fail("analyst_consensus_leaf_wrong_temporal_role")
        if leaf.purpose == "source_of_truth" and leaf.protected_primary_required:
            fail("analyst_consensus_overclaims_source_of_truth")

def sufficiency_template_for_leaf(leaf):
    if leaf.research_factor == "external_expectations_and_source_quality":
        return {
            "required_source_classes": ["independent_secondary", "expert_or_specialist"],
            "protected_primary_required": False,
            "min_independent_source_families": 2,
        }
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/decomposer
python3 -m unittest scripts.tests.test_qdt
python3 -m unittest scripts.tests.test_runtime_decomposition
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Required new tests:

- Analyst-consensus QDT leaf with `resolution_mechanics` fails validation.
- Valid analyst-consensus QDT leaf uses pre-resolution/source-quality role.
- Valid expectation leaf does not require protected-primary by default.
- Bank of Israel-style QDT still passes with corrected leaf role.

Success criteria:

- QDT cannot pass with analyst-consensus leaves typed as settlement mechanics.
- Corrected QDT output remains specific and dispatchable.
- Downstream retrieval receives realistic source-class requirements.

## Phase 7 - Canonical Fetch Dedupe And Multi-Leaf Evidence Fanout

Goal: fetching the same canonical URL for multiple leaves should not inflate evidence breadth or
waste runtime, but a valid source should be able to support multiple leaves through explicit
relevance mappings.

Implementation:

- Add a canonical fetch cache inside the retrieval run:
  - key by canonical URL plus cutoff;
  - fetch once;
  - reuse content artifact across leaf relevance mappings.
- Separate:
  - fetch count,
  - evidence relevance mappings,
  - source family breadth,
  - claim family breadth.
- Do not count one canonical page as multiple source families just because it supports multiple
  leaves.
- Do record per-leaf support when the same source truly supports multiple leaf questions.

Pseudocode:

```python
def fetch_once_and_fanout(candidates, leaves):
    fetch_cache = {}
    for candidate in candidates:
        key = (candidate.canonical_url, candidate.cutoff)
        if key not in fetch_cache:
            fetch_cache[key] = fetch_url(candidate)

        fetched = fetch_cache[key]
        for leaf in leaves_relevant_to(candidate, leaves):
            relevance = extract_leaf_relevant_snippet(fetched, leaf)
            if relevance.usable:
                add_leaf_evidence_mapping(leaf, fetched.source_ref, relevance)

    certify_breadth_using_unique_source_families()
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_retrieval

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_retrieval_transport
python3 -m unittest scripts.tests.test_ads_operational_canary
```

Required new tests:

- Duplicate canonical URL is fetched once.
- Same source can map to multiple leaves without increasing source-family diversity.
- Per-leaf dockets include relevance refs to shared source content.
- Duplicate fetch avoidance does not hide source failures.

Success criteria:

- Representative run has lower duplicate direct URL fetches.
- Breadth counts remain conservative.
- Leaf dockets become more informative without inflating sufficiency.

## Phase 8 - Researcher Dispatch And SCAE Positive Path Proof

Goal: once retrieval certifies evidence, researchers should execute against bounded certified
snippets, verification should validate their classifications, and SCAE should receive verified
delta inputs.

Implementation:

- Use existing researcher assignment bridge.
- Ensure certified retrieval emits all fields needed by assignments:
  - `qdt_leaf_contract`
  - certified snippet refs
  - source metadata refs
  - claim family refs
  - sufficiency certificate refs
- Ensure researcher runtime executes only when `classification_dispatch_allowed = true`.
- Ensure SCAE rejects unverified/unbounded inputs and accepts verified classification deltas.

Pseudocode:

```python
if retrieval_packet.research_sufficiency_summary.all_required_leaves_certified:
    assignments = compile_assignments(qdt, retrieval_packet)
    assert all(a.certified_snippet_refs for a in assignments)
    researcher_bundle = run_researchers(assignments)
    verified = verify_classifications(researcher_bundle, retrieval_packet)
    ledger = scae_from_verified_inputs(verified)
    assert ledger.forecast_validity_status in {"valid_for_forecast", "invalid_for_forecast"}
else:
    assert researcher_dispatch_blocked()
    assert scae_invalid_for_forecast()
```

Testing suite:

```bash
cd /Users/agent2/.openclaw/researcher-swarm
python3 -m unittest scripts.tests.test_assignments
python3 -m unittest discover -s scripts/tests -p 'test_*.py'

cd /Users/agent2/.openclaw/SCAE
python3 -m unittest discover -s scripts/tests -p 'test_scae*.py'

cd /Users/agent2/.openclaw/orchestrator
python3 -m unittest scripts.tests.test_ads_operational_canary
python3 -m unittest scripts.tests.test_ads_production_handlers
```

Clone proof:

```bash
TMPDIR="$(mktemp -d /tmp/ads-v2-live-retrieval-phase8.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp /Users/agent2/.openclaw/orchestrator/scripts/data/predquant.sqlite3 "$TMPDIR/predquant.sqlite3"

cd /Users/agent2/.openclaw/orchestrator
python3 scripts/bin/run_ads_one_case_canary.py \
  --db-path "$TMPDIR/predquant.sqlite3" \
  --handler-factory predquant.ads_production_handlers \
  --runner-mode non_executing_canary \
  --max-cases 1 \
  --skip-existing-ads-predictions \
  --allow-non-scoreable \
  --require-manifest-handoffs \
  --require-real-runtime-canary-criteria \
  --metadata-json '{"audit_id":"ads-v2-live-retrieval-phase8","live_db_mutation":"clone_only"}' \
  --apply \
  --pretty > "$TMPDIR/canary.json" || true
```

Success criteria:

- If retrieval is certified, researcher model execution occurs and is reported.
- If retrieval is not certified, researcher execution remains blocked with clear reason codes.
- SCAE never receives unverifiable or unbounded evidence.
- A valid SCAE forecast requires verified evidence delta refs.

## Phase 9 - Operator Reporting And Final Representative Clone Batch

Goal: prove the complete behavior with existing canary/report scripts and leave the workspace clean.

Implementation:

- Extend existing reports only if needed to show the new counters:
  - search candidates materialized;
  - expansion executed/exhausted;
  - meaningful snippets;
  - hash-only/short chunks excluded from sufficiency;
  - source/freshness/protected-primary status by leaf;
  - researcher dispatch state;
  - SCAE delta validity.
- Run a representative clone batch using existing scripts:
  - Bank of Israel-style central bank rate market;
  - at least one currently eligible market with clear protected-primary source requirements;
  - one market where QDT pre-resolution drivers matter;
  - one market with related market context, if eligible.
- Classify each case as:
  - `scoreable_success`
  - `structured_non_scoreable_insufficiency`
  - `structural_unanswerability`
  - `unexpected_failure`

Pseudocode:

```python
results = []
for selector in representative_case_selectors:
    tmpdir = make_clone_tmpdir()
    try:
        run = run_existing_canary(tmpdir.db, selector)
        reports = collect_existing_reports(tmpdir.db, run.id)
        results.append(classify_case(reports))
    finally:
        delete_tmpdir(tmpdir)

assert not any(r.kind == "unexpected_failure" for r in results)
assert any(r.kind == "scoreable_success" for r in results)
assert all(r.clone_only for r in results)
assert all(r.no_scoreable_write_when_blocked for r in results)
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
```

Success criteria:

- No unexpected stage failures.
- No unresolved handoff manifest refs.
- Active leases and active runs drain to zero.
- At least one representative case reaches full scoreable path:
  - QDT quality passed;
  - retrieval acceptance passed;
  - researcher model executed;
  - classification verification passed;
  - SCAE produced valid forecast with evidence delta refs;
  - prediction persistence occurred only through the decision/SCAE-authorized path.
- Blocked cases write no scoreable predictions and explain the blocker precisely.
- Final clone artifacts and one-off scripts are deleted.

## Phase Completion Checklist

For every phase:

1. Fetch and confirm branch state:

```bash
git -C /Users/agent2/.openclaw fetch origin
git -C /Users/agent2/.openclaw status --short
git -C /Users/agent2/.openclaw rev-list --left-right --count origin/main...HEAD
```

2. Implement the smallest code/test change that satisfies the phase.
3. Run the phase tests.
4. Run `git diff --check`.
5. Delete temp artifacts and one-off scripts.
6. Confirm `git status --short` contains only intentional files.
7. Commit on `main`.
8. Push `HEAD:main`.

## Final Definition Of Done

ADS v2 live retrieval gap closure is complete only when:

- Expansion executes or explicitly exhausts for required thin/empty leaves.
- Real search candidate URLs materialize, or search transport failure blocks truthfully.
- Hash-only/too-short content cannot satisfy research sufficiency.
- Freshness requirements are semantically appropriate by leaf type.
- Official primary source classification is correct without promoting market pages to event proof.
- QDT does not emit analyst/consensus leaves as settlement mechanics.
- Duplicate canonical fetches do not inflate breadth.
- Researchers execute only after certified retrieval and receive bounded snippets.
- SCAE receives only verified evidence deltas for valid forecasts.
- Existing reports make the above visible.
- A final representative clone batch has no unexpected failures and at least one `scoreable_success`.
