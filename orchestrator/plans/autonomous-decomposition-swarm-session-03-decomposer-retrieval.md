# Session 03 Plan: Decomposer and Retrieval Packet

Master anchors:

- Master plan: `plans/autonomous-decomposition-swarm-implementation-plan.md`
- Shared inventory: `plans/autonomous-decomposition-swarm-feature-inventory.md`
- Machine-readable inventory: `plans/autonomous-decomposition-swarm-feature-inventory.yaml`
- Dependency gate: `python3 plans/check_dependency_gates.py`; append `--report-only` for readiness/blocker summaries and omit it when enforcing a real start gate.
- Live-cutover blocker matrix: `plans/autonomous-decomposition-swarm-live-cutover-blocker-matrix.md`
- Schema-name map: `plans/autonomous-decomposition-swarm-schema-name-map.md`
- Golden fixture matrix: `plans/autonomous-decomposition-swarm-golden-fixture-matrix.md`
- Script placement map: `plans/autonomous-decomposition-swarm-script-placement-map.md`
- Source architecture spec: `/Users/agent2/.openclaw/media/inbound/autonomous-decomposition-swarm-architecture-spec---dbda0f1c----c13d6bea-f02f-4991-8d2c-d69ad5a7dc5a.md`

Primary spec references:

- Section 1.1: selected decomposition as authoritative task contract and AMRG anchor dependency boundaries.
- Section 3.4 and 3.5: decomposition and retrieval packet runtime flow.
- Section 4: decomposer agent.
- Section 5: decomposition artifact contract.
- Section 6: required research question purposes.
- Section 7: retrieval packet contract and local model roles.
- Section 10: retrieval quality, QDT anchor dependency, and provenance persistence.
- Section 17.1: decomposer and retrieval migration surfaces.
- Section 18.1: v2 live cutover checklist.

## Mission

Create the canonical QDT task contract and retrieval packet. The decomposer chooses and validates the selected depth-2 question decomposition tree. Retrieval turns that tree into temporally isolated, provenance-rich evidence packets for researcher classification.

This session must not let retrieval or decomposition author probabilities, SCAE deltas, final forecasts, synthesis conclusions, or decision instructions.

## Runtime Script Placement

Session 3 is split by runtime responsibility:

- QDT generation, QDT validation, anchor repair, and per-leaf sufficiency requirement construction belong to ADS Decomposer under `/Users/agent2/.openclaw/decomposer/scripts`.
- Retrieval packet construction, retrieval expansion, and pre-research sufficiency certificates belong to ADS Researcher Swarm under `/Users/agent2/.openclaw/researcher-swarm/scripts` because they directly prepare leaf-research work.
- Orchestrator only wakes ADS Decomposer, validates the returned artifact refs, and then wakes ADS Researcher Swarm.

Planned ADS Decomposer paths:

```text
/Users/agent2/.openclaw/decomposer/scripts/bin/run_decomposition.py
/Users/agent2/.openclaw/decomposer/scripts/bin/validate_question_decomposition.py
/Users/agent2/.openclaw/decomposer/scripts/bin/repair_anchor_dependency.py
/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/qdt.py
/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/handoff.py
/Users/agent2/.openclaw/decomposer/scripts/ads_decomposer/sufficiency_requirements.py
```

Planned ADS Researcher Swarm retrieval paths:

```text
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_retrieval_packet.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_native_gpt_research.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_browser_retrieval.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_source_metadata_classifier.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/build_retrieval_breadth_profile.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/run_retrieval_expansion.py
/Users/agent2/.openclaw/researcher-swarm/scripts/bin/validate_retrieval_breadth.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/retrieval.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/native_research.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/browser_capture.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/metadata_classifier.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/metadata_resolver.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/source_registry.py
/Users/agent2/.openclaw/researcher-swarm/scripts/researcher_swarm/breadth.py
```

If Session 3 needs any additional runtime script, add the exact path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before coding it.

## Owned Inventory Rows

Directly owned rows:

- `QDT-001`: artifact-path handoff contract.
- `QDT-002`: `question-decomposition.json` schema.
- `QDT-003`: deterministic QDT structural validator.
- `QDT-004`: AMRG anchor dependency contract.
- `QDT-005`: per-leaf high-certainty research sufficiency requirements and canonical machine-template enforcement.
- `MODEL-002`: resolve and record `gpt-5.5-high` decomposer QDT model lane.
- `RET-001`: retrieval packet schema.
- `RET-002`: strict temporal isolation validator.
- `RET-003`: retrieval quality scoring slices.
- `RET-004`: source, claim-family, source-family, independence provenance.
- `RET-005`: protected-primary and missingness candidates.
- `RET-006`: starvation expansion and macro fallback.
- `RET-007`: embedding/reranker preflight and resource caps.
- `RET-010`: optional GPT-5.5 native research transport and deterministic source metadata resolver.
- `RET-011`: optional OpenAI OAuth-routed small GPT metadata and claim-tuple classifier assist.
- `RET-009`: retrieval breadth profile and per-leaf breadth coverage slices.
- `RET-008`: high-certainty retrieval sufficiency loop and per-leaf certificate before researcher dispatch.

## Coordination Rules

1. Update only Session 3 rows directly.
2. Do not mark `QDT-001` integration-ready until `CASE-002`, `CTX-001`, `POL-003`, and `AMRG-002` are `done` or explicitly waived.
3. Do not mark `QDT-004` integration-ready until `AMRG-003` exists.
4. Do not mark `RET-*` integration-ready until `QDT-002` and `FND-003` exist.
5. Do not mark `MODEL-002` integration-ready until `MODEL-001` exists.
6. If claim-family fields are insufficient for Session 5, propose inventory changes and coordinate with Session 5 before changing SCAE-owned rows.
7. Do not mark `QDT-005` integration-ready until `QDT-002`, `QDT-003`, and `POL-003` exist.
8. Do not mark `RET-010` integration-ready until `MODEL-001`, retrieval packet schema, temporal isolation, provenance fields, artifact manifests, and native-transport unavailable diagnostics exist.
9. Do not mark `RET-011` integration-ready until `MODEL-001`, source-candidate materialization, provenance fields, classifier output schema, deterministic acceptance/rejection rules, and classifier-unavailable diagnostics exist.
10. Do not mark `RET-009` integration-ready until QDT sufficiency requirements, retrieval packet, temporal isolation, retrieval quality, provenance, source-access, fallback, at least one approved retrieval transport, deterministic metadata/claim resolution, optional classifier-assist diagnostics, and profile context inputs exist.
11. Do not mark `RET-008` integration-ready until the retrieval quality, provenance, source-access, fallback, model-preflight, retrieval-transport interface, deterministic metadata/claim resolution, and retrieval-breadth rows it depends on are ready.
12. Do not hand off researcher dispatch for a live leaf unless `RET-008` produced a high-certainty sufficiency certificate or a policy-valid structural unanswerability proof.
13. Fixture-mode decomposition/retrieval can proceed with stub evidence and AMRG waiver artifacts.

## Migration and Write Path Ownership

Session 3 owns `MIG-003` decomposition/QDT records and `MIG-004` retrieval/evidence records. Runtime integration is blocked until these write paths have destination tables, schemas, or explicit artifact contracts in the shared migration matrix.

Required write paths:

```text
write_decomposition_run
write_required_research_questions
write_qdt_research_sufficiency_requirements
write_qdt_anchor_dependency_slices
write_retrieval_packet
write_retrieval_evidence_items
write_retrieval_evidence_chunk_slices
write_native_research_attempts
write_browser_retrieval_attempts
write_browser_search_provider_diagnostics
write_source_metadata_classifier_slices
write_source_metadata_resolution_slices
write_atomic_claim_candidate_slices
write_claim_family_resolution_slices
write_metadata_fill_diagnostics
write_retrieval_quality_slices
write_evidence_provenance_slices
write_retrieval_breadth_profile
write_retrieval_breadth_coverage_slices
write_contradiction_search_attempts
write_negative_check_attempts
write_source_access_and_missingness_slices
write_retrieval_fallback_state
write_retrieval_expansion_attempts
write_research_sufficiency_certificate
```

The QDT write path must store the selected decomposition, leaf questions, branch IDs, dependency groups, AMRG usage, validation status, research sufficiency requirements, canonical prompt/schema provenance, and decomposer model provenance. The retrieval write path must store approved retrieval transport attempts, OpenClaw browser/search provider diagnostics, admitted evidence items, chunk/span refs, GPT-native research attempts when available, browser retrieval attempts, source metadata classifier-assist slices when available, source metadata resolution slices, atomic claim candidates, claim-family resolution slices, sources, claim families, source families, source classes, timestamps, temporal eligibility, retrieval breadth profiles, contradiction-search attempts, negative-check attempts, retrieval quality, missingness, protected-primary access state, fallback status, expansion attempts, and sufficiency certificate status. These records are the future tuning basis for decomposition shape, retrieval density, source coverage, source diversity, metadata fill rates, classifier acceptance rates, missingness penalties, stale-evidence policy, and the relationship between research sufficiency and resolved forecast quality.

## Technical Specification

### QDT Artifact

Minimum `question-decomposition.json` contract:

