# Session 02 Plan: Evidence Packet, Policy Context, and AMRG

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

- Section 1.1: AMRG boundaries, family-market write boundary, tuning profile boundaries.
- Section 3.1 to 3.3.1: case selection, evidence packet, AMRG.
- Section 10: AMRG, market family, regime, and profile persistence.
- Section 11.2 and 11.2.1: prior reliability inputs and profile resolution.
- Section 17.1: evidence packet and AMRG migration surfaces.
- Section 18.1: v2 live cutover blockers.

## Mission

Produce the pre-decomposition context required for v2: evidence packet v2, family-aware binary child contract context, prior-reliability inputs, deterministic regime/profile context, and AMRG artifacts that are input-only for decomposition/retrieval/SCAE.

This session must not create evidence deltas, author probabilities, select the QDT, or use model-only AMRG outputs for stronger-than-weak effects.

## Runtime Script Placement

Session 2 builds the real-market intake passover, evidence packet, policy context, and AMRG context inside Orchestrator because these artifacts are pipeline-management inputs created before specialist agents run. Place Session 2 scripts under `/Users/agent2/.openclaw/orchestrator/scripts` and add any new path to `plans/autonomous-decomposition-swarm-script-placement-map.md` before implementation.

Planned Session 2 paths:

```text
/Users/agent2/.openclaw/orchestrator/scripts/bin/build_ads_case_contract.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/ads_case_contract.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/build_evidence_packet_v2.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/evidence_packet.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/resolve_tuning_profile_context.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/tuning_profile.py
/Users/agent2/.openclaw/orchestrator/scripts/bin/build_related_live_market_context.py
/Users/agent2/.openclaw/orchestrator/scripts/predquant/amrg.py
```

Ownership boundaries:

- Orchestrator creates these pre-decomposition artifacts and then wakes ADS Decomposer.
- Session 2 AMRG code may nominate context and validated anchor candidates, but it must not select the QDT, spawn researchers, or write SCAE evidence deltas.
- Local AMRG vectorization belongs in `/Users/agent2/.openclaw/orchestrator/scripts/predquant/amrg.py` and must remain non-blocking.

## Owned Inventory Rows

Directly owned rows:

- `CASE-001`: existing case pipeline source adapter over `markets` and `market_snapshots`.
- `CASE-002`: ADS case contract artifact and dispatch/snapshot binding.
- `CTX-001`: evidence packet v2 contract.
- `CTX-002`: family-aware binary child metadata.
- `CTX-003`: prior-reliability input surfaces.
- `POL-001`: tunable registry metadata contract.
- `POL-002`: deterministic market-regime tags.
- `POL-003`: `effective_tuning_profile_context.json`.
- `MODEL-001`: model lane policy artifact with `gpt-5.5-high` decomposer/researcher/native-research defaults plus the OpenAI OAuth-routed `gpt-5.4-mini` source metadata classifier assist lane.
- `AMRG-001`: active-safe candidate pool.
- `AMRG-009`: local Ollama-routed AMRG vector index and weak-context neighbor candidates.
- `AMRG-002`: `related-live-market-context.json` or waiver.
- `AMRG-003`: relationship typing and timing alignment.
- `AMRG-004`: advisory model-assist packet and output schema.
- `AMRG-005`: relationship, graph-safety, refresh slices.
- `AMRG-006`: refresh lifecycle and stale downgrade.
- `AMRG-007`: shared retrieval/classification cache eligibility.
- `AMRG-008`: strict-precedence anchor validation.

## Coordination Rules

1. Update only Session 2 rows directly.
2. If Session 3 needs additional QDT anchor fields, propose the dependency in the inventory instead of editing Session 3 rows.
3. If Session 5 needs additional SCAE prior-anchor fields, propose them in the inventory and mark `AMRG-008` blocked until agreed.
4. AMRG integration work must check `FND-002`, `FND-003`, and `FND-004` first.
5. Fixture-mode work can proceed with stub manifests and generated fixture inputs, but runtime integration cannot proceed until the foundation rows are done.
6. Every phase must record handoff artifact paths and schema names in the inventory.
7. Model IDs for decomposer, researcher, native research discovery, AMRG model assist, and AMRG vector embedding work must resolve through `plans/autonomous-decomposition-swarm-model-lane-policy.json`; do not hardcode model IDs inside runtime business logic.
8. AMRG vector search is a non-blocking candidate source. If the local Ollama route, `BAAI/bge-base-en-v1.5` model, embedding preflight, or vector index is unavailable, record a structured diagnostic and continue with deterministic candidate sources and waiver behavior.

## Migration and Write Path Ownership

Session 2 owns `MIG-012` for existing intake-to-case-contract records and `MIG-005` for AMRG records. It also contributes context fields used by `MIG-007`, `MIG-008`, and `MIG-011`. Runtime integration is blocked until these records have named tables, schemas, or explicit artifact contracts in Session 1's migration matrix.

