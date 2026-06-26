#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from predquant.brier import (
    as_float,
    binary_log_loss,
    brier_edge,
    market_probability_from_snapshot,
    prediction_scores,
    reliability_bucket,
    validate_probability,
)
from predquant.foundation_schema import ensure_foundation_schema

DEFAULT_DB_PATH = Path("data/predquant.sqlite3")
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 3600.0
BRIER_SCORING_VERSION = "brier-v1"
SCORE001_REPORT_SCHEMA_VERSION = "score-001-brier-score-report/v1"
EVALUATOR_SCORECARD_SCHEMA_VERSION = "score-001-evaluator-scorecard/v1"
CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID = "calibration_debt_clearance"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS markets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  external_market_id TEXT NOT NULL,
  slug TEXT,
  title TEXT NOT NULL,
  description TEXT,
  category TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  outcome_type TEXT,
  closes_at TEXT,
  resolves_at TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  current_price REAL,
  pipeline_status TEXT NOT NULL DEFAULT 'pending_research',
  last_reasoned_price REAL,
  closed_at TEXT,
  resolution_outcome REAL,
  resolution_source TEXT,
  resolution_recorded_at TEXT,
  resolution_payload_hash TEXT,
  resolution_payload TEXT,
  resolution_method TEXT,
  resolution_checked_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(platform, external_market_id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  observed_at TEXT NOT NULL,
  last_price REAL,
  best_bid REAL,
  best_ask REAL,
  yes_price REAL,
  no_price REAL,
  volume REAL,
  open_interest REAL,
  raw_payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_markets_status ON markets(status);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_pipeline_status ON markets(pipeline_status);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_market_observed
  ON market_snapshots(market_id, observed_at);

CREATE TABLE IF NOT EXISTS market_predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  prediction_run_id TEXT,
  forecast_artifact_id TEXT,
  case_key TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  engine_stage TEXT,
  prediction_source TEXT NOT NULL DEFAULT 'pipeline',
  prediction_label TEXT,
  predicted_at TEXT NOT NULL,
  predicted_probability REAL NOT NULL,
  market_probability REAL,
  market_probability_method TEXT,
  market_snapshot_id INTEGER REFERENCES market_snapshots(id) ON DELETE SET NULL,
  source_fetched_at TEXT,
  source_payload_hash TEXT,
  code_version TEXT,
  model_name TEXT,
  prompt_version TEXT,
  input_hash TEXT,
  input_artifact_path TEXT,
  input_artifact_sha256 TEXT,
  prediction_artifact_path TEXT,
  prediction_artifact_sha256 TEXT,
  snapshot_age_seconds REAL,
  outcome REAL,
  prediction_brier REAL,
  market_brier REAL,
  scoring_version TEXT,
  scored_at TEXT,
  scoring_resolution_payload_hash TEXT,
  scoring_resolution_source TEXT,
  resolved_at TEXT,
  rationale TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_predictions_market
  ON market_predictions(market_id, predicted_at);
CREATE INDEX IF NOT EXISTS idx_market_predictions_source
  ON market_predictions(prediction_source, predicted_at);
"""


PREDICTION_INDEX_SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_predictions_run_id
  ON market_predictions(prediction_run_id)
  WHERE prediction_run_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_predictions_forecast_artifact
  ON market_predictions(forecast_artifact_id)
  WHERE forecast_artifact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_market_predictions_case
  ON market_predictions(case_key, dispatch_id, predicted_at);
"""


FIRST_WAVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_context_feature_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  feature_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_path TEXT,
  artifact_sha256 TEXT,
  output_json TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  stage_status TEXT NOT NULL,
  policy_sha256 TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(case_key, dispatch_id, feature_id)
);

