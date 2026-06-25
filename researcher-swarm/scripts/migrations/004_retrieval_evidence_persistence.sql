PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS retrieval_packet_artifacts (
  retrieval_packet_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  question_decomposition_artifact_id TEXT,
  forecast_timestamp TEXT,
  source_cutoff_timestamp TEXT,
  temporal_isolation_status TEXT NOT NULL,
  policy_context_ref TEXT,
  artifact_ref TEXT,
  artifact_path TEXT,
  packet_sha256 TEXT NOT NULL,
  leaf_count INTEGER NOT NULL DEFAULT 0,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  omitted_candidate_count INTEGER NOT NULL DEFAULT 0,
  quality_summary_ref TEXT,
  research_sufficiency_status TEXT,
  classification_dispatch_status TEXT,
  leaf_certificate_refs TEXT NOT NULL DEFAULT '[]',
  schema_feature_gates TEXT NOT NULL DEFAULT '{}',
  validation_summary TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_packet_case
  ON retrieval_packet_artifacts(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS retrieval_evidence_items (
  evidence_ref TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT,
  retrieval_transport TEXT NOT NULL,
  transport_attempt_ref TEXT NOT NULL,
  requested_url TEXT,
  final_url TEXT,
  canonical_url TEXT,
  canonical_source_id TEXT,
  source_metadata_resolution_ref TEXT,
  claim_family_resolution_refs TEXT NOT NULL DEFAULT '[]',
  source_family_id TEXT,
  source_class TEXT NOT NULL,
  independence_status TEXT NOT NULL,
  temporal_gate_status TEXT NOT NULL,
  source_published_at TEXT,
  source_updated_at TEXT,
  source_observed_at TEXT,
  source_authored_at TEXT,
  captured_at TEXT,
  artifact_generated_at TEXT,
  retrieval_capture_for_dispatch INTEGER NOT NULL DEFAULT 0,
  pre_dispatch_input_ref TEXT,
  content_sha256 TEXT NOT NULL,
  chunk_refs TEXT NOT NULL DEFAULT '[]',
  retrieval_score REAL,
  admission_status TEXT NOT NULL,
  admission_reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_evidence_case
  ON retrieval_evidence_items(case_id, dispatch_id, leaf_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_evidence_source
  ON retrieval_evidence_items(canonical_source_id, source_family_id, claim_family_resolution_refs);

CREATE TABLE IF NOT EXISTS retrieval_evidence_chunk_slices (
  chunk_ref TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  evidence_ref TEXT NOT NULL,
  content_artifact_ref TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  text_sha256 TEXT NOT NULL,
  excerpt_char_count INTEGER NOT NULL DEFAULT 0,
  excerpt_policy TEXT NOT NULL,
  contains_claim_candidate_ids TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_evidence
  ON retrieval_evidence_chunk_slices(evidence_ref);

CREATE TABLE IF NOT EXISTS native_research_attempts (
  attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_variant_id TEXT,
  model_lane_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  prompt_template_id TEXT NOT NULL,
  query_manifest_sha256 TEXT NOT NULL,
  research_transport TEXT NOT NULL,
  candidate_citation_refs TEXT NOT NULL DEFAULT '[]',
  candidate_claim_refs TEXT NOT NULL DEFAULT '[]',
  contradiction_candidate_refs TEXT NOT NULL DEFAULT '[]',
  negative_check_candidate_refs TEXT NOT NULL DEFAULT '[]',
  model_proposed_source_metadata_sha256 TEXT,
  candidate_output_schema_version TEXT,
  attempt_status TEXT NOT NULL,
  native_transport_availability_status TEXT NOT NULL,
  failure_reason_codes TEXT NOT NULL DEFAULT '[]',
  diagnostic_only_when_unavailable INTEGER NOT NULL DEFAULT 0,
  non_blocking_when_alternative_transport_satisfies_requirements INTEGER NOT NULL DEFAULT 1,
  resolver_required_for_accepted_metadata TEXT,
  feature_gate_status TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_native_research_case
  ON native_research_attempts(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS browser_retrieval_attempts (
  attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_variant_id TEXT,
  query_text_sha256 TEXT,
  browser_session_ref TEXT,
  browser_provider_id TEXT NOT NULL,
  openclaw_transport_ref TEXT,
  provider_capabilities TEXT NOT NULL DEFAULT '[]',
  provider_availability_status TEXT,
  news_feed_api_enabled INTEGER NOT NULL DEFAULT 0,
  navigation_mode TEXT NOT NULL,
  direct_url_source_ref TEXT,
  search_engine_or_navigation_source TEXT,
  result_rank INTEGER,
  requested_url TEXT,
  final_url TEXT,
  canonical_url TEXT,
  normalized_domain TEXT,
  page_title_sha256 TEXT,
  captured_at TEXT,
  published_at TEXT,
  published_at_extraction_method TEXT,
  rendered_text_sha256 TEXT,
  extracted_text_sha256 TEXT,
  screenshot_artifact_ref TEXT,
  content_artifact_ref TEXT,
  extraction_status TEXT NOT NULL,
  feature_gate_status TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_browser_retrieval_case
  ON browser_retrieval_attempts(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS browser_search_provider_diagnostics (
  provider_diagnostic_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  provider_id TEXT NOT NULL,
  provider_refs TEXT NOT NULL DEFAULT '[]',
  capabilities TEXT NOT NULL DEFAULT '[]',
  availability_status TEXT NOT NULL,
  news_feed_api_enabled INTEGER NOT NULL DEFAULT 0,
  direct_url_priority TEXT,
  unavailable_reason TEXT,
  checked_at TEXT,
  feature_gate_status TEXT,
  diagnostic_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_browser_provider_diag_case
  ON browser_search_provider_diagnostics(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS source_metadata_classifier_slices (
  classifier_slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  candidate_id TEXT,
  leaf_id TEXT,
  model_lane_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  provider_model_key TEXT NOT NULL,
  model_policy_ref TEXT,
  prompt_template_id TEXT NOT NULL,
  prompt_template_sha256 TEXT NOT NULL,
  input_candidate_sha256 TEXT NOT NULL,
  classifier_output_schema_version TEXT NOT NULL,
  proposed_source_class TEXT,
  source_class_confidence TEXT,
  proposed_source_family_hint_sha256 TEXT,
  source_family_confidence TEXT,
  syndication_hint TEXT,
  atomic_claim_candidate_count INTEGER NOT NULL DEFAULT 0,
  visible_date_candidate_count INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  classifier_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_classifier_case
  ON source_metadata_classifier_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS source_metadata_resolution_slices (
  resolution_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  evidence_ref TEXT NOT NULL,
  transport_attempt_ref TEXT NOT NULL,
  requested_url TEXT,
  final_url TEXT,
  canonical_url TEXT,
  registrable_domain TEXT,
  canonical_source_id TEXT,
  content_sha256 TEXT,
  source_class TEXT NOT NULL,
  source_class_resolution_method TEXT,
  source_family_id TEXT,
  source_family_resolution_method TEXT,
  source_family_status TEXT,
  claim_family_resolution_refs TEXT NOT NULL DEFAULT '[]',
  claim_family_ids TEXT NOT NULL DEFAULT '[]',
  claim_family_resolution_method TEXT,
  temporal_safety_status TEXT NOT NULL,
  published_at TEXT,
  published_at_method TEXT,
  classifier_slice_ref TEXT,
  classifier_acceptance_status TEXT,
  classifier_acceptance_reason_codes TEXT NOT NULL DEFAULT '[]',
  metadata_confidence TEXT,
  counts_toward_breadth INTEGER NOT NULL DEFAULT 0,
  unknown_reason_codes TEXT NOT NULL DEFAULT '[]',
  accepted_metadata_authority TEXT NOT NULL,
  deterministic_resolver_accepted_fields TEXT NOT NULL DEFAULT '[]',
  model_proposed_metadata_counted INTEGER NOT NULL DEFAULT 0,
  normalizer_version TEXT,
  ret_010_resolver_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_resolution_case
  ON source_metadata_resolution_slices(case_id, dispatch_id, evidence_ref);

CREATE TABLE IF NOT EXISTS atomic_claim_candidate_slices (
  claim_candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  evidence_ref TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  chunk_refs TEXT NOT NULL DEFAULT '[]',
  extraction_method TEXT NOT NULL,
  model_lane_id TEXT,
  prompt_template_id TEXT,
  proposed_tuple_sha256 TEXT NOT NULL,
  supporting_span_refs TEXT NOT NULL DEFAULT '[]',
  candidate_confidence TEXT,
  validation_status TEXT NOT NULL,
  validator_reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_atomic_claim_case
  ON atomic_claim_candidate_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS claim_family_resolution_slices (
  claim_family_resolution_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  claim_family_id TEXT NOT NULL,
  claim_candidate_refs TEXT NOT NULL DEFAULT '[]',
  normalized_tuple_sha256 TEXT NOT NULL,
  resolution_method TEXT NOT NULL,
  equivalence_status TEXT NOT NULL,
  contradiction_family_id TEXT,
  counts_toward_claim_family_breadth INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_claim_family_case
  ON claim_family_resolution_slices(case_id, dispatch_id, claim_family_id);

CREATE TABLE IF NOT EXISTS retrieval_metadata_fill_diagnostics (
  diagnostic_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  retrieval_transport TEXT NOT NULL,
  raw_candidate_count INTEGER NOT NULL DEFAULT 0,
  admitted_ref_count INTEGER NOT NULL DEFAULT 0,
  field_fill_counts TEXT NOT NULL DEFAULT '{}',
  unknown_counts TEXT NOT NULL DEFAULT '{}',
  fill_rates TEXT NOT NULL DEFAULT '{}',
  diagnostic_authority TEXT NOT NULL,
  evaluator_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metadata_fill_case
  ON retrieval_metadata_fill_diagnostics(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS retrieval_quality_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  selected_evidence_refs TEXT NOT NULL DEFAULT '[]',
  quality_score REAL NOT NULL,
  quality_status TEXT NOT NULL,
  penalty_points REAL NOT NULL,
  diagnostic_codes TEXT NOT NULL DEFAULT '[]',
  low_breadth_reason_codes TEXT NOT NULL DEFAULT '[]',
  dimensions TEXT NOT NULL DEFAULT '{}',
  scorer_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_quality_case
  ON retrieval_quality_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS retrieval_evidence_provenance_slices (
  provenance_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  evidence_ref TEXT NOT NULL,
  candidate_id TEXT,
  retrieval_transport TEXT NOT NULL,
  transport_attempt_ref TEXT,
  browser_attempt_ref TEXT,
  native_research_attempt_ref TEXT,
  source_metadata_resolution_ref TEXT NOT NULL,
  source_metadata_classifier_ref TEXT,
  atomic_claim_candidate_refs TEXT NOT NULL DEFAULT '[]',
  claim_family_resolution_refs TEXT NOT NULL DEFAULT '[]',
  claim_family_ids TEXT NOT NULL DEFAULT '[]',
  classifier_acceptance_status TEXT,
  classifier_acceptance_reason_codes TEXT NOT NULL DEFAULT '[]',
  metadata_confidence TEXT,
  unknown_reason_codes TEXT NOT NULL DEFAULT '[]',
  requested_url TEXT,
  final_url TEXT,
  canonical_url TEXT,
  url_identity_basis TEXT,
  captured_at TEXT,
  artifact_generated_at TEXT,
  source_published_at TEXT,
  source_updated_at TEXT,
  source_observed_at TEXT,
  published_at_extraction_method TEXT,
  canonical_source_id TEXT,
  source_class TEXT NOT NULL,
  source_family_id TEXT,
  source_family_status TEXT,
  independence_status TEXT,
  content_sha256 TEXT,
  temporal_gate_status TEXT,
  temporal_validation_ref TEXT,
  temporal_validation_sha256 TEXT,
  counts_toward_breadth INTEGER NOT NULL DEFAULT 0,
  normalizer_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retrieval_provenance_case
  ON retrieval_evidence_provenance_slices(case_id, dispatch_id, evidence_ref);

CREATE TABLE IF NOT EXISTS retrieval_breadth_profiles (
  profile_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  source_class_requirements TEXT NOT NULL DEFAULT '{}',
  claim_family_requirements TEXT NOT NULL DEFAULT '{}',
  source_family_requirements TEXT NOT NULL DEFAULT '{}',
  freshness_requirement TEXT NOT NULL DEFAULT '{}',
  contradiction_search TEXT NOT NULL DEFAULT '{}',
  negative_checks TEXT NOT NULL DEFAULT '{}',
  retrieval_volume_tier TEXT NOT NULL DEFAULT '{}',
  feature_gate_status TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_breadth_profiles_case
  ON retrieval_breadth_profiles(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS retrieval_breadth_coverage_slices (
  coverage_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  breadth_profile_ref TEXT NOT NULL,
  source_class_coverage TEXT NOT NULL DEFAULT '{}',
  claim_family_count INTEGER NOT NULL DEFAULT 0,
  source_family_count INTEGER NOT NULL DEFAULT 0,
  fresh_source_count INTEGER NOT NULL DEFAULT 0,
  contradiction_attempt_refs TEXT NOT NULL DEFAULT '[]',
  negative_check_attempt_refs TEXT NOT NULL DEFAULT '[]',
  protected_primary_status TEXT NOT NULL,
  protected_primary_resolution_basis TEXT,
  structural_unanswerability_proof_ref TEXT,
  raw_candidate_count INTEGER NOT NULL DEFAULT 0,
  admitted_ref_count INTEGER NOT NULL DEFAULT 0,
  independent_claim_family_ids TEXT NOT NULL DEFAULT '[]',
  independent_source_family_ids TEXT NOT NULL DEFAULT '[]',
  metadata_fill_diagnostic_refs TEXT NOT NULL DEFAULT '[]',
  unknown_field_counts TEXT NOT NULL DEFAULT '{}',
  blocking_unknown_fields TEXT NOT NULL DEFAULT '[]',
  expansion_required INTEGER NOT NULL DEFAULT 0,
  expansion_requirement_codes TEXT NOT NULL DEFAULT '[]',
  unsatisfied_breadth_dimensions TEXT NOT NULL DEFAULT '[]',
  breadth_certified INTEGER NOT NULL DEFAULT 0,
  evaluator_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_breadth_coverage_case
  ON retrieval_breadth_coverage_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS contradiction_search_attempts (
  attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  query_variant_id TEXT,
  query_text_sha256 TEXT,
  source_refs_checked TEXT NOT NULL DEFAULT '[]',
  contradiction_found INTEGER NOT NULL DEFAULT 0,
  outcome_status TEXT NOT NULL,
  attempt_authority TEXT NOT NULL,
  evaluator_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contradiction_case
  ON contradiction_search_attempts(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS negative_check_attempts (
  attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  negative_check TEXT NOT NULL,
  query_text_sha256 TEXT NOT NULL,
  source_refs_checked TEXT NOT NULL DEFAULT '[]',
  outcome_status TEXT NOT NULL,
  no_confirmation_found INTEGER NOT NULL DEFAULT 0,
  attempt_authority TEXT NOT NULL,
  evaluator_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_negative_check_case
  ON negative_check_attempts(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS source_access_failure_slices (
  failure_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  required_source_classes TEXT NOT NULL DEFAULT '[]',
  expected_source_refs TEXT NOT NULL DEFAULT '[]',
  observed_attempt_refs TEXT NOT NULL DEFAULT '[]',
  admitted_evidence_refs TEXT NOT NULL DEFAULT '[]',
  access_status TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  candidate_tracking_only INTEGER NOT NULL DEFAULT 1,
  tracker_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_access_case
  ON source_access_failure_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS missingness_signal_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'missingness_signal_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL DEFAULT '{}',
  payload_sha256 TEXT NOT NULL,
  query_context_ref TEXT,
  expected_source_class TEXT,
  expected_source_ref TEXT NOT NULL DEFAULT '{}',
  missingness_status TEXT,
  missingness_basis TEXT,
  evidence_refs_checked TEXT NOT NULL DEFAULT '[]',
  attempt_refs_checked TEXT NOT NULL DEFAULT '[]',
  distinct_absence_mechanism_proof_ref TEXT,
  candidate_tracking_only INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_missingness_signal_case
  ON missingness_signal_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS retrieval_fallback_state_records (
  fallback_state_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  targeted_expansion_attempt_refs TEXT NOT NULL DEFAULT '[]',
  targeted_expansion_required_before_macro_fallback INTEGER NOT NULL DEFAULT 1,
  macro_fallback_requested INTEGER NOT NULL DEFAULT 0,
  macro_fallback_used INTEGER NOT NULL DEFAULT 0,
  macro_fallback_policy TEXT NOT NULL,
  macro_fallback_sufficiency_status TEXT NOT NULL,
  classification_dispatch_allowed_from_macro_fallback INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  planner_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fallback_state_case
  ON retrieval_fallback_state_records(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS retrieval_expansion_attempt_slices (
  attempt_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  attempt_index INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL,
  expansion_strategy TEXT NOT NULL,
  attempt_status TEXT NOT NULL,
  unsatisfied_requirement_codes TEXT NOT NULL DEFAULT '[]',
  query_variant_refs TEXT NOT NULL DEFAULT '[]',
  expansion_query_text_sha256 TEXT NOT NULL,
  candidate_refs TEXT NOT NULL DEFAULT '[]',
  admitted_evidence_refs TEXT NOT NULL DEFAULT '[]',
  bounded_by_requirement_max INTEGER NOT NULL DEFAULT 1,
  macro_fallback_phase INTEGER NOT NULL DEFAULT 0,
  planner_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_expansion_attempt_case
  ON retrieval_expansion_attempt_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS research_sufficiency_certificates (
  certificate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  retrieval_packet_id TEXT,
  leaf_id TEXT NOT NULL,
  query_context_ref TEXT,
  requirement_ref TEXT,
  sufficiency_profile_id TEXT NOT NULL,
  status TEXT NOT NULL,
  classification_dispatch_allowed INTEGER NOT NULL DEFAULT 0,
  evidence_refs TEXT NOT NULL DEFAULT '[]',
  breadth_coverage_ref TEXT,
  breadth_certified INTEGER NOT NULL DEFAULT 0,
  expansion_attempt_refs TEXT NOT NULL DEFAULT '[]',
  fallback_state_ref TEXT,
  structural_unanswerability_proof_ref TEXT,
  temporal_validation_status TEXT NOT NULL,
  freshness_status TEXT NOT NULL,
  macro_fallback_sufficiency_status TEXT NOT NULL,
  unsatisfied_requirement_codes TEXT NOT NULL DEFAULT '[]',
  blocking_reason_codes TEXT NOT NULL DEFAULT '[]',
  certifier_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_sufficiency_cert_case
  ON research_sufficiency_certificates(case_id, dispatch_id, leaf_id);