```json
{
  "artifact_type": "question_decomposition",
  "schema_version": "question-decomposition/v1",
  "case_id": "case-...",
  "market_id": "poly-...",
  "dispatch_id": "dispatch-...",
  "macro_question": "...",
  "market_reality_constraints_digest": "sha256:...",
  "leaf_budget_decision": {
    "market_complexity_score": 0.0,
    "effective_leaf_budget": 6,
    "hierarchical_branch_ledger_required": false,
    "reason_codes": []
  },
  "branches": [],
  "required_leaf_questions": [],
  "related_market_context_usage": {},
  "amrg_anchor_dependency_contracts": [],
  "model_execution_context": {
    "model_lane_id": "decomposer_qdt_generation",
    "resolved_model_id": "gpt-5.5-high",
    "model_policy_ref": "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    "prompt_template_id": "decomposer-qdt/v1",
    "prompt_template_sha256": "sha256:...",
    "input_manifest_ids": [],
    "output_schema_version": "question-decomposition/v1"
  },
  "validation_summary": {}
}
```

Each required leaf question must include:

```json
{
  "leaf_id": "leaf-...",
  "parent_branch_id": "branch-...",
  "question_text": "...",
  "purpose": "base_rate|market_pricing|direct_evidence|source_of_truth|catalyst|resolution_mechanics|structural|other",
  "bayesian_weighting": {
    "static_information_weight": "critical|high|medium|low",
    "weight_reason_codes": []
  },
  "leaf_dependency_group_id": "dep-group-...",
  "leaf_condition_scope": "unconditional|target_given_upstream|target_given_not_upstream|shared_context",
  "required_evidence_fields": [],
  "research_sufficiency_requirements": {
    "sufficiency_profile_id": "high-certainty-default/v1",
    "target_answerability": "high_confidence_or_structurally_unanswerable",
    "retrieval_breadth_profile_ref": "breadth-profile-template:...",
    "required_source_classes": ["official_or_primary", "independent_secondary"],
    "protected_primary_required": false,
    "min_independent_claim_families": 2,
    "min_independent_source_families": 2,
    "min_temporally_fresh_sources": 1,
    "required_value_fields": [],
    "required_negative_checks": [],
    "contradiction_search_required": true,
    "recency_window_seconds": 259200,
    "max_targeted_expansion_attempts": 3,
    "allow_macro_fallback_for_leaf": false,
    "unanswerability_proof_required": true,
    "classification_dispatch_requires_sufficiency_certificate": true
  },
  "market_component_terms": [],
  "structural_validation": {}
}
```

### Retrieval Packet

Minimum retrieval packet contract:

```json
{
  "artifact_type": "retrieval_packet",
  "schema_version": "retrieval-packet/v1",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "question_decomposition_artifact_id": "artifact:...",
  "forecast_timestamp": "...",
  "source_cutoff_timestamp": "...",
  "temporal_isolation_status": "pass|fail",
  "leaf_retrieval_results": [],
  "retrieval_quality_summary": {},
  "retrieval_breadth_profiles": [],
  "retrieval_breadth_coverage_slices": [],
  "research_sufficiency_summary": {
    "all_required_leaves_certified": false,
    "classification_dispatch_status": "blocked_until_certified",
    "leaf_certificate_refs": []
  },
  "omitted_candidates": [],
  "contradiction_search_attempts": [],
  "negative_check_attempts": [],
  "retrieval_expansion_attempts": [],
  "leaf_research_sufficiency_certificates": [],
  "protected_primary_access_failures": [],
  "missingness_candidates": [],
  "policy_context_ref": "artifact:..."
}
```

Each selected evidence item must include canonical source, claim-family, source-family, independence, content hash, temporal gate, retrieval score, evidence origin fields, and bounded chunk/span refs.

Minimum `retrieval-evidence/v1` item:

```json
{
  "artifact_type": "retrieval_evidence",
  "schema_version": "retrieval-evidence/v1",
  "evidence_ref": "retrieval-evidence-...",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "leaf_id": "leaf-...",
  "parent_branch_id": "branch-...",
  "retrieval_transport": "browser|native_gpt_research|structured_feed|db|manual_fixture",
  "transport_attempt_ref": "browser-attempt-...|native-research-...|structured-source-attempt-...",
  "requested_url": "https://...",
  "final_url": "https://...",
  "canonical_url": "https://...",
  "canonical_source_id": "source-...",
  "source_metadata_resolution_ref": "source-metadata-...",
  "claim_family_resolution_refs": [],
  "source_family_id": "source-family-...",
  "source_class": "official_or_primary|primary_reporting|independent_secondary|market_rules_or_resolution_source|market_price_or_orderbook|social_or_user_generated|unknown",
  "independence_status": "independent|same_source_family|same_claim_family|syndicated_copy|derived_from_primary|unknown_not_counted",
  "temporal_gate_status": "pass|fail|unknown_not_counted",
  "source_published_at": "...",
  "source_updated_at": "...",
  "captured_at": "...",
  "artifact_generated_at": "...",
  "content_sha256": "sha256:...",
  "chunk_refs": [],
  "retrieval_score": 0.0,
  "admission_status": "admitted|omitted|rejected",
  "admission_reason_codes": []
}
```

Minimum `retrieval-evidence-chunk/v1` slice:

```json
{
  "artifact_type": "retrieval_evidence_chunk",
  "schema_version": "retrieval-evidence-chunk/v1",
  "chunk_ref": "retrieval-chunk-...",
  "evidence_ref": "retrieval-evidence-...",
  "content_artifact_ref": "artifact:browser-capture/...",
  "chunk_index": 0,
  "char_start": 0,
  "char_end": 0,
  "text_sha256": "sha256:...",
  "excerpt_char_count": 0,
  "excerpt_policy": "bounded_for_classifier|bounded_for_researcher|hash_only",
  "contains_claim_candidate_ids": []
}
```

### Retrieval Transport Contract

No news API transport is required for the first v2 live cutover. Retrieval must be transport-abstract: a live dispatch can proceed when at least one approved transport produces temporally eligible admitted evidence and the deterministic resolver/breadth/sufficiency gates pass.

Approved first-cutover transports:

- `browser`: OpenClaw `web_fetch` / browser web-search transport when available, plus direct URL navigation for official or resolution URLs and bounded site-search/followed-link capture variants.
- `native_gpt_research`: optional candidate-discovery transport only when the configured runtime exposes it.
- `manual_fixture`: fixture-only transport for tests and staged validation.

Reserved future transports:

- `structured_feed`
- `db`

Unavailable optional transports must write compact unavailable diagnostics and must not block retrieval if another approved transport can satisfy breadth. A missing news/feed API adapter is not a live-cutover blocker.

### Browser Search Provider Contract

First cutover uses a single named browser provider contract:

```json
{
  "artifact_type": "browser_search_provider_diagnostic",
  "schema_version": "browser-search-provider-diagnostic/v1",
  "provider_id": "openclaw_web_fetch_browser",
  "provider_refs": ["openclaw:web_fetch", "openclaw:browser_transport"],
  "capabilities": ["web_search", "direct_url", "site_search", "followed_link"],
  "availability_status": "available|unavailable|partial",
  "news_feed_api_enabled": false,
  "direct_url_priority": "official_or_resolution_urls_first",
  "unavailable_reason": null,
  "checked_at": "..."
}
```

Provider resolution rules:

- `openclaw_web_fetch_browser` is the first-cutover provider. Implementations may use OpenClaw `web_fetch` for lightweight page fetch/extraction and the OpenClaw browser transport for rendered navigation, search result pages, followed links, and blocked-page diagnostics.
- Direct URL navigation must run first for URLs already present in the `ads-case-contract`, market rules, resolution source, official primary source, or protected-primary hints. These captures may satisfy protected-primary or source-of-truth requirements when deterministic source identity and temporal gates pass.
- Web search is used only after direct URL capture or when a leaf has no direct official/resolution URL. Search queries must be generated from the retrieval packet and sufficiency requirements.
- If web search is unavailable but direct URL navigation is available, retrieval may proceed only when direct URL captures satisfy the relevant breadth/sufficiency gates or produce a policy-valid structural unanswerability proof. Otherwise write expansion/fallback diagnostics and fail closed before researcher dispatch.
- No first-cutover script may require a news API key, structured news feed adapter, or external feed account. Future `structured_feed` adapters must implement the same evidence/claim/source contracts before they can count toward sufficiency.

### Native GPT Research Transport

`RET-010` may use GPT-5.5 native research/browsing capability for candidate discovery. It is optional for first-cutover retrieval and replaces hand-built search crawling only when the runtime exposes native research. It does not replace deterministic metadata or claim-family resolution.

Native research must use the `native_research_candidate_discovery` model lane from `plans/autonomous-decomposition-swarm-model-lane-policy.json`. It may output citations, canonical URL candidates, snippets, candidate atomic claims, proposed source labels, contradiction candidates, and no-confirmation candidates. It must not output final source-class/source-family/claim-family authority, research sufficiency certification, SCAE deltas, or probabilities.

Minimum `native-research-attempt/v1`:

```json
{
  "artifact_type": "native_research_attempt",
  "schema_version": "native-research-attempt/v1",
  "attempt_id": "native-research-...",
  "leaf_id": "leaf-...",
  "query_variant_id": "query-...",
  "model_lane_id": "native_research_candidate_discovery",
  "resolved_model_id": "gpt-5.5-high",
  "prompt_template_id": "native-gpt-research/v1",
  "query_manifest_sha256": "sha256:...",
  "research_transport": "native_gpt_research",
  "candidate_citation_refs": [],
  "candidate_claim_refs": [],
  "contradiction_candidate_refs": [],
  "negative_check_candidate_refs": [],
  "model_proposed_source_metadata": {},
  "candidate_output_schema_version": "native-research-candidates/v1",
  "attempt_status": "accepted|partial|failed"
}
```

