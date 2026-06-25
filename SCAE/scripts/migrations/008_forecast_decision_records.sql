PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS forecast_decision_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  forecast_decision_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  run_id TEXT,
  forecast_timestamp TEXT,
  scae_ledger_id TEXT NOT NULL,
  scae_ledger_digest TEXT NOT NULL,
  decision_gate_id TEXT NOT NULL,
  decision_gate_digest TEXT NOT NULL,
  synthesis_annotation_ref TEXT,
  synthesis_annotation_digest TEXT,
  production_forecast_prob REAL,
  canonical_probability REAL,
  forecast_validity_status TEXT NOT NULL,
  execution_authority_status TEXT NOT NULL,
  actionability_status TEXT NOT NULL,
  final_probability_fields_status TEXT NOT NULL,
  production_persistence_status TEXT NOT NULL,
  production_forecast_persisted INTEGER NOT NULL DEFAULT 0,
  scoreable_forecast_output INTEGER NOT NULL DEFAULT 0,
  writes_market_prediction INTEGER NOT NULL DEFAULT 0,
  probability_source TEXT NOT NULL,
  decision_effect_status TEXT NOT NULL,
  non_scoreable_reason_code TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  artifact_payload_json TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  scae_ledger_payload_sha256 TEXT NOT NULL,
  decision_gate_payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_forecast_decision_case
  ON forecast_decision_records(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_forecast_decision_scae
  ON forecast_decision_records(scae_ledger_id, decision_gate_id);
CREATE INDEX IF NOT EXISTS idx_forecast_decision_status
  ON forecast_decision_records(forecast_validity_status, actionability_status);
