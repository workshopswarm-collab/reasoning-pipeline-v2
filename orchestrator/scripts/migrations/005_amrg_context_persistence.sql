PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS amrg_candidate_sets (
  candidate_set_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  source_policy TEXT NOT NULL,
  candidate_pool_max INTEGER NOT NULL,
  candidate_count INTEGER NOT NULL,
  exclusion_counts TEXT NOT NULL DEFAULT '{}',
  input_manifest_sha256 TEXT NOT NULL,
  artifact_path TEXT,
  artifact_sha256 TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_candidate_sets_case
  ON amrg_candidate_sets(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_amrg_candidate_sets_market
  ON amrg_candidate_sets(market_id, forecast_timestamp);

CREATE TABLE IF NOT EXISTS amrg_candidate_peer_rows (
  candidate_id TEXT PRIMARY KEY,
  candidate_set_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  selected_market_id TEXT NOT NULL,
  related_market_id TEXT NOT NULL,
  candidate_rank INTEGER NOT NULL,
  nomination_methods TEXT NOT NULL DEFAULT '[]',
  relationship_type_proposals TEXT NOT NULL DEFAULT '[]',
  directionality_proposal TEXT NOT NULL,
  timing_input_refs TEXT NOT NULL DEFAULT '[]',
  snapshot_as_of TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_candidate_peer_rows_case
  ON amrg_candidate_peer_rows(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_amrg_candidate_peer_rows_related
  ON amrg_candidate_peer_rows(related_market_id);

CREATE TABLE IF NOT EXISTS amrg_market_vector_descriptors (
  descriptor_sha256 TEXT PRIMARY KEY,
  market_id TEXT NOT NULL,
  external_market_id TEXT,
  case_key TEXT,
  source_cutoff_timestamp TEXT NOT NULL,
  descriptor_schema_version TEXT NOT NULL,
  descriptor_text TEXT NOT NULL,
  active_safe_fields TEXT NOT NULL DEFAULT '{}',
  generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_amrg_market_vector_descriptors_market
  ON amrg_market_vector_descriptors(market_id, source_cutoff_timestamp);

CREATE TABLE IF NOT EXISTS amrg_vector_index_snapshots (
  index_snapshot_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  embedding_lane_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  route_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  model_policy_ref TEXT NOT NULL,
  embedding_model_sha256 TEXT NOT NULL,
  embedding_dimension INTEGER NOT NULL,
  similarity_metric TEXT NOT NULL,
  source_cutoff_timestamp TEXT NOT NULL,
  descriptor_schema_version TEXT NOT NULL,
  descriptor_count INTEGER NOT NULL,
  descriptor_sha256s TEXT NOT NULL DEFAULT '[]',
  index_status TEXT NOT NULL,
  unavailable_reason TEXT,
  diagnostic TEXT NOT NULL DEFAULT '{}',
  generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_amrg_vector_index_snapshots_cutoff
  ON amrg_vector_index_snapshots(source_cutoff_timestamp, index_status);

CREATE TABLE IF NOT EXISTS amrg_vector_neighbor_candidate_slices (
  vector_neighbor_candidate_id TEXT PRIMARY KEY,
  candidate_set_id TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  market_id TEXT NOT NULL,
  external_market_id TEXT,
  relationship_status TEXT NOT NULL,
  similarity_score REAL NOT NULL,
  similarity_metric TEXT NOT NULL,
  query_descriptor_sha256 TEXT NOT NULL,
  candidate_descriptor_sha256 TEXT NOT NULL,
  index_snapshot_id TEXT NOT NULL,
  embedding_lane_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_vector_neighbor_candidate_slices_case
  ON amrg_vector_neighbor_candidate_slices(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_amrg_vector_neighbor_candidate_slices_snapshot
  ON amrg_vector_neighbor_candidate_slices(index_snapshot_id);

CREATE TABLE IF NOT EXISTS amrg_model_assist_provenance (
  model_assist_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  candidate_set_id TEXT NOT NULL,
  model_assist_status TEXT NOT NULL,
  model_id TEXT NOT NULL,
  input_manifest_sha256 TEXT NOT NULL,
  output_artifact_ref TEXT,
  forbidden_output_check_status TEXT NOT NULL,
  invoked_at TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS related_market_relationship_slices (
  relationship_slice_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  selected_market_id TEXT NOT NULL,
  related_market_id TEXT NOT NULL,
  related_case_key TEXT,
  related_pipeline_state TEXT NOT NULL,
  candidate_set_id TEXT NOT NULL,
  candidate_rank INTEGER NOT NULL,
  candidate_generation_methods TEXT NOT NULL DEFAULT '[]',
  candidate_pool_input_manifest_sha256 TEXT NOT NULL,
  model_assist_status TEXT NOT NULL,
  model_assist_context TEXT NOT NULL DEFAULT '{}',
  relationship_types TEXT NOT NULL DEFAULT '[]',
  relationship_strength TEXT NOT NULL,
  shared_causal_driver_tier TEXT NOT NULL,
  directionality TEXT NOT NULL,
  concrete_shared_objects TEXT NOT NULL DEFAULT '{}',
  causal_influence_fingerprint TEXT,
  relationship_valid_before_forecast INTEGER NOT NULL DEFAULT 0,
  selected_market_snapshot_as_of TEXT,
  related_market_snapshot_as_of TEXT,
  max_snapshot_skew_seconds INTEGER,
  timing_alignment_status TEXT NOT NULL,
  evidence_basis TEXT NOT NULL DEFAULT '[]',
  source_policy TEXT NOT NULL,
  allowed_effects TEXT NOT NULL DEFAULT '[]',
  forbidden_effects TEXT NOT NULL DEFAULT '[]',
  related_market_snapshot_pricing TEXT NOT NULL DEFAULT '{}',
  causal_graph_status TEXT NOT NULL,
  guardrail_status TEXT NOT NULL,
  guardrail_reason_codes TEXT NOT NULL DEFAULT '[]',
  artifact_path TEXT,
  artifact_sha256 TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_related_market_relationship_slices_case
  ON related_market_relationship_slices(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_related_market_relationship_slices_edge
  ON related_market_relationship_slices(edge_id);
CREATE INDEX IF NOT EXISTS idx_related_market_relationship_slices_market
  ON related_market_relationship_slices(market_id, related_market_id);

CREATE TABLE IF NOT EXISTS amrg_causal_graph_safety_slices (
  graph_safety_slice_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  graph_component_id TEXT NOT NULL,
  causal_edge_role TEXT NOT NULL,
  topological_rank INTEGER,
  event_time_ordering_basis TEXT,
  strict_precedence_proof_ref TEXT,
  cycle_status TEXT NOT NULL,
  cycle_break_reason TEXT,
  max_refresh_hop_depth INTEGER NOT NULL,
  refresh_generation_id TEXT NOT NULL,
  downgrade_applied INTEGER NOT NULL DEFAULT 0,
  downgrade_reason_codes TEXT NOT NULL DEFAULT '[]',
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_causal_graph_safety_case
  ON amrg_causal_graph_safety_slices(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS related_market_prior_anchor_slices (
  prior_anchor_slice_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  upstream_market_id TEXT,
  upstream_probability_source TEXT,
  raw_upstream_probability REAL,
  adjusted_upstream_probability REAL,
  upstream_probability_as_of TEXT,
  allowed_use TEXT NOT NULL,
  conditional_model TEXT,
  upstream_prior_reliability_context TEXT NOT NULL DEFAULT '{}',
  dependence_adjustment TEXT NOT NULL DEFAULT '{}',
  double_counting_risk TEXT NOT NULL,
  not_independent_evidence INTEGER NOT NULL DEFAULT 1,
  conditional_branch_group_id TEXT,
  anchor_dependency_contract_id TEXT NOT NULL,
  graph_safety_slice_id TEXT,
  validation_status TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_related_market_prior_anchor_case
  ON related_market_prior_anchor_slices(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS related_market_refresh_events (
  refresh_event_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  candidate_set_id TEXT NOT NULL,
  refresh_status TEXT NOT NULL,
  refresh_reason_codes TEXT NOT NULL DEFAULT '[]',
  refresh_generation_id TEXT NOT NULL,
  max_refresh_hop_depth INTEGER NOT NULL DEFAULT 0,
  stale_effect_downgrade_applied INTEGER NOT NULL DEFAULT 0,
  next_refresh_after TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_related_market_refresh_events_case
  ON related_market_refresh_events(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_related_market_refresh_events_edge
  ON related_market_refresh_events(edge_id);
