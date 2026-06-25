PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS researcher_prompt_artifacts (
  prompt_contract_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  prompt_template_id TEXT NOT NULL,
  prompt_template_sha256 TEXT NOT NULL,
  prompt_text_sha256 TEXT NOT NULL,
  prompt_contract_digest TEXT NOT NULL,
  model_execution_context_ref TEXT,
  model_execution_context_sha256 TEXT,
  output_contract_refs TEXT NOT NULL DEFAULT '{}',
  prompt_artifact_ref TEXT,
  prompt_artifact_path TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_researcher_prompt_artifacts_case
  ON researcher_prompt_artifacts(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS leaf_research_assignments (
  assignment_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT,
  assignment_role TEXT NOT NULL,
  attempt_index INTEGER NOT NULL,
  assigned_lens TEXT NOT NULL,
  escalation_decision_ref TEXT,
  trigger_codes TEXT NOT NULL DEFAULT '[]',
  leaf_artifact_ref TEXT NOT NULL,
  leaf_json_pointer TEXT NOT NULL,
  leaf_digest TEXT NOT NULL,
  condition_scope TEXT NOT NULL,
  sufficiency_requirement_refs TEXT NOT NULL DEFAULT '[]',
  research_sufficiency_certificate_ref TEXT NOT NULL,
  retrieval_breadth_profile_ref TEXT NOT NULL,
  retrieval_breadth_coverage_ref TEXT NOT NULL,
  assigned_evidence_refs TEXT NOT NULL DEFAULT '[]',
  required_value_field_ids TEXT NOT NULL DEFAULT '[]',
  required_negative_check_ids TEXT NOT NULL DEFAULT '[]',
  context_isolation_ref TEXT NOT NULL,
  model_lane_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  prompt_template_id TEXT NOT NULL,
  prompt_template_sha256 TEXT NOT NULL,
  model_policy_ref TEXT NOT NULL,
  model_context_sha256 TEXT NOT NULL,
  budget TEXT NOT NULL DEFAULT '{}',
  artifact_outputs TEXT NOT NULL DEFAULT '{}',
  assignment_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leaf_research_assignments_case
  ON leaf_research_assignments(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS researcher_context_isolation_audits (
  isolation_audit_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  subagent_session_ref TEXT NOT NULL,
  fresh_context INTEGER NOT NULL,
  visible_artifact_refs TEXT NOT NULL DEFAULT '[]',
  visible_artifact_refs_digest TEXT NOT NULL,
  forbidden_ref_scan TEXT NOT NULL DEFAULT '{}',
  peer_output_exclusion_proof TEXT NOT NULL DEFAULT '{}',
  allowed_shared_refs TEXT NOT NULL DEFAULT '[]',
  launch_allowed INTEGER NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  audit_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_researcher_context_isolation_case
  ON researcher_context_isolation_audits(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS classification_lane_evidence_classification_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  sidecar_id TEXT,
  researcher_run_id TEXT,
  persona_id TEXT,
  classification_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT,
  question_id TEXT NOT NULL,
  condition_scope TEXT NOT NULL,
  condition_ref TEXT,
  evidence_ref TEXT NOT NULL,
  source_ref TEXT,
  canonical_source_id TEXT,
  source_class TEXT NOT NULL,
  source_family_id TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  claim_family_resolution_ref TEXT,
  impact_direction TEXT NOT NULL,
  evidence_strength TEXT NOT NULL,
  classification_confidence TEXT NOT NULL,
  answer_value_extraction TEXT NOT NULL DEFAULT '{}',
  evidence_quality_dimensions TEXT NOT NULL DEFAULT '{}',
  research_sufficiency_certificate_ref TEXT NOT NULL,
  coverage_proof_ref TEXT NOT NULL,
  retrieval_breadth_coverage_ref TEXT,
  provenance_slice_ref TEXT,
  model_execution_context_ref TEXT,
  model_execution_context_sha256 TEXT,
  normalized_supplemental_evidence_ref TEXT,
  classification_slice_digest TEXT NOT NULL,
  matrix_digest TEXT,
  materializer_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classification_lane_evidence_provenance_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  sidecar_id TEXT,
  classification_slice_ref TEXT NOT NULL,
  classification_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  condition_scope TEXT,
  evidence_ref TEXT NOT NULL,
  retrieval_evidence_provenance_ref TEXT,
  source_ref TEXT,
  source_class TEXT NOT NULL,
  source_family_id TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  claim_family_resolution_ref TEXT,
  research_sufficiency_certificate_ref TEXT,
  coverage_proof_ref TEXT,
  retrieval_breadth_coverage_ref TEXT,
  provenance_refs TEXT NOT NULL DEFAULT '[]',
  content_sha256 TEXT,
  normalized_supplemental_evidence_ref TEXT,
  provenance_slice_digest TEXT NOT NULL,
  matrix_digest TEXT,
  materializer_version TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS researcher_leaf_coverage_proofs (
  proof_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  assignment_digest TEXT NOT NULL,
  isolation_audit_ref TEXT NOT NULL,
  isolation_audit_digest TEXT NOT NULL,
  sidecar_id TEXT NOT NULL,
  sidecar_digest TEXT NOT NULL,
  coverage_proof_ref TEXT NOT NULL,
  coverage_proof_slice_ref TEXT NOT NULL,
  classification_matrix_id TEXT NOT NULL,
  classification_matrix_digest TEXT NOT NULL,
  research_sufficiency_certificate_ref TEXT NOT NULL,
  certificate_status TEXT NOT NULL,
  retrieval_breadth_coverage_ref TEXT NOT NULL,
  coverage_status TEXT NOT NULL,
  assigned_evidence_refs TEXT NOT NULL DEFAULT '[]',
  reviewed_evidence_refs TEXT NOT NULL DEFAULT '[]',
  certificate_evidence_refs TEXT NOT NULL DEFAULT '[]',
  classified_evidence_refs TEXT NOT NULL DEFAULT '[]',
  requirements_reviewed TEXT NOT NULL DEFAULT '[]',
  requirements_answered TEXT NOT NULL DEFAULT '[]',
  requirements_unanswered TEXT NOT NULL DEFAULT '[]',
  required_value_fields TEXT NOT NULL DEFAULT '[]',
  required_value_fields_extracted TEXT NOT NULL DEFAULT '[]',
  required_negative_checks TEXT NOT NULL DEFAULT '[]',
  required_negative_checks_completed TEXT NOT NULL DEFAULT '[]',
  proof_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_researcher_leaf_coverage_case
  ON researcher_leaf_coverage_proofs(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS researcher_escalation_decisions (
  decision_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  base_assignment_id TEXT NOT NULL,
  trigger_codes TEXT NOT NULL DEFAULT '[]',
  trigger_evidence_refs TEXT NOT NULL DEFAULT '[]',
  retrieval_quality_ref TEXT,
  classification_ids TEXT NOT NULL DEFAULT '[]',
  verification_slice_refs TEXT NOT NULL DEFAULT '[]',
  pre_scae_leverage_proxy TEXT NOT NULL DEFAULT '{}',
  escalation_required INTEGER NOT NULL,
  additional_assignment_count INTEGER NOT NULL,
  max_assignments_for_leaf INTEGER NOT NULL,
  max_concurrent_leaf_researchers_per_case INTEGER NOT NULL,
  escalation_assignment_refs TEXT NOT NULL DEFAULT '[]',
  completion_status TEXT NOT NULL,
  decision_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_researcher_escalation_case
  ON researcher_escalation_decisions(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS normalized_supplemental_evidence (
  normalization_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  classification_id TEXT,
  supplemental_evidence_ref TEXT NOT NULL,
  normalization_status TEXT NOT NULL,
  admission_status TEXT NOT NULL,
  source_access_status TEXT NOT NULL,
  canonical_source_id TEXT NOT NULL,
  event_source_family_id TEXT NOT NULL,
  source_family_id TEXT NOT NULL,
  source_class TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  claim_family_resolution_ref TEXT,
  content_sha256 TEXT NOT NULL,
  temporal_gate_status TEXT NOT NULL,
  temporal_validation_ref TEXT,
  independence_status TEXT NOT NULL,
  counts_toward_breadth INTEGER NOT NULL,
  blockers TEXT NOT NULL DEFAULT '[]',
  rejection_reason_codes TEXT NOT NULL DEFAULT '[]',
  normalization_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_normalized_supplemental_case
  ON normalized_supplemental_evidence(case_id, dispatch_id, leaf_id);
CREATE INDEX IF NOT EXISTS idx_normalized_supplemental_join
  ON normalized_supplemental_evidence(supplemental_evidence_ref, normalization_status);

CREATE TABLE IF NOT EXISTS evidence_direction_verification_slices (
  verification_slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  classification_id TEXT NOT NULL,
  classification_slice_ref TEXT,
  leaf_id TEXT NOT NULL,
  claimed_direction TEXT NOT NULL,
  verified_direction TEXT NOT NULL,
  method_status TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  side_mapping_digest TEXT,
  market_constraints_digest TEXT,
  coverage_after_exclusion_status TEXT,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  direction_verification_slice_digest TEXT NOT NULL,
  direction_verification_digest TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_direction_verification_case
  ON evidence_direction_verification_slices(case_id, dispatch_id, verification_status);

CREATE TABLE IF NOT EXISTS evidence_quality_verification_slices (
  quality_verification_slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  classification_id TEXT NOT NULL,
  classification_slice_ref TEXT,
  leaf_id TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  claimed_quality_fields TEXT NOT NULL DEFAULT '{}',
  machine_normalized_quality_fields TEXT NOT NULL DEFAULT '{}',
  accepted_quality_fields TEXT NOT NULL DEFAULT '{}',
  raw_quality_multiplier REAL NOT NULL,
  quality_correlation_groups TEXT NOT NULL DEFAULT '[]',
  correlated_quality_floor_applied INTEGER NOT NULL,
  final_quality_multiplier REAL NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  quality_verification_slice_digest TEXT NOT NULL,
  quality_verification_digest TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quality_verification_case
  ON evidence_quality_verification_slices(case_id, dispatch_id, verification_status);

CREATE TABLE IF NOT EXISTS scae_readiness_reconciliation_refs (
  reconciliation_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  source_classification_matrix_id TEXT,
  source_classification_matrix_digest TEXT,
  source_direction_verification_digest TEXT,
  source_quality_verification_digest TEXT,
  source_coverage_proof_bundle_digest TEXT,
  ready_for_scae INTEGER NOT NULL,
  ready_classification_slice_refs TEXT NOT NULL DEFAULT '[]',
  excluded_deadlock_safe_classification_slice_refs TEXT NOT NULL DEFAULT '[]',
  blocker_codes TEXT NOT NULL DEFAULT '[]',
  readiness_row_count INTEGER NOT NULL,
  readiness_row_digests TEXT NOT NULL DEFAULT '[]',
  leaf_readiness_refs TEXT NOT NULL DEFAULT '[]',
  readiness_digest TEXT NOT NULL,
  artifact_ref TEXT,
  artifact_path TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_readiness_reconciliation_case
  ON scae_readiness_reconciliation_refs(case_id, dispatch_id, ready_for_scae);

CREATE TABLE IF NOT EXISTS research_sufficiency_reconciliation_slices (
  research_sufficiency_reconciliation_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT,
  condition_scope TEXT,
  certificate_ref TEXT,
  certificate_status TEXT,
  retrieval_breadth_coverage_ref TEXT,
  coverage_proof_refs TEXT NOT NULL DEFAULT '[]',
  classification_slice_refs TEXT NOT NULL DEFAULT '[]',
  required_escalation_decision_refs TEXT NOT NULL DEFAULT '[]',
  completed_escalation_decision_refs TEXT NOT NULL DEFAULT '[]',
  required_value_fields TEXT NOT NULL DEFAULT '[]',
  required_negative_checks TEXT NOT NULL DEFAULT '[]',
  reconciled_status TEXT NOT NULL,
  research_sufficiency_reconciliation_status TEXT NOT NULL,
  missing_requirement_codes TEXT NOT NULL DEFAULT '[]',
  blocking_reason_codes TEXT NOT NULL DEFAULT '[]',
  reason_codes TEXT NOT NULL DEFAULT '[]',
  scae_ready INTEGER NOT NULL,
  scae_consumable_under_policy INTEGER NOT NULL,
  reconciliation_slice_digest TEXT NOT NULL,
  reconciliation_digest TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_sufficiency_reconciliation_case
  ON research_sufficiency_reconciliation_slices(case_id, dispatch_id, leaf_id);
