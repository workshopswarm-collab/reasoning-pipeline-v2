from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "context_usage_telemetry.py"
spec = importlib.util.spec_from_file_location("context_usage_telemetry", MODULE_PATH)
telemetry = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = telemetry
spec.loader.exec_module(telemetry)


class ContextUsageTelemetryReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workbench"
        self.context = self.root / "context"
        self.sessions = Path(self.tmp.name) / "sessions"
        self.context.mkdir(parents=True)
        self.sessions.mkdir(parents=True)
        (self.root / "MEMORY.md").write_text("memory\n", encoding="utf-8")
        (self.context / "active.md").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
        (self.context / "state").mkdir()
        (self.context / "state" / "state.json").write_text("{}\n", encoding="utf-8")

        self.orig = {
            "WORKBENCH_ROOT": telemetry.WORKBENCH_ROOT,
            "WORKBENCH_CONTEXT_ROOT": telemetry.WORKBENCH_CONTEXT_ROOT,
            "WORKBENCH_SESSION_LOG_ROOT": telemetry.WORKBENCH_SESSION_LOG_ROOT,
        }
        telemetry.WORKBENCH_ROOT = self.root.resolve()
        telemetry.WORKBENCH_CONTEXT_ROOT = self.context.resolve()
        telemetry.WORKBENCH_SESSION_LOG_ROOT = self.sessions.resolve()

    def tearDown(self) -> None:
        for name, value in self.orig.items():
            setattr(telemetry, name, value)
        self.tmp.cleanup()

    def write_session(self, *records: dict) -> Path:
        path = self.sessions / "session-1.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return path

    def test_content_hash_helpers_normalize_and_hash_current_span(self) -> None:
        self.assertEqual(
            telemetry.normalized_span_text_hash("  two\nthree   \n"),
            telemetry.normalized_span_text_hash("two\nthree"),
        )
        self.assertEqual(telemetry.current_context_span_text("context/active.md", 2, 3), "two\nthree")
        self.assertEqual(
            telemetry.current_context_span_hash("context/active.md", 2, 3),
            telemetry.normalized_span_text_hash("two\nthree"),
        )
        self.assertIsNone(telemetry.current_context_span_text("context/active.md", 3, 2))
        self.assertIsNone(telemetry.current_context_span_hash("context/missing.md", 1, 1))

    def test_collects_bounded_context_markdown_reads_only(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "assistant-1",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-context",
                            "name": "read",
                            "arguments": {"path": str(self.context / "active.md"), "offset": 2, "limit": 2},
                        },
                        {
                            "type": "toolCall",
                            "id": "call-non-context",
                            "name": "read",
                            "arguments": {"path": str(self.root / "MEMORY.md"), "offset": 1, "limit": 1},
                        },
                        {
                            "type": "toolCall",
                            "id": "call-non-md",
                            "name": "read",
                            "arguments": {"path": str(self.context / "state" / "state.json"), "offset": 1, "limit": 1},
                        },
                    ],
                },
            },
            {
                "type": "message",
                "id": "result-1",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "call-context",
                    "isError": False,
                    "content": [{"type": "text", "text": "two\nthree\n"}],
                },
            },
            {
                "type": "message",
                "id": "result-2",
                "timestamp": "2026-05-20T10:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "call-non-context",
                    "isError": False,
                    "content": [{"type": "text", "text": "memory\n"}],
                },
            },
            {
                "type": "message",
                "id": "result-3",
                "timestamp": "2026-05-20T10:00:03Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "call-non-md",
                    "isError": False,
                    "content": [{"type": "text", "text": "{}\n"}],
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 1)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(data["summary"]["signal_type_counts"], {"read": 1})
        self.assertEqual(data["warnings"], [])
        entry = next(iter(data["entries"].values()))
        self.assertEqual(entry["path"], "context/active.md")
        self.assertEqual(entry["startLine"], 2)
        self.assertEqual(entry["endLine"], 3)
        self.assertEqual(entry["signalType"], "read")
        self.assertEqual(entry["signalCount"], 1)
        self.assertEqual(entry["spanLines"], 2)
        self.assertEqual(entry["spanKind"], "narrow")
        self.assertEqual(entry["evidenceTier"], "medium")
        self.assertEqual(entry["tierReason"], "targeted-read")
        self.assertEqual(entry["followThrough"], "none")
        self.assertFalse(entry["protectsFromPrune"])
        self.assertEqual(entry["sessionCount"], 1)
        self.assertEqual(len(entry["sessionHashes"]), 1)
        self.assertEqual(entry["sourceKinds"], ["read"])
        self.assertTrue(entry["sourceHashes"][0].startswith("sha1:"))
        self.assertNotIn("call-context", json.dumps(data))
        self.assertNotIn("two", json.dumps(data))

    def test_unbounded_read_uses_returned_line_count_and_caps_to_file_length(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "assistant-1",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "call-context",
                            "name": "read",
                            "arguments": {"path": "context/active.md"},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "result-1",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "call-context",
                    "isError": False,
                    "content": [{"type": "text", "text": "one\ntwo\nthree\nfour\nfive\n"}],
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")
        entry = next(iter(data["entries"].values()))
        self.assertEqual(entry["path"], "context/active.md")
        self.assertEqual(entry["startLine"], 1)
        self.assertEqual(entry["endLine"], 4)
        self.assertEqual(entry["spanLines"], 4)
        self.assertEqual(entry["spanKind"], "narrow")

    def test_dedupes_same_session_day_but_keeps_separate_days_and_window(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "assistant-read-old-1",
                "timestamp": "2026-05-18T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "read-old-1",
                            "name": "read",
                            "arguments": {"path": "context/active.md", "offset": 1, "limit": 2},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "read-old-result-1",
                "timestamp": "2026-05-18T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-old-1",
                    "isError": False,
                    "content": [{"type": "text", "text": "one\ntwo\n"}],
                },
            },
            {
                "type": "message",
                "id": "assistant-read-old-2",
                "timestamp": "2026-05-18T11:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "read-old-2",
                            "name": "read",
                            "arguments": {"path": "context/active.md", "offset": 1, "limit": 2},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "read-old-result-2",
                "timestamp": "2026-05-18T11:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-old-2",
                    "isError": False,
                    "content": [{"type": "text", "text": "one\ntwo\n"}],
                },
            },
            {
                "type": "message",
                "id": "assistant-read-current",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "read-current",
                            "name": "read",
                            "arguments": {"path": "context/active.md", "offset": 1, "limit": 2},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "read-current-result",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-current",
                    "isError": False,
                    "content": [{"type": "text", "text": "one\ntwo\n"}],
                },
            },
        )

        long_window = telemetry.build_telemetry(source_window_days=30, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(
            telemetry.DEFAULT_SIGNAL_COUNTS,
            {
                "memory_search_hit": 1,
                "read": 1,
                "memory_get": 2,
                "final_citation": 3,
                "context_edit": 3,
            },
        )
        self.assertEqual(long_window["summary"]["entry_count"], 2)
        self.assertEqual(long_window["summary"]["signal_type_counts"], {"read": 2})
        self.assertEqual(long_window["summary"]["weighted_signal_counts"], {"read": 2})
        self.assertEqual(long_window["summary"]["raw_event_counts"], {"read": 3})
        entries = sorted(long_window["entries"].values(), key=lambda item: item["eventDay"])
        self.assertEqual([entry["eventDay"] for entry in entries], ["2026-05-18", "2026-05-20"])
        self.assertEqual(entries[0]["eventCount"], 2)
        self.assertEqual(entries[0]["signalCount"], 1)
        self.assertEqual(len(entries[0]["sourceHashes"]), 2)
        self.assertEqual(entries[0]["firstSeenAt"], "2026-05-18T10:00:00Z")
        self.assertEqual(entries[0]["lastSeenAt"], "2026-05-18T11:00:00Z")
        self.assertEqual(entries[1]["eventCount"], 1)

        short_window = telemetry.build_telemetry(source_window_days=1, generated_at_utc="2026-05-20T12:00:00Z")
        self.assertEqual(short_window["summary"]["entry_count"], 1)
        only_entry = next(iter(short_window["entries"].values()))
        self.assertEqual(only_entry["eventDay"], "2026-05-20")
        self.assertEqual(only_entry["eventCount"], 1)

    def test_collects_memory_search_context_hits_and_dedupes_one_result(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call-1",
                    "isError": False,
                    "details": {
                        "results": [
                            {
                                "path": "context/active.md",
                                "startLine": 1,
                                "endLine": 2,
                                "score": 0.8,
                                "vectorScore": 0.7,
                                "textScore": 0,
                                "snippet": "raw snippet should not persist",
                            },
                            {
                                "path": "context/active.md",
                                "startLine": 1,
                                "endLine": 2,
                                "score": 0.8,
                                "snippet": "duplicate should not persist",
                            },
                            {
                                "path": "context/active.md",
                                "startLine": 3,
                                "endLine": 4,
                                "score": 0.6,
                            },
                            {
                                "path": "memory/2026-05-20.md",
                                "startLine": 1,
                                "endLine": 2,
                                "score": 0.9,
                            },
                            {
                                "path": "context/state/state.json",
                                "startLine": 1,
                                "endLine": 1,
                                "score": 0.9,
                            },
                        ]
                    },
                    "content": [{"type": "text", "text": "tool result text should not persist"}],
                },
            }
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 2)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(data["summary"]["signal_type_counts"], {"memory_search_hit": 2})
        self.assertEqual(data["warnings"], [])
        entries = sorted(data["entries"].values(), key=lambda item: item["startLine"])
        self.assertEqual([(entry["startLine"], entry["endLine"]) for entry in entries], [(1, 2), (3, 4)])
        self.assertEqual(entries[0]["path"], "context/active.md")
        self.assertEqual(entries[0]["signalType"], "memory_search_hit")
        self.assertEqual(entries[0]["signalCount"], 1)
        self.assertEqual(entries[0]["score"], 0.8)
        self.assertEqual(entries[0]["vectorScore"], 0.7)
        self.assertEqual(entries[0]["textScore"], 0)
        self.assertTrue(entries[0]["sourceHashes"][0].startswith("sha1:"))
        serialized = json.dumps(data)
        self.assertNotIn("raw snippet", serialized)
        self.assertNotIn("search-call-1", serialized)
        self.assertNotIn("tool result text", serialized)

    def test_unresolved_content_hash_warns_and_omits_hash_without_dropping_entry(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call-1",
                    "isError": False,
                    "details": {
                        "results": [
                            {"path": "context/active.md", "startLine": 99, "endLine": 99, "score": 0.8}
                        ]
                    },
                },
            },
            {
                "type": "message",
                "id": "assistant-citation-missing",
                "timestamp": "2026-05-20T10:01:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Source: context/missing.md#L1"}],
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 2)
        self.assertEqual(data["summary"]["entries_with_content_hash"], 0)
        self.assertEqual(data["summary"]["entries_without_content_hash"], 2)
        self.assertEqual(data["summary"]["content_hash_by_signal_type"], {})
        self.assertEqual(
            sorted(warning["reason"] for warning in data["warnings"]),
            ["invalid-content-hash-line-span", "missing-context-file-for-content-hash"],
        )
        for entry in data["entries"].values():
            self.assertNotIn("contentHash", entry)
            self.assertNotIn("contentHashSource", entry)

    def test_collects_memory_get_context_excerpt_with_stronger_signal_count(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call-1",
                    "isError": False,
                    "details": {
                        "results": [
                            {
                                "path": "context/active.md",
                                "startLine": 1,
                                "endLine": 1,
                                "score": 0.5,
                                "snippet": "search snippet should not persist",
                            }
                        ]
                    },
                },
            },
            {
                "type": "message",
                "id": "assistant-1",
                "timestamp": "2026-05-20T10:01:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "memory-get-call",
                            "name": "memory_get",
                            "arguments": {"path": "context/active.md", "from": 2, "lines": 2},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "result-1",
                "timestamp": "2026-05-20T10:01:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "memory-get-call",
                    "isError": False,
                    "details": {
                        "path": "context/active.md",
                        "from": 99,
                        "lines": 99,
                        "text": "raw memory text should not persist",
                    },
                    "content": [{"type": "text", "text": "tool result text should not persist"}],
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 2)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(data["summary"]["signal_type_counts"], {"memory_get": 1, "memory_search_hit": 1})
        self.assertEqual(data["warnings"], [])
        entries_by_type = {entry["signalType"]: entry for entry in data["entries"].values()}
        memory_get_entry = entries_by_type["memory_get"]
        search_entry = entries_by_type["memory_search_hit"]
        self.assertEqual(memory_get_entry["path"], "context/active.md")
        self.assertEqual(memory_get_entry["startLine"], 2)
        self.assertEqual(memory_get_entry["endLine"], 3)
        self.assertEqual(memory_get_entry["signalCount"], 2)
        self.assertEqual(search_entry["signalCount"], 1)
        serialized = json.dumps(data)
        self.assertNotIn("raw memory text", serialized)
        self.assertNotIn("search snippet", serialized)
        self.assertNotIn("memory-get-call", serialized)
        self.assertNotIn("tool result text", serialized)

    def test_memory_get_uses_result_metadata_and_warns_on_missing_spans(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "result-1",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "fallback-call",
                    "isError": False,
                    "details": {
                        "path": "context/active.md",
                        "from": 3,
                        "lines": 2,
                        "text": "three\nfour\n",
                    },
                },
            },
            {
                "type": "message",
                "id": "result-2",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "missing-span-call",
                    "isError": False,
                    "details": {"path": "context/active.md", "text": "unmapped text should not persist"},
                },
            },
            {
                "type": "message",
                "id": "result-3",
                "timestamp": "2026-05-20T10:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "past-eof-call",
                    "isError": False,
                    "details": {"path": "context/active.md", "from": 9, "lines": 2, "text": "past eof"},
                },
            },
            {
                "type": "message",
                "id": "result-4",
                "timestamp": "2026-05-20T10:00:03Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "non-md-call",
                    "isError": False,
                    "details": {"path": "context/state/state.json", "from": 1, "lines": 1},
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 1)
        entry = next(iter(data["entries"].values()))
        self.assertEqual(entry["signalType"], "memory_get")
        self.assertEqual(entry["path"], "context/active.md")
        self.assertEqual(entry["startLine"], 3)
        self.assertEqual(entry["endLine"], 4)
        self.assertEqual(entry["signalCount"], 2)
        self.assertEqual(
            sorted(warning["reason"] for warning in data["warnings"]),
            ["invalid-memory-get-line-span", "missing-memory-get-line-span"],
        )
        serialized = json.dumps(data)
        self.assertNotIn("unmapped text", serialized)
        self.assertNotIn("fallback-call", serialized)
        self.assertNotIn("past-eof-call", serialized)

    def test_collects_final_answer_context_citations_as_strong_signals(self) -> None:
        self.write_session(
            {
                "type": "message",
                "id": "assistant-citation-1",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Grounded answer. Source: context/active.md#L1-L2\n"
                                "Also see `context/active.md#L4` and duplicate context/active.md#L4.\n"
                                "Ignore Source: memory/2026-05-20.md#L1-L2 and context/state/state.json#L1.\n"
                                "Malformed context/active.md#L4-L2. Raw citation message should not persist."
                            ),
                        }
                    ],
                },
            }
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 2)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(data["summary"]["signal_type_counts"], {"final_citation": 2})
        self.assertEqual(
            data["warnings"],
            [
                {
                    "kind": "final_citation",
                    "reason": "invalid-final-citation-line-span",
                    "path": "context/active.md",
                    "sourceHash": data["warnings"][0]["sourceHash"],
                }
            ],
        )
        entries = sorted(data["entries"].values(), key=lambda item: item["startLine"])
        self.assertEqual([(entry["startLine"], entry["endLine"]) for entry in entries], [(1, 2), (4, 4)])
        for entry in entries:
            self.assertEqual(entry["path"], "context/active.md")
            self.assertEqual(entry["signalType"], "final_citation")
            self.assertEqual(entry["signalCount"], 3)
            self.assertEqual(entry["sourceKinds"], ["final_citation"])
            self.assertTrue(entry["sourceHashes"][0].startswith("sha1:"))
        serialized = json.dumps(data)
        self.assertNotIn("Raw citation message", serialized)
        self.assertNotIn("assistant-citation-1", serialized)
        self.assertNotIn("memory/2026-05-20.md", serialized)
        self.assertNotIn("context/state/state.json", serialized)

    def test_collects_bounded_context_edit_and_apply_patch_spans(self) -> None:
        (self.context / "active.md").write_text(
            "one\nTWO NEW\nTHREE NEW\nfour\npatch updated\npatch extra\n",
            encoding="utf-8",
        )
        self.write_session(
            {
                "type": "message",
                "id": "assistant-edit-1",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "edit-context-call",
                            "name": "edit",
                            "arguments": {
                                "path": "context/active.md",
                                "edits": [
                                    {
                                        "oldText": "two\nthree\n",
                                        "newText": "TWO NEW\nTHREE NEW\n",
                                    }
                                ],
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "patch-context-call",
                            "name": "apply_patch",
                            "arguments": {
                                "input": (
                                    "*** Begin Patch\n"
                                    "*** Update File: context/active.md\n"
                                    "@@ -4,1 +5,2 @@\n"
                                    "-old patch line\n"
                                    "+patch updated\n"
                                    "+patch extra\n"
                                    "*** End Patch\n"
                                )
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "write-context-call",
                            "name": "write",
                            "arguments": {"path": "context/active.md", "content": "whole file content should not persist"},
                        },
                        {
                            "type": "toolCall",
                            "id": "edit-memory-call",
                            "name": "edit",
                            "arguments": {
                                "path": "MEMORY.md",
                                "edits": [{"oldText": "memory", "newText": "memory changed"}],
                            },
                        },
                    ],
                },
            },
            {
                "type": "message",
                "id": "edit-result",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "edit",
                    "toolCallId": "edit-context-call",
                    "isError": False,
                    "details": {"diff": "raw diff should not persist"},
                },
            },
            {
                "type": "message",
                "id": "patch-result",
                "timestamp": "2026-05-20T10:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "apply_patch",
                    "toolCallId": "patch-context-call",
                    "isError": False,
                    "details": {"status": "ok"},
                },
            },
            {
                "type": "message",
                "id": "write-result",
                "timestamp": "2026-05-20T10:00:03Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "write",
                    "toolCallId": "write-context-call",
                    "isError": False,
                    "content": [{"type": "text", "text": "write output should not persist"}],
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 2)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(data["summary"]["signal_type_counts"], {"context_edit": 2})
        self.assertEqual([warning["reason"] for warning in data["warnings"]], ["ambiguous-write-line-span"])
        entries = sorted(data["entries"].values(), key=lambda item: item["startLine"])
        self.assertEqual([(entry["startLine"], entry["endLine"]) for entry in entries], [(2, 3), (5, 6)])
        for entry in entries:
            self.assertEqual(entry["path"], "context/active.md")
            self.assertEqual(entry["signalType"], "context_edit")
            self.assertEqual(entry["signalCount"], 3)
            self.assertEqual(entry["sourceKinds"], ["context_edit"])
            self.assertTrue(entry["sourceHashes"][0].startswith("sha1:"))
        serialized = json.dumps(data)
        self.assertNotIn("TWO NEW", serialized)
        self.assertNotIn("patch updated", serialized)
        self.assertNotIn("whole file content", serialized)
        self.assertNotIn("raw diff", serialized)
        self.assertNotIn("edit-context-call", serialized)
        self.assertNotIn("write output", serialized)

    def test_context_edit_uses_tool_result_diff_when_newtext_no_longer_matches(self) -> None:
        (self.context / "active.md").write_text("one\nlater replacement\nthree\n", encoding="utf-8")
        self.write_session(
            {
                "type": "message",
                "id": "assistant-edit-diff-span",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "edit-diff-span-call",
                            "name": "edit",
                            "arguments": {
                                "path": "context/active.md",
                                "edits": [{"oldText": "two\n", "newText": "intermediate text no longer present\n"}],
                            },
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "edit-diff-span-result",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "edit",
                    "toolCallId": "edit-diff-span-call",
                    "isError": False,
                    "details": {"diff": "     ...\n+ 2 intermediate text no longer present\n     ...\n"},
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 1)
        self.assertEqual(data["warnings"], [])
        entry = next(iter(data["entries"].values()))
        self.assertEqual((entry["startLine"], entry["endLine"]), (2, 2))
        self.assertEqual(entry["signalType"], "context_edit")
        self.assertEqual(entry["evidenceTier"], "strong")
        serialized = json.dumps(data)
        self.assertNotIn("intermediate text", serialized)
        self.assertNotIn("edit-diff-span-call", serialized)

    def test_context_edit_ambiguous_spans_warn_without_entries(self) -> None:
        (self.context / "active.md").write_text("duplicate\nduplicate\n", encoding="utf-8")
        self.write_session(
            {
                "type": "message",
                "id": "assistant-edit-ambiguous",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "ambiguous-edit-call",
                            "name": "edit",
                            "arguments": {
                                "path": "context/active.md",
                                "edits": [{"oldText": "old", "newText": "duplicate\n"}],
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "ambiguous-patch-call",
                            "name": "apply_patch",
                            "arguments": {
                                "input": (
                                    "*** Begin Patch\n"
                                    "*** Update File: context/active.md\n"
                                    "@@\n"
                                    "+ambiguous patch text should not persist\n"
                                    "*** End Patch\n"
                                )
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "failed-patch-call",
                            "name": "apply_patch",
                            "arguments": {
                                "input": (
                                    "*** Begin Patch\n"
                                    "*** Update File: context/active.md\n"
                                    "@@ -1,1 +1,1 @@\n"
                                    "-duplicate\n"
                                    "+failed patch text should not persist\n"
                                    "*** End Patch\n"
                                )
                            },
                        },
                    ],
                },
            },
            {
                "type": "message",
                "id": "ambiguous-edit-result",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "edit",
                    "toolCallId": "ambiguous-edit-call",
                    "isError": False,
                },
            },
            {
                "type": "message",
                "id": "ambiguous-patch-result",
                "timestamp": "2026-05-20T10:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "apply_patch",
                    "toolCallId": "ambiguous-patch-call",
                    "isError": False,
                    "details": {"status": "ok"},
                },
            },
            {
                "type": "message",
                "id": "failed-patch-result",
                "timestamp": "2026-05-20T10:00:03Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "apply_patch",
                    "toolCallId": "failed-patch-call",
                    "isError": False,
                    "details": {"status": "error"},
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["summary"]["entry_count"], 0)
        self.assertEqual(data["summary"]["covered_file_count"], 0)
        self.assertEqual(data["summary"]["signal_type_counts"], {})
        self.assertEqual(
            sorted(warning["reason"] for warning in data["warnings"]),
            [
                "ambiguous-apply-patch-line-span",
                "ambiguous-edit-newtext-span",
                "context-edit-tool-error",
            ],
        )
        serialized = json.dumps(data)
        self.assertNotIn("duplicate", serialized)
        self.assertNotIn("ambiguous patch text", serialized)
        self.assertNotIn("failed patch text", serialized)
        self.assertNotIn("ambiguous-edit-call", serialized)

    def test_materializer_schema_all_sources_bounded_spans_and_deterministic_dedupe(self) -> None:
        (self.context / "active.md").write_text(
            "cited line\nedited line\nread a\nread b\nsearch line\nmemory get line\n",
            encoding="utf-8",
        )
        self.write_session(
            {
                "type": "message",
                "id": "assistant-all-sources",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "read-context-1",
                            "name": "read",
                            "arguments": {"path": "context/active.md", "offset": 3, "limit": 2},
                        },
                        {
                            "type": "toolCall",
                            "id": "read-context-2",
                            "name": "read",
                            "arguments": {"path": "context/active.md", "offset": 3, "limit": 2},
                        },
                        {
                            "type": "toolCall",
                            "id": "read-memory",
                            "name": "read",
                            "arguments": {"path": "MEMORY.md", "offset": 1, "limit": 1},
                        },
                        {
                            "type": "toolCall",
                            "id": "memory-get-context",
                            "name": "memory_get",
                            "arguments": {"path": "context/active.md", "from": 6, "lines": 1},
                        },
                        {
                            "type": "toolCall",
                            "id": "memory-get-memory",
                            "name": "memory_get",
                            "arguments": {"path": "MEMORY.md", "from": 1, "lines": 1},
                        },
                        {
                            "type": "toolCall",
                            "id": "edit-context",
                            "name": "edit",
                            "arguments": {
                                "path": "context/active.md",
                                "edits": [{"oldText": "old edited line\n", "newText": "edited line\n"}],
                            },
                        },
                        {
                            "type": "toolCall",
                            "id": "edit-memory",
                            "name": "edit",
                            "arguments": {
                                "path": "MEMORY.md",
                                "edits": [{"oldText": "memory", "newText": "memory changed"}],
                            },
                        },
                    ],
                },
            },
            {
                "type": "message",
                "id": "read-context-result-1",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-context-1",
                    "isError": False,
                    "content": [{"type": "text", "text": "read a\nread b\n"}],
                },
            },
            {
                "type": "message",
                "id": "read-context-result-2",
                "timestamp": "2026-05-20T10:00:02Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-context-2",
                    "isError": False,
                    "content": [{"type": "text", "text": "read a\nread b\n"}],
                },
            },
            {
                "type": "message",
                "id": "read-memory-result",
                "timestamp": "2026-05-20T10:00:03Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-memory",
                    "isError": False,
                    "content": [{"type": "text", "text": "memory\n"}],
                },
            },
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:04Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-context",
                    "isError": False,
                    "details": {
                        "results": [
                            {"path": "context/active.md", "startLine": 5, "endLine": 5, "score": 0.9},
                            {"path": "context/active.md", "startLine": 5, "endLine": 5, "score": 0.9},
                            {"path": "memory/2026-05-20.md", "startLine": 1, "endLine": 1, "score": 1.0},
                        ]
                    },
                    "content": [{"type": "text", "text": "search raw result text should not persist"}],
                },
            },
            {
                "type": "message",
                "id": "memory-get-context-result",
                "timestamp": "2026-05-20T10:00:05Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "memory-get-context",
                    "isError": False,
                    "details": {"path": "context/active.md", "from": 6, "lines": 1, "text": "memory get line\n"},
                },
            },
            {
                "type": "message",
                "id": "memory-get-memory-result",
                "timestamp": "2026-05-20T10:00:06Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "memory-get-memory",
                    "isError": False,
                    "details": {"path": "MEMORY.md", "from": 1, "lines": 1, "text": "memory\n"},
                },
            },
            {
                "type": "message",
                "id": "citation-message",
                "timestamp": "2026-05-20T10:00:07Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Cited context/active.md#L1 and duplicate context/active.md#L1. "
                                "Ignore memory/2026-05-20.md#L1. Citation raw text should not persist."
                            ),
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "edit-context-result",
                "timestamp": "2026-05-20T10:00:08Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "edit",
                    "toolCallId": "edit-context",
                    "isError": False,
                    "details": {"diff": "edit raw diff should not persist"},
                },
            },
            {
                "type": "message",
                "id": "edit-memory-result",
                "timestamp": "2026-05-20T10:00:09Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "edit",
                    "toolCallId": "edit-memory",
                    "isError": False,
                },
            },
        )

        data = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")
        second = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")

        self.assertEqual(data["entries"], second["entries"])
        self.assertEqual(data["summary"], second["summary"])
        self.assertEqual(data["schema_version"], telemetry.SCHEMA_VERSION)
        self.assertEqual(data["generated_at_utc"], "2026-05-20T12:00:00Z")
        self.assertEqual(data["source_window_days"], 3650)
        self.assertEqual(data["summary"]["entry_count"], 5)
        self.assertEqual(data["summary"]["covered_file_count"], 1)
        self.assertEqual(
            data["summary"]["signal_type_counts"],
            {
                "context_edit": 1,
                "final_citation": 1,
                "memory_get": 1,
                "memory_search_hit": 1,
                "read": 1,
            },
        )
        self.assertEqual(
            data["summary"]["weighted_signal_counts"],
            {
                "context_edit": 3,
                "final_citation": 3,
                "memory_get": 2,
                "memory_search_hit": 1,
                "read": 1,
            },
        )
        self.assertEqual(
            data["summary"]["raw_event_counts"],
            {
                "context_edit": 1,
                "final_citation": 1,
                "memory_get": 1,
                "memory_search_hit": 1,
                "read": 2,
            },
        )
        self.assertEqual(data["summary"]["evidence_tier_counts"], {"medium": 1, "strong": 3, "weak": 1})
        self.assertEqual(data["summary"]["span_kind_counts"], {"narrow": 5})
        self.assertEqual(data["summary"]["broad_read_count"], 0)
        self.assertEqual(data["summary"]["raw_search_only_count"], 1)
        self.assertEqual(data["summary"]["entries_with_content_hash"], 5)
        self.assertEqual(data["summary"]["entries_without_content_hash"], 0)
        self.assertEqual(
            data["summary"]["content_hash_by_signal_type"],
            {
                "context_edit": 1,
                "final_citation": 1,
                "memory_get": 1,
                "memory_search_hit": 1,
                "read": 1,
            },
        )
        self.assertEqual(data["summary"]["warning_reason_counts"], {})
        self.assertEqual(data["warnings"], [])
        by_type = {entry["signalType"]: entry for entry in data["entries"].values()}
        self.assertEqual((by_type["final_citation"]["startLine"], by_type["final_citation"]["endLine"]), (1, 1))
        self.assertEqual((by_type["context_edit"]["startLine"], by_type["context_edit"]["endLine"]), (2, 2))
        self.assertEqual((by_type["read"]["startLine"], by_type["read"]["endLine"]), (3, 4))
        self.assertEqual((by_type["memory_search_hit"]["startLine"], by_type["memory_search_hit"]["endLine"]), (5, 5))
        self.assertEqual((by_type["memory_get"]["startLine"], by_type["memory_get"]["endLine"]), (6, 6))
        self.assertEqual(by_type["read"]["eventCount"], 2)
        self.assertEqual(len(by_type["read"]["sourceHashes"]), 2)
        self.assertEqual(by_type["final_citation"]["evidenceTier"], "strong")
        self.assertTrue(by_type["final_citation"]["protectsFromPrune"])
        self.assertEqual(by_type["context_edit"]["evidenceTier"], "strong")
        self.assertFalse(by_type["context_edit"]["protectsFromPrune"])
        self.assertEqual(by_type["context_edit"]["tierReason"], "context-edit-not-usage")
        self.assertEqual(by_type["memory_get"]["evidenceTier"], "strong")
        self.assertTrue(by_type["memory_get"]["protectsFromPrune"])
        self.assertEqual(by_type["read"]["evidenceTier"], "medium")
        self.assertFalse(by_type["read"]["protectsFromPrune"])
        self.assertEqual(by_type["memory_search_hit"]["evidenceTier"], "weak")
        self.assertEqual(by_type["memory_search_hit"]["followThrough"], "none")
        self.assertFalse(by_type["memory_search_hit"]["protectsFromPrune"])
        for entry in data["entries"].values():
            self.assertEqual(entry["path"], "context/active.md")
            self.assertEqual(entry["eventDay"], "2026-05-20")
            self.assertIn(entry["signalCount"], telemetry.DEFAULT_SIGNAL_COUNTS.values())
            self.assertTrue(all(source_hash.startswith("sha1:") for source_hash in entry["sourceHashes"]))
            self.assertEqual(entry["contentHashSource"], telemetry.CONTENT_HASH_SOURCE)
            self.assertEqual(
                entry["contentHash"],
                telemetry.current_context_span_hash(entry["path"], entry["startLine"], entry["endLine"]),
            )
        serialized = json.dumps(data)
        for forbidden in [
            "read-context-1",
            "search raw result text",
            "memory get line",
            "Citation raw text",
            "edit raw diff",
            "memory/2026-05-20.md",
            "memory changed",
        ]:
            self.assertNotIn(forbidden, serialized)

    def test_refresh_writes_canonical_json_and_optional_markdown(self) -> None:
        json_path = Path(self.tmp.name) / "nested" / "context-usage-telemetry.json"
        markdown_path = Path(self.tmp.name) / "nested" / "context-usage-telemetry.md"

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = telemetry.command_refresh(
                SimpleNamespace(
                    window_days=7,
                    source_window_days=None,
                    max_hot_entries=telemetry.DEFAULT_MAX_HOT_ENTRIES,
                    compact_hot_json=False,
                    output_json=json_path,
                    output_markdown=markdown_path,
                    write_markdown=True,
                )
            )

        self.assertEqual(rc, 0)
        self.assertIn("CONTEXT_USAGE_TELEMETRY_REFRESH_OK", stdout.getvalue())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], telemetry.SCHEMA_VERSION)
        self.assertEqual(data["source_window_days"], 7)
        self.assertEqual(data["workspace_root"], str(self.root.resolve()))
        self.assertEqual(data["context_root"], str(self.context.resolve()))
        self.assertEqual(data["summary"]["entry_count"], 0)
        self.assertEqual(data["summary"]["covered_file_count"], 0)
        self.assertEqual(data["summary"]["signal_type_counts"], {})
        self.assertEqual(data["summary"]["warning_count"], 0)

        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("# Workbench Context Usage Telemetry", markdown)
        self.assertIn("source window days: `7`", markdown)
        self.assertIn("entries: `0`", markdown)
        self.assertIn("covered files: `0`", markdown)
        self.assertIn("signal counts: none", markdown)
        self.assertIn("warnings: `0`", markdown)

        markdown_path.unlink()
        with redirect_stdout(io.StringIO()):
            rc = telemetry.command_refresh(
                SimpleNamespace(
                    window_days=7,
                    source_window_days=None,
                    max_hot_entries=telemetry.DEFAULT_MAX_HOT_ENTRIES,
                    compact_hot_json=False,
                    output_json=json_path,
                    output_markdown=markdown_path,
                    write_markdown=False,
                )
            )
        self.assertEqual(rc, 0)
        self.assertFalse(markdown_path.exists())

    def test_compact_telemetry_hot_json_keeps_classifier_fields_only(self) -> None:
        payload = {
            "schema_version": telemetry.SCHEMA_VERSION,
            "generated_at_utc": "2026-05-20T12:00:00Z",
            "source_window_days": 30,
            "workspace_root": str(self.root.resolve()),
            "context_root": str(self.context.resolve()),
            "warnings": [],
            "entries": {
                "old": {
                    "path": "context/active.md",
                    "startLine": 1,
                    "endLine": 1,
                    "signalType": "read",
                    "signalCount": 1,
                    "firstSeenAt": "2026-04-01T00:00:00Z",
                    "lastSeenAt": "2026-04-01T00:00:00Z",
                    "evidenceTier": "medium",
                    "spanKind": "narrow",
                    "protectsFromPrune": False,
                    "sourceHashes": ["sha1:old"],
                    "sessionHashes": ["sha1:session-old"],
                },
                "protected": {
                    "path": "context/active.md",
                    "startLine": 2,
                    "endLine": 2,
                    "signalType": "memory_get",
                    "signalCount": 2,
                    "firstSeenAt": "2026-05-12T00:00:00Z",
                    "lastSeenAt": "2026-05-12T00:00:00Z",
                    "evidenceTier": "weak",
                    "spanKind": "narrow",
                    "protectsFromPrune": True,
                    "sourceHashes": ["sha1:protected"],
                    "sessionHashes": ["sha1:session-protected"],
                },
                "strong": {
                    "path": "context/active.md",
                    "startLine": 3,
                    "endLine": 3,
                    "signalType": "final_citation",
                    "signalCount": 3,
                    "firstSeenAt": "2026-05-19T00:00:00Z",
                    "lastSeenAt": "2026-05-19T00:00:00Z",
                    "evidenceTier": "strong",
                    "spanKind": "narrow",
                    "protectsFromPrune": False,
                    "sourceHashes": ["sha1:strong"],
                    "sessionHashes": ["sha1:session-strong"],
                },
                "weak-overflow": {
                    "path": "context/active.md",
                    "startLine": 4,
                    "endLine": 4,
                    "signalType": "read",
                    "signalCount": 1,
                    "firstSeenAt": "2026-05-19T00:00:00Z",
                    "lastSeenAt": "2026-05-19T00:00:00Z",
                    "evidenceTier": "weak",
                    "spanKind": "narrow",
                    "protectsFromPrune": False,
                    "sourceHashes": ["sha1:weak"],
                    "sessionHashes": ["sha1:session-weak"],
                },
            },
        }

        compacted, manifest = telemetry.compact_telemetry_hot_json(payload, source_window_days=14, max_hot_entries=2)

        self.assertEqual(set(compacted["entries"]), {"protected", "strong"})
        self.assertEqual(manifest["entry_count_before"], 4)
        self.assertEqual(manifest["entry_count_after"], 2)
        self.assertEqual(manifest["dropped_expired_entry_count"], 1)
        self.assertEqual(manifest["dropped_overflow_entry_count"], 1)
        self.assertEqual(compacted["entries"]["protected"]["sourceHash"], "sha1:protected")
        self.assertNotIn("sourceHashes", compacted["entries"]["protected"])
        self.assertNotIn("sessionHashes", compacted["entries"]["protected"])
        self.assertEqual(compacted["summary"]["entry_count"], 2)
        self.assertEqual(compacted["compaction"], manifest)

    def test_compact_telemetry_drops_expired_verbose_entries_from_hot_json(self) -> None:
        payload = {
            "schema_version": telemetry.SCHEMA_VERSION,
            "generated_at_utc": "2026-05-20T12:00:00Z",
            "source_window_days": 30,
            "workspace_root": str(self.root.resolve()),
            "context_root": str(self.context.resolve()),
            "warnings": [],
            "entries": {
                "expired": {
                    "path": "context/active.md",
                    "startLine": 1,
                    "endLine": 1,
                    "signalType": "memory_get",
                    "signalCount": 8,
                    "firstSeenAt": "2026-04-01T00:00:00Z",
                    "lastSeenAt": "2026-04-01T00:00:00Z",
                    "evidenceTier": "strong",
                    "spanKind": "narrow",
                    "protectsFromPrune": True,
                    "sourceHashes": ["sha1:expired"],
                    "sessionHashes": ["sha1:session-expired"],
                },
                "recent": {
                    "path": "context/active.md",
                    "startLine": 2,
                    "endLine": 2,
                    "signalType": "memory_get",
                    "signalCount": 1,
                    "firstSeenAt": "2026-05-18T00:00:00Z",
                    "lastSeenAt": "2026-05-18T00:00:00Z",
                    "evidenceTier": "medium",
                    "spanKind": "narrow",
                    "protectsFromPrune": True,
                    "sourceHashes": ["sha1:recent"],
                    "sessionHashes": ["sha1:session-recent"],
                },
            },
        }

        compacted, manifest = telemetry.compact_telemetry_hot_json(payload, source_window_days=14, max_hot_entries=750)

        self.assertEqual(set(compacted["entries"]), {"recent"})
        self.assertEqual(manifest["dropped_expired_entry_count"], 1)
        self.assertEqual(compacted["entries"]["recent"]["sourceHash"], "sha1:recent")
        self.assertNotIn("sessionHashes", compacted["entries"]["recent"])

    def test_report_writes_compact_markdown_from_existing_json(self) -> None:
        json_path = Path(self.tmp.name) / "context-usage-telemetry.json"
        markdown_path = Path(self.tmp.name) / "context-usage-telemetry.md"
        payload = {
            "schema_version": telemetry.SCHEMA_VERSION,
            "generated_at_utc": "2026-05-20T12:00:00Z",
            "source_window_days": 30,
            "workspace_root": str(self.root.resolve()),
            "context_root": str(self.context.resolve()),
            "entries": {
                "read:1": {"path": "context/active.md", "signalType": "read"},
                "memory_get:1": {"path": "context/active.md", "signalType": "memory_get"},
            },
            "summary": {
                "entry_count": 2,
                "covered_file_count": 1,
                "signal_type_counts": {"read": 1, "memory_get": 1},
                "evidence_tier_counts": {"medium": 1, "strong": 1},
                "span_kind_counts": {"narrow": 2},
                "broad_read_count": 0,
                "raw_search_only_count": 0,
                "entries_with_content_hash": 1,
                "entries_without_content_hash": 1,
                "content_hash_by_signal_type": {"memory_get": 1},
                "warning_reason_counts": {"sample-warning": 1},
                "warning_count": 1,
            },
            "warnings": [{"kind": "read", "reason": "sample-warning"}],
        }
        json_path.write_text(json.dumps(payload), encoding="utf-8")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = telemetry.command_report(
                SimpleNamespace(input_json=json_path, output_markdown=markdown_path, write_markdown=True)
            )

        self.assertEqual(rc, 0)
        self.assertIn("CONTEXT_USAGE_TELEMETRY_REPORT_OK", stdout.getvalue())
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("entries: `2`", markdown)
        self.assertIn("covered files: `1`", markdown)
        self.assertIn("signal counts: memory_get=1, read=1", markdown)
        self.assertIn("evidence tier counts: medium=1, strong=1", markdown)
        self.assertIn("span kind counts: narrow=2", markdown)
        self.assertIn("broad read entries: `0`", markdown)
        self.assertIn("raw search-only entries: `0`", markdown)
        self.assertIn("entries with content hash: `1`", markdown)
        self.assertIn("entries without content hash: `1`", markdown)
        self.assertIn("content hash by signal type: memory_get=1", markdown)
        self.assertIn("warning reason counts: sample-warning=1", markdown)
        self.assertIn("warnings: `1`", markdown)
        self.assertIn("sample-warning", markdown)


if __name__ == "__main__":
    unittest.main()


class ContextUsageTelemetryWarningTests(unittest.TestCase):
    def test_dedupe_warnings_collapses_exact_duplicate_warning_records(self) -> None:
        warnings = [
            {"kind": "context_edit", "path": "context/active.md", "reason": "edit-newtext-not-found", "sourceHash": "sha1:a"},
            {"kind": "context_edit", "path": "context/active.md", "reason": "edit-newtext-not-found", "sourceHash": "sha1:a"},
            {"kind": "context_edit", "path": "context/active.md", "reason": "edit-newtext-not-found", "sourceHash": "sha1:b"},
        ]

        deduped = telemetry.dedupe_warnings(warnings)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0], warnings[0])
        self.assertEqual(deduped[1], warnings[2])