Required write paths:

```text
write_evidence_packet_v2
write_case_intake_handoff
write_ads_case_contract
write_market_family_context
write_prior_reliability_inputs
write_effective_tuning_profile_context
write_related_market_context
write_amrg_vector_descriptors
write_amrg_vector_index_snapshot
write_amrg_vector_neighbor_candidates
write_amrg_refresh_event
```

The AMRG write path must store related-market candidates, vector index snapshots, vector-neighbor candidates, edge type, relationship status, timing validation, graph-safety status, anchor eligibility, refresh lifecycle state, model-assist provenance, and allowed downstream effects. These records are for decomposition context, risk diagnostics, and later tuning of AMRG usefulness; they must not write SCAE evidence deltas or probabilities.

## Technical Specification

### ADS Case Contract

The ADS case contract is the canonical entry artifact for real markets already present in the existing intake system. It is produced before the evidence packet and is consumed by evidence packet construction, AMRG, decomposition, forecast persistence, replay, and scoring.

Minimum contract:

```json
{
  "artifact_type": "ads_case_contract",
  "schema_version": "ads-case-contract/v1",
  "case_key": "polymarket:...",
  "case_id": "case-...",
  "dispatch_id": "dispatch-...",
  "prediction_run_id": "ads-run-...",
  "forecast_artifact_id": "forecast-...",
  "forecast_timestamp": "...",
  "source_cutoff_timestamp": "...",
  "intake_source": {
    "system": "predquant_sqlite",
    "db_path_ref": "PREDQUANT_SQLITE_PATH|scripts/data/predquant.sqlite3",
    "source_tables": ["markets", "market_snapshots"],
    "market_row_id": 0,
    "market_snapshot_id": 0,
    "snapshot_observed_at": "...",
    "source_payload_hash": "sha256:...",
    "ingestion_runner": "ingest_polymarket_market_snapshots",
    "ingestion_schema_version": "polymarket-snapshot-ingester/v1"
  },
  "market_identity": {
    "platform": "polymarket",
    "internal_market_id": 0,
    "external_market_id": "...",
    "slug": "...",
    "title": "...",
    "description": "...",
    "category": "...",
    "status": "open",
    "outcome_type": "binary",
    "closes_at": "...",
    "resolves_at": "..."
  },
  "prediction_time_market_baseline": {
    "market_snapshot_id": 0,
    "source_fetched_at": "...",
    "snapshot_age_seconds_at_dispatch": 0.0,
    "max_snapshot_age_seconds": 3600.0,
    "market_probability": 0.5,
    "market_probability_method": "bid_ask_midpoint|yes_price|last_price|current_price"
  },
  "raw_input_refs": [],
  "downstream_artifact_refs": {
    "evidence_packet": null,
    "related_live_market_context": null,
    "question_decomposition": null,
    "retrieval_packet": null,
    "verification_bundle": null,
    "scae_ledger": null,
    "forecast_decision": null,
    "market_prediction_row": null
  }
}
```

### Evidence Packet V2

Minimum contract:

```json
{
  "artifact_type": "evidence_packet",
  "schema_version": "evidence-packet/v2",
  "case_contract_ref": "artifact:ads-case-contract/...",
  "case_id": "case-...",
  "market_id": "poly-...",
  "dispatch_id": "dispatch-...",
  "forecast_timestamp": "...",
  "market_identity": {},
  "market_reality_constraints": {
    "side_mapping": {},
    "source_of_truth_status": "clear|ambiguous|unknown",
    "contract_structure": "binary|family_aware_binary_child|other",
    "close_timestamp": "...",
    "resolve_timestamp": "..."
  },
  "family_context": {
    "mode": "family_aware_binary_child|standalone_binary|unknown",
    "parent_event_id": null,
    "selected_child_market_id": "...",
    "sibling_child_ids": [],
    "family_type": "exclusive|range|ordered|cumulative|negative_risk|none|unknown",
    "relation_constraints": [],
    "sibling_prices": [],
    "family_validation_flags": []
  },
  "prior_context_seed": {
    "market_live_probability": null,
    "market_snapshot_timestamp": "...",
    "quote_observation_refs": [],
    "microstructure_input_refs": [],
    "market_priced_through_timestamp": null
  },
  "regime_seed_fields": {},
  "active_safe_refs": {}
}
```

### Policy and Profile Context

The central registry owns metadata, not live math. Subsystems continue to own their policy files.

The concrete model-lane policy artifact is:

```text
plans/autonomous-decomposition-swarm-model-lane-policy.json
```

It defines:

