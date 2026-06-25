PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS qdt_decomposition_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decomposition_run_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_key TEXT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  market_complexity_score REAL NOT NULL,
  market_complexity_class TEXT NOT NULL,
  selected_candidate_id TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  artifact_manifest_id INTEGER,
  qdt_artifact_id TEXT NOT NULL,
  qdt_artifact_ref TEXT NOT NULL,
  artifact_path TEXT,
  artifact_sha256 TEXT,
  prompt_template_id TEXT NOT NULL,
  prompt_template_sha256 TEXT NOT NULL,
  model_lane_id TEXT NOT NULL,
  resolved_model_id TEXT NOT NULL,
  model_policy_ref TEXT NOT NULL,
  model_execution_context_sha256 TEXT NOT NULL,
  input_manifest_ids TEXT NOT NULL DEFAULT '[]',
  output_schema_version TEXT NOT NULL,
  branch_ids TEXT NOT NULL DEFAULT '[]',
  dependency_group_ids TEXT NOT NULL DEFAULT '[]',
  related_market_context_usage TEXT NOT NULL DEFAULT '{}',
  amrg_anchor_dependency_contract_refs TEXT NOT NULL DEFAULT '[]',
  candidate_selection_audit TEXT NOT NULL DEFAULT '{}',
  validation_summary TEXT NOT NULL DEFAULT '{}',
  qdt_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (artifact_manifest_id) REFERENCES case_artifact_manifest(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_case
  ON qdt_decomposition_runs(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_market_policy
  ON qdt_decomposition_runs(market_id, policy_hash);
CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_artifact
  ON qdt_decomposition_runs(qdt_artifact_id);

CREATE TABLE IF NOT EXISTS qdt_required_research_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decomposition_run_id TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  case_key TEXT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  qdt_artifact_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  leaf_condition_scope TEXT NOT NULL,
  dependency_group_id TEXT NOT NULL,
  question TEXT NOT NULL,
  leaf_json_pointer TEXT NOT NULL,
  leaf_digest TEXT NOT NULL,
  bayesian_weight_class TEXT NOT NULL,
  static_information_weight TEXT NOT NULL,
  information_weight REAL NOT NULL,
  weight_reason_codes TEXT NOT NULL DEFAULT '[]',
  required_evidence_fields TEXT NOT NULL DEFAULT '[]',
  required_sufficiency_requirement_id TEXT NOT NULL,
  retrieval_breadth_profile_ref TEXT NOT NULL,
  required_source_classes TEXT NOT NULL DEFAULT '[]',
  required_value_fields TEXT NOT NULL DEFAULT '[]',
  required_negative_checks TEXT NOT NULL DEFAULT '[]',
  market_component_terms TEXT NOT NULL DEFAULT '[]',
  structural_validation TEXT NOT NULL DEFAULT '{}',
  artifact_manifest_id INTEGER,
  question_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (decomposition_run_id, question_id),
  FOREIGN KEY (artifact_manifest_id) REFERENCES case_artifact_manifest(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_case
  ON qdt_required_research_questions(case_id, dispatch_id, question_id);
CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_purpose
  ON qdt_required_research_questions(purpose, leaf_condition_scope);
CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_run_leaf
  ON qdt_required_research_questions(decomposition_run_id, leaf_id);

CREATE TABLE IF NOT EXISTS qdt_leaf_research_sufficiency_requirements (
  sufficiency_requirement_record_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  requirement_schema_version TEXT NOT NULL,
  template_version TEXT NOT NULL,
  case_key TEXT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  decomposition_run_id TEXT NOT NULL,
  qdt_artifact_id TEXT NOT NULL,
  leaf_id TEXT NOT NULL,
  parent_branch_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  static_information_weight TEXT NOT NULL,
  leaf_condition_scope TEXT NOT NULL,
  requirement_id TEXT NOT NULL,
  sufficiency_profile_id TEXT NOT NULL,
  target_answerability TEXT NOT NULL,
  retrieval_breadth_profile_ref TEXT NOT NULL,
  required_source_classes TEXT NOT NULL DEFAULT '[]',
  protected_primary_required INTEGER NOT NULL,
  min_independent_claim_families INTEGER NOT NULL,
  min_independent_source_families INTEGER NOT NULL,
  min_temporally_fresh_sources INTEGER NOT NULL,
  required_value_fields TEXT NOT NULL DEFAULT '[]',
  required_negative_checks TEXT NOT NULL DEFAULT '[]',
  contradiction_search_required INTEGER NOT NULL,
  recency_window_seconds INTEGER NOT NULL,
  max_targeted_expansion_attempts INTEGER NOT NULL,
  allow_macro_fallback_for_leaf INTEGER NOT NULL,
  unanswerability_proof_required INTEGER NOT NULL,
  classification_dispatch_requires_sufficiency_certificate INTEGER NOT NULL,
  requirement_reason_codes TEXT NOT NULL DEFAULT '[]',
  requirement_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qdt_leaf_sufficiency_case
  ON qdt_leaf_research_sufficiency_requirements(case_id, dispatch_id, leaf_id);
CREATE INDEX IF NOT EXISTS idx_qdt_leaf_sufficiency_run
  ON qdt_leaf_research_sufficiency_requirements(decomposition_run_id, requirement_id);

CREATE TABLE IF NOT EXISTS qdt_amrg_anchor_dependency_slices (
  anchor_dependency_slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  contract_schema_version TEXT NOT NULL,
  case_key TEXT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  decomposition_run_id TEXT NOT NULL,
  qdt_artifact_id TEXT NOT NULL,
  anchor_dependency_contract_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  edge_status TEXT NOT NULL,
  related_market_ref TEXT,
  qdt_branch_id TEXT,
  conditional_branch_group_id TEXT NOT NULL,
  anchor_mode TEXT NOT NULL,
  condition_scoped_leaf_ids TEXT NOT NULL DEFAULT '[]',
  required_before_leaf_ids TEXT NOT NULL DEFAULT '[]',
  fallback_policy_id TEXT NOT NULL,
  fallback_mode TEXT NOT NULL,
  fallback_leaf_ids TEXT NOT NULL DEFAULT '[]',
  fallback_reason_codes TEXT NOT NULL DEFAULT '[]',
  max_anchor_repair_attempts INTEGER NOT NULL,
  max_anchor_repair_wall_clock_seconds INTEGER NOT NULL,
  repair_exhaustion_policy TEXT NOT NULL,
  contract_digest TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qdt_anchor_dependency_case
  ON qdt_amrg_anchor_dependency_slices(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_qdt_anchor_dependency_run
  ON qdt_amrg_anchor_dependency_slices(decomposition_run_id, anchor_dependency_contract_id);