CREATE INDEX IF NOT EXISTS idx_market_context_outputs_case
  ON market_context_feature_outputs(case_key, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_market_context_outputs_market
  ON market_context_feature_outputs(market_id, feature_id);

CREATE TABLE IF NOT EXISTS market_context_stage_status (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  feature_id TEXT NOT NULL,
  stage_name TEXT NOT NULL,
  stage_status TEXT NOT NULL,
  stage_detail_state TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  input_refs TEXT NOT NULL DEFAULT '[]',
  input_sha256 TEXT,
  output_refs TEXT NOT NULL DEFAULT '[]',
  output_sha256 TEXT,
  policy_ids TEXT NOT NULL DEFAULT '[]',
  policy_sha256 TEXT,
  model_or_tool_versions TEXT NOT NULL DEFAULT '{}',
  runtime_command TEXT,
  replay_command TEXT,
  validation_status TEXT NOT NULL,
  failure_class TEXT,
  failure_reason_codes TEXT NOT NULL DEFAULT '[]',
  terminality TEXT NOT NULL DEFAULT 'terminal',
  repair_hint TEXT,
  safe_to_retry INTEGER NOT NULL DEFAULT 0,
  operator_action_required INTEGER NOT NULL DEFAULT 0,
  learning_event_refs TEXT NOT NULL DEFAULT '[]',
  metrics_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(case_key, dispatch_id, feature_id)
);

CREATE INDEX IF NOT EXISTS idx_market_context_stage_status_case
  ON market_context_stage_status(case_key, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_market_context_stage_status_status
  ON market_context_stage_status(stage_status, feature_id);

CREATE TABLE IF NOT EXISTS market_context_artifact_manifest (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  feature_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  schema_id TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  producer_stage TEXT NOT NULL,
  replay_command TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(case_key, dispatch_id, artifact_path)
);

CREATE INDEX IF NOT EXISTS idx_market_context_manifest_case
  ON market_context_artifact_manifest(case_key, dispatch_id);

CREATE TABLE IF NOT EXISTS case_artifact_manifest (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT,
  case_key TEXT,
  market_id TEXT,
  dispatch_id TEXT NOT NULL,
  feature_id TEXT,
  artifact_type TEXT NOT NULL,
  schema_version TEXT,
  schema_id TEXT,
  producer_stage TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  sha256 TEXT,
  artifact_sha256 TEXT,
  replay_command TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_case
  ON case_artifact_manifest(case_key, case_id, dispatch_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_market
  ON case_artifact_manifest(market_id, dispatch_id);

CREATE TABLE IF NOT EXISTS pipeline_stage_status (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  feature_id TEXT NOT NULL,
  stage_id TEXT NOT NULL,
  status TEXT NOT NULL,
  reason_code TEXT,
  artifact_manifest_id INTEGER REFERENCES case_artifact_manifest(id) ON DELETE SET NULL,
  policy_hash TEXT,
  details TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pipeline_stage_status_case_feature
  ON pipeline_stage_status(case_id, dispatch_id, feature_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_stage_status_market
  ON pipeline_stage_status(market_id, dispatch_id, status);

CREATE TABLE IF NOT EXISTS qdt_decomposition_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  market_complexity_score REAL NOT NULL,
  market_complexity_class TEXT NOT NULL,
  selected_candidate_id TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  artifact_manifest_id INTEGER NOT NULL REFERENCES case_artifact_manifest(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_case
  ON qdt_decomposition_runs(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_market_policy
  ON qdt_decomposition_runs(market_id, policy_hash);

CREATE TABLE IF NOT EXISTS qdt_required_research_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  parent_branch_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  leaf_condition_scope TEXT NOT NULL,
  dependency_group_id TEXT NOT NULL,
  question TEXT NOT NULL,
  bayesian_weight_class TEXT NOT NULL,
  information_weight REAL NOT NULL,
  artifact_manifest_id INTEGER NOT NULL REFERENCES case_artifact_manifest(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_case
  ON qdt_required_research_questions(case_id, dispatch_id, question_id);
CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_purpose
  ON qdt_required_research_questions(purpose, leaf_condition_scope);

CREATE TABLE IF NOT EXISTS qdt_decomposition_miss_labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  label_type TEXT NOT NULL,
  leaf_id TEXT,
  purpose TEXT,
  reason_code TEXT NOT NULL,
  evidence_ref TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_miss_labels_case
  ON qdt_decomposition_miss_labels(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_miss_labels_reason
  ON qdt_decomposition_miss_labels(reason_code);

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

CREATE TABLE IF NOT EXISTS amrg_temporal_eligibility_slices (
  temporal_eligibility_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  consuming_forecast_timestamp TEXT NOT NULL,
  max_underlying_source_timestamp TEXT,
  common_temporal_cohort_cutoff TEXT,
  temporal_eligibility_status TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_temporal_eligibility_case
  ON amrg_temporal_eligibility_slices(case_id, dispatch_id);

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

CREATE TABLE IF NOT EXISTS amrg_shared_evidence_cache_entries (
  reuse_entry_id TEXT PRIMARY KEY,
  reuse_key TEXT NOT NULL,
  event_source_family TEXT,
  claim_family_id TEXT,
  canonical_source_id TEXT,
  leaf_condition_scope TEXT NOT NULL,
  contract_scope TEXT NOT NULL,
  source_policy TEXT NOT NULL,
  forecast_time_window TEXT,
  artifact_ref TEXT,
  artifact_sha256 TEXT,
  reuse_scope TEXT NOT NULL,
  compatibility_status TEXT NOT NULL,
  producer_forecast_timestamp TEXT,
  artifact_generated_at TEXT,
  cache_generated_at TEXT,
  temporal_cutoff_timestamp TEXT,
  max_underlying_source_timestamp TEXT,
  temporal_eligibility_status TEXT NOT NULL,
  producer_case_id TEXT,
  producer_dispatch_id TEXT,
  generated_at TEXT NOT NULL,
  expires_at TEXT,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_shared_evidence_cache_entries_key
  ON amrg_shared_evidence_cache_entries(reuse_key);

CREATE TABLE IF NOT EXISTS amrg_relationship_observation_slices (
  observation_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  edge_id TEXT NOT NULL,
  selected_market_id TEXT NOT NULL,
  related_market_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  relationship_type_proposed TEXT NOT NULL DEFAULT '[]',
  relationship_type_accepted_or_downgraded TEXT NOT NULL DEFAULT '[]',
  relationship_strength TEXT NOT NULL,
  directionality TEXT NOT NULL,
  shared_entities TEXT NOT NULL DEFAULT '[]',
  shared_events TEXT NOT NULL DEFAULT '[]',
  shared_sources TEXT NOT NULL DEFAULT '[]',
  shared_driver_ids TEXT NOT NULL DEFAULT '[]',
  nomination_methods TEXT NOT NULL DEFAULT '[]',
  candidate_set_id TEXT NOT NULL,
  candidate_generation_methods TEXT NOT NULL DEFAULT '[]',
  model_assist_context TEXT NOT NULL DEFAULT '{}',
  causal_influence_fingerprint TEXT,
  feedback_scope TEXT NOT NULL,
  learning_escalation_allowed INTEGER NOT NULL DEFAULT 0,
  learning_escalation_reason TEXT,
  learning_escalation_targets TEXT NOT NULL DEFAULT '[]',
  question_decomposition_stage_usage_status TEXT NOT NULL,
  retrieval_outcome_status TEXT NOT NULL,
  scae_usage_status TEXT NOT NULL,
  decision_effect_status TEXT NOT NULL,
  forecast_validity_effect TEXT NOT NULL,
  observation_status TEXT NOT NULL,
  artifact_refs TEXT NOT NULL DEFAULT '[]',
  future_leakage_check_status TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_relationship_observation_case
  ON amrg_relationship_observation_slices(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS amrg_learning_escalation_records (
  escalation_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  escalation_status TEXT NOT NULL,
  routed_evaluation_lanes TEXT NOT NULL DEFAULT '[]',
  learning_escalation_reason TEXT,
  approved_evaluator_artifact_refs TEXT NOT NULL DEFAULT '[]',
  policy_ingest_status TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_amrg_learning_escalation_case
  ON amrg_learning_escalation_records(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS classification_prompt_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  classification_lane TEXT NOT NULL,
  prompt_contract_version TEXT NOT NULL,
  prompt_path TEXT NOT NULL,
  prompt_sha256 TEXT NOT NULL,
  market_reality_constraints_sha256 TEXT NOT NULL,
  classification_matrix_sha256 TEXT NOT NULL,
  policy_sha256 TEXT,
  generated_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  UNIQUE(case_key, dispatch_id, classification_lane)
);

CREATE TABLE IF NOT EXISTS classification_lane_evidence_classification_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  classification_lane TEXT NOT NULL,
  question_id TEXT NOT NULL,
  parent_branch_id TEXT,
  leaf_dependency_group_id TEXT NOT NULL,
  leaf_condition_scope TEXT NOT NULL,
  answer_value TEXT,
  impact_direction TEXT NOT NULL,
  evidence_diagnosticity TEXT NOT NULL,
  evidence_reliability TEXT NOT NULL,
  classification_confidence TEXT NOT NULL,
  classification_uncertainty_level TEXT NOT NULL,
  classification_uncertainty_reason TEXT,
  source_authority TEXT NOT NULL,
  evidence_directness TEXT NOT NULL,
  recency_status TEXT NOT NULL,
  specificity TEXT NOT NULL,
  classification_status TEXT NOT NULL,
  unanswerable_reason TEXT,
  uses_retrieval_packet_evidence INTEGER NOT NULL,
  uses_supplemental_research INTEGER NOT NULL,
  sidecar_schema_version TEXT NOT NULL,
  sidecar_artifact_path TEXT NOT NULL,
  sidecar_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(case_key, dispatch_id, classification_id)
);

CREATE INDEX IF NOT EXISTS idx_cls_slices_case_question
  ON classification_lane_evidence_classification_slices(case_key, dispatch_id, question_id);
CREATE INDEX IF NOT EXISTS idx_cls_slices_claim_lookup
  ON classification_lane_evidence_classification_slices(case_key, dispatch_id, leaf_dependency_group_id);

CREATE TABLE IF NOT EXISTS classification_lane_evidence_provenance_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provenance_slice_id TEXT NOT NULL UNIQUE,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  classification_lane TEXT NOT NULL,
  question_id TEXT NOT NULL,
  leaf_dependency_group_id TEXT NOT NULL,
  event_source_family TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  canonical_source_id TEXT NOT NULL,
  canonical_source_key TEXT,
  claim_fingerprint TEXT NOT NULL,
  content_sha256 TEXT,
  chunk_sha256 TEXT,
  source TEXT,
  source_type TEXT,
  evidence_origin TEXT NOT NULL,
  canonicalization_status TEXT NOT NULL,
  source_class_for_discounting TEXT NOT NULL,
  source_class_cap_scope TEXT NOT NULL,
  forecast_time_eligible INTEGER NOT NULL,
  published_at TEXT,
  observed_at TEXT,
  retrieved_at TEXT,
  artifact_ref TEXT,
  snippet_sha256 TEXT,
  retrieval_quality_status TEXT,
  retrieval_quality_score REAL,
  source_family_status TEXT,
  independence_status TEXT,
  claim_equivalence_status TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cls_provenance_case_claim
  ON classification_lane_evidence_provenance_slices(case_key, dispatch_id, event_source_family, claim_family_id);
CREATE INDEX IF NOT EXISTS idx_cls_provenance_source
  ON classification_lane_evidence_provenance_slices(canonical_source_id, claim_fingerprint);

CREATE TABLE IF NOT EXISTS evidence_direction_verification_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  verification_slice_id TEXT NOT NULL UNIQUE,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  question_id TEXT NOT NULL,
  proposed_direction TEXT NOT NULL,
  verified_direction TEXT NOT NULL,
  verified_directional_multiplier REAL NOT NULL,
  verification_status TEXT NOT NULL,
  verifier_reason_codes TEXT NOT NULL DEFAULT '[]',
  confidence_status TEXT NOT NULL,
  ambiguity_flag INTEGER NOT NULL DEFAULT 0,
  side_mapping_ref TEXT,
  market_constraints_sha256 TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_direction_verification_case
  ON evidence_direction_verification_slices(case_key, dispatch_id, verification_status);

CREATE TABLE IF NOT EXISTS evidence_quality_verification_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quality_verification_slice_id TEXT NOT NULL UNIQUE,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  question_id TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  verified_source_authority TEXT NOT NULL,
  verified_evidence_directness TEXT NOT NULL,
  verified_recency_status TEXT NOT NULL,
  verified_specificity TEXT NOT NULL,
  verified_classification_confidence TEXT NOT NULL,
  verifier_reason_codes TEXT NOT NULL DEFAULT '[]',
  caveat_flag INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quality_verification_case
  ON evidence_quality_verification_slices(case_key, dispatch_id, verification_status);

CREATE TABLE IF NOT EXISTS scae_mechanism_family_assignment_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mechanism_slice_id TEXT NOT NULL UNIQUE,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  parent_branch_id TEXT,
  leaf_dependency_group_id TEXT NOT NULL,
  information_cluster_key TEXT NOT NULL,
  event_source_family TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  canonical_source_id TEXT NOT NULL,
  claim_fingerprint TEXT NOT NULL,
  mechanism_family_tags TEXT NOT NULL DEFAULT '[]',
  primary_mechanism_family TEXT,
  causal_driver_family_id TEXT,
  mechanism_assignment_method TEXT NOT NULL,
  mechanism_assignment_status TEXT NOT NULL,
  mechanism_assignment_confidence TEXT NOT NULL,
  mechanism_assignment_reason_codes TEXT NOT NULL DEFAULT '[]',
  mechanism_policy_id TEXT,
  active_causal_family_policy_id TEXT,
  input_manifest_sha256 TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mechanism_case_cluster
  ON scae_mechanism_family_assignment_slices(case_key, dispatch_id, information_cluster_key);

CREATE TABLE IF NOT EXISTS scae_cross_leaf_dependency_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dependency_slice_id TEXT NOT NULL UNIQUE,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  information_cluster_key TEXT NOT NULL,
  event_source_family TEXT NOT NULL,
  claim_family_id TEXT NOT NULL,
  cross_leaf_reuse_count INTEGER NOT NULL,
  cross_dependency_group_reuse_count INTEGER NOT NULL,
  cross_leaf_allocation_method TEXT NOT NULL,
  selected_union_representative_classification_id TEXT,
  affected_leaf_allocations TEXT NOT NULL DEFAULT '[]',
  dependency_reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cross_leaf_case_cluster
  ON scae_cross_leaf_dependency_slices(case_key, dispatch_id, information_cluster_key);

CREATE TABLE IF NOT EXISTS public_structural_overlap_guard_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  overlap_guard_slice_id TEXT NOT NULL UNIQUE,
  classification_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  information_cluster_key TEXT NOT NULL,
  source_class_for_discounting TEXT NOT NULL,
  overlap_status TEXT NOT NULL,
  market_assimilation_context_ref TEXT,
  discount_policy TEXT NOT NULL,
  guard_reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS verification_deadlock_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deadlock_record_id TEXT NOT NULL UNIQUE,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  classification_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  deadlock_type TEXT NOT NULL,
  deadlock_status TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  blocked_downstream_stages TEXT NOT NULL DEFAULT '[]',
  repair_hint TEXT,
  forecast_validity_effect TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deadlocks_case
  ON verification_deadlock_records(case_key, dispatch_id, deadlock_status);
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upsert one market and insert one market snapshot into SQLite"
    )
    parser.add_argument("--file", default="-", help="Path to input JSON file, or - for stdin")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON result")
    return parser.parse_args()


def load_json(path_str: str):
    if path_str == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path_str).read_text()
    if not raw.strip():
        raise ValueError("input JSON is empty")
    return json.loads(raw)


def normalize_payload(payload: dict) -> tuple[dict, dict]:
    required = ["platform", "external_market_id", "title"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    payload.setdefault("metadata", {})
    snapshot = payload.get("snapshot") or {}
    if not snapshot.get("observed_at"):
        snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
    return payload, snapshot


def to_json_text(value) -> str:
    if value is None:
        value = {}
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def canonical_json_bytes(value) -> bytes:
    return to_json_text(value).encode("utf-8")


def payload_hash(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


MARKET_COLUMN_MIGRATIONS = {
    "closed_at": "TEXT",
    "resolution_outcome": "REAL",
    "resolution_source": "TEXT",
    "resolution_recorded_at": "TEXT",
    "resolution_payload_hash": "TEXT",
    "resolution_payload": "TEXT",
    "resolution_method": "TEXT",
    "resolution_checked_at": "TEXT",
}

PREDICTION_COLUMN_MIGRATIONS = {
    "prediction_run_id": "TEXT",
    "forecast_artifact_id": "TEXT",
    "case_key": "TEXT",
    "case_id": "TEXT",
    "dispatch_id": "TEXT",
    "engine_stage": "TEXT",
    "market_probability_method": "TEXT",
    "source_fetched_at": "TEXT",
    "source_payload_hash": "TEXT",
    "code_version": "TEXT",
    "model_name": "TEXT",
    "prompt_version": "TEXT",
    "input_hash": "TEXT",
    "input_artifact_path": "TEXT",
    "input_artifact_sha256": "TEXT",
    "prediction_artifact_path": "TEXT",
    "prediction_artifact_sha256": "TEXT",
    "snapshot_age_seconds": "REAL",
    "scoring_version": "TEXT",
    "scored_at": "TEXT",
    "scoring_resolution_payload_hash": "TEXT",
    "scoring_resolution_source": "TEXT",
}

FOUNDATION_COMPAT_COLUMN_MIGRATIONS = {
    "artifact_manifest": {
        "case_id": "TEXT",
        "market_id": "TEXT",
        "policy_hash": "TEXT",
    },
    "pipeline_stage_status_snapshots": {
        "case_id": "TEXT",
        "market_id": "TEXT",
        "stage_id": "TEXT",
        "feature_id": "TEXT",
        "status": "TEXT",
        "policy_hash": "TEXT",
        "terminal": "INTEGER DEFAULT 0",
    },
    "pipeline_error_events": {
        "case_id": "TEXT",
        "market_id": "TEXT",
        "stage_id": "TEXT",
        "grouping_key": "TEXT",
        "severity": "TEXT",
        "safe_details": "TEXT",
    },
    "pipeline_replay_manifests": {
        "case_id": "TEXT",
        "stage_id": "TEXT",
        "artifact_manifest_id": "TEXT",
        "input_hash": "TEXT",
        "policy_hash": "TEXT",
    },
    "pipeline_replay_result_records": {
        "case_id": "TEXT",
        "stage_id": "TEXT",
        "status": "TEXT",
        "output_hash": "TEXT",
        "message": "TEXT",
    },
    "pipeline_failure_pattern_groups": {
        "event_count": "INTEGER DEFAULT 0",
    },
    "golden_fixture_case_registry": {
        "title": "TEXT",
        "market_family": "TEXT",
        "tags": "TEXT DEFAULT '[]'",
        "expected_artifacts": "TEXT DEFAULT '[]'",
        "fixture_payload": "TEXT DEFAULT '{}'",
        "schema_id": "TEXT",
        "enabled": "INTEGER DEFAULT 1",
        "updated_at": "TEXT",
    },
    "golden_fixture_case_results": {
        "case_id": "TEXT",
        "status": "TEXT",
        "report_artifact_id": "TEXT",
        "missing_artifacts": "TEXT DEFAULT '[]'",
        "failure_class": "TEXT",
    },
}

SESSION6_COMPAT_COLUMN_MIGRATIONS = {
    "training_trace_full_materializations": {
        "schema_version": "TEXT",
        "trace_id": "TEXT",
        "case_key": "TEXT",
        "dispatch_id": "TEXT",
        "forecast_timestamp": "TEXT",
        "artifact_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
        "artifact_hashes": "TEXT NOT NULL DEFAULT '{}'",
        "replay_manifest_refs": "TEXT NOT NULL DEFAULT '[]'",
        "materialization_status": "TEXT",
        "temporal_leak_check_status": "TEXT",
        "live_authority": "TEXT",
        "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    },
    "calibration_candidate_records": {
        "schema_version": "TEXT",
        "owner_session": "TEXT",
        "changed_parameters": "TEXT NOT NULL DEFAULT '[]'",
        "source_replay_cohort_ids": "TEXT NOT NULL DEFAULT '[]'",
        "source_scorecard_refs": "TEXT NOT NULL DEFAULT '[]'",
        "source_trace_materialization_refs": "TEXT NOT NULL DEFAULT '[]'",
        "component_diagnostics_ref": "TEXT",
        "bounds_check_status": "TEXT",
        "protected_slice_non_degradation_status": "TEXT",
        "holdout_status": "TEXT",
        "canary_status": "TEXT",
        "promotion_status": "TEXT",
        "rollback_pointer_ref": "TEXT",
        "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    },
}

PRE_OPERATIONAL_COMPAT_COLUMN_MIGRATIONS = {
    "training_trace_minimal_pointers": {
        "trace_id": "TEXT",
        "schema_version": "TEXT",
        "case_key": "TEXT",
        "dispatch_id": "TEXT",
        "forecast_timestamp": "TEXT",
        "artifact_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
        "artifact_hashes": "TEXT NOT NULL DEFAULT '{}'",
        "trace_status": "TEXT",
        "live_authority": "TEXT",
        "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    },
    "training_trace_full_materializations": SESSION6_COMPAT_COLUMN_MIGRATIONS[
        "training_trace_full_materializations"
    ],
}


OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_ceiling_records (
  resource_record_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  stage_id TEXT NOT NULL,
  resource_name TEXT NOT NULL,
  observed_value REAL NOT NULL,
  ceiling_value REAL NOT NULL,
  status TEXT NOT NULL,
  unit TEXT NOT NULL,
  policy_hash TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resource_ceiling_records_case
  ON resource_ceiling_records(case_id, stage_id, status);

CREATE TABLE IF NOT EXISTS schema_evolution_checks (
  schema_check_id TEXT PRIMARY KEY,
  case_id TEXT,
  status TEXT NOT NULL,
  checked_schema_id TEXT NOT NULL,
  compatible INTEGER NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_schema_evolution_checks_case
  ON schema_evolution_checks(case_id, created_at);

CREATE TABLE IF NOT EXISTS launch_gate_results (
  launch_gate_result_id TEXT PRIMARY KEY,
  case_id TEXT,
  status TEXT NOT NULL,
  blocker_count INTEGER NOT NULL,
  warning_count INTEGER NOT NULL,
  report_artifact_id TEXT,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_launch_gate_results_case
  ON launch_gate_results(case_id, created_at);

CREATE TABLE IF NOT EXISTS training_trace_minimal_pointers (
  trace_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  market_id TEXT,
  run_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  artifact_manifest_ids TEXT NOT NULL DEFAULT '[]',
  artifact_hashes TEXT NOT NULL DEFAULT '{}',
  trace_status TEXT NOT NULL,
  live_authority TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  materialization_status TEXT NOT NULL,
  trace_pointer_id TEXT,
  pointer_artifact_id TEXT NOT NULL,
  stage_status_snapshot_ids TEXT NOT NULL DEFAULT '[]',
  forecast_authority TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_case
  ON training_trace_minimal_pointers(case_id, dispatch_id, run_id);

CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_status
  ON training_trace_minimal_pointers(trace_status, materialization_status);

CREATE TABLE IF NOT EXISTS training_trace_full_materializations (
  trace_materialization_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  artifact_manifest_ids TEXT NOT NULL DEFAULT '[]',
  artifact_hashes TEXT NOT NULL DEFAULT '{}',
  replay_manifest_refs TEXT NOT NULL DEFAULT '[]',
  materialization_status TEXT NOT NULL,
  temporal_leak_check_status TEXT NOT NULL,
  live_authority TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  queue_reason TEXT,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_trace_full_case
  ON training_trace_full_materializations(case_id, run_id);
CREATE INDEX IF NOT EXISTS idx_training_trace_full_trace
  ON training_trace_full_materializations(trace_id, materialization_status);

CREATE TABLE IF NOT EXISTS case_annotation_outputs (
  annotation_id TEXT PRIMARY KEY,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  scae_artifact_id TEXT,
  forecast_decision_id TEXT,
  annotation_path TEXT NOT NULL,
  annotation_sha256 TEXT NOT NULL,
  boundary_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_case_annotation_outputs_case
  ON case_annotation_outputs(case_key, dispatch_id, created_at);

CREATE TABLE IF NOT EXISTS evaluator_scorecards (
  scorecard_id TEXT PRIMARY KEY,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  forecast_decision_id TEXT,
  evaluation_cluster_id TEXT NOT NULL,
  outcome REAL,
  prediction_brier REAL,
  log_loss REAL,
  market_brier REAL,
  reliability_bucket TEXT NOT NULL,
  resolution_component REAL,
  diagnostic_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_evaluator_scorecards_case
  ON evaluator_scorecards(case_key, dispatch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evaluator_scorecards_cluster
  ON evaluator_scorecards(evaluation_cluster_id, created_at);

CREATE TABLE IF NOT EXISTS calibration_candidate_records (
  candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  owner_session TEXT NOT NULL,
  candidate_status TEXT NOT NULL,
  baseline_policy_sha256 TEXT,
  candidate_policy_sha256 TEXT,
  changed_parameters TEXT NOT NULL DEFAULT '[]',
  source_replay_cohort_ids TEXT NOT NULL DEFAULT '[]',
  scorecard_refs TEXT NOT NULL DEFAULT '[]',
  source_scorecard_refs TEXT NOT NULL DEFAULT '[]',
  source_trace_materialization_refs TEXT NOT NULL DEFAULT '[]',
  component_diagnostics_ref TEXT,
  bounds_check_status TEXT NOT NULL,
  protected_slice_non_degradation_status TEXT NOT NULL,
  holdout_status TEXT NOT NULL,
  canary_status TEXT NOT NULL,
  promotion_status TEXT NOT NULL,
  promotion_decision TEXT NOT NULL,
  canary_bucket TEXT NOT NULL,
  rollback_pointer_ref TEXT,
  rollback_status TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calibration_candidate_records_lane
  ON calibration_candidate_records(lane_id, created_at);

CREATE TABLE IF NOT EXISTS calibration_component_diagnostic_records (
  diagnostic_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  replay_cohort_id TEXT NOT NULL,
  headline_status TEXT NOT NULL,
  protected_slice_non_degradation_status TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  protected_slice_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS calibration_lane_health_records (
  health_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  health_status TEXT NOT NULL,
  active_pointer_id TEXT,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS calibration_canary_state_records (
  canary_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  canary_status TEXT NOT NULL,
  canary_bucket TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS calibration_lane_pointer_records (
  pointer_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  pointer_status TEXT NOT NULL,
  active_policy_snapshot_ref TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  rollback_pointer_ref TEXT,
  canary_status TEXT NOT NULL,
  promoted_at TEXT NOT NULL,
  promoted_by TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calibration_lane_pointers_lane
  ON calibration_lane_pointer_records(lane_id, pointer_status);

CREATE TABLE IF NOT EXISTS policy_rollback_events (
  rollback_event_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  pointer_id TEXT,
  rollback_pointer_ref TEXT,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  health_evidence_refs TEXT NOT NULL DEFAULT '[]',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS retrieval_policy_snapshot_records (
  snapshot_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  replay_feature_summary TEXT NOT NULL DEFAULT '{}',
  protected_primary_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decomposer_profile_candidate_records (
  profile_candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  qdt_shape_summary TEXT NOT NULL DEFAULT '{}',
  decomposer_miss_labels TEXT NOT NULL DEFAULT '[]',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decision_actionability_candidate_records (
  actionability_candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  route_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS emergency_conservative_overlay_records (
  overlay_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  trigger_kind TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  effects TEXT NOT NULL DEFAULT '[]',
  expires_at TEXT NOT NULL,
  rollback_semantics TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS optimization_maturity_results (
  maturity_result_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  status TEXT NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);
"""


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict) -> None:
    existing = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    ensure_columns(conn, "markets", MARKET_COLUMN_MIGRATIONS)
    ensure_columns(conn, "market_predictions", PREDICTION_COLUMN_MIGRATIONS)
    conn.executescript(PREDICTION_INDEX_SCHEMA)
    ensure_foundation_schema(conn)
    for table, columns in FOUNDATION_COMPAT_COLUMN_MIGRATIONS.items():
        ensure_columns(conn, table, columns)
    for table, columns in PRE_OPERATIONAL_COMPAT_COLUMN_MIGRATIONS.items():
        if table_exists(conn, table):
            ensure_columns(conn, table, columns)
    conn.executescript(OPERATIONAL_SCHEMA)
    conn.executescript(FIRST_WAVE_SCHEMA)
    for table, columns in SESSION6_COMPAT_COLUMN_MIGRATIONS.items():
        ensure_columns(conn, table, columns)


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            ensure_schema(conn)
    finally:
        conn.close()


def parse_market_time(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"([+-]\d{2})$", r"\1:00", text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_timestamp(value, field_name: str, default: Optional[str] = None) -> str:
    raw_value = value if value not in (None, "") else default
    parsed = parse_market_time(raw_value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a valid timestamp")
    return parsed.isoformat()


def snapshot_age_seconds(
    source_fetched_at: Optional[str],
    predicted_at: Optional[str],
    max_snapshot_age_seconds: Optional[float] = None,
) -> Optional[float]:
    if not source_fetched_at or not predicted_at:
        return None
    source_time = parse_market_time(source_fetched_at)
    prediction_time = parse_market_time(predicted_at)
    if source_time is None or prediction_time is None:
        return None
    age = (prediction_time - source_time).total_seconds()
    if age < 0:
        raise ValueError("source_fetched_at cannot be after predicted_at")
    if max_snapshot_age_seconds is not None and age > max_snapshot_age_seconds:
        raise ValueError(
            "market snapshot is stale for prediction: "
            f"{age:.3f}s > {max_snapshot_age_seconds:.3f}s"
        )
    return age


def market_expired_at(row: sqlite3.Row, cutoff: datetime):
    for column in ("closes_at", "resolves_at"):
        value = parse_market_time(row[column])
        if value is not None and value <= cutoff:
            return value
    return None


def market_expired(row: sqlite3.Row, cutoff: datetime) -> bool:
    return market_expired_at(row, cutoff) is not None


def cleanup_expired_markets(
    db_path: Path,
    grace_minutes: int = 0,
    dry_run: bool = False,
) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
        rows = conn.execute(
            """
            SELECT id, platform, external_market_id, title, closes_at, resolves_at
            FROM markets
            WHERE status NOT IN ('closed', 'resolved')
            """
        ).fetchall()
        expired = [
            (row, market_expired_at(row, cutoff))
            for row in rows
            if market_expired_at(row, cutoff) is not None
        ]
        messages = [
            (
                f"Would mark closed market {row['id']} "
                f"({row['platform']}:{row['external_market_id']}) {row['title']}"
            )
            for row, _ in expired
        ]

        if not dry_run:
            with conn:
                conn.executemany(
                    """
                    UPDATE markets
                    SET status = 'closed',
                        pipeline_status = 'expired',
                        closed_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        (
                            expired_at.isoformat(),
                            datetime.now(timezone.utc).isoformat(),
                            int(row["id"]),
                        )
                        for row, expired_at in expired
                    ],
                )

        return {
            "deleted": 0,
            "marked_closed": 0 if dry_run else len(expired),
            "expired": len(expired),
            "dry_run": dry_run,
            "messages": messages,
        }
    finally:
        conn.close()


def resolve_pipeline_status(
    existing: Optional[sqlite3.Row],
    current_price: Optional[float],
) -> str:
    if not existing:
        return "pending_research"

    prior_status = existing["pipeline_status"] or "pending_research"
    last_reasoned_price = existing["last_reasoned_price"]
    if (
        prior_status in {"ignored", "executed"}
        and last_reasoned_price is not None
        and current_price is not None
        and abs(float(last_reasoned_price) - current_price) >= 0.05
    ):
        return "pending_research"
    return prior_status


def upsert_market(conn: sqlite3.Connection, payload: dict, snapshot: dict) -> int:
    now = datetime.now(timezone.utc).isoformat()
    current_price = as_float(snapshot.get("yes_price"))

    existing = conn.execute(
        """
        SELECT id, status, pipeline_status, last_reasoned_price
        FROM markets
        WHERE platform = ? AND external_market_id = ?
        """,
        (payload["platform"], str(payload["external_market_id"])),
    ).fetchone()
    pipeline_status = resolve_pipeline_status(existing, current_price)

    if existing:
        market_id = int(existing["id"])
        existing_status = existing["status"]
        next_status = (
            existing_status
            if existing_status in {"closed", "resolved"}
            else payload.get("status") or "open"
        )
        conn.execute(
            """
            UPDATE markets
            SET slug = ?,
                title = ?,
                description = ?,
                category = ?,
                status = ?,
                outcome_type = ?,
                closes_at = ?,
                resolves_at = ?,
                metadata = ?,
                current_price = ?,
                pipeline_status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload.get("slug") or None,
                payload["title"],
                payload.get("description") or None,
                payload.get("category") or None,
                next_status,
                payload.get("outcome_type") or None,
                payload.get("closes_at") or None,
                payload.get("resolves_at") or None,
                to_json_text(payload.get("metadata")),
                current_price,
                pipeline_status,
                now,
                market_id,
            ),
        )
        return market_id

    cursor = conn.execute(
        """
        INSERT INTO markets (
          platform,
          external_market_id,
          slug,
          title,
          description,
          category,
          status,
          outcome_type,
          closes_at,
          resolves_at,
          metadata,
          current_price,
          pipeline_status,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["platform"],
            str(payload["external_market_id"]),
            payload.get("slug") or None,
            payload["title"],
            payload.get("description") or None,
            payload.get("category") or None,
            payload.get("status") or "open",
            payload.get("outcome_type") or None,
            payload.get("closes_at") or None,
            payload.get("resolves_at") or None,
            to_json_text(payload.get("metadata")),
            current_price,
            pipeline_status,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def insert_snapshot(conn: sqlite3.Connection, market_id: int, snapshot: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO market_snapshots (
          market_id,
          observed_at,
          last_price,
          best_bid,
          best_ask,
          yes_price,
          no_price,
          volume,
          open_interest,
          raw_payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            snapshot.get("observed_at"),
            as_float(snapshot.get("last_price")),
            as_float(snapshot.get("best_bid")),
            as_float(snapshot.get("best_ask")),
            as_float(snapshot.get("yes_price")),
            as_float(snapshot.get("no_price")),
            as_float(snapshot.get("volume")),
            as_float(snapshot.get("open_interest")),
            to_json_text(snapshot.get("raw_payload")),
        ),
    )
    return int(cursor.lastrowid)


def run_sqlite(db_path: Path, payload: dict, snapshot: dict) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            market_id = upsert_market(conn, payload, snapshot)
            snapshot_id = insert_snapshot(conn, market_id, snapshot)
        return {
            "market_id": market_id,
            "snapshot_id": snapshot_id,
            "observed_at": snapshot["observed_at"],
        }
    finally:
        conn.close()


def find_market(
    conn: sqlite3.Connection,
    market_id: Optional[int] = None,
    platform: Optional[str] = None,
    external_market_id: Optional[str] = None,
):
    if market_id is not None:
        return conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
    if platform and external_market_id:
        return conn.execute(
            """
            SELECT * FROM markets
            WHERE platform = ? AND external_market_id = ?
            """,
            (platform, str(external_market_id)),
        ).fetchone()
    raise ValueError("market_id or platform + external_market_id is required")


def latest_snapshot_for_market(
    conn: sqlite3.Connection,
    market_id: int,
    predicted_at: Optional[str] = None,
):
    if predicted_at:
        return conn.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE market_id = ? AND observed_at <= ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (market_id, predicted_at),
        ).fetchone()
    return conn.execute(
        """
        SELECT *
        FROM market_snapshots
        WHERE market_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (market_id,),
    ).fetchone()


def find_existing_prediction(
    conn: sqlite3.Connection,
    prediction_run_id: Optional[str] = None,
    forecast_artifact_id: Optional[str] = None,
):
    clauses = []
    params = []
    if prediction_run_id:
        clauses.append("prediction_run_id = ?")
        params.append(prediction_run_id)
    if forecast_artifact_id:
        clauses.append("forecast_artifact_id = ?")
        params.append(forecast_artifact_id)
    if not clauses:
        return None
    rows = conn.execute(
        f"""
        SELECT *
        FROM market_predictions
        WHERE {" OR ".join(clauses)}
        ORDER BY id
        """,
        params,
    ).fetchall()
    if not rows:
        return None
    if len({int(row["id"]) for row in rows}) > 1:
        raise ValueError("prediction identity matches multiple existing rows")
    return rows[0]


def prediction_result(row: sqlite3.Row, idempotent: bool = False) -> dict:
    result = {
        "prediction_id": int(row["id"]),
        "market_id": int(row["market_id"]),
        "prediction_run_id": row["prediction_run_id"],
        "forecast_artifact_id": row["forecast_artifact_id"],
        "case_key": row["case_key"],
        "case_id": row["case_id"],
        "dispatch_id": row["dispatch_id"],
        "engine_stage": row["engine_stage"],
        "snapshot_id": row["market_snapshot_id"],
        "predicted_probability": row["predicted_probability"],
        "market_probability": row["market_probability"],
        "market_probability_method": row["market_probability_method"],
        "source_fetched_at": row["source_fetched_at"],
        "source_payload_hash": row["source_payload_hash"],
        "snapshot_age_seconds": row["snapshot_age_seconds"],
        "prediction_brier": row["prediction_brier"],
        "market_brier": row["market_brier"],
        "scoring_version": row["scoring_version"],
        "scored_at": row["scored_at"],
    }
    if idempotent:
        result["idempotent"] = True
    return result


def _json_object_from_row(row: sqlite3.Row, column_name: str) -> dict:
    value = row[column_name]
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _scorecard_id_for_prediction(row: sqlite3.Row, evaluation_cluster_id: str) -> str:
    key = {
        "prediction_id": int(row["id"]),
        "evaluation_cluster_id": evaluation_cluster_id,
        "scoring_version": row["scoring_version"],
        "resolution_payload_hash": row["scoring_resolution_payload_hash"],
    }
    return "scorecard:" + payload_hash(key)


def _scorecard_result(row: sqlite3.Row, idempotent: bool = False) -> dict:
    metadata = _json_object_from_row(row, "metadata")
    result = {
        "schema_version": EVALUATOR_SCORECARD_SCHEMA_VERSION,
        "feature_id": "SCORE-001",
        "scorecard_id": row["scorecard_id"],
        "prediction_id": metadata.get("prediction_id"),
        "market_id": metadata.get("market_id"),
        "market_snapshot_id": metadata.get("market_snapshot_id"),
        "prediction_run_id": metadata.get("prediction_run_id"),
        "forecast_artifact_id": metadata.get("forecast_artifact_id"),
        "evaluation_cluster_id": row["evaluation_cluster_id"],
        "prediction_brier": row["prediction_brier"],
        "market_brier": row["market_brier"],
        "brier_edge": metadata.get("brier_edge"),
        "reliability_bucket": row["reliability_bucket"],
        "diagnostic_status": row["diagnostic_status"],
    }
    if idempotent:
        result["idempotent"] = True
    return result


def _scorecard_values_from_prediction(
    row: sqlite3.Row,
    *,
    evaluation_cluster_id: str,
    forecast_decision_id: Optional[str] = None,
    reliability_bucket_override: Optional[str] = None,
    diagnostic_status: str = "scoreable",
    metadata: Optional[dict] = None,
) -> dict:
    if row["outcome"] is None or row["prediction_brier"] is None:
        raise ValueError("prediction must be scored before writing an evaluator scorecard")
    if row["market_brier"] is None or row["market_probability"] is None:
        raise ValueError("prediction-time market baseline is required for SCORE-001 scorecards")
    if row["market_snapshot_id"] is None:
        raise ValueError("market_snapshot_id is required for SCORE-001 scorecards")
    if not row["scoring_version"]:
        raise ValueError("scoring_version is required for SCORE-001 scorecards")
    if not row["scoring_resolution_payload_hash"]:
        raise ValueError("resolution payload hash is required for SCORE-001 scorecards")

    prediction_metadata = _json_object_from_row(row, "metadata")
    resolved_forecast_decision_id = (
        forecast_decision_id or prediction_metadata.get("forecast_decision_id")
    )
    edge = brier_edge(row["prediction_brier"], row["market_brier"])
    scorecard_metadata = {
        "schema_version": EVALUATOR_SCORECARD_SCHEMA_VERSION,
        "feature_id": "SCORE-001",
        "prediction_id": int(row["id"]),
        "market_id": int(row["market_id"]),
        "market_snapshot_id": int(row["market_snapshot_id"]),
        "prediction_run_id": row["prediction_run_id"],
        "forecast_artifact_id": row["forecast_artifact_id"],
        "case_key": row["case_key"],
        "case_id": row["case_id"],
        "dispatch_id": row["dispatch_id"],
        "prediction_source": row["prediction_source"],
        "prediction_label": row["prediction_label"],
        "predicted_probability": row["predicted_probability"],
        "market_probability": row["market_probability"],
        "market_probability_method": row["market_probability_method"],
        "snapshot_age_seconds": row["snapshot_age_seconds"],
        "source_payload_hash": row["source_payload_hash"],
        "input_artifact_path": row["input_artifact_path"],
        "input_artifact_sha256": row["input_artifact_sha256"],
        "prediction_artifact_path": row["prediction_artifact_path"],
        "prediction_artifact_sha256": row["prediction_artifact_sha256"],
        "outcome": row["outcome"],
        "prediction_brier": row["prediction_brier"],
        "market_brier": row["market_brier"],
        "brier_edge": edge,
        "scoring_version": row["scoring_version"],
        "scored_at": row["scored_at"],
        "resolved_at": row["resolved_at"],
        "resolution_source": row["scoring_resolution_source"],
        "resolution_payload_hash": row["scoring_resolution_payload_hash"],
        "allowed_uses": [
            "calibration_debt_clearance_metric",
            "replay_scorecard_reference",
            "session6_evaluator_tuning_input",
        ],
        "forbidden_uses": [
            "production_forecast_write",
            "calibration_policy_promotion",
            "scae_probability_rewrite",
        ],
        "live_forecast_authority": False,
        "production_forecast_write_authority": False,
        "calibration_policy_promotion_authority": False,
        "scae_probability_rewrite_authority": False,
    }
    if metadata:
        scorecard_metadata["scorecard_metadata"] = metadata

    return {
        "scorecard_id": _scorecard_id_for_prediction(row, evaluation_cluster_id),
        "case_key": row["case_key"] or f"market:{row['market_id']}",
        "dispatch_id": row["dispatch_id"] or f"prediction:{row['id']}",
        "forecast_decision_id": resolved_forecast_decision_id,
        "evaluation_cluster_id": evaluation_cluster_id,
        "outcome": row["outcome"],
        "prediction_brier": row["prediction_brier"],
        "log_loss": binary_log_loss(row["predicted_probability"], row["outcome"]),
        "market_brier": row["market_brier"],
        "reliability_bucket": (
            reliability_bucket_override
            if reliability_bucket_override is not None
            else reliability_bucket(row["predicted_probability"])
        ),
        "resolution_component": edge,
        "diagnostic_status": diagnostic_status,
        "metadata": to_json_text(scorecard_metadata),
    }


def _write_evaluator_scorecard_for_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    evaluation_cluster_id: str,
    forecast_decision_id: Optional[str] = None,
    reliability_bucket_override: Optional[str] = None,
    diagnostic_status: str = "scoreable",
    metadata: Optional[dict] = None,
) -> dict:
    values = _scorecard_values_from_prediction(
        row,
        evaluation_cluster_id=evaluation_cluster_id,
        forecast_decision_id=forecast_decision_id,
        reliability_bucket_override=reliability_bucket_override,
        diagnostic_status=diagnostic_status,
        metadata=metadata,
    )
    existing = conn.execute(
        "SELECT * FROM evaluator_scorecards WHERE scorecard_id = ?",
        (values["scorecard_id"],),
    ).fetchone()
    now = utc_now()
    if existing:
        conn.execute(
            """
            UPDATE evaluator_scorecards
            SET case_key = ?,
                dispatch_id = ?,
                forecast_decision_id = ?,
                evaluation_cluster_id = ?,
                outcome = ?,
                prediction_brier = ?,
                log_loss = ?,
                market_brier = ?,
                reliability_bucket = ?,
                resolution_component = ?,
                diagnostic_status = ?,
                metadata = ?
            WHERE scorecard_id = ?
            """,
            (
                values["case_key"],
                values["dispatch_id"],
                values["forecast_decision_id"],
                values["evaluation_cluster_id"],
                values["outcome"],
                values["prediction_brier"],
                values["log_loss"],
                values["market_brier"],
                values["reliability_bucket"],
                values["resolution_component"],
                values["diagnostic_status"],
                values["metadata"],
                values["scorecard_id"],
            ),
        )
        scorecard_row = conn.execute(
            "SELECT * FROM evaluator_scorecards WHERE scorecard_id = ?",
            (values["scorecard_id"],),
        ).fetchone()
        return _scorecard_result(scorecard_row, idempotent=True)

    conn.execute(
        """
        INSERT INTO evaluator_scorecards (
          scorecard_id,
          case_key,
          dispatch_id,
          forecast_decision_id,
          evaluation_cluster_id,
          outcome,
          prediction_brier,
          log_loss,
          market_brier,
          reliability_bucket,
          resolution_component,
          diagnostic_status,
          created_at,
          metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["scorecard_id"],
            values["case_key"],
            values["dispatch_id"],
            values["forecast_decision_id"],
            values["evaluation_cluster_id"],
            values["outcome"],
            values["prediction_brier"],
            values["log_loss"],
            values["market_brier"],
            values["reliability_bucket"],
            values["resolution_component"],
            values["diagnostic_status"],
            now,
            values["metadata"],
        ),
    )
    scorecard_row = conn.execute(
        "SELECT * FROM evaluator_scorecards WHERE scorecard_id = ?",
        (values["scorecard_id"],),
    ).fetchone()
    return _scorecard_result(scorecard_row)


def write_evaluator_scorecard(
    db_path: Path,
    prediction_id: int,
    *,
    evaluation_cluster_id: str = CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    forecast_decision_id: Optional[str] = None,
    reliability_bucket_override: Optional[str] = None,
    diagnostic_status: str = "scoreable",
    metadata: Optional[dict] = None,
) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            prediction_row = conn.execute(
                "SELECT * FROM market_predictions WHERE id = ?",
                (int(prediction_id),),
            ).fetchone()
            if prediction_row is None:
                raise ValueError("prediction not found")
            return _write_evaluator_scorecard_for_row(
                conn,
                prediction_row,
                evaluation_cluster_id=evaluation_cluster_id,
                forecast_decision_id=forecast_decision_id,
                reliability_bucket_override=reliability_bucket_override,
                diagnostic_status=diagnostic_status,
                metadata=metadata,
            )
    finally:
        conn.close()


def write_evaluator_scorecards(
    db_path: Path,
    *,
    prediction_source: Optional[str] = None,
    prediction_label: Optional[str] = None,
    market_id: Optional[int] = None,
    evaluation_cluster_id: str = CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    metadata: Optional[dict] = None,
) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            filter_sql, filter_params = _prediction_filter_clause(
                prediction_source=prediction_source,
                prediction_label=prediction_label,
            )
            market_sql = ""
            if market_id is not None:
                market_sql = " AND market_id = ?"
                filter_params.append(int(market_id))
            rows = conn.execute(
                f"""
                SELECT *
                FROM market_predictions
                WHERE outcome IS NOT NULL
                  AND prediction_brier IS NOT NULL
                  AND market_brier IS NOT NULL
                  AND market_snapshot_id IS NOT NULL{filter_sql}{market_sql}
                ORDER BY scored_at, id
                """,
                filter_params,
            ).fetchall()
            scorecards = [
                _write_evaluator_scorecard_for_row(
                    conn,
                    row,
                    evaluation_cluster_id=evaluation_cluster_id,
                    metadata=metadata,
                )
                for row in rows
            ]
        return {
            "schema_version": EVALUATOR_SCORECARD_SCHEMA_VERSION,
            "feature_id": "SCORE-001",
            "evaluation_cluster_id": evaluation_cluster_id,
            "scored_predictions_considered": len(rows),
            "written_scorecards": len(scorecards),
            "scorecard_ids": [scorecard["scorecard_id"] for scorecard in scorecards],
        }
    finally:
        conn.close()


def existing_prediction_result_or_error(
    row: sqlite3.Row,
    *,
    predicted_probability,
    market_snapshot_id: Optional[int] = None,
    prediction_run_id: Optional[str],
    forecast_artifact_id: Optional[str],
    case_key: Optional[str],
    case_id: Optional[str],
    dispatch_id: Optional[str],
    engine_stage: Optional[str],
    prediction_source: str,
    prediction_label: Optional[str],
    source_payload_hash: Optional[str],
) -> dict:
    mismatches = []
    expected_fields = {
        "prediction_run_id": prediction_run_id,
        "forecast_artifact_id": forecast_artifact_id,
        "case_key": case_key,
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "engine_stage": engine_stage,
    }
    for field_name, expected_value in expected_fields.items():
        if expected_value is not None and row[field_name] != expected_value:
            mismatches.append(field_name)
    if float(row["predicted_probability"]) != float(predicted_probability):
        mismatches.append("predicted_probability")
    if market_snapshot_id is not None and row["market_snapshot_id"] != int(market_snapshot_id):
        mismatches.append("market_snapshot_id")
    if row["prediction_source"] != prediction_source:
        mismatches.append("prediction_source")
    if (row["prediction_label"] or None) != (prediction_label or None):
        mismatches.append("prediction_label")
    if source_payload_hash and row["source_payload_hash"] != source_payload_hash:
        mismatches.append("source_payload_hash")
    if mismatches:
        raise ValueError(
            "prediction identity already exists with different "
            + ", ".join(mismatches)
        )
    return prediction_result(row, idempotent=True)


def record_market_prediction(
    db_path: Path,
    predicted_probability,
    market_id: Optional[int] = None,
    market_snapshot_id: Optional[int] = None,
    platform: str = "polymarket",
    external_market_id: Optional[str] = None,
    prediction_run_id: Optional[str] = None,
    forecast_artifact_id: Optional[str] = None,
    case_key: Optional[str] = None,
    case_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    engine_stage: Optional[str] = None,
    prediction_source: str = "pipeline",
    prediction_label: Optional[str] = None,
    predicted_at: Optional[str] = None,
    market_probability=None,
    market_probability_method: Optional[str] = None,
    source_fetched_at: Optional[str] = None,
    source_payload_hash: Optional[str] = None,
    code_version: Optional[str] = None,
    model_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    input_artifact_path: Optional[str] = None,
    input_artifact_sha256: Optional[str] = None,
    prediction_artifact_path: Optional[str] = None,
    prediction_artifact_sha256: Optional[str] = None,
    max_snapshot_age_seconds: Optional[float] = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    rationale: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    predicted_probability = validate_probability(
        predicted_probability,
        "predicted_probability",
    )
    predicted_at = normalize_timestamp(predicted_at, "predicted_at", utc_now())
    if source_fetched_at:
        source_fetched_at = normalize_timestamp(source_fetched_at, "source_fetched_at")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            existing_prediction = find_existing_prediction(
                conn,
                prediction_run_id=prediction_run_id,
                forecast_artifact_id=forecast_artifact_id,
            )
            if existing_prediction:
                return existing_prediction_result_or_error(
                    existing_prediction,
                    predicted_probability=predicted_probability,
                    market_snapshot_id=market_snapshot_id,
                    prediction_run_id=prediction_run_id,
                    forecast_artifact_id=forecast_artifact_id,
                    case_key=case_key,
                    case_id=case_id,
                    dispatch_id=dispatch_id,
                    engine_stage=engine_stage,
                    prediction_source=prediction_source,
                    prediction_label=prediction_label,
                    source_payload_hash=source_payload_hash,
                )

            market = find_market(conn, market_id, platform, external_market_id)
            if not market:
                raise ValueError("market not found")

            if market_snapshot_id is not None:
                snapshot = conn.execute(
                    """
                    SELECT *
                    FROM market_snapshots
                    WHERE id = ? AND market_id = ?
                    """,
                    (int(market_snapshot_id), int(market["id"])),
                ).fetchone()
                if not snapshot:
                    raise ValueError("market snapshot not found")
                snapshot_time = parse_market_time(snapshot["observed_at"])
                prediction_time = parse_market_time(predicted_at)
                if snapshot_time is not None and prediction_time is not None and snapshot_time > prediction_time:
                    raise ValueError("market snapshot is after prediction timestamp")
            else:
                snapshot = latest_snapshot_for_market(conn, int(market["id"]), predicted_at)
            if source_fetched_at is None and snapshot:
                source_fetched_at = snapshot["observed_at"]
            if source_fetched_at:
                source_fetched_at = normalize_timestamp(source_fetched_at, "source_fetched_at")
            snapshot_age = snapshot_age_seconds(
                source_fetched_at,
                predicted_at,
                max_snapshot_age_seconds,
            )
            if market_probability is None:
                market_probability, market_probability_method = market_probability_from_snapshot(
                    snapshot,
                    market["current_price"],
                )
            elif market_probability_method is None:
                market_probability_method = "override"
            if market_probability is None:
                market_probability = market["current_price"]
                if market_probability_method is None:
                    market_probability_method = "current_price"
            if market_probability is not None:
                market_probability = validate_probability(
                    market_probability,
                    "market_probability",
                )

            outcome = market["resolution_outcome"]
            prediction_brier = None
            market_brier = None
            scoring_version = None
            scored_at = None
            scoring_resolution_payload_hash = None
            scoring_resolution_source = None
            resolved_at = None
            if outcome is not None:
                scores = prediction_scores(
                    predicted_probability,
                    market_probability,
                    outcome,
                )
                prediction_brier = scores["prediction_brier"]
                market_brier = scores["market_brier"]
                resolved_at = market["resolution_recorded_at"]
                scoring_version = BRIER_SCORING_VERSION
                scored_at = utc_now()
                scoring_resolution_payload_hash = market["resolution_payload_hash"]
                scoring_resolution_source = market["resolution_source"]

            now = utc_now()
            cursor = conn.execute(
                """
                INSERT INTO market_predictions (
                  market_id,
                  prediction_run_id,
                  forecast_artifact_id,
                  case_key,
                  case_id,
                  dispatch_id,
                  engine_stage,
                  prediction_source,
                  prediction_label,
                  predicted_at,
                  predicted_probability,
                  market_probability,
                  market_probability_method,
                  market_snapshot_id,
                  source_fetched_at,
                  source_payload_hash,
                  code_version,
                  model_name,
                  prompt_version,
                  input_hash,
                  input_artifact_path,
                  input_artifact_sha256,
                  prediction_artifact_path,
                  prediction_artifact_sha256,
                  snapshot_age_seconds,
                  outcome,
                  prediction_brier,
                  market_brier,
                  scoring_version,
                  scored_at,
                  scoring_resolution_payload_hash,
                  scoring_resolution_source,
                  resolved_at,
                  rationale,
                  metadata,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(market["id"]),
                    prediction_run_id,
                    forecast_artifact_id,
                    case_key,
                    case_id,
                    dispatch_id,
                    engine_stage,
                    prediction_source,
                    prediction_label,
                    predicted_at,
                    predicted_probability,
                    market_probability,
                    market_probability_method,
                    int(snapshot["id"]) if snapshot else None,
                    source_fetched_at,
                    source_payload_hash,
                    code_version,
                    model_name,
                    prompt_version,
                    input_hash,
                    input_artifact_path,
                    input_artifact_sha256,
                    prediction_artifact_path,
                    prediction_artifact_sha256,
                    snapshot_age,
                    outcome,
                    prediction_brier,
                    market_brier,
                    scoring_version,
                    scored_at,
                    scoring_resolution_payload_hash,
                    scoring_resolution_source,
                    resolved_at,
                    rationale,
                    to_json_text(metadata),
                    now,
                    now,
                ),
            )
            prediction_row = conn.execute(
                "SELECT * FROM market_predictions WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return prediction_result(prediction_row)
    finally:
        conn.close()


def record_prediction_with_snapshot(
    db_path: Path,
    payload: dict,
    predicted_probability,
    prediction_run_id: Optional[str] = None,
    forecast_artifact_id: Optional[str] = None,
    case_key: Optional[str] = None,
    case_id: Optional[str] = None,
    dispatch_id: Optional[str] = None,
    engine_stage: Optional[str] = None,
    prediction_source: str = "pipeline",
    prediction_label: Optional[str] = None,
    predicted_at: Optional[str] = None,
    market_probability=None,
    market_probability_method: Optional[str] = None,
    source_fetched_at: Optional[str] = None,
    source_payload_hash: Optional[str] = None,
    code_version: Optional[str] = None,
    model_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    input_artifact_path: Optional[str] = None,
    input_artifact_sha256: Optional[str] = None,
    prediction_artifact_path: Optional[str] = None,
    prediction_artifact_sha256: Optional[str] = None,
    max_snapshot_age_seconds: Optional[float] = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    rationale: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    predicted_probability = validate_probability(
        predicted_probability,
        "predicted_probability",
    )
    source_payload_hash = source_payload_hash or payload_hash(payload)
    payload, snapshot = normalize_payload(payload)
    if source_fetched_at:
        source_fetched_at = normalize_timestamp(source_fetched_at, "source_fetched_at")
        snapshot["observed_at"] = source_fetched_at
    else:
        source_fetched_at = normalize_timestamp(
            snapshot.get("observed_at"),
            "source_fetched_at",
        )
        snapshot["observed_at"] = source_fetched_at
    predicted_at = normalize_timestamp(
        predicted_at,
        "predicted_at",
        source_fetched_at,
    )
    snapshot_age = snapshot_age_seconds(
        source_fetched_at,
        predicted_at,
        max_snapshot_age_seconds,
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            existing_prediction = find_existing_prediction(
                conn,
                prediction_run_id=prediction_run_id,
                forecast_artifact_id=forecast_artifact_id,
            )
            if existing_prediction:
                return existing_prediction_result_or_error(
                    existing_prediction,
                    predicted_probability=predicted_probability,
                    prediction_run_id=prediction_run_id,
                    forecast_artifact_id=forecast_artifact_id,
                    case_key=case_key,
                    case_id=case_id,
                    dispatch_id=dispatch_id,
                    engine_stage=engine_stage,
                    prediction_source=prediction_source,
                    prediction_label=prediction_label,
                    source_payload_hash=source_payload_hash,
                )

            market_id = upsert_market(conn, payload, snapshot)
            snapshot_id = insert_snapshot(conn, market_id, snapshot)
            market = conn.execute(
                "SELECT * FROM markets WHERE id = ?",
                (market_id,),
            ).fetchone()
            snapshot_row = conn.execute(
                "SELECT * FROM market_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()

            if market_probability is None:
                market_probability, market_probability_method = market_probability_from_snapshot(
                    snapshot_row,
                    market["current_price"],
                )
            elif market_probability_method is None:
                market_probability_method = "override"
            if market_probability is not None:
                market_probability = validate_probability(
                    market_probability,
                    "market_probability",
                )

            outcome = market["resolution_outcome"]
            prediction_brier = None
            market_brier = None
            scoring_version = None
            scored_at = None
            scoring_resolution_payload_hash = None
            scoring_resolution_source = None
            resolved_at = None
            if outcome is not None:
                scores = prediction_scores(
                    predicted_probability,
                    market_probability,
                    outcome,
                )
                prediction_brier = scores["prediction_brier"]
                market_brier = scores["market_brier"]
                resolved_at = market["resolution_recorded_at"]
                scoring_version = BRIER_SCORING_VERSION
                scored_at = utc_now()
                scoring_resolution_payload_hash = market["resolution_payload_hash"]
                scoring_resolution_source = market["resolution_source"]

            now = utc_now()
            cursor = conn.execute(
                """
                INSERT INTO market_predictions (
                  market_id,
                  prediction_run_id,
                  forecast_artifact_id,
                  case_key,
                  case_id,
                  dispatch_id,
                  engine_stage,
                  prediction_source,
                  prediction_label,
                  predicted_at,
                  predicted_probability,
                  market_probability,
                  market_probability_method,
                  market_snapshot_id,
                  source_fetched_at,
                  source_payload_hash,
                  code_version,
                  model_name,
                  prompt_version,
                  input_hash,
                  input_artifact_path,
                  input_artifact_sha256,
                  prediction_artifact_path,
                  prediction_artifact_sha256,
                  snapshot_age_seconds,
                  outcome,
                  prediction_brier,
                  market_brier,
                  scoring_version,
                  scored_at,
                  scoring_resolution_payload_hash,
                  scoring_resolution_source,
                  resolved_at,
                  rationale,
                  metadata,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    prediction_run_id,
                    forecast_artifact_id,
                    case_key,
                    case_id,
                    dispatch_id,
                    engine_stage,
                    prediction_source,
                    prediction_label,
                    predicted_at,
                    predicted_probability,
                    market_probability,
                    market_probability_method,
                    snapshot_id,
                    source_fetched_at,
                    source_payload_hash,
                    code_version,
                    model_name,
                    prompt_version,
                    input_hash,
                    input_artifact_path,
                    input_artifact_sha256,
                    prediction_artifact_path,
                    prediction_artifact_sha256,
                    snapshot_age,
                    outcome,
                    prediction_brier,
                    market_brier,
                    scoring_version,
                    scored_at,
                    scoring_resolution_payload_hash,
                    scoring_resolution_source,
                    resolved_at,
                    rationale,
                    to_json_text(metadata),
                    now,
                    now,
                ),
            )
            prediction_row = conn.execute(
                "SELECT * FROM market_predictions WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return prediction_result(prediction_row)
    finally:
        conn.close()


def settle_market_outcome(
    db_path: Path,
    outcome,
    market_id: Optional[int] = None,
    platform: str = "polymarket",
    external_market_id: Optional[str] = None,
    resolved_at: Optional[str] = None,
    resolution_source: str = "manual",
    resolution_payload: Optional[dict] = None,
    resolution_payload_hash: Optional[str] = None,
    resolution_method: Optional[str] = None,
    resolution_checked_at: Optional[str] = None,
) -> dict:
    outcome = validate_probability(outcome, "outcome")
    resolved_at = resolved_at or datetime.now(timezone.utc).isoformat()
    resolution_checked_at = resolution_checked_at or datetime.now(timezone.utc).isoformat()
    if resolution_payload is not None and resolution_payload_hash is None:
        resolution_payload_hash = payload_hash(resolution_payload)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_schema(conn)
            market = find_market(conn, market_id, platform, external_market_id)
            if not market:
                raise ValueError("market not found")

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE markets
                SET status = 'resolved',
                    pipeline_status = 'resolved',
                    closed_at = ?,
                    resolution_outcome = ?,
                    resolution_source = ?,
                    resolution_recorded_at = ?,
                    resolution_payload_hash = ?,
                    resolution_payload = ?,
                    resolution_method = ?,
                    resolution_checked_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    resolved_at,
                    outcome,
                    resolution_source,
                    resolved_at,
                    resolution_payload_hash,
                    to_json_text(resolution_payload) if resolution_payload is not None else None,
                    resolution_method,
                    resolution_checked_at,
                    now,
                    int(market["id"]),
                ),
            )
            scored_at = utc_now()
            conn.execute(
                """
                UPDATE market_predictions
                SET outcome = ?,
                    prediction_brier = (predicted_probability - ?) *
                                       (predicted_probability - ?),
                    market_brier = CASE
                        WHEN market_probability IS NULL THEN NULL
                        ELSE (market_probability - ?) * (market_probability - ?)
                    END,
                    scoring_version = ?,
                    scored_at = ?,
                    scoring_resolution_payload_hash = ?,
                    scoring_resolution_source = ?,
                    resolved_at = ?,
                    updated_at = ?
                WHERE market_id = ?
                """,
                (
                    outcome,
                    outcome,
                    outcome,
                    outcome,
                    outcome,
                    BRIER_SCORING_VERSION,
                    scored_at,
                    resolution_payload_hash,
                    resolution_source,
                    resolved_at,
                    now,
                    int(market["id"]),
                ),
            )
            updated_predictions = conn.execute(
                "SELECT changes()"
            ).fetchone()[0]
        return {
            "market_id": int(market["id"]),
            "outcome": outcome,
            "resolved_at": resolved_at,
            "resolution_source": resolution_source,
            "resolution_method": resolution_method,
            "resolution_payload_hash": resolution_payload_hash,
            "updated_predictions": updated_predictions,
        }
    finally:
        conn.close()


def write_resolution_score(
    db_path: Path,
    outcome,
    market_id: Optional[int] = None,
    platform: str = "polymarket",
    external_market_id: Optional[str] = None,
    resolved_at: Optional[str] = None,
    resolution_source: str = "manual",
    resolution_payload: Optional[dict] = None,
    resolution_payload_hash: Optional[str] = None,
    resolution_method: Optional[str] = None,
    resolution_checked_at: Optional[str] = None,
    prediction_source: Optional[str] = None,
    prediction_label: Optional[str] = None,
    evaluation_cluster_id: str = CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    write_scorecards: bool = True,
) -> dict:
    if write_scorecards and resolution_payload is None and not resolution_payload_hash:
        raise ValueError("resolution payload hash is required for SCORE-001 scorecards")
    settled = settle_market_outcome(
        db_path=db_path,
        market_id=market_id,
        platform=platform,
        external_market_id=external_market_id,
        outcome=outcome,
        resolved_at=resolved_at,
        resolution_source=resolution_source,
        resolution_payload=resolution_payload,
        resolution_payload_hash=resolution_payload_hash,
        resolution_method=resolution_method,
        resolution_checked_at=resolution_checked_at,
    )
    scorecards = None
    if write_scorecards:
        scorecards = write_evaluator_scorecards(
            db_path,
            market_id=settled["market_id"],
            prediction_source=prediction_source,
            prediction_label=prediction_label,
            evaluation_cluster_id=evaluation_cluster_id,
            metadata={
                "resolution_source": settled["resolution_source"],
                "resolution_payload_hash": settled["resolution_payload_hash"],
                "resolution_method": settled["resolution_method"],
            },
        )
    return {
        "schema_version": SCORE001_REPORT_SCHEMA_VERSION,
        "feature_id": "SCORE-001",
        "settled_market": settled,
        "scorecards": scorecards,
        "calibration_policy_promotion_authority": False,
        "production_forecast_write_authority": False,
        "scae_probability_rewrite_authority": False,
    }


def _prediction_filter_clause(
    prediction_source: Optional[str] = None,
    prediction_label: Optional[str] = None,
) -> tuple[str, list]:
    clauses = []
    params = []
    if prediction_source:
        clauses.append("prediction_source = ?")
        params.append(prediction_source)
    if prediction_label:
        clauses.append("prediction_label = ?")
        params.append(prediction_label)
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def brier_score_report(
    db_path: Path,
    prediction_source: Optional[str] = None,
    prediction_label: Optional[str] = None,
    evaluation_cluster_id: Optional[str] = CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        filter_sql, filter_params = _prediction_filter_clause(
            prediction_source=prediction_source,
            prediction_label=prediction_label,
        )
        overall = conn.execute(
            f"""
            SELECT
              COUNT(*) AS predictions,
              COUNT(prediction_brier) AS scored_predictions,
              COUNT(market_brier) AS scored_market_baselines,
              COALESCE(SUM(CASE
                    WHEN prediction_brier IS NOT NULL AND market_brier IS NOT NULL THEN 1
                    ELSE 0
                  END), 0) AS scored_predictions_with_market_baseline,
              COALESCE(SUM(CASE
                    WHEN prediction_brier IS NOT NULL AND market_brier IS NULL THEN 1
                    ELSE 0
                  END), 0) AS scored_predictions_missing_market_baseline,
              COALESCE(SUM(CASE
                    WHEN prediction_brier IS NOT NULL
                     AND market_brier IS NOT NULL
                     AND market_snapshot_id IS NOT NULL
                     AND scoring_resolution_payload_hash IS NOT NULL THEN 1
                    ELSE 0
                  END), 0) AS scoreable_resolution_records,
              AVG(prediction_brier) AS avg_prediction_brier,
              AVG(market_brier) AS avg_market_brier,
              AVG(CASE
                    WHEN market_brier IS NULL OR prediction_brier IS NULL THEN NULL
                    ELSE market_brier - prediction_brier
                  END) AS avg_brier_edge,
              GROUP_CONCAT(DISTINCT scoring_version) AS scoring_versions,
              MIN(predicted_at) AS first_prediction_at,
              MAX(predicted_at) AS last_prediction_at,
              MAX(resolved_at) AS latest_resolved_at
            FROM market_predictions
            WHERE 1 = 1{filter_sql}
            """,
            filter_params,
        ).fetchone()
        by_source = conn.execute(
            f"""
            SELECT
              prediction_source,
              COALESCE(prediction_label, '') AS prediction_label,
              COUNT(*) AS predictions,
              COUNT(prediction_brier) AS scored_predictions,
              COUNT(market_brier) AS scored_market_baselines,
              COALESCE(SUM(CASE
                    WHEN prediction_brier IS NOT NULL AND market_brier IS NOT NULL THEN 1
                    ELSE 0
                  END), 0) AS scored_predictions_with_market_baseline,
              AVG(prediction_brier) AS avg_prediction_brier,
              AVG(market_brier) AS avg_market_brier,
              AVG(CASE
                    WHEN market_brier IS NULL OR prediction_brier IS NULL THEN NULL
                    ELSE market_brier - prediction_brier
                  END) AS avg_brier_edge
            FROM market_predictions
            WHERE 1 = 1{filter_sql}
            GROUP BY prediction_source, prediction_label
            ORDER BY scored_predictions DESC, prediction_source, prediction_label
            """,
            filter_params,
        ).fetchall()
        bucket_rows = conn.execute(
            f"""
            SELECT predicted_probability, prediction_brier, market_brier
            FROM market_predictions
            WHERE prediction_brier IS NOT NULL{filter_sql}
            """,
            filter_params,
        ).fetchall()
        bucket_summaries: dict[str, dict] = {}
        for row in bucket_rows:
            bucket = reliability_bucket(row["predicted_probability"])
            summary = bucket_summaries.setdefault(
                bucket,
                {
                    "reliability_bucket": bucket,
                    "scored_predictions": 0,
                    "scored_market_baselines": 0,
                    "prediction_brier_sum": 0.0,
                    "market_brier_sum": 0.0,
                    "brier_edge_sum": 0.0,
                    "brier_edge_count": 0,
                },
            )
            summary["scored_predictions"] += 1
            summary["prediction_brier_sum"] += float(row["prediction_brier"])
            if row["market_brier"] is not None:
                summary["scored_market_baselines"] += 1
                summary["market_brier_sum"] += float(row["market_brier"])
                summary["brier_edge_sum"] += brier_edge(
                    row["prediction_brier"],
                    row["market_brier"],
                )
                summary["brier_edge_count"] += 1
        by_reliability_bucket = []
        for bucket in sorted(bucket_summaries):
            summary = bucket_summaries[bucket]
            scored_predictions = summary["scored_predictions"]
            scored_market_baselines = summary["scored_market_baselines"]
            edge_count = summary["brier_edge_count"]
            by_reliability_bucket.append(
                {
                    "reliability_bucket": bucket,
                    "scored_predictions": scored_predictions,
                    "scored_market_baselines": scored_market_baselines,
                    "avg_prediction_brier": (
                        summary["prediction_brier_sum"] / scored_predictions
                        if scored_predictions
                        else None
                    ),
                    "avg_market_brier": (
                        summary["market_brier_sum"] / scored_market_baselines
                        if scored_market_baselines
                        else None
                    ),
                    "avg_brier_edge": (
                        summary["brier_edge_sum"] / edge_count
                        if edge_count
                        else None
                    ),
                }
            )
        scorecard_sql = ""
        scorecard_params: list[str] = []
        if evaluation_cluster_id:
            scorecard_sql = "WHERE evaluation_cluster_id = ?"
            scorecard_params.append(evaluation_cluster_id)
        scorecards = conn.execute(
            f"""
            SELECT
              COUNT(*) AS scorecards,
              COUNT(DISTINCT case_key || '|' || dispatch_id) AS scored_cases,
              AVG(prediction_brier) AS avg_prediction_brier,
              AVG(market_brier) AS avg_market_brier,
              AVG(CASE
                    WHEN market_brier IS NULL OR prediction_brier IS NULL THEN NULL
                    ELSE market_brier - prediction_brier
                  END) AS avg_brier_edge,
              MIN(created_at) AS first_scorecard_at,
              MAX(created_at) AS latest_scorecard_at
            FROM evaluator_scorecards
            {scorecard_sql}
            """,
            scorecard_params,
        ).fetchone()
        return {
            "schema_version": SCORE001_REPORT_SCHEMA_VERSION,
            "feature_id": "SCORE-001",
            "db_path": str(db_path),
            "prediction_source": prediction_source,
            "prediction_label": prediction_label,
            "evaluation_cluster_id": evaluation_cluster_id,
            "overall": dict(overall),
            "by_source": [dict(row) for row in by_source],
            "by_reliability_bucket": by_reliability_bucket,
            "scorecards": dict(scorecards),
            "notes": {
                "brier_direction": "lower_is_better",
                "avg_brier_edge": "avg_market_brier - avg_prediction_brier; positive means pipeline beat the market baseline",
                "scorecard_authority": "SCORE-001 scorecards are diagnostic references only; they do not promote calibration policy, rewrite SCAE probability, or write live forecasts.",
            },
        }
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    try:
        payload = load_json(args.file)
        payload, snapshot = normalize_payload(payload)
        result = run_sqlite(Path(args.db_path), payload, snapshot)
        if args.pretty:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