Native research output becomes evidence only after `metadata_resolver.py` captures/normalizes the cited source refs, assigns source metadata, checks temporal safety, and writes source metadata resolution slices. Model-proposed labels are stored as proposals and diagnostics only.

### Small Source Metadata Classifier Assist

`RET-011` uses the `source_metadata_classifier_assist` lane from `plans/autonomous-decomposition-swarm-model-lane-policy.json`. The default provider/model key is `openai/gpt-5.4-mini`, routed through the OpenAI OAuth profile exposed by OpenClaw. This is a fast classifier/parser assist, not a research agent and not a forecast authority. It is optional for first-cutover retrieval; if unavailable, deterministic resolver outputs stay conservative and unresolved claim/source fields become `unknown_not_counted` where required.

Runtime model import/availability contract:

- Do not change the global OpenClaw default model for this lane.
- Resolve the lane explicitly by `default_provider_model_key`.
- Verify availability before first runtime use with `openclaw models list --json` or the equivalent model-catalog API.
- Smoke-test explicit invocation with `openclaw infer model run --model openai/gpt-5.4-mini --prompt ...` during implementation verification.
- If `openai/gpt-5.4-mini` is unavailable, try configured allowed fallbacks in order: `openai/gpt-5.4-nano`, `openai/o4-mini`, then `openai/o3-mini`.
- If no allowed OAuth-routed small model is available, write `source_metadata_classifier_unavailable`, skip classifier-assist promotion, and keep resolver outputs conservative rather than blocking non-critical retrieval.

The classifier receives only compact source-candidate packets:

```json
{
  "candidate_id": "candidate-...",
  "leaf_id": "leaf-...",
  "transport_attempt_ref": "native-research-...|browser-attempt-...",
  "canonical_url": "https://...",
  "registrable_domain": "example.com",
  "page_title_excerpt": "short title only",
  "publisher_metadata": {},
  "byline_excerpt": "short byline only",
  "snippet_excerpt": "short snippet only",
  "visible_date_text_candidates": [],
  "content_sha256": "sha256:...",
  "market_contract_source_hints": [],
  "forbidden_outputs": [
    "probability",
    "scae_evidence_delta",
    "research_sufficiency_certification",
    "claim_family_final_authority"
  ]
}
```

The classifier output must stay compact:

```json
{
  "artifact_type": "source_metadata_classifier_slice",
  "schema_version": "source-metadata-classifier/v1",
  "classifier_slice_id": "source-classifier-...",
  "candidate_id": "candidate-...",
  "model_lane_id": "source_metadata_classifier_assist",
  "resolved_model_id": "gpt-5.4-mini",
  "provider_model_key": "openai/gpt-5.4-mini",
  "prompt_template_id": "source-metadata-classifier/v1",
  "input_candidate_sha256": "sha256:...",
  "proposed_source_class": "official_or_primary|primary_reporting|independent_secondary|market_rules_or_resolution_source|market_price_or_orderbook|social_or_user_generated|unknown",
  "source_class_confidence": "high|medium|low|unknown",
  "proposed_source_family_hint": "publisher-or-wire-hint|unknown",
  "source_family_confidence": "high|medium|low|unknown",
  "syndication_hint": "reuters_copy|ap_copy|press_release_copy|none|unknown",
  "atomic_claim_candidates": [],
  "visible_date_candidates": [],
  "reason_codes": []
}
```

Authority rules:

- The classifier may supply an accepted `source_class` for ordinary, non-protected sources when confidence is high and no deterministic resolver evidence contradicts it.
- The classifier may parse bounded article passages and supply atomic claim tuple candidates, but `claim_family_id` is final only after deterministic tuple validation, normalization, span binding, and hashing.
- The classifier may supply `source_family` and syndication hints, but final `source_family_id` requires canonical URL/domain, curated registry, publisher metadata, or syndication evidence.
- The classifier may supply visible date candidates, but temporal safety is final only after deterministic date parsing and source-cutoff validation.
- The classifier cannot satisfy `protected_primary`, `market_rules_or_resolution_source`, or source-of-truth requirements unless market-contract or deterministic resolver evidence also proves the source identity.
- Unsupported classifier outputs become `classifier_unsupported` or `unknown_not_counted` and are retained for fill-rate and acceptance-rate diagnostics.

### Browser Retrieval Transport

If retrieval uses an agent browser instead of a news/API feed, the browser is only the transport. It must never become the `source_class`, `source_family_id`, or `claim_family_id`. The first-cutover implementation resolves `openclaw_web_fetch_browser`, captures direct official/resolution URLs first, then uses OpenClaw browser/web-search capture for bounded expansion when available.

Every browser candidate must write a compact `browser-retrieval-attempt/v1` record:

```json
{
  "artifact_type": "browser_retrieval_attempt",
  "schema_version": "browser-retrieval-attempt/v1",
  "attempt_id": "browser-attempt-...",
  "leaf_id": "leaf-...",
  "query_variant_id": "query-...",
  "query_text_sha256": "sha256:...",
  "browser_session_ref": "browser-session:...",
  "browser_provider_id": "openclaw_web_fetch_browser",
  "openclaw_transport_ref": "openclaw:web_fetch|browser-session:...",
  "provider_capabilities": ["web_search", "direct_url"],
  "provider_availability_status": "available|partial|unavailable",
  "news_feed_api_enabled": false,
  "navigation_mode": "web_search|direct_url|site_search|followed_link",
  "direct_url_source_ref": "ads-case-contract:resolution_url|market_rules|official_source_hint|null",
  "search_engine_or_navigation_source": "web_search|direct_url|site_search|followed_link",
  "result_rank": 1,
  "requested_url": "https://...",
  "final_url": "https://...",
  "canonical_url": "https://...",
  "normalized_domain": "example.com",
  "page_title_sha256": "sha256:...",
  "captured_at": "...",
  "published_at": "...",
  "published_at_extraction_method": "html_meta|structured_data|visible_text|unknown",
  "rendered_text_sha256": "sha256:...",
  "extracted_text_sha256": "sha256:...",
  "screenshot_artifact_ref": null,
  "content_artifact_ref": "artifact:browser-capture/...",
  "extraction_status": "accepted|rejected|paywalled|blocked|duplicate|temporal_fail"
}
```

Browser retrieval storage should keep provider refs, navigation mode, hashes, canonical URLs, timestamps, and optional artifact refs. Full rendered pages, screenshots, and large snippets should live behind artifact refs only when needed for replay or debugging.

### Source Identity and Breadth Classification

`RET-004` and `RET-009` must classify source identity deterministically before any leaf is certified. More URLs are not enough; the breadth validator must prove structurally different evidence.

### Layered Source Metadata Resolver

Final source metadata is filled by deterministic resolver stages. GPT-native research can propose values, but final accepted fields require resolver evidence. Any unresolved or low-confidence value becomes `unknown_not_counted`.

Resolver stages:

1. **Market-contract resolver**: match against `ads-case-contract/v1`, market rules, resolution-source URL/domain, platform, and named official/source-of-truth entities. This is the strongest source for `official_or_primary` and `market_rules_or_resolution_source`.
2. **Small curated family registry**: match common official domains, platforms, wire services, data providers, and known syndication/ownership families. This is intentionally small and grows from recurring unknowns, not from preloading the internet.
3. **Page metadata resolver**: derive canonical URL, registrable domain, schema.org/JSON-LD publisher, OpenGraph site name, canonical link, byline, published/updated timestamps, and syndication markers from the captured citation/page.
4. **Deterministic fallback**: default `source_family_id` to normalized registrable domain plus canonical URL/content hash grouping when no stronger family is known. Fallback cannot satisfy protected-primary rules unless the market-contract resolver confirms it.
5. **Classifier-assist acceptance**: compare `source_metadata_classifier_assist` proposals to deterministic evidence. High-confidence ordinary source-class proposals can be accepted when no deterministic evidence contradicts them. Claim tuple proposals can create final claim-family IDs only after deterministic normalization and hashing. Source-family hints and visible date candidates require deterministic confirmation before final use.
6. **Model proposal audit**: compare GPT-native research source labels/family/claims to deterministic evidence and classifier-assist slices. Accepted only if resolver acceptance rules support them; otherwise retained as diagnostic proposal.

Minimum `source-metadata-resolution/v1`:

```json
{
  "artifact_type": "source_metadata_resolution",
  "schema_version": "source-metadata-resolution/v1",
  "resolution_id": "source-metadata-...",
  "evidence_ref": "retrieval-evidence-...",
  "transport_attempt_ref": "native-research-...|browser-attempt-...",
  "canonical_url": "https://...",
  "registrable_domain": "example.com",
  "source_class": "official_or_primary|primary_reporting|independent_secondary|market_rules_or_resolution_source|market_price_or_orderbook|social_or_user_generated|unknown",
  "source_class_resolution_method": "market_contract|curated_registry|page_metadata|deterministic_fallback|unknown",
  "source_family_id": "source-family-...",
  "source_family_resolution_method": "market_contract|curated_registry|publisher_metadata|domain_fallback|unknown",
  "claim_family_resolution_refs": [],
  "claim_family_ids": [],
  "claim_family_resolution_method": "structured_data|source_specific_template|model_proposed_then_validated_and_normalized|native_research_candidate_then_validated|unknown",
  "temporal_safety_status": "pass|fail|unknown_not_counted",
  "published_at": "...",
  "published_at_method": "structured_data|html_meta|visible_text|model_proposed_unaccepted|unknown",
  "classifier_slice_ref": "source-classifier:...|null",
  "classifier_acceptance_status": "not_used|accepted_source_class|accepted_claim_tuple|accepted_source_family_hint|accepted_visible_date_candidate|unsupported|contradicted",
  "classifier_acceptance_reason_codes": [],
  "metadata_confidence": "high|medium|low|unknown",
  "counts_toward_breadth": true,
  "unknown_reason_codes": []
}
```