- `decomposer_qdt_generation.default_model_id = "gpt-5.5-high"`
- `researcher_leaf_nli_classification.default_model_id = "gpt-5.5-high"`
- `native_research_candidate_discovery.default_model_id = "gpt-5.5-high"` with native research/browsing capability required and final metadata authority forbidden
- `source_metadata_classifier_assist.default_provider_model_key = "openai/gpt-5.4-mini"` routed through OpenAI OAuth for compact metadata classification, with bounded authority and protected-primary/temporal-safety final authority forbidden
- `amrg_model_assist.default_model_id = "gpt-5.4-high"` with `gpt-5.5-high` allowed as a future promoted value
- SCAE deterministic aggregation uses no model lane

Resolver output:

```json
{
  "artifact_type": "effective_tuning_profile_context",
  "schema_version": "effective-tuning-profile-context/v1",
  "global_baseline_profile_id": "global_baseline_profile",
  "intended_domain_profile_id": "geopolitics_catalyst_deadline_profile",
  "domain_profile_activation_status": "global_baseline_only_under_threshold",
  "active_domain_profile_id": null,
  "conservative_overlay_ids": [],
  "subsystem_policy_slices": {
    "scae": {},
    "retrieval": {},
    "decomposer": {},
    "decision": {}
  },
  "excluded_domain_tags": [],
  "profile_pointer_refs": [],
  "effective_policy_sha256": "sha256:..."
}
```

### AMRG Contract

AMRG materializes `related-live-market-context.json` after the evidence packet and profile context and before decomposition.

Allowed AMRG effects:

```text
decomposition_hint
retrieval_hint
duplicate_diagnostic
family_diagnostic
source_of_truth_check
portfolio_warning
sibling_refresh_recommendation
rerun_recommendation
conditional_prior_candidate
```

Forbidden AMRG effects:

```text
probability_override
scae_evidence_delta
qdt_selection
concept_creation
external_graph_promotion
decision_probability_override
```

## Phase 0: Anchor and Dependency Gate

Goal: confirm this session can proceed and does not depend on missing foundation contracts.

Pseudocode:

```python
owned = ["CASE-001", "CASE-002",
         "CTX-001", "CTX-002", "CTX-003", "POL-001", "POL-002", "POL-003", "MODEL-001",
         "AMRG-001", "AMRG-002", "AMRG-003",
         "AMRG-004", "AMRG-005", "AMRG-006", "AMRG-007", "AMRG-008", "AMRG-009"]

for feature_id in owned:
    assert inventory.owner(feature_id) == "Session 2"

if mode == "runtime_integration":
    assert_done("FND-002")
    assert_done("FND-003")
    assert_done("FND-004")
```

Tests:

- Static: all owned feature IDs are present and owned by Session 2.
- Static: `CASE-001` and `CASE-002` have downstream consumers in `CTX-001`, `PERSIST-002`, and replay/scoring.
- Static: every AMRG row has explicit downstream consumers.
- Gate: runtime integration blocks if foundation rows are not ready.

Checklist:

- [ ] Inventory status moved to `in_progress` for active rows.
- [ ] Any missing dependency added as proposed inventory change.
- [ ] Fixture mode versus runtime integration mode declared.

## Phase 1: ADS Case Contract From Existing Intake

Goal: take a real market already present in the existing intake system and produce the canonical ADS case contract.

Implementation tasks:

- Read eligible active rows from existing `markets`.
- Select the latest `market_snapshots` row with `observed_at <= forecast_timestamp`.
- Reject or block when no snapshot exists, when the snapshot is after forecast time, or when the snapshot exceeds the configured age policy.
- Generate stable `case_key`, `case_id`, `dispatch_id`, `prediction_run_id`, and `forecast_artifact_id`.
- Record source tables, row IDs, raw payload/source hash, `source_cutoff_timestamp`, and snapshot baseline probability method.
- Register the contract in the artifact manifest and write the Session 2 intake handoff record.

Pseudocode:

```python
def build_ads_case_contract(market_row, snapshot_row, forecast_timestamp, policy):
    assert market_row["status"] in {"open", "active"}
    assert snapshot_row["observed_at"] <= forecast_timestamp
    snapshot_age = age_seconds(snapshot_row["observed_at"], forecast_timestamp)
    if snapshot_age > policy.max_snapshot_age_seconds:
        return block("case_contract_snapshot_stale")
    market_probability, method = market_probability_from_snapshot(snapshot_row, market_row["current_price"])
    contract = {
        "artifact_type": "ads_case_contract",
        "schema_version": "ads-case-contract/v1",
        "case_key": f"{market_row['platform']}:{market_row['external_market_id']}",
        "case_id": stable_case_id(market_row),
        "dispatch_id": stable_dispatch_id(market_row, forecast_timestamp),
        "prediction_run_id": stable_prediction_run_id(market_row, forecast_timestamp),
        "forecast_artifact_id": stable_forecast_artifact_id(market_row, forecast_timestamp),
        "forecast_timestamp": forecast_timestamp,
        "source_cutoff_timestamp": snapshot_row["observed_at"],
        "intake_source": intake_source_refs(market_row, snapshot_row),
        "market_identity": market_identity_from_row(market_row),
        "prediction_time_market_baseline": {
            "market_snapshot_id": snapshot_row["id"],
            "source_fetched_at": snapshot_row["observed_at"],
            "snapshot_age_seconds_at_dispatch": snapshot_age,
            "max_snapshot_age_seconds": policy.max_snapshot_age_seconds,
            "market_probability": market_probability,
            "market_probability_method": method,
        },
    }
    validate_schema("ads-case-contract/v1", contract)
    write_case_intake_handoff(contract)
    return write_ads_case_contract(contract)
```

