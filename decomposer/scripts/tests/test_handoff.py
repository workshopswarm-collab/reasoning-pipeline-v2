#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DecomposerHandoffError,
    build_decomposer_handoff,
    resolve_decomposer_model_lane,
)
from predquant.ads_handoff import ArtifactManifestContext, build_artifact_manifest, canonical_json  # noqa: E402


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class DecomposerHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.case_fields = {
            "case_id": "case-1",
            "case_key": "polymarket:market-1",
            "dispatch_id": "dispatch-1",
            "forecast_timestamp": "2026-06-24T18:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T17:55:00+00:00",
        }
        self.bundle = self._build_bundle(use_waiver=False)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_json(self, name: str, payload: dict) -> Path:
        path = self.base / name
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        return path

    def _manifest(
        self,
        *,
        payload: dict,
        file_name: str,
        manifest_artifact_type: str,
        schema_version: str,
        stage: str,
        producer: str,
        input_manifest_ids: list[str] | None = None,
    ) -> dict:
        path = self._write_json(file_name, payload)
        context = ArtifactManifestContext(
            case_id=payload["case_id"],
            case_key=payload["case_key"],
            dispatch_id=payload["dispatch_id"],
            stage=stage,
            producer=producer,
            forecast_timestamp=payload["forecast_timestamp"],
            source_cutoff_timestamp=payload["source_cutoff_timestamp"],
            generated_at="2026-06-24T18:01:00+00:00",
        )
        return build_artifact_manifest(
            context=context,
            artifact_type=manifest_artifact_type,
            artifact_schema_version=schema_version,
            path=path,
            input_manifest_ids=input_manifest_ids or [],
            validation_status="valid",
            validator_version=schema_version,
            temporal_isolation_status="pass",
            metadata={"fixture": "session-03-phase-1"},
        )

    def _case_payload(self) -> dict:
        return {
            "artifact_type": "ads_case_contract",
            "schema_version": "ads-case-contract/v1",
            **self.case_fields,
            "prediction_run_id": "prediction-run-1",
            "forecast_artifact_id": "forecast-artifact-1",
            "market_identity": {
                "platform": "polymarket",
                "internal_market_id": "market-1",
                "external_market_id": "0xabc",
                "slug": "will-example-happen",
                "title": "Will example happen?",
            },
            "prediction_time_market_baseline": {
                "market_snapshot_id": 10,
                "market_probability": 0.42,
                "market_probability_method": "best_bid_ask_midpoint",
            },
        }

    def _build_bundle(self, *, use_waiver: bool) -> dict[str, dict]:
        case_manifest = self._manifest(
            payload=self._case_payload(),
            file_name="ads-case-contract.json",
            manifest_artifact_type="ads-case-contract",
            schema_version="ads-case-contract/v1",
            stage="case_selection",
            producer="session-02-case-contract",
        )
        evidence_payload = {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            **self.case_fields,
            "case_contract_ref": case_manifest["artifact_id"],
            "market_id": "market-1",
            "market_identity": {"title": "Will example happen?"},
            "market_reality_constraints": {"contract_structure": "binary"},
        }
        evidence_manifest = self._manifest(
            payload=evidence_payload,
            file_name="evidence-packet-v2.json",
            manifest_artifact_type="evidence-packet-v2",
            schema_version="evidence-packet/v2",
            stage="evidence_packet",
            producer="session-02-evidence-packet",
            input_manifest_ids=[case_manifest["artifact_id"]],
        )
        profile_payload = {
            "artifact_type": "effective_tuning_profile_context",
            "schema_version": "effective-tuning-profile-context/v1",
            **self.case_fields,
            "evidence_packet_ref": evidence_manifest["artifact_id"],
            "model_lane_policy_ref": "plans/autonomous-decomposition-swarm-model-lane-policy.json",
        }
        profile_manifest = self._manifest(
            payload=profile_payload,
            file_name="effective-profile-context.json",
            manifest_artifact_type="effective-tuning-profile-context",
            schema_version="effective-tuning-profile-context/v1",
            stage="profile_context",
            producer="session-02-tuning-profile",
            input_manifest_ids=[evidence_manifest["artifact_id"], profile_payload["model_lane_policy_ref"]],
        )
        if use_waiver:
            amrg_payload = {
                "artifact_type": "no_related_context_waiver",
                "schema_version": "no-related-context-waiver/v1",
                **self.case_fields,
                "evidence_packet_ref": evidence_manifest["artifact_id"],
                "profile_context_ref": profile_manifest["artifact_id"],
                "candidate_set_id": "candidate-set-empty",
                "input_manifest_ids": [evidence_manifest["artifact_id"], profile_manifest["artifact_id"]],
                "input_manifest_hash": "sha256:fixture",
            }
            amrg_manifest = self._manifest(
                payload=amrg_payload,
                file_name="no-related-context-waiver.json",
                manifest_artifact_type="no-related-context-waiver",
                schema_version="no-related-context-waiver/v1",
                stage="amrg",
                producer="session-02-amrg",
                input_manifest_ids=amrg_payload["input_manifest_ids"],
            )
            return {
                "ads_case_contract_manifest": case_manifest,
                "evidence_packet_manifest": evidence_manifest,
                "effective_profile_context_manifest": profile_manifest,
                "no_related_context_waiver_manifest": amrg_manifest,
            }

        amrg_payload = {
            "artifact_type": "related_live_market_context",
            "schema_version": "related-live-market-context/v1",
            **self.case_fields,
            "evidence_packet_ref": evidence_manifest["artifact_id"],
            "profile_context_ref": profile_manifest["artifact_id"],
            "candidate_set_id": "candidate-set-1",
            "input_manifest_ids": [evidence_manifest["artifact_id"], profile_manifest["artifact_id"]],
            "input_manifest_hash": "sha256:fixture",
        }
        amrg_manifest = self._manifest(
            payload=amrg_payload,
            file_name="related-live-market-context.json",
            manifest_artifact_type="related-live-market-context",
            schema_version="related-live-market-context/v1",
            stage="amrg",
            producer="session-02-amrg",
            input_manifest_ids=amrg_payload["input_manifest_ids"],
        )
        return {
            "ads_case_contract_manifest": case_manifest,
            "evidence_packet_manifest": evidence_manifest,
            "effective_profile_context_manifest": profile_manifest,
            "related_market_context_manifest": amrg_manifest,
        }

    def test_builds_handoff_with_manifest_refs_and_model_lane(self):
        handoff = build_decomposer_handoff(**self.bundle)

        self.assertEqual(handoff["schema_version"], "decomposer-handoff/v1")
        self.assertEqual(handoff["case_id"], "case-1")
        self.assertEqual(handoff["dispatch_id"], "dispatch-1")
        self.assertEqual(handoff["macro_question"], "Will example happen?")
        self.assertEqual(
            handoff["artifact_refs"]["evidence_packet"]["artifact_type"],
            "evidence-packet-v2",
        )
        self.assertTrue(Path(handoff["artifact_refs"]["ads_case_contract"]["path"]).is_absolute())
        model_context = handoff["model_execution_context"]
        self.assertEqual(model_context["model_lane_id"], "decomposer_qdt_generation")
        self.assertEqual(model_context["resolved_model_id"], DECOMPOSER_MODEL_ID)
        self.assertEqual(model_context["output_schema_version"], "question-decomposition/v1")
        self.assertEqual(set(model_context["input_manifest_ids"]), set(handoff["input_manifest_ids"]))
        self.assertIn("scae", handoff["forbidden_refs"])

    def test_no_related_context_waiver_is_accepted(self):
        handoff = build_decomposer_handoff(**self._build_bundle(use_waiver=True))

        self.assertEqual(
            handoff["artifact_refs"]["related_market_context"]["artifact_type"],
            "no-related-context-waiver",
        )

    def test_missing_related_context_or_waiver_is_rejected(self):
        bundle = dict(self.bundle)
        bundle.pop("related_market_context_manifest")

        with self.assertRaisesRegex(DecomposerHandoffError, "waiver manifest is required"):
            build_decomposer_handoff(**bundle)

    def test_context_and_waiver_together_are_rejected(self):
        bundle = dict(self.bundle)
        bundle["no_related_context_waiver_manifest"] = self._build_bundle(use_waiver=True)[
            "no_related_context_waiver_manifest"
        ]

        with self.assertRaisesRegex(DecomposerHandoffError, "not both"):
            build_decomposer_handoff(**bundle)

    def test_manifest_digest_mismatch_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        path = Path(bundle["evidence_packet_manifest"]["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["market_id"] = "changed"
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(DecomposerHandoffError, "digest mismatch"):
            build_decomposer_handoff(**bundle)

    def test_wrong_manifest_schema_version_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["evidence_packet_manifest"]["artifact_schema_version"] = "evidence-packet/v3"

        with self.assertRaisesRegex(DecomposerHandoffError, "schema version"):
            build_decomposer_handoff(**bundle)

    def test_wrong_payload_schema_version_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        path = Path(bundle["evidence_packet_manifest"]["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = "evidence-packet/v3"
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        bundle["evidence_packet_manifest"]["sha256"] = file_sha256(path)

        with self.assertRaisesRegex(DecomposerHandoffError, "payload schema_version"):
            build_decomposer_handoff(**bundle)

    def test_case_dispatch_and_timestamp_mismatch_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["effective_profile_context_manifest"]["source_cutoff_timestamp"] = "2026-06-24T17:50:00+00:00"

        with self.assertRaisesRegex(DecomposerHandoffError, "source_cutoff_timestamp mismatch"):
            build_decomposer_handoff(**bundle)

        bundle = copy.deepcopy(self.bundle)
        bundle["evidence_packet_manifest"]["case_id"] = "case-other"
        with self.assertRaisesRegex(DecomposerHandoffError, "case_id mismatch"):
            build_decomposer_handoff(**bundle)

    def test_transitive_manifest_refs_are_required(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["effective_profile_context_manifest"]["input_manifest_ids"] = []

        with self.assertRaisesRegex(DecomposerHandoffError, "missing input manifest ref"):
            build_decomposer_handoff(**bundle)

    def test_relative_artifact_path_is_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["ads_case_contract_manifest"]["path"] = "relative/ads-case-contract.json"

        with self.assertRaisesRegex(DecomposerHandoffError, "path must be absolute"):
            build_decomposer_handoff(**bundle)

    def test_model_lane_resolution_rejects_wrong_default(self):
        policy = json.loads((ROOT / "orchestrator" / "plans" / "autonomous-decomposition-swarm-model-lane-policy.json").read_text(encoding="utf-8"))
        policy["lanes"]["decomposer_qdt_generation"]["default_model_id"] = "gpt-5.4-high"
        policy_path = self.base / "bad-model-policy.json"
        policy_path.write_text(canonical_json(policy) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(DecomposerHandoffError, "default_model_id"):
            resolve_decomposer_model_lane(model_lane_policy_path=policy_path)


if __name__ == "__main__":
    unittest.main()