Expected fill behavior:

- `source_family_id` should usually be fillable from canonical URL/domain fallback. Unknown should be rare; low-confidence domain fallback can count as a family but not as protected-primary.
- `source_class` should be confidently fillable for official/rules/known data sources and many known publishers. The small classifier should materially reduce unknowns for ordinary publisher pages, but protected-primary/source-of-truth source class still requires market-contract or deterministic resolver evidence.
- `claim_family_id` should be fillable whenever there is enough snippet/page text to support a bounded atomic claim candidate. A parser/model may propose the tuple, but deterministic code must validate the supporting span refs, normalize the tuple, and hash it into the final family. If the page only provides a vague mention or inaccessible content, it becomes `unknown_not_counted` for claim-family diversity.
- `temporal_safety_status` should be pass/fail only when published/updated time or source-cutoff eligibility is known. Missing publication time becomes `unknown_not_counted` for freshness-critical leaves.

Every dispatch should write aggregate metadata-fill diagnostics: counts and percentages for source class, source family, claim family, and temporal safety by leaf and by transport. High unknown rates trigger retrieval expansion or lower sufficiency status; they do not silently pass.

Minimum `retrieval-metadata-fill-diagnostics/v1`:

```json
{
  "artifact_type": "retrieval_metadata_fill_diagnostics",
  "schema_version": "retrieval-metadata-fill-diagnostics/v1",
  "leaf_id": "leaf-...",
  "transport": "native_gpt_research|browser|feed|db|mixed",
  "candidate_count": 0,
  "accepted_evidence_count": 0,
  "source_class_known_rate": 0.0,
  "source_family_known_rate": 0.0,
  "claim_family_known_rate": 0.0,
  "temporal_safety_known_rate": 0.0,
  "required_breadth_unknown_blockers": [],
  "unknown_reason_counts": {},
  "expansion_required": false
}
```

Source class answers "what kind of source is this?" It is assigned from a source registry and market-rule metadata before any model judgment. Allowed enums:

```text
official_or_primary
primary_reporting
independent_secondary
market_rules_or_resolution_source
market_price_or_orderbook
social_or_user_generated
unknown
```

Rules:

- `official_or_primary` requires a source-of-truth match to the entity, platform, regulator, resolution source, official database, or primary event record named by the market contract.
- `market_rules_or_resolution_source` requires the market platform's rules, resolution text, or named resolution-source artifact.
- `primary_reporting` requires direct reporting with independently attributable observation or interview, not syndicated rewrite.
- `independent_secondary` can summarize or analyze, but cannot satisfy protected-primary requirements.
- `unknown` never satisfies a required source-class breadth dimension.

Source family answers "are these sources operationally the same origin?" It is keyed by canonical publisher/feed/service ownership group, not the browser tool and not just URL. The canonical key should use normalized domain, canonical URL, `canonical_source_id`, publisher owner ID, syndication/wire ID, feed/API provider ID when applicable, platform ID, and mirrored endpoint ID when available. A Reuters/AP copy republished by many outlets counts as one source family for independence. One feed/API endpoint mirrored under several URLs also counts as one source family.

Claim family answers "are these sources making the same atomic claim?" It is keyed by normalized subject, predicate, object/value, event time, jurisdiction/entity, market-relevant condition, and polarity. Formatting, headline wording, quote boundaries, and boilerplate must not create new claim families. Deterministic tuple/hash matching is primary; embedding similarity may nominate candidate merges but cannot by itself create independence. A conflicting polarity about the same object becomes a related contradiction family, not independent corroboration.

### Atomic Claim Candidate and Claim-Family Resolution

Arbitrary article prose is not "deterministically understood" by code alone. The deterministic boundary is:

1. A source-specific parser, structured-data parser, native-research candidate, or small classifier/model assist may propose an atomic claim tuple from bounded chunk refs.
2. Deterministic code validates that the proposal is schema-valid, bound to source text spans or structured fields, temporally eligible, market-relevant for the leaf, and free of forbidden probability/SCAE fields.
3. Deterministic code normalizes entities, predicates, values, event times, jurisdiction/entity scope, condition scope, and polarity.
4. Deterministic code hashes the normalized tuple and assigns or joins the claim family.
5. Ambiguous, unsupported, multi-claim, or spanless proposals become `unknown_not_counted` or are split/rejected before breadth certification.

Minimum `atomic-claim-candidate/v1`:

```json
{
  "artifact_type": "atomic_claim_candidate",
  "schema_version": "atomic-claim-candidate/v1",
  "claim_candidate_id": "claim-candidate-...",
  "evidence_ref": "retrieval-evidence-...",
  "leaf_id": "leaf-...",
  "chunk_refs": [],
  "extraction_method": "structured_data|source_specific_template|native_research_candidate|model_assisted_bounded_passage|manual_fixture",
  "model_lane_id": "source_metadata_classifier_assist|null",
  "prompt_template_id": "source-metadata-classifier/v1|null",
  "proposed_tuple": {
    "subject": "...",
    "predicate": "...",
    "object_or_value": "...",
    "event_time": "...",
    "entity_or_jurisdiction": "...",
    "condition_scope": "unconditional|target_given_upstream|target_given_not_upstream|shared_context",
    "polarity": "affirmed|negated|uncertain"
  },
  "supporting_span_refs": [],
  "candidate_confidence": "high|medium|low|unknown",
  "validation_status": "accepted_for_normalization|rejected_multi_claim|rejected_no_span|rejected_not_market_relevant|rejected_temporal|rejected_forbidden_output|unknown_not_counted",
  "validator_reason_codes": []
}
```

Minimum `claim-family-resolution/v1`:

```json
{
  "artifact_type": "claim_family_resolution",
  "schema_version": "claim-family-resolution/v1",
  "claim_family_resolution_id": "claim-family-resolution-...",
  "claim_family_id": "claim-family-...",
  "claim_candidate_refs": [],
  "normalized_tuple": {
    "subject_id": "...",
    "predicate_id": "...",
    "object_or_value_normalized": "...",
    "event_time_normalized": "...",
    "entity_or_jurisdiction_id": "...",
    "condition_scope": "unconditional|target_given_upstream|target_given_not_upstream|shared_context",
    "polarity": "affirmed|negated|uncertain"
  },
  "normalized_tuple_sha256": "sha256:...",
  "resolution_method": "structured_data|source_specific_template|model_proposed_then_validated_and_normalized|native_research_candidate_then_validated|manual_fixture",
  "equivalence_status": "new_family|matched_existing_family|related_contradiction_family|unknown_not_counted",
  "contradiction_family_id": null,
  "counts_toward_claim_family_breadth": true,
  "reason_codes": []
}
```

Independence status must be one of:

```text
independent
same_source_family
same_claim_family
syndicated_copy
derived_from_primary
unknown_not_counted
```

Only `independent` and, where policy permits, `derived_from_primary` can count toward independent breadth. `unknown_not_counted` is conservative and cannot satisfy source-family or claim-family minimums.

### Retrieval Breadth Profile

Each leaf must receive a compact `retrieval-breadth-profile/v1` derived from QDT sufficiency requirements and the effective tuning profile:

```json
{
  "artifact_type": "retrieval_breadth_profile",
  "schema_version": "retrieval-breadth-profile/v1",
  "leaf_id": "leaf-...",
  "source_class_requirements": {
    "required": ["official_or_primary", "independent_secondary"],
    "protected_primary_required": false
  },
  "claim_family_requirements": {
    "min_independent_claim_families": 2,
    "duplicate_same_claim_counts_once": true
  },
  "source_family_requirements": {
    "min_independent_source_families": 2,
    "wire_or_api_syndication_counts_once": true
  },
  "freshness_requirement": {
    "recency_window_seconds": 259200,
    "min_fresh_sources": 1
  },
  "contradiction_search": {
    "required": true,
    "query_variants": []
  },
  "negative_checks": {
    "required_checks": [],
    "query_variants_by_check": {}
  },
  "retrieval_volume_tier": {
    "tier": "normal|high|critical_source_of_truth",
    "query_variant_count": 3,
    "raw_candidate_target_range": [30, 50],
    "admitted_evidence_target_range": [8, 12],
    "max_targeted_expansion_attempts": 3
  }
}
```

Default retrieval volume tiers:

| Tier | Query variants | Raw candidates | Admitted refs | Max expansion |
| --- | ---: | ---: | ---: | ---: |
| normal | 3 | 30-50 | 8-12 | 3 |
| high | 4-5 | 50-80 | 12-16 | 4 |
| critical/source-of-truth | 5-7 | 80-120 | 15-25 | 5 |

The matching breadth coverage slice must stay small:

```json
{
  "artifact_type": "retrieval_breadth_coverage",
  "schema_version": "retrieval-breadth-coverage/v1",
  "leaf_id": "leaf-...",
  "source_class_coverage": {},
  "claim_family_count": 2,
  "source_family_count": 2,
  "fresh_source_count": 1,
  "contradiction_attempt_refs": [],
  "negative_check_attempt_refs": [],
  "protected_primary_status": "satisfied|not_required|blocked|missing",
  "unsatisfied_breadth_dimensions": [],
  "breadth_certified": true
}
```

Each leaf research sufficiency certificate must be compact and machine-readable:

```json
{
  "certificate_id": "research-sufficiency-...",
  "leaf_id": "leaf-...",
  "sufficiency_profile_id": "high-certainty-default/v1",
  "coverage_status": "certified_high_certainty|expansion_exhausted_structurally_unanswerable|blocked_insufficient_research",
  "requirements_satisfied": [],
  "requirements_unsatisfied": [],
  "evidence_refs_by_requirement": {},
  "breadth_coverage_ref": "breadth-coverage:...",
  "source_class_coverage_status": "satisfied|partial|failed",
  "source_family_diversity_status": "satisfied|partial|failed",
  "claim_family_diversity_status": "satisfied|partial|failed",
  "contradiction_search_status": "satisfied|partial|failed|not_required",
  "negative_check_status": "satisfied|partial|failed|not_required",
  "independent_claim_family_count": 2,
  "independent_source_family_count": 2,
  "fresh_source_count": 1,
  "protected_primary_status": "satisfied|not_required|blocked|missing",
  "targeted_expansion_attempt_refs": [],
  "macro_fallback_used": false,
  "structural_unanswerability_proof_ref": null,
  "classification_dispatch_allowed": true
}
```

## Phase 0: Anchor and Dependency Gate

Goal: verify Session 3 ownership and dependency status.

Pseudocode:

```python
owned = ["QDT-001", "QDT-002", "QDT-003", "QDT-004", "QDT-005", "MODEL-002",
         "RET-001", "RET-002", "RET-003", "RET-004", "RET-005", "RET-006",
         "RET-007", "RET-010", "RET-011", "RET-009", "RET-008"]

for feature_id in owned:
    assert inventory.owner(feature_id) == "Session 3"

if mode == "runtime_integration":
    assert_done("FND-003")
    assert_done("CTX-001")
    assert_done("POL-003")
    assert_done_or_waived("AMRG-002")
    assert_done("MODEL-001")
```

Tests:

- Static: all owned rows exist.
- Gate: integration blocks when upstream artifacts are absent.
- Gate: fixture-mode allows stub inputs with explicit fixture refs.

Checklist:

- [ ] Inventory status updated for active rows.
- [ ] Mode declared as fixture or runtime integration.
- [ ] Any missing upstream dependencies recorded.

## Phase 1: Decomposer Handoff Contract

Goal: define how the decomposer receives inputs without stuffing large artifact payloads into prompts.

Implementation tasks:

- Pass absolute artifact paths and manifest IDs.
- Pass SHA-256 digests.
- Pass compact summaries only where required.
- Resolve the `decomposer_qdt_generation` model lane from `plans/autonomous-decomposition-swarm-model-lane-policy.json`.
- Include evidence packet, AMRG artifact/waiver, regime/profile context, market metadata, and current market-implied probability.
- Forbid decomposer access to SCAE outputs, synthesis conclusions, decision packets, raw resolved outcomes, and evaluator labels.

Pseudocode:

```python
def build_decomposer_handoff(case_context):
    required = [
        "ads_case_contract_manifest",
        "evidence_packet_manifest",
        "related_market_context_manifest_or_waiver",
        "effective_profile_context_manifest",
    ]
    for key in required:
        assert case_context[key].validation_status == "valid"
    return {
        "case_id": case_context.case_id,
        "dispatch_id": case_context.dispatch_id,
        "macro_question": case_context.market_title,
        "model_execution_context": resolve_model_lane("decomposer_qdt_generation"),
        "artifact_refs": manifest_refs(required),
        "artifact_digests": digest_map(required),
        "forbidden_refs": ["scae", "synthesis", "decision", "outcomes", "evaluator_labels"],
    }

def resolve_model_lane(lane_id):
    policy = read_json("plans/autonomous-decomposition-swarm-model-lane-policy.json")
    lane = policy["lanes"][lane_id]
    return {
        "model_lane_id": lane_id,
        "resolved_model_id": lane["default_model_id"],
        "model_policy_ref": policy["policy_id"],
        "required_artifact_fields": lane["required_artifact_fields"],
    }
```

Testing suite:

- Unit: missing or invalid ADS case contract blocks decomposer handoff.
- Unit: missing evidence packet blocks handoff.
- Unit: invalid AMRG artifact requires waiver or blocks.
- Unit: handoff includes paths and digests.
- Unit: handoff resolves `decomposer_qdt_generation` to `gpt-5.5-high`.
- Unit: handoff records model policy ref and prompt template hash requirement.
- Security: forbidden refs are not present.

Completion checklist:

- [x] Handoff schema written.
- [x] Decomposer model lane resolution written.
- [x] Required input refs listed.
- [x] Forbidden input refs listed.
- [x] `QDT-001` and `MODEL-002` inventory rows updated.

## Phase 2: QDT Schema and Candidate Selection Contract

Goal: define the selected depth-2 tree as the canonical task contract.

Implementation tasks:

- Define branches and required leaves.
- Define leaf budget decision.
- Define static information weights and dependency groups.
- Define required evidence purposes.
- Define per-leaf high-certainty research sufficiency requirements.
- Define canonical machine-readable output constraints: enum fields, stable IDs, schema refs, prompt hash, no free-form probability text, and compact reason codes.
- Define related-market context usage.
- Define branch sub-ledger requirement when leaf budget exceeds compact default.

Pseudocode:

```python
def build_qdt_candidates(handoff):
    components = extract_market_components(handoff.evidence_packet)
    amrg_hints = read_amrg_hints(handoff.related_market_context)
    purposes = required_purposes_for(components, handoff.profile_context)
    sufficiency_policy = resolve_research_sufficiency_policy(handoff.profile_context)
    candidates = []
    for strategy in search_strategies(policy):
        tree = propose_depth2_tree(components, purposes, amrg_hints, strategy)
        attach_research_sufficiency_requirements(tree, sufficiency_policy)
        candidates.append(tree)
    return candidates

def attach_research_sufficiency_requirements(tree, sufficiency_policy):
    for leaf in tree.required_leaf_questions:
        leaf.research_sufficiency_requirements = sufficiency_policy.requirements_for(
            purpose=leaf.purpose,
            static_information_weight=leaf.bayesian_weighting.static_information_weight,
            condition_scope=leaf.leaf_condition_scope,
        )

def select_qdt(candidates):
    valid = [c for c in candidates if validate_qdt_structure(c).valid]
    scored = [(score_qdt(c), c) for c in valid]
    return max(scored)[1]
```

Testing suite:

- Unit: no valid candidate fails dispatch preparation.
- Unit: selected QDT has at least one branch and required leaves.
- Unit: every leaf has parent branch, purpose, condition scope, dependency group, and weight.
- Unit: every leaf has research sufficiency requirements.
- Unit: critical/source-of-truth leaves require protected primary or explicit structural unanswerability proof.
- Unit: QDT schema rejects prose-only leaves without machine-readable sufficiency fields.
- Unit: large leaf budget sets `hierarchical_branch_ledger_required`.
- Regression: decomposer does not produce sub-forecast probabilities.
- Regression: QDT artifact records resolved model ID and prompt template hash.

Completion checklist:

- [ ] QDT schema written.
- [ ] Candidate selection audit fields written.
- [ ] Leaf budget decision fields written.
- [ ] Research sufficiency requirement fields written.
- [ ] Canonical machine-readable QDT template fields enforced.
- [ ] `QDT-002` inventory row updated.
- [ ] `QDT-005` inventory row updated.

## Phase 3: Deterministic QDT Structural Validation

Goal: validate leaf clarity and Causal Proximity Framework constraints without an LLM adversarial validator.

Implementation tasks:

- Validate depth exactly two unless waiver exists.
- Validate every required leaf question is answerable or intentionally marked unanswerable policy candidate.
- Validate required purposes are covered.
- Validate every leaf has a research sufficiency requirement block.
- Validate critical/source-of-truth leaves cannot permit macro fallback as sufficient research.
- Validate market reality constraints digest matches evidence packet.
- Validate no probability fields exist.
- Validate condition-scoped leaves reference valid anchor contracts when applicable.

Pseudocode:

```python
def validate_qdt_structure(qdt, evidence_packet):
    errors = []
    if max_depth(qdt) != 2:
        errors.append("invalid_depth")
    if contains_probability_field(qdt):
        errors.append("probability_field_forbidden")
    for leaf in qdt.required_leaf_questions:
        if not leaf.question_text or not leaf.purpose:
            errors.append(("leaf_incomplete", leaf.leaf_id))
        if not leaf.research_sufficiency_requirements:
            errors.append(("research_sufficiency_requirements_missing", leaf.leaf_id))
        if leaf.bayesian_weighting.static_information_weight == "critical":
            if leaf.research_sufficiency_requirements.allow_macro_fallback_for_leaf:
                errors.append(("critical_leaf_macro_fallback_forbidden", leaf.leaf_id))
        if leaf.leaf_condition_scope != "unconditional":
            assert_valid_condition_scope(leaf, qdt.amrg_anchor_dependency_contracts)
    if missing_required_purposes(qdt, evidence_packet):
        errors.append("required_purpose_coverage_missing")
    return ValidationResult(errors)
```