Testing suite:

- Unit: a `markets` row plus latest pre-forecast `market_snapshots` row creates a valid case contract.
- Unit: post-forecast snapshot is rejected.
- Unit: stale snapshot blocks runtime case contract creation with `case_contract_snapshot_stale`.
- Unit: contract IDs are stable and idempotent for the same market and forecast timestamp.
- Unit: contract records source table names, row IDs, source payload hash, and snapshot probability method.
- Integration: one real SQLite fixture market becomes an artifact-manifested ADS case contract.

Completion checklist:

- [ ] Existing intake source adapter written.
- [ ] `ads-case-contract/v1` schema written.
- [ ] Dispatch/prediction/forecast artifact identity rules written.
- [ ] Snapshot freshness/cutoff validation written.
- [ ] Raw intake provenance fields written.
- [ ] `CASE-001` and `CASE-002` inventory rows updated.

## Phase 2: Evidence Packet V2 and Family Context

Goal: produce a deterministic market/contract/source/current-state artifact for downstream context.

Implementation tasks:

- Define evidence-packet v2 schema.
- Add family-aware binary child fields.
- Add side/axis mapping and source-of-truth status.
- Add quote/probability provenance refs.
- Add regime seed fields.
- Add validation for family-aware selected child versus sibling context.

Pseudocode:

```python
def build_evidence_packet_v2(case_contract, market_snapshot, family_rows, quote_refs):
    packet = EvidencePacketV2(
        case_contract_ref=case_contract.artifact_ref,
        case_id=case_contract.case_id,
        market_id=case_contract.market_identity.internal_market_id,
        forecast_timestamp=case_contract.forecast_timestamp,
        market_identity=extract_market_identity(case_contract),
        market_reality_constraints=extract_constraints(case_contract, market_snapshot),
        family_context=build_family_context(case_contract, family_rows),
        prior_context_seed=build_prior_seed(market_snapshot, quote_refs),
        regime_seed_fields=derive_regime_seed(case_contract, market_snapshot),
    )
    validate(packet)
    return write_artifact(packet)

def validate_family_context(packet):
    if packet.family_context.mode == "family_aware_binary_child":
        assert packet.family_context.selected_child_market_id
        assert packet.family_context.parent_event_id
        assert packet.family_context.relation_constraints
```

Testing suite:

- Unit: standalone binary packet validates without sibling context.
- Unit: family-aware packet rejects missing selected child.
- Unit: family-aware packet carries sibling prices only as context.
- Unit: invalid side mapping fails closed.
- Unit: missing or invalid case contract blocks evidence packet creation.
- Integration: fixture packet registers artifact manifest.

Completion checklist:

- [ ] Evidence packet v2 schema exists.
- [ ] Family-aware selected-child mode covered.
- [ ] Prior seed refs included.
- [ ] Regime seed fields included.
- [ ] `CTX-001` and `CTX-002` inventory rows updated.

## Phase 3: Prior Reliability Inputs

Goal: materialize inputs SCAE will later use for prior reliability without computing SCAE probability.

Implementation tasks:

- Define rolling microstructure summary fields.
- Prefer quote observations over one-off prompt scraping.
- Carry market snapshot freshness and priced-through timestamp.
- Carry reason-code candidates, not final SCAE reliability unless policy permits.

Pseudocode:

```python
def build_prior_reliability_inputs(market_id, forecast_timestamp):
    window = load_quote_observations(market_id, lookback_policy)
    summary = {
        "bid_ask_spread_twap": twap(window.spread),
        "order_book_depth_twap": twap(window.depth),
        "recent_volume_rolling": rolling_volume(window),
        "last_trade_age_seconds_rolling": age_seconds(window.last_trade_at),
        "market_snapshot_freshness": freshness(window.latest_snapshot_at, forecast_timestamp),
        "microstructure_spoofing_check_status": spoofing_check(window),
        "market_priced_through_timestamp": infer_priced_through(window),
    }
    return summary
```

Testing suite:

- Unit: stale snapshot produces stale reason candidate.
- Unit: fresh liquid market produces fresh/liquid candidate.
- Unit: one instant spread spike alone is only a warning candidate.
- Unit: missing quote observations produce unavailable status.
- Contract: no SCAE posterior probability is computed here.

