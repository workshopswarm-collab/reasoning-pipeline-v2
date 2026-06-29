#!/usr/bin/env python3

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import build_fixture_qdt_candidate, select_qdt_candidate  # noqa: E402
from predquant.ads_retrieval_transport import (  # noqa: E402
    RetrievalProviderPolicy,
    collect_live_retrieval_candidates,
)
from researcher_swarm.retrieval import (  # noqa: E402
    build_live_retrieval_packet_from_candidates,
)


FORECAST_AT = "2026-06-24T12:00:00+00:00"
CUTOFF_AT = "2026-06-24T11:59:00+00:00"
SOURCE_AT = "2026-06-24T11:30:00+00:00"


class FakeBrowserProvider:
    def __init__(self, *, fetch_payloads: dict[str, dict] | None = None, search_results: list[dict] | None = None):
        self.fetch_payloads = fetch_payloads or {}
        self.search_results = search_results or []
        self.events: list[tuple[str, str]] = []

    def fetch_url(self, url: str) -> dict:
        self.events.append(("fetch", url))
        payload = copy.deepcopy(self.fetch_payloads.get(url, {}))
        payload.setdefault("url", url)
        payload.setdefault("final_url", url)
        payload.setdefault("extraction_status", "accepted")
        payload.setdefault("source_published_at", SOURCE_AT)
        payload.setdefault("content", f"Fetched content for {url}")
        return payload

    def search_candidate_urls(self, query_context: dict, query_variant: dict, *, searched_at: str | None = None) -> list[dict]:
        self.events.append(("search", str(query_context["leaf_id"])))
        records = []
        for index, result in enumerate(self.search_results, start=1):
            records.append(
                {
                    "leaf_id": query_context["leaf_id"],
                    "query_variant_id": query_variant["query_variant_id"],
                    "query_role": query_variant.get("query_role") or "primary_leaf_retrieval",
                    "rank": result.get("rank") or index,
                    "url": result.get("url"),
                    "title": result.get("title") or "fake search result",
                    "snippet": result.get("snippet") or "",
                    "searched_at": searched_at,
                }
            )
        return records


class DiagnosticsBrowserProvider(FakeBrowserProvider):
    def __init__(self, *, search_configured: bool, fetch_configured: bool):
        super().__init__(search_results=[{"url": "https://secondary.example/report"}])
        self.search_configured = search_configured
        self.fetch_configured = fetch_configured

    def provider_diagnostics(self) -> dict:
        return {
            "provider_id": "diagnostics-provider",
            "search_configured": self.search_configured,
            "fetch_configured": self.fetch_configured,
            "web_fetch_must_not_be_used_as_search": True,
            "authority_boundary": {
                "certifies_source_class": False,
                "certifies_research_sufficiency": False,
                "certifies_probability": False,
            },
        }


class TimeoutSearchBrowserProvider(FakeBrowserProvider):
    def __init__(self) -> None:
        super().__init__()
        self.last_search_error: str | None = None

    def search_candidate_urls(self, query_context: dict, query_variant: dict, *, searched_at: str | None = None) -> list[dict]:
        self.events.append(("search", str(query_context["leaf_id"])))
        self.last_search_error = "simulated_search_timeout"
        raise TimeoutError("simulated search timeout")

    def provider_diagnostics(self) -> dict:
        return {
            "provider_id": "timeout-search-provider",
            "search_configured": True,
            "fetch_configured": True,
            "last_search_error": self.last_search_error,
            "web_fetch_must_not_be_used_as_search": True,
        }


class NoTimestampBrowserProvider(FakeBrowserProvider):
    def fetch_url(self, url: str) -> dict:
        self.events.append(("fetch", url))
        return {
            "url": url,
            "final_url": url,
            "extraction_status": "accepted",
            "content": f"Fetched undated direct content for {url}",
        }


class AdsRetrievalTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        handoff = {
            "artifact_type": "decomposer_handoff",
            "schema_version": "decomposer-handoff/v1",
            "case_id": "case-1",
            "case_key": "polymarket:market-1",
            "dispatch_id": "dispatch-1",
            "macro_question": "Will example happen?",
            "market_context": {
                "market_id": "market-1",
                "market_reality_constraints_digest": "sha256:" + "0" * 64,
            },
            "artifact_refs": {
                "related_market_context": {
                    "artifact_id": "artifact:amrg-1",
                    "artifact_type": "related-live-market-context",
                },
            },
            "model_execution_context": {
                "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
                "resolved_model_id": DECOMPOSER_MODEL_ID,
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "prompt_template_id": DECOMPOSER_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
                "output_schema_version": "question-decomposition/v1",
            },
        }
        self.qdt = select_qdt_candidate([build_fixture_qdt_candidate(handoff)])
        self.evidence_packet = {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "forecast_timestamp": FORECAST_AT,
            "source_cutoff_timestamp": CUTOFF_AT,
            "market_rules": {"resolution_url": "https://rules.example/resolution"},
            "official_source_hints": ["https://official.example/source-of-truth"],
            "market_reality_constraints": {
                "source_of_truth_hints": ["https://protected.example/primary"],
            },
        }
        self.case_contract = {
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "market_identity": {
                "platform": "polymarket",
                "internal_market_id": "market-1",
                "external_market_id": "market-1",
                "slug": "example-market",
            },
        }

    def _resolution_mechanics_qdt(self) -> dict:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [
            leaf for leaf in qdt["required_leaf_questions"] if leaf["leaf_id"] == "leaf-resolution-mechanics"
        ]
        qdt["branches"] = [
            branch
            for branch in qdt["branches"]
            if "leaf-resolution-mechanics" in branch.get("leaf_ids", [])
        ]
        return qdt

    def test_direct_url_collection_prioritizes_source_truth_before_broad_search(self) -> None:
        provider = FakeBrowserProvider(search_results=[{"url": "https://secondary.example/report"}])

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context={
                "candidate_edges": [
                    {
                        "allowed_effects": ["retrieval_query_hint"],
                        "source_url": "https://amrg.example/source-hint",
                    }
                ]
            },
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=8, max_search_results_per_variant=1),
            browser_provider=provider,
        )

        self.assertIn("official_source_hints", transport.direct_url_candidates[0]["source_ref"])
        self.assertIn("source_of_truth_hints", transport.direct_url_candidates[1]["source_ref"])
        self.assertEqual(transport.direct_url_candidates[-1]["source_ref"], "case_contract.market_url")
        first_search_index = next(index for index, event in enumerate(provider.events) if event[0] == "search")
        self.assertTrue(all(event[0] == "fetch" for event in provider.events[:first_search_index]))
        self.assertGreater(len(transport.fetched_candidates), len(transport.search_candidate_urls))
        diagnostics = transport.transport_diagnostics
        self.assertTrue(diagnostics["direct_url_capture_executed"])
        self.assertEqual(diagnostics["direct_url_capture_status"], "executed")
        self.assertTrue(diagnostics["browser_search_executed"])
        self.assertEqual(diagnostics["browser_search_status"], "executed")
        self.assertFalse(diagnostics["native_research_model_executed"])
        self.assertEqual(diagnostics["native_research_status"], "disabled")

    def test_embedded_resolution_urls_become_direct_candidates(self) -> None:
        provider = FakeBrowserProvider(search_results=[{"url": "https://secondary.example/report"}])
        case_contract = copy.deepcopy(self.case_contract)
        case_contract["market_identity"]["description"] = (
            "This market resolves using Tesla releases at https://ir.tesla.com/press. "
            "If unavailable, use https://example.com/fallback-report."
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=8, max_search_results_per_variant=1),
            browser_provider=provider,
        )

        direct_urls = [item["url"] for item in transport.direct_url_candidates]
        self.assertIn("https://ir.tesla.com/press", direct_urls)
        self.assertIn("https://example.com/fallback-report", direct_urls)
        self.assertLess(
            direct_urls.index("https://ir.tesla.com/press"),
            direct_urls.index("https://polymarket.com/event/example-market"),
        )
        self.assertTrue(
            all(event[0] == "fetch" for event in provider.events[: len(transport.direct_url_candidates)])
        )

    def test_embedded_source_url_survives_tight_direct_url_cap(self) -> None:
        provider = FakeBrowserProvider()
        case_contract = copy.deepcopy(self.case_contract)
        case_contract["market_identity"]["description"] = (
            "Resolution source: https://ir.tesla.com/press"
        )
        evidence_packet = {
            **self.evidence_packet,
            "official_source_hints": [],
            "market_reality_constraints": {},
            "market_rules": {},
        }

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=evidence_packet,
            case_contract=case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=1, broad_search_enabled=False),
            browser_provider=provider,
        )

        self.assertEqual(
            [item["url"] for item in transport.direct_url_candidates],
            ["https://ir.tesla.com/press"],
        )

    def test_direct_fetch_elapsed_does_not_preconsume_search_budget(self) -> None:
        clock = {"now": 0.0}

        class SlowDirectProvider(FakeBrowserProvider):
            def fetch_url(self, url: str) -> dict:
                clock["now"] += 120.0
                return super().fetch_url(url)

        provider = SlowDirectProvider(search_results=[{"url": "https://www.reuters.com/world/example-report"}])

        with patch("predquant.ads_retrieval_transport.time.monotonic", side_effect=lambda: clock["now"]):
            transport = collect_live_retrieval_candidates(
                qdt=self._resolution_mechanics_qdt(),
                evidence_packet=self.evidence_packet,
                case_contract=self.case_contract,
                amrg_context=None,
                source_cutoff_timestamp=CUTOFF_AT,
                forecast_timestamp=FORECAST_AT,
                provider_policy=RetrievalProviderPolicy(
                    max_direct_urls=1,
                    max_total_direct_fetches=1,
                    max_total_search_calls=1,
                    max_total_search_elapsed_seconds=1,
                    max_search_results_per_variant=1,
                    max_total_search_result_fetches=1,
                ),
                browser_provider=provider,
            )

        diagnostics = transport.transport_diagnostics
        self.assertEqual(diagnostics["direct_url_elapsed_seconds"], 120.0)
        self.assertEqual(diagnostics["search_call_count"], 1)
        self.assertEqual(diagnostics["search_call_skipped_count"], 0)
        self.assertEqual([event[0] for event in provider.events].count("search"), 1)

    def test_tesla_ir_resolution_url_is_deterministic_official_after_fetch(self) -> None:
        provider = FakeBrowserProvider()
        case_contract = copy.deepcopy(self.case_contract)
        case_contract["market_identity"]["description"] = (
            "This market resolves from Tesla releases at https://ir.tesla.com/press."
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=8, broad_search_enabled=False),
            browser_provider=provider,
        )
        tesla_candidate = next(
            item for item in transport.fetched_candidates if item["canonical_url"] == "https://ir.tesla.com/press"
        )

        self.assertEqual(tesla_candidate["source_class"], "official_or_primary")
        self.assertEqual(tesla_candidate["source_class_resolution_method"], "deterministic_url_registry")
        self.assertEqual(tesla_candidate["source_class_registry_match"], "ir.tesla.com")

    def test_provider_diagnostics_control_configured_search_status(self) -> None:
        provider = DiagnosticsBrowserProvider(search_configured=False, fetch_configured=True)

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=1, max_search_results_per_variant=1),
            browser_provider=provider,
        )

        diagnostics = transport.transport_diagnostics
        self.assertEqual(diagnostics["browser_provider_status"], "available")
        self.assertTrue(diagnostics["browser_fetch_configured"])
        self.assertFalse(diagnostics["browser_search_configured"])
        self.assertEqual(diagnostics["browser_provider_diagnostics"]["provider_id"], "diagnostics-provider")
        self.assertEqual(
            diagnostics["browser_provider_diagnostics"]["provider_authority_status"],
            "non_authoritative_transport_only",
        )
        self.assertNotIn("authority_boundary", diagnostics["browser_provider_diagnostics"])

    def test_bad_post_cutoff_duplicate_and_disallowed_urls_flow_to_rejections(self) -> None:
        provider = FakeBrowserProvider(
            fetch_payloads={
                "https://late.example/source": {"source_published_at": "2026-06-24T12:00:01+00:00"},
            },
            search_results=[
                {"url": "https://official.example/source-of-truth"},
                {"url": "not-a-url"},
                {"url": "ftp://bad.example/source"},
                {"url": "https://late.example/source"},
            ],
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=2, max_search_results_per_variant=4),
            browser_provider=provider,
        )
        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )
        omitted_reasons = [
            reason
            for item in packet["omitted_candidates"]
            for reason in item.get("omission_reason_codes", [])
        ]

        self.assertIn("malformed_url", omitted_reasons)
        self.assertIn("post_cutoff_source_time", omitted_reasons)
        self.assertIn("duplicate_canonical_url", omitted_reasons)
        self.assertGreaterEqual(packet["retrieval_runtime_summary"]["omitted_or_rejected_candidate_count"], 3)

    def test_browser_fetch_authority_fields_are_stripped_and_fail_closed(self) -> None:
        provider = FakeBrowserProvider(
            search_results=[{"url": "https://secondary.example/report"}],
            fetch_payloads={
                "https://secondary.example/report": {
                    "source_published_at": SOURCE_AT,
                    "source_class": "official_or_primary",
                    "claim_family_id": "claim-family:provider-final",
                    "temporal_gate_status": "pass",
                    "research_sufficiency_certification": "allowed",
                    "content": "Provider tried to certify source metadata.",
                }
            },
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=0, max_search_results_per_variant=1),
            browser_provider=provider,
        )
        self.assertNotIn("source_class", transport.fetched_candidates[0])
        self.assertNotIn("claim_family_id", transport.fetched_candidates[0])

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertFalse(packet["retrieval_evidence_provenance_slices"][0]["counts_toward_breadth"])

    def test_static_url_registry_enriches_secondary_without_provider_authority(self) -> None:
        provider = FakeBrowserProvider(
            search_results=[
                {
                    "url": "https://www.reuters.com/world/example-report",
                    "title": "Provider title is discovery only",
                    "snippet": "Provider snippet is discovery only",
                }
            ],
            fetch_payloads={
                "https://www.reuters.com/world/example-report": {
                    "source_published_at": SOURCE_AT,
                    "source_class": "official_or_primary",
                    "claim_family_id": "claim-family:provider-final",
                    "temporal_gate_status": "pass",
                    "research_sufficiency_certification": "allowed",
                    "content": "Reuters reported the example event before the cutoff.",
                    "validated_atomic_claim_candidates": [
                        {
                            "subject": "example event",
                            "predicate": "reported before",
                            "object_or_value": "cutoff",
                            "event_time": "2026-06-24",
                            "entity_or_jurisdiction": "example",
                            "condition_scope": "unconditional",
                            "polarity": "affirmed",
                            "supporting_text": "Reuters reported the example event before the cutoff.",
                            "candidate_confidence": "high",
                        }
                    ],
                }
            },
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract={**self.case_contract, "market_identity": {}},
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=0, max_search_results_per_variant=1),
            browser_provider=provider,
        )

        candidate = transport.fetched_candidates[0]
        self.assertEqual(candidate["source_class"], "independent_secondary")
        self.assertEqual(candidate["source_class_resolution_method"], "deterministic_url_registry")
        self.assertTrue(candidate["deterministic_source_class_proof"])
        self.assertNotIn("claim_family_id", candidate)
        self.assertEqual(candidate["source_class_registry_match"], "reuters.com")

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]

        self.assertEqual(provenance["source_class"], "independent_secondary")
        self.assertTrue(provenance["claim_family_ids"])
        self.assertIn("snippet_sha256", packet["search_candidate_urls"][0])
        self.assertNotIn("snippet", packet["search_candidate_urls"][0])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_browser_fetch_snippet_or_title_only_is_not_page_text_evidence(self) -> None:
        provider = FakeBrowserProvider(
            search_results=[{"url": "https://secondary.example/snippet-only"}],
            fetch_payloads={
                "https://secondary.example/snippet-only": {
                    "source_published_at": SOURCE_AT,
                    "content": "",
                    "snippet": "Search snippet is not fetched page text.",
                    "title": "Search title only",
                }
            },
        )

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract={**self.case_contract, "market_identity": {}},
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=0, max_search_results_per_variant=1),
            browser_provider=provider,
        )
        self.assertEqual(transport.fetched_candidates[0]["content"], "")

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertEqual(packet["retrieval_runtime_summary"]["admitted_initial_evidence_count"], 0)
        self.assertFalse(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])
        self.assertIn("retrieved_source_text_missing", packet["omitted_candidates"][0]["omission_reason_codes"])

    def test_native_candidate_output_is_url_proposal_only(self) -> None:
        def native_provider(_context: dict, _variant: dict) -> list[dict]:
            return [
                {
                    "url": "https://native.example/source",
                    "source_label": "Native candidate",
                    "candidate_claim_text": "Candidate claim only.",
                    "source_class": "official_or_primary",
                    "claim_family_id": "claim-family:native-final",
                    "temporal_safety_final_authority": "pass",
                    "research_sufficiency": "allowed",
                }
            ]

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=0, broad_search_enabled=False, native_enabled=True),
            browser_provider=None,
            native_candidate_provider=native_provider,
        )
        native_candidate = transport.native_research_candidates[0]["candidate_urls"][0]

        self.assertTrue(transport.transport_diagnostics["native_research_model_executed"])
        self.assertEqual(transport.transport_diagnostics["native_research_status"], "executed")
        self.assertEqual(transport.transport_diagnostics["native_research_call_count"], 1)
        self.assertEqual(native_candidate["url"], "https://native.example/source")
        self.assertNotIn("source_class", native_candidate)
        self.assertNotIn("claim_family_id", native_candidate)
        self.assertNotIn("temporal_safety_final_authority", native_candidate)
        self.assertNotIn("research_sufficiency", native_candidate)

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            native_research_candidates=transport.native_research_candidates,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )
        discovery = packet["native_research_candidate_discoveries"][0]
        runtime_summary = packet["retrieval_runtime_summary"]
        self.assertTrue(runtime_summary["native_research_model_executed"])
        self.assertEqual(runtime_summary["native_research_status"], "executed")
        self.assertFalse(runtime_summary["browser_search_executed"])
        self.assertEqual(runtime_summary["metadata_classifier_assist_status"], "not_executed")
        self.assertFalse(discovery["authority_boundary"]["research_sufficiency_authority"])
        self.assertTrue(discovery["fetch_required_before_admission"])

    def test_source_populated_attempts_fail_closed_when_secondary_class_is_not_deterministic(self) -> None:
        provider = FakeBrowserProvider(search_results=[{"url": "https://secondary.example/report"}])
        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=1, max_search_results_per_variant=1),
            browser_provider=provider,
        )

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertGreater(packet["retrieval_runtime_summary"]["direct_url_attempt_count"], 0)
        self.assertGreater(packet["retrieval_runtime_summary"]["web_search_attempt_count"], 0)
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_direct_official_urls_without_http_date_use_pre_dispatch_observation_time(self) -> None:
        provider = NoTimestampBrowserProvider()
        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=4, broad_search_enabled=False),
            browser_provider=provider,
        )

        self.assertTrue(transport.fetched_candidates)
        self.assertTrue(
            all(candidate["extraction_status"] == "accepted" for candidate in transport.fetched_candidates)
        )
        self.assertTrue(
            all(candidate["admission_status"] == "admitted" for candidate in transport.fetched_candidates)
        )
        self.assertTrue(
            all(candidate.get("source_observed_at") == "2026-06-24T11:58:59+00:00" for candidate in transport.fetched_candidates)
        )
        self.assertIn(
            "pre_dispatch_direct_url_source_time_inferred",
            transport.fetched_candidates[0]["admission_reason_code"],
        )

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertTrue(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])
        self.assertTrue(
            all(
                item["source_metadata_resolution"]["temporal_safety_status"] == "pass"
                for item in packet["retrieval_evidence_provenance_slices"]
            )
        )

    def test_broad_search_without_source_time_still_fails_closed(self) -> None:
        provider = NoTimestampBrowserProvider(search_results=[{"url": "https://secondary.example/report"}])
        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract={**self.case_contract, "market_identity": {}},
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(
                max_direct_urls=0,
                max_total_search_calls=1,
                max_total_search_result_fetches=1,
                max_search_results_per_variant=1,
            ),
            browser_provider=provider,
        )

        self.assertEqual(transport.fetched_candidates[0]["navigation_mode"], "web_search")
        self.assertEqual(transport.fetched_candidates[0]["admission_status"], "rejected")
        self.assertIn(
            "source_time_unknown_not_admitted_by_transport_adapter",
            transport.fetched_candidates[0]["omission_reason_codes"],
        )
        self.assertIn(
            "source_time_unknown_with_fetched_content",
            transport.fetched_candidates[0]["omission_reason_codes"],
        )

    def test_bounded_search_caps_materialize_fail_closed_packet(self) -> None:
        provider = FakeBrowserProvider(
            search_results=[
                {"url": "https://secondary.example/report-a"},
                {"url": "https://secondary.example/report-b"},
            ]
        )

        transport = collect_live_retrieval_candidates(
            qdt=self.qdt,
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(
                max_direct_urls=2,
                max_total_direct_fetches=1,
                max_search_results_per_variant=2,
                max_total_search_calls=1,
                max_total_search_result_fetches=1,
            ),
            browser_provider=provider,
        )

        diagnostics = transport.transport_diagnostics
        self.assertEqual(diagnostics["direct_url_fetch_attempt_count"], 1)
        self.assertEqual(diagnostics["search_call_count"], 1)
        self.assertEqual(diagnostics["search_result_fetch_attempt_count"], 1)
        self.assertGreater(diagnostics["direct_url_fetch_skipped_count"], 0)
        self.assertGreater(diagnostics["search_call_skipped_count"], 0)
        self.assertGreater(diagnostics["search_result_fetch_skipped_count"], 0)
        self.assertIn("direct_url_fetch_limit_reached", diagnostics["bounded_retrieval_reason_codes"])
        self.assertIn("search_call_limit_reached", diagnostics["bounded_retrieval_reason_codes"])
        self.assertIn("search_result_fetch_limit_reached", diagnostics["bounded_retrieval_reason_codes"])
        self.assertEqual(len([event for event in provider.events if event[0] == "search"]), 1)

        packet = build_live_retrieval_packet_from_candidates(
            self.qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_broad_search_is_capped_across_leaves_with_diagnostics(self) -> None:
        provider = FakeBrowserProvider(search_results=[{"url": "https://secondary.example/report"}])

        transport = collect_live_retrieval_candidates(
            qdt=self.qdt,
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(
                max_direct_urls=0,
                max_total_search_calls=1,
                max_total_search_result_fetches=1,
                max_search_results_per_variant=1,
            ),
            browser_provider=provider,
        )

        self.assertEqual([event[0] for event in provider.events].count("search"), 1)
        self.assertEqual(transport.transport_diagnostics["search_call_count"], 1)
        self.assertGreater(transport.transport_diagnostics["search_call_skipped_count"], 0)
        self.assertIn("search_call_limit_reached", transport.transport_diagnostics["bounded_retrieval_reason_codes"])
        self.assertEqual(
            transport.transport_diagnostics["search_skipped_diagnostics"][0]["reason_code"],
            "search_call_limit_reached",
        )

    def test_search_timeout_materializes_fail_closed_packet(self) -> None:
        provider = TimeoutSearchBrowserProvider()

        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet={**self.evidence_packet, "official_source_hints": []},
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=0, max_total_search_calls=1),
            browser_provider=provider,
        )
        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertEqual(transport.transport_diagnostics["search_failure_count"], 1)
        self.assertIn("search_provider_failure_recorded", transport.transport_diagnostics["bounded_retrieval_reason_codes"])
        self.assertEqual(transport.transport_diagnostics["search_failure_diagnostics"][0]["reason_code"], "browser_provider_search_exception")
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertFalse(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])

    def test_no_admissible_evidence_records_bounded_failure_not_certification(self) -> None:
        provider = FakeBrowserProvider(
            fetch_payloads={
                "https://polymarket.com/event/example-market": {
                    "extraction_status": "blocked",
                    "reason_codes": ["protected_primary_blocked"],
                },
                "https://official.example/source-of-truth": {
                    "extraction_status": "blocked",
                    "reason_codes": ["protected_primary_blocked"],
                },
                "https://protected.example/primary": {
                    "extraction_status": "blocked",
                    "reason_codes": ["protected_primary_blocked"],
                },
            },
        )
        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=2, broad_search_enabled=False),
            browser_provider=provider,
        )
        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertFalse(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertIn("protected_primary_blocked", packet["omitted_candidates"][0]["omission_reason_codes"])

    def test_missing_browser_provider_reports_unavailable_without_certifying(self) -> None:
        transport = collect_live_retrieval_candidates(
            qdt=self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            case_contract=self.case_contract,
            amrg_context=None,
            source_cutoff_timestamp=CUTOFF_AT,
            forecast_timestamp=FORECAST_AT,
            provider_policy=RetrievalProviderPolicy(max_direct_urls=1, broad_search_enabled=False),
            browser_provider=None,
        )

        self.assertEqual(transport.transport_diagnostics["browser_provider_status"], "unavailable")
        self.assertEqual(
            transport.transport_diagnostics["browser_provider_unavailable_reason"],
            "browser_provider_not_configured",
        )
        self.assertEqual(transport.fetched_candidates[0]["admission_status"], "rejected")
        self.assertIn("browser_provider_not_configured", transport.fetched_candidates[0]["omission_reason_codes"])

        packet = build_live_retrieval_packet_from_candidates(
            self._resolution_mechanics_qdt(),
            evidence_packet=self.evidence_packet,
            fetched_candidates=transport.fetched_candidates,
            search_candidate_urls=transport.search_candidate_urls,
            forecast_timestamp=FORECAST_AT,
            source_cutoff_timestamp=CUTOFF_AT,
            live_policy_overlay=True,
        )

        self.assertFalse(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )


if __name__ == "__main__":
    unittest.main()