Testing suite:

- Unit: depth-3 tree rejected.
- Unit: leaf probability field rejected.
- Unit: missing required purpose rejected or policy-waived.
- Unit: invalid condition scope rejected.
- Unit: unanswerable critical leaf has explicit policy consequence.
- Unit: missing research sufficiency requirements rejected.
- Unit: critical leaf allowing macro fallback rejected.

Completion checklist:

- [ ] Structural validator implemented or specified.
- [ ] No-LLM validator rule documented.
- [ ] Negative fixtures written.
- [ ] `QDT-003` inventory row updated.
- [ ] `QDT-005` validation cases included.

## Phase 4: AMRG Anchor Dependency Contract

Goal: make AMRG-derived conditional branches explicit and bounded.

Implementation tasks:

- Record edge IDs used by decomposition.
- Classify anchor dependency as `diagnostic_only`, `anchor_optional`, or `anchor_required`.
- Define fallback branch policy.
- Define repair budget and repair exhaustion policy.
- Require condition-scoped leaves for conditional branch math.

Pseudocode:

```python
def build_anchor_dependency_contract(edge, qdt_branch):
    if edge.status not in ["strict_precedence_anchor_candidate", "validated_strict_precedence_anchor"]:
        return {"anchor_mode": "diagnostic_only"}
    return {
        "anchor_dependency_contract_id": make_id(edge, qdt_branch),
        "edge_id": edge.edge_id,
        "conditional_branch_group_id": make_branch_group_id(edge),
        "anchor_mode": choose_anchor_mode(edge, qdt_branch),
        "condition_scoped_leaf_ids": find_condition_scoped_leaves(qdt_branch),
        "fallback_policy": derive_fallback_policy(qdt_branch),
        "max_anchor_repair_attempts": policy.max_anchor_repair_attempts,
        "max_anchor_repair_wall_clock_seconds": policy.max_anchor_repair_wall_clock_seconds,
        "repair_exhaustion_policy": "watch_only_if_forecastable|fail_dispatch_preparation",
    }
```

Testing suite:

- Unit: weak AMRG edge cannot create anchor-required contract.
- Unit: anchor-required without fallback or repair policy rejected.
- Unit: condition-scoped leaves required for conditional math.
- Unit: repair budget fields required.
- Integration: Session 5 can consume contract fixture for SCAE conditional branch negative test.

Completion checklist:

- [ ] Anchor dependency schema written.
- [ ] Fallback/repair/exhaustion fields included.
- [ ] Condition-scoped leaf requirements included.
- [ ] `QDT-004` inventory row updated.

## Phase 5: Retrieval Packet Schema and Query Planning

Goal: turn required leaves into retrieval tasks and selected evidence items.

Implementation tasks:

- Define per-leaf retrieval query context.
- Use leaf text, branch label, purpose, market-component terms, market constraints digest, required evidence fields, and AMRG hints.
- Include research sufficiency requirements as retrieval constraints, not as prompt-only hints.
- Execute GPT-5.5 native research for query variants when the configured runtime exposes native research, and materialize candidate citations through `native-research-attempt/v1`.
- Execute OpenClaw `web_fetch` / browser retrieval when available: direct official/resolution URL capture first, then bounded browser web-search/site-search/followed-link expansion, and materialize browser captures through `browser-retrieval-attempt/v1`.
- Resolve source metadata through deterministic resolver stages before any candidate can count toward breadth.
- Keep `parent_branch_id` as audit join key, not semantic query text.
- Produce selected evidence and omitted candidate records.

Pseudocode:

```python
def build_retrieval_queries(qdt, evidence_packet, amrg_context):
    queries = []
    for leaf in qdt.required_leaf_questions:
        breadth_profile = build_retrieval_breadth_profile(
            leaf=leaf,
            evidence_packet=evidence_packet,
            policy=resolve_retrieval_policy(qdt.policy_context_ref),
        )
        query = {
            "leaf_id": leaf.leaf_id,
            "query_variants": compose_query_variants(
                macro=qdt.macro_question,
                leaf=leaf.question_text,
                purpose=leaf.purpose,
                market_terms=leaf.market_component_terms,
                constraints=evidence_packet.market_reality_constraints,
                amrg_hints=allowed_amrg_hints(amrg_context, leaf),
                breadth_profile=breadth_profile,
            ),
            "condition_scope": leaf.leaf_condition_scope,
            "sufficiency_requirements": leaf.research_sufficiency_requirements,
            "breadth_profile_ref": breadth_profile.profile_id,
            "contradiction_query_variants": breadth_profile.contradiction_search.query_variants,
            "negative_check_query_variants": breadth_profile.negative_checks.query_variants_by_check,
        }
        queries.append(query)
    return queries

def run_browser_retrieval_for_query(query, browser_policy):
    provider = resolve_browser_provider("openclaw_web_fetch_browser", browser_policy)
    write_browser_search_provider_diagnostic(provider)

    attempts = []
    if provider.supports("direct_url"):
        direct_urls = official_or_resolution_urls_for_query(query)
        for direct_url in direct_urls:
            attempts.append(
                browser_direct_capture(
                    direct_url,
                    provider=provider,
                    navigation_mode="direct_url",
                    direct_url_source_ref=direct_url.source_ref,
                    source_cutoff=query["source_cutoff_timestamp"],
                )
            )

    direct_candidates = [materialize_candidate_from_browser_attempt(a) for a in attempts]
    if enough_candidates(direct_candidates, query):
        return direct_candidates

    if not provider.supports("web_search"):
        return direct_candidates

    for variant in query["query_variants"]:
        attempts.extend(
            browser_search_and_capture(
                variant,
                provider=provider,
                navigation_mode="web_search",
                max_results=browser_policy.max_results_per_variant,
                source_cutoff=query["source_cutoff_timestamp"],
            )
        )
    return [materialize_candidate_from_browser_attempt(a) for a in attempts]

def run_native_research_for_query(query, model_policy):
    lane = resolve_model_lane("native_research_candidate_discovery", model_policy)
    attempt = native_research(
        lane=lane,
        prompt_template_id="native-gpt-research/v1",
        query_manifest=query,
        forbidden_outputs=[
            "probability",
            "source_metadata_final_authority",
            "research_sufficiency_certification",
        ],
    )
    return [materialize_candidate_from_native_research(c) for c in attempt.candidate_citation_refs]

def classify_source_metadata_candidate(candidate, model_policy):
    lane = resolve_model_lane("source_metadata_classifier_assist", model_policy)
    compact_packet = build_compact_source_candidate_packet(candidate)
    return source_metadata_classifier(
        lane=lane,
        prompt_template_id="source-metadata-classifier/v1",
        candidate_packet=compact_packet,
        max_excerpt_chars=1200,
        forbidden_outputs=[
            "probability",
            "scae_evidence_delta",
            "research_sufficiency_certification",
        ],
    )

def materialize_evidence_candidates(query, policy):
    candidates = []
    if policy.browser_retrieval_enabled:
        candidates.extend(run_browser_retrieval_for_query(query, policy.browser_policy))
    if policy.native_gpt_research_enabled and not enough_candidates(candidates, query):
        candidates.extend(run_native_research_for_query(query, policy.model_policy))
    resolved = []
    for candidate in candidates:
        classifier_slice = maybe_classify_source_metadata_candidate(candidate, policy.model_policy)
        claim_candidates = extract_atomic_claim_candidates(
            candidate,
            classifier_slice=classifier_slice,
            max_excerpt_chars=policy.claim_parser_excerpt_cap,
        )
        claim_resolutions = resolve_claim_families(claim_candidates, policy.claim_family_policy)
        source_metadata = resolve_source_metadata(
            candidate,
            classifier_slice=classifier_slice,
            claim_family_resolution_refs=[r.claim_family_resolution_id for r in claim_resolutions],
        )
        resolved.append(materialize_retrieval_evidence(candidate, source_metadata, claim_resolutions))
    return resolved
```

Testing suite:

- Unit: every required leaf gets at least one query or explicit unanswerable/minimal-authoritative status.
- Unit: every query includes sufficiency requirements.
- Unit: every query includes a breadth profile ref and source-class/claim-family/source-family targets.
- Unit: contradiction and negative-check query variants are present when the breadth profile requires them.
- Unit: browser retrieval writes attempt refs and materializes candidates without treating the browser as the source.
- Unit: native GPT research writes attempt refs and materializes citations without granting final metadata authority to model-proposed labels.
- Unit: source metadata classifier writes compact slices with resolved `gpt-5.4-mini` model lane provenance.
- Unit: high-confidence classifier source class can count for ordinary non-protected sources only when deterministic evidence does not contradict it.
- Unit: classifier source-family hint cannot become final family unless URL/domain/registry/publisher/syndication evidence supports it.
- Unit: classifier claim tuple creates a claim-family ID only through deterministic normalization and hashing.
- Unit: model-assisted claim extraction without supporting span refs becomes `unknown_not_counted`.
- Unit: composite article text with multiple market-relevant claims is split into separate atomic claim candidates or rejected before family assignment.
- Unit: claim-family resolution stores normalized tuple hash and candidate refs.
- Unit: classifier visible date cannot pass temporal safety until deterministic parsing and source-cutoff validation succeed.
- Unit: classifier output cannot satisfy protected-primary/source-of-truth or market rules/resolution-source requirements by itself.
- Unit: metadata resolver writes `unknown_not_counted` when no deterministic resolver stage supports a proposed class/family/timestamp.
- Unit: AMRG hints cannot inject probability or other model conclusion.
- Unit: parent branch ID is preserved as metadata.
- Unit: query text includes condition scope when applicable.