Completion checklist:

- [x] Prior-reliability input schema exists.
- [x] Rolling window fields covered.
- [x] Priced-through timestamp represented.
- [x] `CTX-003` inventory row updated.

## Phase 4: Tunable Registry, Regime Tags, and Effective Profile Context

Goal: produce deterministic policy context before decomposition/retrieval/SCAE without creating a hidden model loop.

Implementation tasks:

- Define tunable registry metadata schema.
- Define and validate the model-lane policy artifact.
- Define deterministic market-regime tag slices.
- Implement profile context resolver defaulting to `global_baseline_profile`.
- Allow only promoted active overlays and conservative risk-reducing overlays.
- Record intended domain profile for learning even when inactive.

Pseudocode:

```python
def materialize_market_regime_tags(evidence_packet):
    return {
        "domain_family": classify_domain(evidence_packet.regime_seed_fields),
        "contract_type": classify_contract(evidence_packet.market_reality_constraints),
        "market_state": classify_market_state(evidence_packet.prior_context_seed),
        "evidence_environment": classify_evidence_environment(evidence_packet),
        "liquidity_regime": classify_liquidity(evidence_packet.prior_context_seed),
        "resolution_proximity": classify_resolution_proximity(evidence_packet),
    }

def resolve_tuning_profile_context(tags, registry, active_pointers, lane_health):
    intended = map_tags_to_candidate_domain_profile(tags)
    active = active_pointers.get(intended) if gates_pass(intended, lane_health) else None
    overlays = eligible_conservative_overlays(tags, active_pointers)
    return EffectiveProfileContext(
        global_baseline_profile_id="global_baseline_profile",
        intended_domain_profile_id=intended,
        active_domain_profile_id=active,
        conservative_overlay_ids=overlays,
        subsystem_policy_slices=resolve_subsystem_slices(active, overlays),
    )

def validate_model_lane_policy(policy):
    assert policy["lanes"]["decomposer_qdt_generation"]["default_model_id"] == "gpt-5.5-high"
    assert policy["lanes"]["researcher_leaf_nli_classification"]["default_model_id"] == "gpt-5.5-high"
    assert policy["lanes"]["native_research_candidate_discovery"]["default_model_id"] == "gpt-5.5-high"
    assert policy["lanes"]["native_research_candidate_discovery"]["native_research_capability_required"] is True
    assert policy["lanes"]["source_metadata_classifier_assist"]["default_model_id"] == "gpt-5.4-mini"
    assert policy["lanes"]["source_metadata_classifier_assist"]["default_provider_model_key"] == "openai/gpt-5.4-mini"
    assert policy["lanes"]["source_metadata_classifier_assist"]["provider"] == "openai"
    assert policy["lanes"]["source_metadata_classifier_assist"]["oauth_route_required"] is True
    assert "protected_primary_final_authority" in policy["lanes"]["source_metadata_classifier_assist"]["forbidden_outputs"]
    assert "temporal_safety_final_authority" in policy["lanes"]["source_metadata_classifier_assist"]["forbidden_outputs"]
    assert policy["authority_boundary"]["scae_numeric_aggregation_uses_model"] is False
    assert policy["local_embedding_lanes"]["amrg_vector_embedding"]["provider"] == "ollama"
    assert policy["local_embedding_lanes"]["amrg_vector_embedding"]["default_model_id"] == "BAAI/bge-base-en-v1.5"
    for lane in policy["lanes"].values():
        assert "resolved_model_id" in lane["required_artifact_fields"]
        assert "prompt_template_sha256" in lane["required_artifact_fields"]
    for lane in policy["local_embedding_lanes"].values():
        assert "resolved_model_id" in lane["required_artifact_fields"]
        assert "descriptor_sha256" in lane["required_artifact_fields"]
```

Testing suite:

- Unit: unknown domain resolves to global baseline plus optional conservative overlay.
- Unit: sports/crypto price tags are excluded from active initial domain profiles.
- Unit: inactive candidate domain profile is recorded as intended but not active.
- Unit: profile resolver cannot author numeric weights outside subsystem policy slices.
- Unit: model-lane policy validates `gpt-5.5-high` defaults for decomposer, researcher, and native research discovery lanes, and the OpenAI OAuth-routed `gpt-5.4-mini` default for source metadata classifier assist.
- Unit: native research discovery lane forbids final source metadata authority, probability output, and SCAE deltas.
- Unit: model-lane policy validates local Ollama `BAAI/bge-base-en-v1.5` for AMRG vector embeddings.
- Unit: model-lane policy marks SCAE model usage as false.
- Integration: effective profile context artifact registers manifest and hash.

Completion checklist:

