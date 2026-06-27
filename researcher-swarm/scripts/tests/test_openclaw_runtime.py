#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from researcher_swarm.assignments import build_leaf_research_assignments  # noqa: E402
from researcher_swarm.openclaw_runtime import (  # noqa: E402
    LEAF_RUNTIME_REQUEST_SCHEMA_VERSION,
    build_leaf_scoped_runtime_requests,
    build_researcher_swarm_openclaw_prompt,
)
from test_assignments import LeafResearchAssignmentContractTest  # noqa: E402


def _contains_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(str(key) in forbidden or _contains_key(child, forbidden) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


class OpenClawRuntimeBoundaryTest(unittest.TestCase):
    def _assignments(self) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        helper = LeafResearchAssignmentContractTest(methodName="test_builds_compact_primary_assignment_for_each_dispatchable_leaf")
        helper.setUp()
        packet = helper._certifiable_packet()
        assignments = build_leaf_research_assignments(qdt=helper.qdt, retrieval_packet=packet)
        return assignments, helper.qdt, packet

    def test_leaf_scoped_runtime_requests_exclude_sibling_and_probability_context(self) -> None:
        assignments, _qdt, _packet = self._assignments()

        requests = build_leaf_scoped_runtime_requests(assignments)

        self.assertEqual(len(requests), len(assignments))
        assignment_ids = {assignment["assignment_id"] for assignment in assignments}
        forbidden_keys = {
            "sibling_outputs",
            "scae_refs",
            "replay_outcomes",
            "scoring_data",
            "market_predictions",
            "probability",
            "forecast_probability",
            "production_probability",
        }
        for request in requests:
            self.assertEqual(request["schema_version"], LEAF_RUNTIME_REQUEST_SCHEMA_VERSION)
            child_input = request["child_session_input"]
            self.assertEqual(child_input["assignment"]["assignment_id"], request["assignment_ref"])
            sibling_ids = assignment_ids - {request["assignment_ref"]}
            serialized = json.dumps(child_input, sort_keys=True)
            self.assertFalse(any(sibling_id in serialized for sibling_id in sibling_ids))
            self.assertFalse(_contains_key(child_input, forbidden_keys))
            self.assertTrue(child_input["allowed_evidence_refs"])
            self.assertIn("schema:researcher-sidecar/v2", child_input["schema_refs"])
            self.assertTrue(request["forbidden_context"]["probability_context"] is False)

    def test_openclaw_prompt_includes_leaf_runtime_requests(self) -> None:
        assignments, qdt, packet = self._assignments()

        prompt = build_researcher_swarm_openclaw_prompt(
            assignments=assignments,
            qdt=qdt,
            retrieval_packet=packet,
            true_production_mode=True,
            max_concurrent=5,
        )

        self.assertIn("leaf_runtime_requests", prompt)
        self.assertIn(LEAF_RUNTIME_REQUEST_SCHEMA_VERSION, prompt)
        self.assertIn("use only the matching leaf_runtime_requests[].child_session_input", prompt)


if __name__ == "__main__":
    unittest.main()