Completion checklist:

- [ ] Retrieval packet schema written.
- [ ] Query construction rules written.
- [ ] Native GPT research attempt schema and model-lane invocation written.
- [ ] Browser retrieval attempt schema and capture normalization written.
- [ ] Source metadata classifier schema, OpenAI OAuth model-lane invocation, and acceptance/rejection rules written.
- [ ] Source metadata resolver schema and deterministic resolver stages written.
- [ ] Retrieval evidence item schema written.
- [ ] Evidence chunk/span schema written.
- [ ] Atomic claim candidate schema written.
- [ ] Claim-family resolution schema written.
- [ ] Omitted candidate fields written.
- [ ] `RET-001` inventory row updated.

## Phase 6: Temporal Isolation and Provenance

Goal: make every retrieval result forecast-time safe and SCAE-ready.

Implementation tasks:

- Enforce authored timestamps, DB row timestamps, external `published_at`, source cutoff, and manifest digests.
- For browser captures, record `captured_at`, extracted `published_at`, extraction method, final/canonical URL, content hashes, and browser session ref.
- For native GPT research candidates, record attempt refs, model lane provenance, citation refs, snippets/hashes, model-proposed metadata, and post-resolver accepted metadata.
- Browser `captured_at` and `artifact_generated_at` may be at forecast time if the capture is part of live retrieval, but source eligibility must be evaluated from `source_published_at`, `source_updated_at`, source-specific snapshot/observation time, market-contract cutoff rules, and explicit live-capture allowlist status.
- Treat filesystem mtime as warning only.
- Block same-case post-dispatch artifacts.
- Whitelist pre-dispatch inputs.
- Create source, claim-family, source-family, independence, content hash, and temporal gate fields.

Pseudocode:

```python
def validate_temporal_eligibility(candidate, dispatch):
    if candidate.artifact_generated_at >= dispatch.forecast_timestamp:
        if not candidate.retrieval_capture_for_dispatch:
            return reject("post_dispatch_artifact_not_from_live_retrieval")
    source_times = [
        candidate.source_published_at,
        candidate.source_updated_at,
        candidate.source_observed_at,
        candidate.db_row_created_at,
    ]
    if any(ts >= dispatch.source_cutoff_timestamp for ts in source_times if ts):
        if not source_time_allowed_by_market_contract(candidate, dispatch):
            return reject("source_after_cutoff")
    if not any(source_times):
        return unknown_not_counted("source_time_unknown")
    if candidate.filesystem_mtime and candidate.filesystem_mtime >= dispatch.forecast_timestamp:
        warn("mtime_after_forecast_timestamp")
    return accept()

def normalize_retrieval_provenance(candidate):
    classifier_slice = candidate.classifier_slice_ref and load_classifier_slice(candidate.classifier_slice_ref)
    claim_candidates = extract_atomic_claim_candidates(
        candidate,
        classifier_slice=classifier_slice,
        chunk_refs=candidate.chunk_refs,
    )
    claim_resolutions = resolve_claim_families(claim_candidates)
    metadata = resolve_source_metadata(
        candidate,
        classifier_slice=classifier_slice,
        claim_family_resolution_refs=[r.claim_family_resolution_id for r in claim_resolutions],
    )
    source_class = classify_source_class(
        metadata,
        source_registry=active_source_registry(),
        market_rules=candidate.market_rules_ref,
    )
    source_family = canonical_source_family(
        metadata,
        publisher_registry=active_publisher_registry(),
        syndication_registry=active_syndication_registry(),
    )
    return {
        "retrieval_transport": candidate.transport,  # browser|native_gpt_research|structured_feed|db|manual_fixture
        "browser_attempt_ref": candidate.browser_attempt_ref,
        "native_research_attempt_ref": candidate.native_research_attempt_ref,
        "source_metadata_resolution_ref": metadata.resolution_id,
        "source_metadata_classifier_ref": classifier_slice.classifier_slice_id if classifier_slice else None,
        "atomic_claim_candidate_refs": [c.claim_candidate_id for c in claim_candidates],
        "claim_family_resolution_refs": [r.claim_family_resolution_id for r in claim_resolutions],
        "classifier_acceptance_status": metadata.classifier_acceptance_status,
        "metadata_confidence": metadata.metadata_confidence,
        "unknown_reason_codes": metadata.unknown_reason_codes,
        "requested_url": candidate.requested_url,
        "final_url": candidate.final_url,
        "canonical_url": candidate.canonical_url,
        "captured_at": candidate.captured_at,
        "artifact_generated_at": candidate.artifact_generated_at,
        "source_published_at": candidate.source_published_at,
        "source_updated_at": candidate.source_updated_at,
        "source_observed_at": candidate.source_observed_at,
        "published_at_extraction_method": candidate.published_at_extraction_method,
        "canonical_source_id": canonical_source(candidate),
        "source_class": source_class,
        "event_source_family": source_family,
        "claim_family_ids": [r.claim_family_id for r in claim_resolutions if r.counts_toward_claim_family_breadth],
        "claim_family_creation_method": "candidate_validated_then_deterministic_tuple_hash",
        "source_family_status": source_family_status(candidate),
        "independence_status": independence_status(candidate),
        "content_sha256": sha256(candidate.content),
        "temporal_gate_status": validate_temporal_eligibility(candidate),
    }
```

Testing suite:

- Unit: post-forecast source rejected.
- Unit: browser capture at dispatch time can pass only when the page content is eligible under source cutoff rules.
- Unit: browser `artifact_generated_at` after forecast passes only when it is an explicit live retrieval capture and source time is cutoff-eligible.
- Unit: unknown source time becomes `unknown_not_counted` for freshness-critical leaves.
- Unit: native GPT citation with unsupported proposed source class becomes `unknown_not_counted`.
- Unit: classifier accepted source-class is recorded with classifier slice ref and acceptance reason codes.
- Unit: classifier-proposed protected-primary status without deterministic proof becomes `classifier_unsupported` and does not count.
- Unit: browser final/canonical URL is stored and used for source identity, not the search result URL alone.
- Unit: mtime warning does not alone reject.
- Unit: whitelisted pre-dispatch artifact passes.
- Unit: same claim across leaves gets same claim family ID.
- Unit: different claims from same official source can remain distinct claim families.
- Unit: same syndicated wire copy across multiple publishers maps to one source family.
- Unit: mirrored API endpoints map to one source family.
- Unit: same article reached through browser search, direct URL, and redirected URL deduplicates by canonical URL/content hash.
- Unit: unknown source class cannot satisfy `official_or_primary` or `market_rules_or_resolution_source`.
- Unit: contradictory polarity over the same object maps to a related contradiction family, not independent corroboration.

Completion checklist:

- [ ] Temporal validator written.
- [ ] Provenance fields written.
- [ ] Claim-family deterministic normalization written.
- [ ] `RET-002` and `RET-004` inventory rows updated.

## Phase 7: Retrieval Breadth Profile and Coverage

Goal: prove retrieval breadth before research sufficiency certification. Breadth is measured by source class, claim family, source family, freshness, contradiction search, negative checks, and protected-primary handling.

Implementation tasks:

- Build `retrieval-breadth-profile/v1` for every leaf from QDT sufficiency requirements and profile context.
- Write compact breadth coverage slices for every leaf.
- Require explicit contradiction-search attempts when the profile requires them.
- Require explicit negative-check attempts for absence, cancellation, non-occurrence, no official confirmation, or equivalent leaf-specific checks.
- Enforce protected-primary handling: critical/source-of-truth leaves cannot pass without primary/source-of-truth access or a structural unanswerability proof.
- Treat duplicate same-claim or same-source-family material as non-independent for breadth.
- Preserve raw candidate counts and admitted-ref counts as diagnostics, but certify breadth only from classified families and required source classes.
- Compute metadata-fill diagnostics by leaf and transport before breadth certification.
- Block or expand when unknown source-class/source-family/claim-family/temporal fields prevent required breadth from being satisfied.

Pseudocode:

```python
def evaluate_retrieval_breadth(leaf, admitted, attempts, profile):
    coverage = {
        "source_class_coverage": coverage_by_source_class(admitted),
        "claim_family_count": count_independent_claim_families(admitted),
        "source_family_count": count_independent_source_families(admitted),
        "fresh_source_count": count_fresh_sources(admitted, profile.freshness_requirement),
        "contradiction_attempt_refs": contradiction_attempt_refs(attempts),
        "negative_check_attempt_refs": negative_check_attempt_refs(attempts),
        "protected_primary_status": protected_primary_status(admitted, attempts, profile),
        "metadata_fill": metadata_fill_diagnostics(admitted),
    }
    coverage["unsatisfied_breadth_dimensions"] = missing_breadth_dimensions(profile, coverage)
    coverage["breadth_certified"] = not coverage["unsatisfied_breadth_dimensions"]
    return coverage

def certify_leaf_research_sufficiency(leaf, admitted, retrieval_state):
    breadth = evaluate_retrieval_breadth(
        leaf,
        admitted,
        retrieval_state.attempts,
        retrieval_state.breadth_profile_for(leaf.leaf_id),
    )
    if not breadth["breadth_certified"]:
        retrieval_state.add_unsatisfied_requirements(breadth["unsatisfied_breadth_dimensions"])
    return certify_against_requirements(leaf, admitted, retrieval_state, breadth)
```