- [x] Tunable registry metadata schema exists.
- [x] Model-lane policy artifact exists and validates.
- [x] Regime tag slices defined.
- [x] Profile context artifact defined.
- [x] Default global baseline behavior verified.
- [x] `POL-001`, `POL-002`, `POL-003`, and `MODEL-001` inventory rows updated.

## Phase 5: AMRG Local Vector Index

Goal: make vector-neighbor candidate discovery concrete, local, replayable, and non-blocking.

Implementation tasks:

- Resolve `amrg_vector_embedding` from `plans/autonomous-decomposition-swarm-model-lane-policy.json`.
- Route embedding calls through the local Ollama route `ollama/local`.
- Ensure the implementation bootstrap includes the download contract `ollama pull BAAI/bge-base-en-v1.5`.
- Build deterministic active-market descriptor documents from active-safe fields only.
- Persist descriptor hashes, model/route provenance, source cutoff timestamp, embedding dimension, and index snapshot ID.
- Query vector neighbors by cosine similarity under configured caps.
- Emit vector neighbors as candidate-source rows only; every vector-only candidate starts as `weak_context_only`.
- If Ollama, the BGE model, embedding generation, or the vector index is unavailable, record `amrg_vector_candidate_source_unavailable` and continue with deterministic candidate construction. This must not block `related-live-market-context.json`, the no-related-context waiver, decomposition, retrieval, SCAE, or decision.

Descriptor contract:

```json
{
  "artifact_type": "amrg_market_vector_descriptor",
  "schema_version": "amrg-market-vector-descriptor/v1",
  "market_id": "...",
  "case_key": "...",
  "source_cutoff_timestamp": "...",
  "active_safe_fields": {
    "title": "...",
    "description_or_rules": "...",
    "normalized_entities": [],
    "contract_terms": [],
    "source_of_truth_kind": "...",
    "family_context_tokens": [],
    "close_timestamp": "...",
    "resolve_timestamp": "...",
    "market_state_tags": []
  },
  "descriptor_text": "compact deterministic descriptor text",
  "descriptor_sha256": "sha256:..."
}
```

Index snapshot contract:

```json
{
  "artifact_type": "amrg_vector_index_snapshot",
  "schema_version": "amrg-vector-index-snapshot/v1",
  "embedding_lane_id": "amrg_vector_embedding",
  "provider": "ollama",
  "route_id": "ollama/local",
  "resolved_model_id": "BAAI/bge-base-en-v1.5",
  "model_policy_ref": "plans/autonomous-decomposition-swarm-model-lane-policy.json",
  "embedding_model_sha256": "sha256:...",
  "embedding_dimension": 768,
  "similarity_metric": "cosine",
  "source_cutoff_timestamp": "...",
  "descriptor_schema_version": "amrg-market-vector-descriptor/v1",
  "index_snapshot_id": "amrg-vector-index:...",
  "index_status": "ready|unavailable|degraded",
  "unavailable_reason": null
}
```

Pseudocode:

```python
def ensure_amrg_vector_model(policy):
    lane = resolve_local_embedding_lane("amrg_vector_embedding")
    assert lane["provider"] == "ollama"
    assert lane["default_model_id"] == "BAAI/bge-base-en-v1.5"
    if not ollama_model_available(lane["default_model_id"]):
        result = try_ollama_pull(lane["default_model_id"])
        if not result.ok:
            return unavailable("ollama_bge_model_unavailable", result.reason)
    return ready(lane)

def build_active_market_descriptor(market, source_cutoff):
    active_safe = extract_active_safe_market_fields(market, source_cutoff)
    descriptor_text = canonical_descriptor_text(active_safe)
    return {
        "schema_version": "amrg-market-vector-descriptor/v1",
        "market_id": market.market_id,
        "source_cutoff_timestamp": source_cutoff,
        "active_safe_fields": active_safe,
        "descriptor_text": descriptor_text,
        "descriptor_sha256": sha256(descriptor_text),
    }

def refresh_amrg_vector_index(active_market_index, source_cutoff, policy):
    model = ensure_amrg_vector_model(policy)
    if not model.ok:
        write_amrg_vector_index_snapshot(status="unavailable", reason=model.reason)
        return unavailable_vector_source(model.reason)

    descriptors = [
        build_active_market_descriptor(market, source_cutoff)
        for market in active_market_index.markets
        if is_active_safe_for_amrg(market, source_cutoff)
    ]
    embeddings = ollama_embed(
        model_id=model.resolved_model_id,
        texts=[d["descriptor_text"] for d in descriptors],
    )
    write_amrg_vector_descriptors(descriptors)
    snapshot = build_vector_index_snapshot(descriptors, embeddings, model)
    write_amrg_vector_index_snapshot(snapshot)
    return snapshot

def bounded_vector_neighbors(case, vector_index_snapshot, cap):
    if not vector_index_snapshot or vector_index_snapshot.index_status != "ready":
        write_amrg_vector_neighbor_candidates(case.case_key, [], source_status="unavailable")
        return []

    query = build_active_market_descriptor(case.market, case.forecast_timestamp)
    query_embedding = ollama_embed(
        model_id=vector_index_snapshot.resolved_model_id,
        texts=[query["descriptor_text"]],
    )[0]
    neighbors = vector_index_snapshot.search(query_embedding, metric="cosine", top_k=cap)
    candidates = [
        make_vector_neighbor_candidate(
            neighbor,
            query_descriptor_sha256=query["descriptor_sha256"],
            relationship_status="weak_context_only",
            candidate_source="local_bge_vector_neighbor",
        )
        for neighbor in neighbors
        if neighbor.market_id != case.market_id and neighbor.score >= policy.vector_min_similarity
    ]
    write_amrg_vector_neighbor_candidates(case.case_key, candidates)
    return candidates
```

Testing suite:

- Unit: model-lane policy resolves `amrg_vector_embedding` to provider `ollama`, route `ollama/local`, and model `BAAI/bge-base-en-v1.5`.
- Unit: missing local model invokes the configured pull contract before marking unavailable.
- Unit: Ollama/model/index unavailable writes `amrg_vector_candidate_source_unavailable` and does not block deterministic AMRG candidates.
- Unit: descriptor builder rejects inactive, resolved, post-cutoff, replay/outcome, or unsafe fields.
- Unit: descriptor text and hash are deterministic for the same active-safe market fields.
- Unit: vector-only candidates are always `weak_context_only`.
- Integration: ready vector index writes index snapshot and capped neighbor candidate rows with model/route/hash provenance.

Completion checklist:

- [x] `amrg_vector_embedding` local embedding lane exists in the model-lane policy artifact.
- [x] Ollama download/wiring contract for `BAAI/bge-base-en-v1.5` is documented.
- [x] Descriptor schema and deterministic hashing are specified.
- [x] Descriptor write path is specified.
- [x] Index snapshot schema is specified.
- [x] Vector-neighbor candidate write path is specified.
- [x] Unavailable model/index path is non-blocking and records diagnostics.
- [x] `AMRG-009` inventory row updated.

## Phase 6: AMRG Candidate Pool and Weak-Context Artifact

Goal: produce `related-live-market-context.json` or a no-related-context waiver.

Implementation tasks:

- Build deterministic/indexed candidate set first.
- Refresh or load the local AMRG vector index as an optional candidate source.
- Cap candidate pool size.
- Record candidate set ID, source policy, input manifest hash, exclusion counts, and timing inputs.
- Produce weak-context edges unless promotion validation proves stronger use.
- Produce explicit waiver when no active-safe related context exists.

Pseudocode:

```python
def build_related_live_market_context(case, evidence_packet, active_market_index, exposure_context):
    candidates = []
    candidates += platform_family_candidates(evidence_packet.family_context)
    candidates += active_market_entity_matches(case, active_market_index)
    candidates += contract_source_matches(case, active_market_index)
    candidates += shared_resolution_source_matches(case, active_market_index)
    candidates += current_exposure_matches(case, exposure_context)
    vector_index = refresh_amrg_vector_index(active_market_index, case.forecast_timestamp, policy)
    candidates += bounded_vector_neighbors(case, vector_index, cap=policy.vector_neighbor_cap)
    candidates = dedupe_and_cap(candidates, policy.candidate_pool_max)

    if not candidates:
        return no_related_context_waiver(case, reason="empty_active_safe_candidate_pool")

    edges = [make_weak_edge(candidate) for candidate in candidates]
    return RelatedLiveMarketContext(candidate_set_id=make_id(candidates), relationship_edges=edges)
```

Testing suite:

- Unit: no candidates produces explicit waiver.
- Unit: candidate cap is enforced.
- Unit: resolved/past markets are excluded unless masked analog support.
- Unit: generic theme candidate remains weak context only.
- Unit: vector source unavailable still produces deterministic candidates or an explicit no-related-context waiver.
- Integration: artifact validates and registers manifest.

Completion checklist:

- [ ] Candidate construction implemented or specified.
- [ ] Waiver artifact implemented or specified.
- [ ] Candidate cap enforced.
- [ ] Weak-context default enforced.
- [ ] Vector source availability/unavailability is recorded without blocking AMRG.
- [ ] `AMRG-001`, `AMRG-002`, and `AMRG-009` inventory rows updated.

## Phase 7: AMRG Typing, Timing, Model Assist, and Persistence

Goal: enrich candidate edges while preserving advisory and active-safe boundaries.

Implementation tasks:

- Add relationship type vocabulary.
- Add relationship status vocabulary.
- Add timing-alignment status and basis refs.
- Add model-assist packet contract and output schema.
- Add relationship, graph-safety, refresh, and model-enrichment persistence surfaces.