Testing suite:

- Unit: five sources repeating the same atomic claim produce one claim family and do not pass claim-family diversity.
- Unit: five outlets republishing the same wire/API payload produce one source family and do not pass source-family diversity.
- Unit: official/source-of-truth requirement cannot be satisfied by secondary summaries.
- Unit: time-sensitive leaf requires at least one admitted source inside the recency window.
- Unit: contradiction-search attempt is recorded even when no contradiction is found.
- Unit: required negative checks are recorded with query text, source refs, and no-confirmation outcome.
- Unit: protected-primary failure on a critical/source-of-truth leaf blocks normal certification unless structural unanswerability proof is present.
- Unit: high unknown source-class or temporal-safety rate triggers expansion or prevents freshness/source-class certification.

Completion checklist:

- [ ] `retrieval-breadth-profile/v1` schema written.
- [ ] Breadth coverage slice schema written.
- [ ] Contradiction-search attempt record written.
- [ ] Negative-check attempt record written.
- [ ] Source-class/source-family/claim-family classification tests written.
- [ ] Metadata fill-rate diagnostics written.
- [ ] `RET-011` and `RET-009` inventory rows updated.

## Phase 8: Retrieval Quality, Source Access, Missingness, Fallback, and Model Preflight

Goal: give downstream SCAE structured quality and missingness inputs without overclaiming.

Implementation tasks:

- Score retrieval quality per leaf.
- Track source-class coverage and protected-primary access failures.
- Track expected-source missingness candidates.
- Implement bounded starvation expansion.
- Implement high-certainty sufficiency scoring against the QDT leaf requirements and breadth coverage.
- Implement macro fallback only as a marked last-resort evidence-discovery path, not as sufficient research for critical/source-of-truth leaves.
- Define local embedding/reranker preflight and resource caps.

Pseudocode:

```python
def score_retrieval_quality(leaf_results, policy):
    score = 1.0
    if leaf_results.selected_count == 0:
        score -= policy.empty_penalty
    if leaf_results.protected_primary_access_failed:
        score -= policy.protected_primary_penalty
    if leaf_results.stale_ratio > policy.stale_ratio_threshold:
        score -= policy.stale_penalty
    return clamp(score, 0.0, 1.0)

def retrieval_with_fallback(query):
    candidates = bi_encoder_search(query, top_k=policy.bi_encoder_top_k)
    if thin(candidates):
        candidates += bounded_expansion(query, attempts=policy.starvation_attempts)
    admitted = cross_encoder_rerank(candidates[:policy.cross_encoder_admission_cap])
    if empty(admitted) and macro_fallback_allowed(query):
        return macro_fallback(query)
    return admitted

def certify_leaf_research_sufficiency(leaf, admitted, retrieval_state):
    requirements = leaf.research_sufficiency_requirements
    breadth = evaluate_retrieval_breadth(
        leaf,
        admitted,
        retrieval_state.attempts,
        retrieval_state.breadth_profile_for(leaf.leaf_id),
    )
    coverage = evaluate_requirements(requirements, admitted, retrieval_state)
    coverage.include_breadth(breadth)
    while not coverage.high_certainty and retrieval_state.attempts < requirements.max_targeted_expansion_attempts:
        attempt = targeted_expansion(leaf, coverage.unsatisfied_requirements)
        retrieval_state.record_attempt(attempt)
        admitted += cross_encoder_rerank(attempt.candidates)
        breadth = evaluate_retrieval_breadth(leaf, admitted, retrieval_state.attempts,
                                             retrieval_state.breadth_profile_for(leaf.leaf_id))
        coverage = evaluate_requirements(requirements, admitted, retrieval_state)
        coverage.include_breadth(breadth)

    if coverage.high_certainty:
        return certificate(leaf, coverage_status="certified_high_certainty",
                           classification_dispatch_allowed=True)
    if can_prove_structural_unanswerability(leaf, coverage, retrieval_state):
        return certificate(leaf, coverage_status="expansion_exhausted_structurally_unanswerable",
                           structural_unanswerability_proof_ref=make_unanswerability_ref(leaf, coverage),
                           classification_dispatch_allowed=True)
    return certificate(leaf, coverage_status="blocked_insufficient_research",
                       classification_dispatch_allowed=False)

def preflight_local_models():
    assert embedding_model_loads()
    assert reranker_model_loads()
    assert long_context_smoke_test(policy.cross_encoder_top_k)
```

Testing suite:

- Unit: empty retrieval triggers expansion before fallback.
- Unit: fallback is flagged, not hidden.
- Unit: thin retrieval cannot receive `certified_high_certainty`.
- Unit: breadth coverage failure prevents `certified_high_certainty`.
- Unit: critical/source-of-truth leaf with unresolved protected primary remains blocked after expansion.
- Unit: structural unanswerability requires expansion exhaustion and proof ref.
- Unit: researcher dispatch is blocked when any required leaf certificate has `classification_dispatch_allowed=false`.
- Unit: protected-primary access failure produces dedicated slice.
- Unit: retrieval quality score lowers confidence but does not create signed evidence.
- Unit: cross-encoder admission cap enforced.
- Preflight: embedding and reranker smoke tests pass or block live retrieval.

Completion checklist:

- [ ] Retrieval quality scoring written.
- [ ] Source access failures written.
- [ ] Missingness candidate tracking written.
- [ ] Starvation expansion and fallback written.
- [ ] High-certainty sufficiency certificate written.
- [ ] Targeted expansion attempt records written.
- [ ] Local model preflight written.
- [ ] `RET-003`, `RET-005`, `RET-006`, `RET-007`, `RET-011`, `RET-009`, and `RET-008` inventory rows updated.

## Phase 9: Research Sufficiency Dispatch Gate

Goal: prevent researcher classification from starting until each leaf has enough research to answer with high certainty, or a structurally unanswerable leaf has been proven after bounded expansion.

Implementation tasks:

- Build one sufficiency certificate per required leaf.
- Persist expansion attempts and unsatisfied requirement codes.
- Set `classification_dispatch_status` on the retrieval packet.
- Reject `classification_dispatch_status=allowed` if any required certificate is missing, blocked, stale, temporally invalid, or macro-fallback-only for a critical/source-of-truth leaf.
- Emit stage status and `stage_blocked` execution events through Session 1 contracts when dispatch is blocked by insufficient research.

Pseudocode:

```python
def finalize_retrieval_packet(qdt, retrieval_packet):
    certificates = []
    for leaf in qdt.required_leaf_questions:
        cert = certify_leaf_research_sufficiency(
            leaf,
            retrieval_packet.evidence_for(leaf.leaf_id),
            retrieval_packet.state_for(leaf.leaf_id),
        )
        certificates.append(cert)

    if all(c.classification_dispatch_allowed for c in certificates):
        retrieval_packet.research_sufficiency_summary = {
            "all_required_leaves_certified": True,
            "classification_dispatch_status": "allowed",
            "leaf_certificate_refs": [c.certificate_id for c in certificates],
        }
    else:
        retrieval_packet.research_sufficiency_summary = {
            "all_required_leaves_certified": False,
            "classification_dispatch_status": "blocked_insufficient_research",
            "leaf_certificate_refs": [c.certificate_id for c in certificates],
        }
        write_stage_status("retrieval", status="blocked",
                           reason_code="research_sufficiency_not_met")
        write_stage_execution_event(
            stage="retrieval",
            event_type="stage_blocked",
            reason_code="research_sufficiency_not_met",
            replay_command=replay_retrieval_command(retrieval_packet),
        )
    return retrieval_packet
```

Testing suite:

- Unit: missing certificate blocks classification dispatch.
- Unit: macro fallback alone cannot satisfy critical/source-of-truth leaf.
- Unit: missing or failed breadth coverage blocks classification dispatch.
- Unit: certificate with post-forecast evidence fails temporal isolation and blocks dispatch.
- Unit: expansion attempts are persisted with unsatisfied requirement codes.
- Integration: fixture with initially thin retrieval expands to a certified packet before Session 4 prompt rendering.

Completion checklist:

- [ ] Per-leaf certificate schema written.
- [ ] Packet-level dispatch status written.
- [ ] Insufficient-research stage status/execution/error path written.
- [ ] Session 4 handoff requires certificate refs.
- [ ] `RET-008` inventory row updated.

## End-to-End Completion Checklist

- [ ] Decomposer handoff uses artifact paths and digests.
- [ ] QDT schema validates fixture tree.
- [ ] QDT structural validator rejects invalid trees.
- [ ] QDT leaves carry research sufficiency requirements.
- [ ] AMRG anchor dependency contract supports optional, diagnostic, and repair-required modes.
- [ ] Retrieval packet schema validates fixture evidence.
- [ ] Temporal isolation rejects invalid evidence.
- [ ] Claim-family and source-family provenance are present.
- [ ] Source-class, claim-family, and source-family identity rules are deterministic and conservative.
- [ ] Retrieval breadth profiles and coverage slices are present.
- [ ] Contradiction and negative-check attempts are present when required.
- [ ] Retrieval quality slices are present.
- [ ] Protected-primary and missingness candidate records are present.
- [ ] Fallback and model preflight behavior is defined.
- [ ] High-certainty research sufficiency certificates are present before researcher dispatch.
- [ ] All Session 3 inventory rows have handoff artifacts and acceptance evidence.