Pseudocode:

```python
def type_and_validate_edge(edge, evidence_packet, timing_inputs):
    edge.relationship_types = deterministic_relationship_types(edge)
    edge.timing_alignment_status = compare_timing(
        selected_snapshot=evidence_packet.prior_context_seed.market_snapshot_timestamp,
        related_snapshot=edge.related_market_snapshot_as_of,
        event_windows=edge.event_driver_windows,
        close_resolve_times=edge.close_resolve_times,
    )
    edge.allowed_effects = allowed_effects_for(edge)
    edge.forbidden_effects = forbidden_effects_for(edge)
    return edge

def run_model_assist_if_allowed(context):
    assert context.candidate_set
    packet = build_active_safe_model_packet(context)
    assert packet.input_manifest_sha256
    output = call_model_assist(packet)
    schema_validate("amrg-model-assist-output/v1", output)
    return attach_advisory_output(output)
```

Testing suite:

- Unit: model output with probability field is rejected.
- Unit: model-only candidate remains weak context.
- Unit: missing active-safe manifest downgrades model-assisted edges.
- Unit: timing mismatch prevents stronger effects.

Completion checklist:

- [ ] Relationship type/status vocabularies implemented.
- [ ] Timing-alignment fields implemented.
- [ ] Model-assist advisory schema implemented.
- [ ] Persistence surfaces mapped to Section 10.
- [ ] `AMRG-003`, `AMRG-004`, and `AMRG-005` inventory rows updated.

## Phase 8: AMRG Refresh, Reuse, and Strict-Precedence Anchors

Goal: support downstream safety features without letting AMRG become a second forecast engine.

Implementation tasks:

- Refresh-first lifecycle with conservative downgrade.
- Graph-safety and cycle handling for causal-prior candidates.
- Shared retrieval/classification reuse eligibility, temporal provenance only.
- Strict-precedence anchor candidate validation and audit records.

Pseudocode:

```python
def refresh_related_market_context(edge, material_change):
    refreshed = try_refresh(edge, budget=policy.refresh_budget)
    if refreshed.ok:
        return refreshed.edge
    return downgrade(edge, target_status="weak_context_only", reason="refresh_budget_exhausted")

def validate_strict_precedence_anchor(edge, qdt_contract):
    assert edge.status == "strict_precedence_anchor_candidate"
    assert edge.relationship_type == "causal_upstream"
    assert strict_event_time_or_contractual_precedence(edge)
    assert graph_is_acyclic(edge.graph_component_id)
    assert qdt_contract.has_condition_scoped_leaves(edge.edge_id)
    return make_prior_anchor_slice(edge, validation_status="validated")

def can_reuse_shared_cache(entry, consuming_dispatch):
    return (
        entry.leaf_condition_scope == consuming_dispatch.leaf_condition_scope
        and entry.contract_scope == consuming_dispatch.contract_scope
        and entry.max_underlying_source_timestamp < consuming_dispatch.forecast_timestamp
    )
```

Testing suite:

- Unit: refresh failure downgrades promoted effect.
- Unit: cyclic or concurrent causal relationship cannot become prior anchor.
- Unit: anchor candidate without QDT condition-scoped leaves is rejected.
- Unit: shared cache without temporal provenance is rejected or source-hint-only.
- Unit: AMRG never writes SCAE evidence deltas.

Completion checklist:

- [ ] Refresh lifecycle specified.
- [ ] Graph-safety validation specified.
- [ ] Shared reuse eligibility specified.
- [ ] Strict-precedence anchor validation specified.
- [ ] `AMRG-006`, `AMRG-007`, and `AMRG-008` inventory rows updated.

## End-to-End Completion Checklist

- [ ] Existing intake market/snapshot fixture becomes a valid `ads-case-contract/v1`.
- [ ] Case contract records dispatch identity, source cutoff, snapshot binding, source table/row refs, and raw payload hash.
- [ ] Evidence packet v2 fixture validates.
- [ ] Family-aware binary child context validates.
- [ ] Prior-reliability inputs are present and non-authoritative.
- [ ] Regime tags and profile context validate with global baseline default.
- [ ] AMRG vector index uses Ollama-routed `BAAI/bge-base-en-v1.5` when available.
- [ ] AMRG vector unavailable/degraded state records diagnostics and does not block the pipeline.
- [ ] AMRG no-related-context waiver works.
- [ ] AMRG weak-context artifact works.
- [ ] AMRG model assist is advisory only.
- [ ] AMRG refresh downgrades stale effects safely.
- [ ] AMRG reuse enforces consuming-dispatch temporal eligibility.
- [ ] AMRG strict-precedence anchors require QDT/SCAE dependencies and cannot be used prematurely.
- [ ] All Session 2 inventory rows have handoff artifacts and acceptance evidence.
