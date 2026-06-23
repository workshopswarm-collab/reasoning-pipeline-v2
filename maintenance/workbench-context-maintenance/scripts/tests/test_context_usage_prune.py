from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "context_usage_prune.py"
spec = importlib.util.spec_from_file_location("context_usage_prune", MODULE_PATH)
prune = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = prune
spec.loader.exec_module(prune)

TELEMETRY_MODULE_PATH = Path(__file__).resolve().parents[1] / "context_usage_telemetry.py"
telemetry_spec = importlib.util.spec_from_file_location("context_usage_telemetry_prune_tests", TELEMETRY_MODULE_PATH)
telemetry = importlib.util.module_from_spec(telemetry_spec)
assert telemetry_spec and telemetry_spec.loader
sys.modules[telemetry_spec.name] = telemetry
telemetry_spec.loader.exec_module(telemetry)


OLD = "2026-04-20T00:00:00Z"
NOW = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
RUN_BUCKET = "2026-05-01"


class ContextUsagePruneProjectSpineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = self.root / "context"
        self.sessions = Path(self.tmp.name) / "sessions"
        self.active_path = self.context / "active.md"
        self.project_path = self.context / "projects" / "quant-pipeline.md"
        self.workbench_context_path = self.context / "projects" / "workbench-context.md"
        (self.context / "projects").mkdir(parents=True)
        self.sessions.mkdir(parents=True)
        (self.context / "state").mkdir(parents=True)
        (self.root / "memory" / ".dreams").mkdir(parents=True)
        (self.root / "tmp" / "context-archive" / "section-prune").mkdir(parents=True)
        (self.root / "memory" / ".dreams" / "short-term-recall.json").write_text(json.dumps({"entries": {}}))

        self.orig = {
            "WORKBENCH_ROOT": prune.WORKBENCH_ROOT,
            "CONTEXT_ROOT": prune.CONTEXT_ROOT,
            "STATE_PATH": prune.STATE_PATH,
            "REPORT_PATH": prune.REPORT_PATH,
            "CONTEXT_TELEMETRY_PATH": prune.CONTEXT_TELEMETRY_PATH,
            "ARCHIVE_ROOT": prune.ARCHIVE_ROOT,
            "STATE_ARCHIVE_ROOT": prune.STATE_ARCHIVE_ROOT,
            "STATE_REBASE_ARCHIVE_ROOT": prune.STATE_REBASE_ARCHIVE_ROOT,
            "STATE_HISTORY_SHARD_ROOT": prune.STATE_HISTORY_SHARD_ROOT,
            "DECISIONS_CONSOLIDATION_ARCHIVE_ROOT": prune.DECISIONS_CONSOLIDATION_ARCHIVE_ROOT,
            "STATE_REBASE_PREVIEW_PATH": prune.STATE_REBASE_PREVIEW_PATH,
            "STATE_REBASE_MANIFEST_PATH": prune.STATE_REBASE_MANIFEST_PATH,
            "STATE_COMPACTION_PREVIEW_PATH": prune.STATE_COMPACTION_PREVIEW_PATH,
            "STATE_COMPACTION_MANIFEST_PATH": prune.STATE_COMPACTION_MANIFEST_PATH,
            "DECISIONS_CONSOLIDATION_ROOT": prune.DECISIONS_CONSOLIDATION_ROOT,
            "RECALL_STORE_PATH": prune.RECALL_STORE_PATH,
            "MODEL_LOCK_ROOT": prune.MODEL_LOCK_ROOT,
            "LAST_RECALL_LOAD_STATS": prune.LAST_RECALL_LOAD_STATS,
            "LAST_CONTEXT_TELEMETRY_HITS": prune.LAST_CONTEXT_TELEMETRY_HITS,
            "LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX": prune.LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX,
            "LAST_CONTEXT_TELEMETRY_MATCH_STATS": prune.LAST_CONTEXT_TELEMETRY_MATCH_STATS,
            "TELEMETRY_WORKBENCH_ROOT": telemetry.WORKBENCH_ROOT,
            "TELEMETRY_WORKBENCH_CONTEXT_ROOT": telemetry.WORKBENCH_CONTEXT_ROOT,
            "TELEMETRY_WORKBENCH_SESSION_LOG_ROOT": telemetry.WORKBENCH_SESSION_LOG_ROOT,
            "TELEMETRY_JSON_PATH": telemetry.TELEMETRY_JSON_PATH,
            "TELEMETRY_MARKDOWN_PATH": telemetry.TELEMETRY_MARKDOWN_PATH,
        }
        prune.WORKBENCH_ROOT = self.root
        prune.CONTEXT_ROOT = self.context
        prune.STATE_PATH = self.context / "state" / "context-pruning-state.json"
        prune.REPORT_PATH = self.context / "state" / "context-pruning-report.md"
        prune.CONTEXT_TELEMETRY_PATH = self.context / "state" / "context-usage-telemetry.json"
        prune.ARCHIVE_ROOT = self.root / "tmp" / "context-archive" / "section-prune"
        prune.STATE_ARCHIVE_ROOT = self.root / "tmp" / "context-archive" / "state-prune"
        prune.STATE_REBASE_ARCHIVE_ROOT = self.root / "tmp" / "context-archive" / "state-rebase"
        prune.STATE_HISTORY_SHARD_ROOT = self.root / "tmp" / "context-archive" / "state-history-shards"
        prune.DECISIONS_CONSOLIDATION_ARCHIVE_ROOT = self.root / "tmp" / "context-archive" / "decisions-consolidation"
        prune.STATE_REBASE_PREVIEW_PATH = self.context / "state" / "context-pruning-state-rebase-preview.json"
        prune.STATE_REBASE_MANIFEST_PATH = self.context / "state" / "context-pruning-state.rebase-manifest.json"
        prune.STATE_COMPACTION_PREVIEW_PATH = self.context / "state" / "context-pruning-state-compaction-preview.json"
        prune.STATE_COMPACTION_MANIFEST_PATH = self.context / "state" / "context-pruning-state.compaction-manifest.json"
        prune.DECISIONS_CONSOLIDATION_ROOT = self.root / "generated" / "decisions-consolidation"
        prune.RECALL_STORE_PATH = self.root / "memory" / ".dreams" / "short-term-recall.json"
        prune.MODEL_LOCK_ROOT = self.root / "locks"
        prune.LAST_RECALL_LOAD_STATS = prune.empty_recall_load_stats()
        prune.LAST_CONTEXT_TELEMETRY_HITS = {}
        prune.LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX = None
        prune.LAST_CONTEXT_TELEMETRY_MATCH_STATS = prune.empty_context_telemetry_match_stats()
        telemetry.WORKBENCH_ROOT = self.root.resolve()
        telemetry.WORKBENCH_CONTEXT_ROOT = self.context.resolve()
        telemetry.WORKBENCH_SESSION_LOG_ROOT = self.sessions.resolve()
        telemetry.TELEMETRY_JSON_PATH = prune.CONTEXT_TELEMETRY_PATH
        telemetry.TELEMETRY_MARKDOWN_PATH = self.context / "state" / "context-usage-telemetry.md"

    def tearDown(self) -> None:
        for name, value in self.orig.items():
            if name.startswith("TELEMETRY_"):
                continue
            setattr(prune, name, value)
        telemetry.WORKBENCH_ROOT = self.orig["TELEMETRY_WORKBENCH_ROOT"]
        telemetry.WORKBENCH_CONTEXT_ROOT = self.orig["TELEMETRY_WORKBENCH_CONTEXT_ROOT"]
        telemetry.WORKBENCH_SESSION_LOG_ROOT = self.orig["TELEMETRY_WORKBENCH_SESSION_LOG_ROOT"]
        telemetry.TELEMETRY_JSON_PATH = self.orig["TELEMETRY_JSON_PATH"]
        telemetry.TELEMETRY_MARKDOWN_PATH = self.orig["TELEMETRY_MARKDOWN_PATH"]
        self.tmp.cleanup()

    def config(self) -> prune.AuditConfig:
        return prune.AuditConfig(
            stale_days=10,
            dormant_days=5,
            recent_grace_days=3,
            min_seen_runs_review=1,
            min_seen_runs_prune=1,
            min_unrecalled_runs_review=1,
            min_unrecalled_runs_prune=1,
        )

    def deterministic_local_config(self) -> prune.LocalCompressionConfig:
        return prune.LocalCompressionConfig(
            enabled=False,
            model="qwen3.5:4b",
            ollama_url="http://127.0.0.1:11434/api/generate",
            max_blocks=0,
            timeout_seconds=1,
            lock_timeout_seconds=0.0,
            max_summary_chars=700,
        )

    def state_for(self, keys: list[str]) -> dict:
        return {
            "version": 2,
            "items": {
                key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 0,
                    "unrecalledRuns": 4,
                    "maxCharCount": 1000,
                }
                for key in keys
            },
        }

    def build(self, text: str, state: dict | None = None) -> tuple[list[prune.Item], dict]:
        self.project_path.write_text(text)
        state = state or {"version": 2, "items": {}}
        items = prune.build_items(NOW, state, self.config(), RUN_BUCKET)
        return items, state

    def build_all(self, state: dict | None = None) -> tuple[list[prune.Item], dict]:
        state = state or {"version": 2, "items": {}}
        items = prune.build_items(NOW, state, self.config(), RUN_BUCKET)
        return items, state

    def find_item(self, items: list[prune.Item], kind: str, heading: str) -> prune.Item:
        for item in items:
            if item.kind == kind and item.section_heading == heading:
                return item
        raise AssertionError(f"missing {kind} under {heading!r}")

    def find_items(self, items: list[prune.Item], kind: str, heading: str) -> list[prune.Item]:
        return [item for item in items if item.kind == kind and item.section_heading == heading]

    def write_session(self, *records: dict) -> Path:
        path = self.sessions / "session-1.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return path

    def materialize_telemetry(self, *records: dict) -> dict:
        self.write_session(*records)
        payload = telemetry.build_telemetry(source_window_days=3650, generated_at_utc="2026-05-20T12:00:00Z")
        prune.CONTEXT_TELEMETRY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

    def write_telemetry_entries(self, *entries: dict) -> None:
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps({"entries": {f"entry-{idx}": entry for idx, entry in enumerate(entries, start=1)}}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def mature_state_for_items(self, items: list[prune.Item]) -> dict:
        return self.state_for([item.key for item in items])

    def synthetic_item(
        self,
        key: str,
        *,
        path: str = "context/projects/quant-pipeline.md",
        heading: str = "Synthetic heading",
        classification: str = "keep",
        reason: str = "synthetic",
        evidence_class: str = "none",
        strong: int = 0,
        medium: int = 0,
        weak_broad: int = 0,
        char_count: int = 500,
        start_line: int = 1,
    ) -> prune.Item:
        return prune.Item(
            key=key,
            kind="section",
            path=path,
            section_heading=heading,
            heading_level=2,
            start_line=start_line,
            end_line=start_line + 3,
            char_count=char_count,
            text_hash=f"hash-{key}",
            explicit_dates=[],
            recall_hits=1 if strong and classification == "keep" else 0,
            recall_signal_count=strong,
            last_recalled_at="2026-05-01T10:00:00Z" if strong and classification == "keep" else None,
            age_days=20,
            pinned=False,
            seen_runs=5,
            recall_runs=1 if strong and classification == "keep" else 0,
            unrecalled_runs=0 if strong and classification == "keep" else 5,
            classification=classification,
            reason=reason,
            evidence_class=evidence_class,
            strong_evidence_hits=strong,
            medium_evidence_hits=medium,
            weak_broad_evidence_hits=weak_broad,
        )

    def test_item_fingerprint_key_ignores_line_number(self) -> None:
        text = "- Same durable point across line shifts"
        first_key, first_exact, first_prefix, first_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-05-01",
            10,
            text,
        )
        second_key, second_exact, second_prefix, second_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-05-01",
            25,
            text,
        )

        self.assertNotEqual(first_key, second_key)
        self.assertEqual(first_exact, [])
        self.assertEqual(first_prefix, [])
        self.assertEqual(second_exact, [])
        self.assertEqual(second_prefix, [])
        self.assertEqual(first_fingerprints, second_fingerprints)
        self.assertEqual(len(first_fingerprints), 1)
        self.assertTrue(first_fingerprints[0].startswith("fingerprint:context/active.md:bullet:2026-05-01:"))

    def test_item_fingerprint_ignores_line_number(self) -> None:
        text = "- Same durable point across line shifts."

        first_key, _first_exact, _first_prefix, first_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            2,
            text,
        )
        second_key, _second_exact, _second_prefix, second_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            30,
            text,
        )

        self.assertNotEqual(first_key, second_key)
        self.assertEqual(first_fingerprints, second_fingerprints)
        self.assertEqual(first_fingerprints, [prune.item_fingerprint_key(Path("context/active.md"), "bullet", "2026-04-01", text)])

    def test_project_spine_volatile_keys_keep_stable_primary_and_fingerprint_alias(self) -> None:
        text = "## Current active implementation concerns\n\n- A volatile but recurring implementation concern.\n"
        key, exact_aliases, prefix_aliases, fingerprint_aliases = prune.item_keys(
            Path("context/projects/quant-pipeline.md"),
            "section",
            "Current active implementation concerns",
            42,
            text,
        )

        stable_key = "section:context/projects/quant-pipeline.md:current-active-implementation-concerns"
        self.assertEqual(key, stable_key)
        self.assertEqual(len(exact_aliases), 1)
        self.assertTrue(exact_aliases[0].startswith(f"{stable_key}:"))
        self.assertEqual(prefix_aliases, [f"{stable_key}:"])
        self.assertEqual(len(fingerprint_aliases), 1)
        self.assertTrue(
            fingerprint_aliases[0].startswith(
                "fingerprint:context/projects/quant-pipeline.md:section:current-active-implementation-concerns:"
            )
        )

    def test_build_items_populates_content_fingerprint_identity(self) -> None:
        section_text = "## 2026-04-01\n\n- A dated item large enough to inspect identity fields."
        bullet_text = "- A dated item large enough to inspect identity fields."
        items, _state = self.build(f"{section_text}\n")
        section = self.find_item(items, "section", "2026-04-01")
        bullet = self.find_item(items, "bullet", "2026-04-01")

        self.assertEqual(
            section.fingerprint,
            prune.item_fingerprint(Path(section.path), section.kind, section.section_heading, section_text),
        )
        self.assertEqual(
            section.identity_key,
            prune.item_fingerprint_key(Path(section.path), section.kind, section.section_heading, section_text),
        )
        self.assertEqual(section.identity_mode, "content-fingerprint")
        self.assertEqual(
            bullet.identity_key,
            prune.item_fingerprint_key(Path(bullet.path), bullet.kind, bullet.section_heading, bullet_text),
        )
        self.assertEqual(bullet.identity_mode, "content-fingerprint")

    def test_fingerprint_state_alias_preserves_entry_across_line_shift(self) -> None:
        bullet_text = "- Same durable point across line shifts"
        old_key, _old_exact, _old_prefix, fingerprint_aliases = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            3,
            bullet_text,
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {fingerprint_aliases[0]: old_key},
            "items": {
                old_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 0,
                    "maxCharCount": 900,
                }
            },
        }

        self.active_path.write_text(f"## 2026-04-01\n\nContext line that shifts the bullet.\n\n{bullet_text}\n", encoding="utf-8")
        items, state = self.build_all(state)
        bullet = self.find_item(items, "bullet", "2026-04-01")

        self.assertNotEqual(bullet.key, old_key)
        self.assertEqual(bullet.seen_runs, 5)
        self.assertEqual(bullet.recall_runs, 1)
        self.assertEqual(state["items"][bullet.key]["migratedFrom"], [old_key])
        self.assertEqual(state["items"][bullet.key]["identityMatchedBy"], "fingerprint")
        self.assertEqual(state.get("warningCounters", {}).get("fingerprint_ambiguous", 0), 0)

    def test_line_legacy_state_alias_ignores_fingerprint_match(self) -> None:
        bullet_text = "- Same durable point across line shifts"
        old_key, _old_exact, _old_prefix, fingerprint_aliases = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            3,
            bullet_text,
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {fingerprint_aliases[0]: old_key},
            "items": {
                old_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 0,
                    "maxCharCount": 900,
                }
            },
        }

        self.active_path.write_text(f"## 2026-04-01\n\nContext line that shifts the bullet.\n\n{bullet_text}\n", encoding="utf-8")
        items = prune.build_items(NOW, state, self.config(), RUN_BUCKET, identity_mode="line-legacy")
        bullet = self.find_item(items, "bullet", "2026-04-01")
        updated = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET, identity_mode="line-legacy")

        self.assertNotEqual(bullet.key, old_key)
        self.assertEqual(bullet.seen_runs, 1)
        self.assertEqual(updated["identityMode"], "line-legacy")
        self.assertNotIn("migratedFrom", updated["items"][bullet.key])
        self.assertNotEqual(updated["items"][bullet.key].get("identityMatchedBy"), "fingerprint")
        self.assertEqual(updated.get("warningCounters", {}).get("fingerprint_ambiguous", 0), 0)

    def test_ambiguous_fingerprint_state_alias_starts_fresh_and_warns(self) -> None:
        bullet_text = "- Ambiguous duplicate point"
        _old_key, _old_exact, _old_prefix, fingerprint_aliases = prune.item_keys(
            Path("context/projects/quant-pipeline.md"),
            "bullet",
            "2026-04-01",
            3,
            bullet_text,
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {fingerprint_aliases[0]: ["old-a", "old-b"]},
            "items": {
                "old-a": {"firstSeenAt": OLD, "seenRuns": 4, "recallRuns": 0, "unrecalledRuns": 4, "maxCharCount": 900},
                "old-b": {"firstSeenAt": OLD, "seenRuns": 3, "recallRuns": 0, "unrecalledRuns": 3, "maxCharCount": 800},
            },
        }

        items, state = self.build(f"## 2026-04-01\n\n{bullet_text}\n", state)
        bullet = self.find_item(items, "bullet", "2026-04-01")

        self.assertEqual(bullet.seen_runs, 1)
        self.assertNotIn("migratedFrom", state["items"].get(bullet.key, {}))
        self.assertEqual(state["warningCounters"]["fingerprint_ambiguous"], 1)

    def test_update_state_writes_v3_fingerprint_index_and_identity_fields(self) -> None:
        items, state = self.build("## 2026-04-01\n\n- A dated item large enough to inspect identity fields.\n", {"version": 2, "items": {}})
        section = self.find_item(items, "section", "2026-04-01")

        updated = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        entry = updated["items"][section.key]

        self.assertEqual(updated["version"], 3)
        self.assertEqual(updated["identityMode"], "content-primary")
        self.assertEqual(updated["fingerprints"][section.identity_key], section.key)
        self.assertEqual(entry["fingerprint"], section.fingerprint)
        self.assertEqual(entry["identityKey"], section.identity_key)
        self.assertEqual(entry["identityMode"], "content-fingerprint")
        self.assertEqual(entry["lastLineSpan"], {"startLine": section.start_line, "endLine": section.end_line})
        self.assertEqual(entry["textHash"], section.text_hash)
        self.assertEqual(entry["seenRuns"], section.seen_runs)
        self.assertEqual(entry["recallRuns"], section.recall_runs)
        self.assertEqual(entry["unrecalledRuns"], section.unrecalled_runs)
        self.assertEqual(entry["maxCharCount"], section.char_count)

    def test_update_state_skips_ambiguous_live_fingerprint_index(self) -> None:
        bullet_text = "- Duplicate current point"
        _old_key, _old_exact, _old_prefix, fingerprint_aliases = prune.item_keys(
            Path("context/projects/quant-pipeline.md"),
            "bullet",
            "2026-04-01",
            3,
            bullet_text,
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {fingerprint_aliases[0]: "old-duplicate"},
            "items": {
                "old-duplicate": {
                    "firstSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 0,
                    "unrecalledRuns": 4,
                    "maxCharCount": 900,
                }
            },
        }
        items, state = self.build(f"## 2026-04-01\n\n{bullet_text}\n{bullet_text}\n", state)
        bullets = [item for item in items if item.kind == "bullet" and item.section_heading == "2026-04-01"]
        self.assertEqual(len(bullets), 2)
        self.assertEqual(bullets[0].identity_key, bullets[1].identity_key)
        self.assertEqual([item.seen_runs for item in bullets], [1, 1])

        updated = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)

        self.assertNotIn(bullets[0].identity_key, updated["fingerprints"])
        self.assertEqual(updated["warningCounters"]["fingerprint_ambiguous"], 1)
        self.assertNotIn(prune.FINGERPRINT_AMBIGUITY_WARNED_KEY, updated)

    def test_build_rebased_state_preserves_exact_fingerprint_and_prefix_entries(self) -> None:
        active_bullet_text = "- Same durable point across line shifts"
        self.active_path.write_text(
            f"## 2026-04-01\n\nContext line that shifts the bullet.\n\n{active_bullet_text}\n",
            encoding="utf-8",
        )
        self.project_path.write_text(
            "## Current active implementation concerns\n\n"
            "Current implementation concern text.\n\n"
            "- Fresh volatile project-spine bullet.\n",
            encoding="utf-8",
        )
        candidates = prune.current_state_rebase_candidates()
        active_section = next(candidate for candidate in candidates if candidate.path == "context/active.md" and candidate.kind == "section")
        active_bullet = next(candidate for candidate in candidates if candidate.path == "context/active.md" and candidate.kind == "bullet")
        project_section = next(candidate for candidate in candidates if candidate.path == "context/projects/quant-pipeline.md" and candidate.kind == "section")
        project_bullet = next(candidate for candidate in candidates if candidate.path == "context/projects/quant-pipeline.md" and candidate.kind == "bullet")
        old_bullet_key, _old_exact, _old_prefix, old_bullet_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            3,
            active_bullet_text,
        )
        old_project_section_key = "section:context/projects/quant-pipeline.md:current-active-implementation-concerns:oldhash"
        state = {
            "version": 2,
            "fingerprints": {old_bullet_fingerprints[0]: old_bullet_key},
            "items": {
                active_section.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 7,
                    "recallRuns": 2,
                    "unrecalledRuns": 0,
                    "maxCharCount": 1000,
                },
                old_bullet_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 0,
                    "maxCharCount": 900,
                },
                old_project_section_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 6,
                    "recallRuns": 0,
                    "unrecalledRuns": 6,
                    "maxCharCount": 800,
                },
            },
        }

        rebased, manifest = prune.build_rebased_state(state, NOW.isoformat().replace("+00:00", "Z"))

        self.assertEqual(rebased["version"], 3)
        self.assertEqual(rebased["identityMode"], "content-primary")
        self.assertEqual(rebased["items"][active_section.key]["identityMatchedBy"], "exact")
        self.assertEqual(rebased["items"][active_section.key]["seenRuns"], 7)
        self.assertNotEqual(active_bullet.key, old_bullet_key)
        self.assertEqual(rebased["items"][active_bullet.key]["identityMatchedBy"], "fingerprint")
        self.assertEqual(rebased["items"][active_bullet.key]["migratedFrom"], [old_bullet_key])
        self.assertEqual(rebased["items"][active_bullet.key]["seenRuns"], 4)
        self.assertEqual(rebased["items"][project_section.key]["identityMatchedBy"], "prefix")
        self.assertEqual(rebased["items"][project_section.key]["migratedFrom"], [old_project_section_key])
        self.assertEqual(rebased["items"][project_section.key]["seenRuns"], 6)
        self.assertEqual(rebased["items"][project_bullet.key]["seenRuns"], 0)
        self.assertEqual(rebased["fingerprints"][active_bullet.identity_key], active_bullet.key)
        self.assertGreaterEqual(manifest["entries_preserved_by_exact_key"], 1)
        self.assertGreaterEqual(manifest["entries_preserved_by_fingerprint"], 1)
        self.assertGreaterEqual(manifest["entries_preserved_by_prefix_alias"], 1)
        self.assertGreaterEqual(manifest["entries_started_fresh"], 1)

    def test_state_rebase_preserves_counters_for_moved_unchanged_section(self) -> None:
        section_text = "## 2026-04-01\n\n- Same section after line shift.\n"
        self.active_path.write_text(section_text, encoding="utf-8")
        old_section = next(
            candidate
            for candidate in prune.current_state_rebase_candidates()
            if candidate.path == "context/active.md" and candidate.kind == "section" and candidate.section_heading == "2026-04-01"
        )
        self.active_path.write_text("# Active\n\nIntro line shifts the dated section.\n\n" + section_text, encoding="utf-8")
        moved_section = next(
            candidate
            for candidate in prune.current_state_rebase_candidates()
            if candidate.path == "context/active.md" and candidate.kind == "section" and candidate.section_heading == "2026-04-01"
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {old_section.identity_key: old_section.key},
            "items": {
                old_section.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 9,
                    "recallRuns": 2,
                    "unrecalledRuns": 1,
                    "maxCharCount": 1200,
                }
            },
        }

        rebased, manifest = prune.build_rebased_state(state, NOW.isoformat().replace("+00:00", "Z"))

        self.assertEqual(moved_section.identity_key, old_section.identity_key)
        self.assertEqual(rebased["items"][moved_section.key]["identityMatchedBy"], "exact")
        self.assertEqual(rebased["items"][moved_section.key]["seenRuns"], 9)
        self.assertEqual(rebased["items"][moved_section.key]["recallRuns"], 2)
        self.assertNotIn("migratedFrom", rebased["items"][moved_section.key])
        self.assertGreaterEqual(manifest["entries_preserved_by_exact_key"], 1)

    def test_state_rebase_starts_fresh_when_text_hash_changes(self) -> None:
        old_section_text = "## 2026-04-01\n\n- Original section text.\n"
        self.active_path.write_text(old_section_text, encoding="utf-8")
        old_section = next(
            candidate
            for candidate in prune.current_state_rebase_candidates()
            if candidate.path == "context/active.md" and candidate.kind == "section" and candidate.section_heading == "2026-04-01"
        )
        self.active_path.write_text("## 2026-04-01\n\n- Changed section text.\n", encoding="utf-8")
        changed_section = next(
            candidate
            for candidate in prune.current_state_rebase_candidates()
            if candidate.path == "context/active.md" and candidate.kind == "section" and candidate.section_heading == "2026-04-01"
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {old_section.identity_key: old_section.key},
            "items": {
                old_section.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 9,
                    "recallRuns": 2,
                    "unrecalledRuns": 1,
                    "maxCharCount": 1200,
                }
            },
        }

        rebased, manifest = prune.build_rebased_state(state, NOW.isoformat().replace("+00:00", "Z"))

        self.assertNotEqual(changed_section.identity_key, old_section.identity_key)
        self.assertEqual(rebased["items"][changed_section.key]["seenRuns"], 0)
        self.assertNotEqual(rebased["items"][changed_section.key].get("identityMatchedBy"), "fingerprint")
        self.assertNotIn("migratedFrom", rebased["items"][changed_section.key])
        self.assertGreaterEqual(manifest["entries_started_fresh"], 1)

    def test_build_rebased_state_line_legacy_skips_fingerprint_preservation(self) -> None:
        active_bullet_text = "- Same durable point across line shifts"
        self.active_path.write_text(
            f"## 2026-04-01\n\nContext line that shifts the bullet.\n\n{active_bullet_text}\n",
            encoding="utf-8",
        )
        self.project_path.write_text(
            "## Current active implementation concerns\n\n"
            "Current implementation concern text.\n\n"
            "- Fresh volatile project-spine bullet.\n",
            encoding="utf-8",
        )
        candidates = prune.current_state_rebase_candidates()
        active_bullet = next(candidate for candidate in candidates if candidate.path == "context/active.md" and candidate.kind == "bullet")
        project_section = next(candidate for candidate in candidates if candidate.path == "context/projects/quant-pipeline.md" and candidate.kind == "section")
        old_bullet_key, _old_exact, _old_prefix, old_bullet_fingerprints = prune.item_keys(
            Path("context/active.md"),
            "bullet",
            "2026-04-01",
            3,
            active_bullet_text,
        )
        old_project_section_key = "section:context/projects/quant-pipeline.md:current-active-implementation-concerns:oldhash"
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {old_bullet_fingerprints[0]: old_bullet_key},
            "items": {
                old_bullet_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 0,
                    "maxCharCount": 900,
                },
                old_project_section_key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 6,
                    "recallRuns": 0,
                    "unrecalledRuns": 6,
                    "maxCharCount": 800,
                },
            },
        }

        rebased, manifest = prune.build_rebased_state(state, NOW.isoformat().replace("+00:00", "Z"), identity_mode="line-legacy")

        self.assertEqual(rebased["identityMode"], "line-legacy")
        self.assertEqual(manifest["identityMode"], "line-legacy")
        self.assertEqual(manifest["entries_preserved_by_fingerprint"], 0)
        self.assertNotEqual(active_bullet.key, old_bullet_key)
        self.assertEqual(rebased["items"][active_bullet.key]["seenRuns"], 0)
        self.assertNotIn("migratedFrom", rebased["items"][active_bullet.key])
        self.assertNotEqual(rebased["items"][active_bullet.key].get("identityMatchedBy"), "fingerprint")
        self.assertEqual(rebased["items"][project_section.key]["identityMatchedBy"], "prefix")
        self.assertEqual(rebased["items"][project_section.key]["seenRuns"], 6)

    def test_identity_mode_line_legacy_restores_old_matching_behavior(self) -> None:
        active_bullet_text = "- Same durable point across line shifts"
        self.active_path.write_text(active_bullet_text + "\n", encoding="utf-8")
        old_bullet = next(candidate for candidate in prune.current_state_rebase_candidates() if candidate.path == "context/active.md" and candidate.kind == "bullet")
        self.active_path.write_text("## 2026-04-01\n\nIntro shifts the bullet.\n\n" + active_bullet_text + "\n", encoding="utf-8")
        shifted_bullet = next(candidate for candidate in prune.current_state_rebase_candidates() if candidate.path == "context/active.md" and candidate.kind == "bullet")
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {old_bullet.identity_key: old_bullet.key},
            "items": {
                old_bullet.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 0,
                    "maxCharCount": 900,
                }
            },
        }

        rebased, manifest = prune.build_rebased_state(
            state,
            NOW.isoformat().replace("+00:00", "Z"),
            identity_mode="line-legacy",
        )

        self.assertEqual(rebased["identityMode"], "line-legacy")
        self.assertEqual(manifest["entries_preserved_by_fingerprint"], 0)
        self.assertNotEqual(shifted_bullet.key, old_bullet.key)
        self.assertEqual(rebased["items"][shifted_bullet.key]["seenRuns"], 0)
        self.assertNotEqual(rebased["items"][shifted_bullet.key].get("identityMatchedBy"), "fingerprint")
        self.assertNotIn("migratedFrom", rebased["items"][shifted_bullet.key])

    def test_run_state_rebase_dry_run_writes_preview_without_mutating_state(self) -> None:
        self.project_path.write_text("## 2026-04-01\n\n- A current item.\n", encoding="utf-8")
        original_state = {"version": 2, "items": {}}
        prune.STATE_PATH.write_text(json.dumps(original_state, indent=2) + "\n", encoding="utf-8")

        manifest = prune.run_state_rebase(stamp="unit-dry-run", apply=False, now_str=NOW.isoformat().replace("+00:00", "Z"))

        self.assertTrue(prune.STATE_REBASE_PREVIEW_PATH.exists())
        preview = json.loads(prune.STATE_REBASE_PREVIEW_PATH.read_text(encoding="utf-8"))
        self.assertEqual(preview["manifest"]["stamp"], "unit-dry-run")
        self.assertEqual(preview["proposed_state"]["version"], 3)
        self.assertEqual(json.loads(prune.STATE_PATH.read_text(encoding="utf-8")), original_state)
        self.assertTrue(manifest["dry_run"])
        self.assertIsNone(manifest["archived_state_path"])

    def test_run_state_rebase_apply_archives_and_writes_manifest(self) -> None:
        self.project_path.write_text("## 2026-04-01\n\n- A current item.\n", encoding="utf-8")
        original_state = {"version": 2, "items": {"stale-key": {"seenRuns": 2}}}
        original_text = json.dumps(original_state, indent=2) + "\n"
        prune.STATE_PATH.write_text(original_text, encoding="utf-8")

        manifest = prune.run_state_rebase(stamp="unit-apply", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))

        archive_path = Path(manifest["archived_state_path"])
        self.assertTrue(archive_path.exists())
        self.assertEqual(archive_path.read_text(encoding="utf-8"), original_text)
        self.assertTrue(prune.STATE_REBASE_MANIFEST_PATH.exists())
        written_manifest = json.loads(prune.STATE_REBASE_MANIFEST_PATH.read_text(encoding="utf-8"))
        written_state = json.loads(prune.STATE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(manifest["dry_run"])
        self.assertEqual(written_manifest["stamp"], "unit-apply")
        self.assertEqual(written_state["version"], 3)
        self.assertEqual(written_state["identityMode"], "content-primary")
        self.assertIn("fingerprints", written_state)

    def test_state_rebase_archives_previous_state_before_apply(self) -> None:
        self.project_path.write_text("## 2026-04-01\n\n- A current item.\n", encoding="utf-8")
        original_state = {"version": 2, "items": {"legacy-key": {"seenRuns": 3, "recallRuns": 1}}}
        original_text = json.dumps(original_state, indent=2, sort_keys=True) + "\n"
        prune.STATE_PATH.write_text(original_text, encoding="utf-8")

        manifest = prune.run_state_rebase(stamp="archive-before-apply", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))

        archive_path = Path(manifest["archived_state_path"])
        self.assertTrue(archive_path.exists())
        self.assertEqual(archive_path.read_text(encoding="utf-8"), original_text)
        self.assertNotEqual(prune.STATE_PATH.read_text(encoding="utf-8"), original_text)
        self.assertEqual(json.loads(prune.STATE_REBASE_MANIFEST_PATH.read_text(encoding="utf-8"))["archived_state_path"], str(archive_path))

    def state_compaction_fixture(self) -> tuple[dict, prune.Item]:
        self.project_path.write_text("## 2026-05-01\n\n- Current retained item.\n", encoding="utf-8")
        current_items = prune.build_items(NOW, {"version": 3, "items": {}}, self.config(), RUN_BUCKET)
        current_item = next(item for item in current_items if item.path == "context/projects/quant-pipeline.md" and item.kind == "section")
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "updatedAt": OLD,
            "fingerprints": {
                current_item.identity_key: current_item.key,
                "fingerprint:dead": "expired-key",
            },
            "items": {
                current_item.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 1,
                    "maxCharCount": 1000,
                    "identityKey": current_item.identity_key,
                    "fingerprint": current_item.fingerprint,
                },
                "expired-key": {
                    "firstSeenAt": "2026-03-01T00:00:00Z",
                    "lastSeenAt": "2026-03-01T00:00:00Z",
                    "firstMissingAt": "2026-04-01T00:00:00Z",
                    "lastMissingAt": "2026-04-01T00:00:00Z",
                    "seenRuns": 3,
                    "recallRuns": 0,
                    "unrecalledRuns": 3,
                    "identityKey": "fingerprint:dead",
                    "fingerprint": "fingerprint:dead",
                },
                "recent-missing-key": {
                    "firstSeenAt": "2026-04-20T00:00:00Z",
                    "lastSeenAt": "2026-04-20T00:00:00Z",
                    "firstMissingAt": "2026-04-25T00:00:00Z",
                    "lastMissingAt": "2026-04-25T00:00:00Z",
                    "seenRuns": 1,
                    "recallRuns": 0,
                    "unrecalledRuns": 1,
                    "identityKey": "fingerprint:recent",
                    "fingerprint": "fingerprint:recent",
                },
            },
        }
        return state, current_item

    def test_run_state_compaction_dry_run_writes_preview_without_mutating_state(self) -> None:
        state, _current_item = self.state_compaction_fixture()
        original_text = json.dumps(state, indent=2, sort_keys=True) + "\n"
        prune.STATE_PATH.write_text(original_text, encoding="utf-8")

        manifest = prune.run_state_compaction(stamp="unit-compact-dry-run", apply=False, now_str=NOW.isoformat().replace("+00:00", "Z"))

        self.assertTrue(prune.STATE_COMPACTION_PREVIEW_PATH.exists())
        preview = json.loads(prune.STATE_COMPACTION_PREVIEW_PATH.read_text(encoding="utf-8"))
        self.assertTrue(manifest["dry_run"])
        self.assertIsNone(manifest["archived_state_path"])
        self.assertEqual(preview["manifest"]["stamp"], "unit-compact-dry-run")
        self.assertEqual(preview["manifest"]["entries_dropped"], 1)
        self.assertNotIn("expired-key", preview["proposed_state"]["items"])
        self.assertEqual(prune.STATE_PATH.read_text(encoding="utf-8"), original_text)

    def test_compact_pruning_state_archives_before_dropping_orphans(self) -> None:
        state, current_item = self.state_compaction_fixture()
        original_text = json.dumps(state, indent=2, sort_keys=True) + "\n"
        prune.STATE_PATH.write_text(original_text, encoding="utf-8")

        manifest = prune.run_state_compaction(stamp="unit-compact-apply", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))

        archive_path = Path(manifest["archived_state_path"])
        self.assertTrue(archive_path.exists())
        self.assertEqual(archive_path.read_text(encoding="utf-8"), original_text)
        self.assertTrue(prune.STATE_COMPACTION_MANIFEST_PATH.exists())
        written_manifest = json.loads(prune.STATE_COMPACTION_MANIFEST_PATH.read_text(encoding="utf-8"))
        written_state = json.loads(prune.STATE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(manifest["dry_run"])
        self.assertEqual(written_manifest["entries_dropped"], 1)
        self.assertIn(current_item.key, written_state["items"])
        self.assertIn("recent-missing-key", written_state["items"])
        self.assertNotIn("expired-key", written_state["items"])
        self.assertEqual(written_state["fingerprints"], {})
        self.assertEqual(written_state["items"][current_item.key]["identityKey"], current_item.identity_key)
        self.assertEqual(written_state["lastCompaction"]["archived_state_path"], str(archive_path))
        self.assertEqual(written_manifest["entries_archived"], 1)
        self.assertEqual(written_manifest["entries_retained_current"], 1)
        self.assertEqual(written_manifest["entries_retained_history"], 1)
        self.assertTrue(written_manifest["state_budget_met"])
        self.assertEqual(written_manifest["state_budget_status"], "state_budget_met")
        shards = written_manifest["archived_history_shards"]
        self.assertEqual(len(shards), 1)
        shard_path = Path(shards[0]["path"])
        self.assertTrue(shard_path.exists())
        shard_lines = shard_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(shard_lines), 1)
        self.assertEqual(json.loads(shard_lines[0])["key"], "expired-key")

    def test_compact_pruning_state_preserves_current_item_counters(self) -> None:
        state, current_item = self.state_compaction_fixture()
        prune.STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        prune.run_state_compaction(stamp="unit-compact-counters", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))

        written_state = json.loads(prune.STATE_PATH.read_text(encoding="utf-8"))
        retained = written_state["items"][current_item.key]
        self.assertEqual(retained["seenRuns"], 4)
        self.assertEqual(retained["recallRuns"], 1)
        self.assertEqual(retained["unrecalledRuns"], 1)
        self.assertEqual(retained["firstSeenAt"], "2026-04-20")
        self.assertEqual(retained["identityKey"], current_item.identity_key)
        self.assertNotIn("maxCharCount", retained)
        self.assertNotIn("kind", retained)
        self.assertNotIn("path", retained)
        self.assertNotIn("fingerprint", retained)

    def test_compact_pruning_state_drops_recent_history_until_hard_budget_met(self) -> None:
        state, current_item = self.state_compaction_fixture()
        for index in range(800):
            state["items"][f"recent-history-{index:03d}"] = {
                "firstSeenAt": "2026-04-25T00:00:00Z",
                "lastSeenAt": "2026-04-25T00:00:00Z",
                "firstMissingAt": "2026-04-30T00:00:00Z",
                "lastMissingAt": "2026-04-30T00:00:00Z",
                "seenRuns": 1,
                "recallRuns": 0,
                "unrecalledRuns": 1,
                "identityKey": f"fingerprint:recent-{index:03d}",
                "fingerprint": f"fingerprint:recent-{index:03d}",
                "largeLegacyBlob": "recent history detail " * 20,
            }
        original_budget = prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")]
        prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")] = {"target_bytes": 34_000, "hard_bytes": 68_000}
        try:
            prune.STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            manifest = prune.run_state_compaction(stamp="unit-compact-budget", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))
        finally:
            prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")] = original_budget

        written_state = json.loads(prune.STATE_PATH.read_text(encoding="utf-8"))
        self.assertTrue(manifest["state_budget_met"])
        self.assertEqual(manifest["state_budget_status"], "state_budget_met")
        self.assertLessEqual(manifest["state_bytes_after_planned"], 68_000)
        self.assertIn(current_item.key, written_state["items"])
        self.assertGreater(manifest["entries_archived"], 1)
        self.assertGreater(manifest["dropped_reason_counts"]["budget_drop_recent_tombstone_or_alias"], 0)
        self.assertGreater(manifest["archived_history_shard_count"], 0)
        for shard in manifest["archived_history_shards"]:
            self.assertTrue(Path(shard["path"]).exists())

    def test_compact_pruning_state_reports_degraded_when_current_items_exceed_budget(self) -> None:
        self.project_path.write_text("## 2026-05-01\n\n- " + ("Current retained item. " * 250) + "\n", encoding="utf-8")
        current_items = prune.build_items(NOW, {"version": 3, "items": {}}, self.config(), RUN_BUCKET)
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "updatedAt": OLD,
            "fingerprints": {item.identity_key: item.key for item in current_items if item.identity_key},
            "items": {
                item.key: {
                    "firstSeenAt": OLD,
                    "lastSeenAt": OLD,
                    "seenRuns": 4,
                    "recallRuns": 1,
                    "unrecalledRuns": 1,
                    "identityKey": item.identity_key,
                    "fingerprint": item.fingerprint,
                }
                for item in current_items
            },
        }
        original_budget = prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")]
        prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")] = {"target_bytes": 200, "hard_bytes": 400}
        try:
            prune.STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            manifest = prune.run_state_compaction(stamp="unit-compact-degraded", apply=True, now_str=NOW.isoformat().replace("+00:00", "Z"))
        finally:
            prune.STATE_FILE_BUDGETS[Path("context/state/context-pruning-state.json")] = original_budget

        written_state = json.loads(prune.STATE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(manifest["state_budget_met"])
        self.assertEqual(manifest["state_budget_status"], "degraded_state_budget_unmet")
        self.assertGreater(manifest["state_bytes_over_hard"], 0)
        self.assertEqual(manifest["entries_after"], manifest["entries_retained_current"])
        self.assertEqual(set(written_state["items"]), set(state["items"]))

    def test_context_telemetry_loader_missing_file_is_nonfatal(self) -> None:
        stats = prune.empty_recall_load_stats()

        hits = prune.load_context_telemetry_hits(stats=stats, now_dt=NOW)

        self.assertEqual(hits, {})
        self.assertEqual(stats["context_telemetry_entries_seen"], 0)
        self.assertEqual(stats["context_telemetry_entries_loaded"], 0)
        self.assertEqual(stats["context_telemetry_covered_files"], 0)
        self.assertEqual(stats["warnings"], [])

    def test_context_telemetry_loader_invalid_file_records_warning(self) -> None:
        prune.CONTEXT_TELEMETRY_PATH.write_text("{not valid json", encoding="utf-8")
        stats = prune.empty_recall_load_stats()

        hits = prune.load_context_telemetry_hits(stats=stats, now_dt=NOW)

        self.assertEqual(hits, {})
        self.assertEqual(len(stats["warnings"]), 1)
        warning = stats["warnings"][0]
        self.assertEqual(warning["kind"], "context_telemetry")
        self.assertEqual(warning["path"], "context/state/context-usage-telemetry.json")
        self.assertTrue(warning["reason"].startswith("invalid-telemetry:JSONDecodeError"))

    def test_context_telemetry_loader_materializes_hot_doc_hits(self) -> None:
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "raw-entry-id-is-not-exposed": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 4,
                            "endLine": 8,
                            "signalCount": 3,
                            "lastSeenAt": "2026-05-20T10:00:00Z",
                            "protectsFromPrune": True,
                        },
                        "non-hot-doc": {
                            "path": "context/projects/not-pruned.md",
                            "startLine": 1,
                            "endLine": 2,
                            "signalCount": 99,
                            "lastSeenAt": "2026-05-20T10:01:00Z",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        stats = prune.empty_recall_load_stats()

        hits = prune.load_context_telemetry_hits(stats=stats, now_dt=NOW)

        self.assertEqual(list(hits), ["context/projects/quant-pipeline.md"])
        hit = hits["context/projects/quant-pipeline.md"][0]
        self.assertEqual(hit.start_line, 4)
        self.assertEqual(hit.end_line, 8)
        self.assertEqual(hit.signal_count, 3)
        self.assertEqual(hit.last_recalled_at, "2026-05-20T10:00:00Z")
        self.assertEqual(stats["context_telemetry_entries_seen"], 2)
        self.assertEqual(stats["context_telemetry_entries_loaded"], 1)
        self.assertEqual(stats["context_telemetry_covered_files"], 1)
        self.assertEqual(stats["warnings"], [])

    def test_typed_context_telemetry_loader_loads_all_hot_doc_evidence(self) -> None:
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "protective-final-citation": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 4,
                            "endLine": 8,
                            "signalCount": 3,
                            "lastSeenAt": "2026-05-20T10:00:00Z",
                            "signalType": "final_citation",
                            "evidenceTier": "strong",
                            "spanKind": "narrow",
                            "followThrough": "quoted_in_answer",
                            "tierReason": "direct final citation",
                            "contentHash": "abc123",
                            "protectsFromPrune": True,
                        },
                        "non-protective-context-edit": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 20,
                            "endLine": 25,
                            "signalCount": 2,
                            "lastSeenAt": "2026-05-20T11:00:00Z",
                            "signalType": "context_edit",
                            "evidenceTier": "strong",
                            "spanKind": "narrow",
                            "followThrough": "provenance_only",
                            "tierReason": "edit provenance only",
                            "protectsFromPrune": False,
                        },
                        "non-hot-doc": {
                            "path": "context/projects/not-pruned.md",
                            "startLine": 1,
                            "endLine": 2,
                            "signalCount": 99,
                            "lastSeenAt": "2026-05-20T12:00:00Z",
                            "protectsFromPrune": True,
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        typed_stats = prune.empty_recall_load_stats()

        typed_hits = prune.load_context_telemetry_evidence_hits(stats=typed_stats, now_dt=NOW)

        self.assertEqual(list(typed_hits), ["context/projects/quant-pipeline.md"])
        self.assertEqual(len(typed_hits["context/projects/quant-pipeline.md"]), 2)
        protective = typed_hits["context/projects/quant-pipeline.md"][0]
        self.assertEqual(protective.signal_type, "final_citation")
        self.assertEqual(protective.evidence_tier, "strong")
        self.assertEqual(protective.span_kind, "narrow")
        self.assertTrue(protective.protects_from_prune)
        self.assertEqual(protective.follow_through, "quoted_in_answer")
        self.assertEqual(protective.tier_reason, "direct final citation")
        self.assertEqual(protective.content_hash, "abc123")
        non_protective = typed_hits["context/projects/quant-pipeline.md"][1]
        self.assertEqual(non_protective.signal_type, "context_edit")
        self.assertFalse(non_protective.protects_from_prune)
        self.assertEqual(typed_stats["context_telemetry_entries_seen"], 3)
        self.assertEqual(typed_stats["context_telemetry_typed_entries_loaded"], 2)
        self.assertEqual(typed_stats["context_telemetry_entries_loaded"], 0)

        compatibility_stats = prune.empty_recall_load_stats()
        compatibility_hits = prune.load_context_telemetry_hits(stats=compatibility_stats, now_dt=NOW)

        self.assertEqual(len(compatibility_hits["context/projects/quant-pipeline.md"]), 1)
        self.assertEqual(compatibility_hits["context/projects/quant-pipeline.md"][0].signal_count, 3)
        self.assertEqual(compatibility_stats["context_telemetry_entries_seen"], 3)
        self.assertEqual(compatibility_stats["context_telemetry_typed_entries_loaded"], 2)
        self.assertEqual(compatibility_stats["context_telemetry_entries_loaded"], 1)
        self.assertEqual(compatibility_stats["context_telemetry_covered_files"], 1)

    def test_typed_context_telemetry_loader_expires_protective_hits_for_compatibility(self) -> None:
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "expired-protective": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 4,
                            "endLine": 8,
                            "signalCount": 3,
                            "lastSeenAt": "2026-04-01T10:00:00Z",
                            "signalType": "memory_get",
                            "evidenceTier": "strong",
                            "spanKind": "narrow",
                            "protectsFromPrune": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        typed_stats = prune.empty_recall_load_stats()

        typed_hits = prune.load_context_telemetry_evidence_hits(stats=typed_stats, now_dt=NOW, max_age_days=8)

        hit = typed_hits["context/projects/quant-pipeline.md"][0]
        self.assertEqual(hit.evidence_tier, "strong")
        self.assertFalse(hit.protects_from_prune)
        self.assertEqual(typed_stats["context_telemetry_expired_protective_entries"], 1)

        compatibility_stats = prune.empty_recall_load_stats()
        compatibility_hits = prune.load_context_telemetry_hits(stats=compatibility_stats, now_dt=NOW, max_age_days=8)

        self.assertEqual(compatibility_hits, {})
        self.assertEqual(compatibility_stats["context_telemetry_entries_loaded"], 0)
        self.assertEqual(compatibility_stats["context_telemetry_expired_protective_entries"], 1)

    def test_item_evidence_for_span_counts_dream_and_strong_targeted_telemetry(self) -> None:
        dream_hits = {
            "context/projects/quant-pipeline.md": [
                prune.RecallHit(start_line=5, end_line=6, signal_count=2, last_recalled_at="2026-05-20T10:00:00Z")
            ]
        }
        telemetry_hits = {
            "context/projects/quant-pipeline.md": [
                prune.TelemetryEvidenceHit(
                    start_line=10,
                    end_line=60,
                    signal_count=3,
                    last_seen_at="2026-05-20T11:00:00Z",
                    signal_type="final_citation",
                    evidence_tier="medium",
                    span_kind="medium",
                    protects_from_prune=True,
                    follow_through="quoted",
                    tier_reason="final citation",
                    content_hash="hash-a",
                )
            ]
        }

        evidence = prune.item_evidence_for_span("context/projects/quant-pipeline.md", 1, 80, dream_hits, telemetry_hits)

        self.assertEqual(evidence.dream_strong_hits, 1)
        self.assertEqual(evidence.telemetry_strong_targeted, 1)
        self.assertEqual(evidence.strong_signal_count, 5)
        self.assertEqual(evidence.total_hits, 2)
        self.assertTrue(evidence.has_strong_targeted)
        self.assertEqual(evidence.evidence_class, "strong_targeted")

    def test_item_evidence_for_span_requires_protective_memory_get_and_ignores_context_edit_as_strong(self) -> None:
        telemetry_hits = {
            "context/projects/quant-pipeline.md": [
                prune.TelemetryEvidenceHit(
                    start_line=5,
                    end_line=8,
                    signal_count=2,
                    last_seen_at="2026-05-20T11:00:00Z",
                    signal_type="memory_get",
                    evidence_tier="strong",
                    span_kind="narrow",
                    protects_from_prune=False,
                    follow_through="inspected",
                    tier_reason="expired protective evidence",
                    content_hash=None,
                ),
                prune.TelemetryEvidenceHit(
                    start_line=9,
                    end_line=12,
                    signal_count=1,
                    last_seen_at="2026-05-20T11:01:00Z",
                    signal_type="context_edit",
                    evidence_tier="strong",
                    span_kind="narrow",
                    protects_from_prune=False,
                    follow_through="edited",
                    tier_reason="provenance only",
                    content_hash=None,
                ),
                prune.TelemetryEvidenceHit(
                    start_line=13,
                    end_line=15,
                    signal_count=4,
                    last_seen_at="2026-05-20T11:02:00Z",
                    signal_type="memory_get",
                    evidence_tier="strong",
                    span_kind="narrow",
                    protects_from_prune=True,
                    follow_through="quoted",
                    tier_reason="direct memory get",
                    content_hash="hash-b",
                ),
            ]
        }

        evidence = prune.item_evidence_for_span("context/projects/quant-pipeline.md", 1, 20, {}, telemetry_hits)

        self.assertEqual(evidence.telemetry_strong_targeted, 1)
        self.assertEqual(evidence.telemetry_unknown, 2)
        self.assertEqual(evidence.strong_signal_count, 4)
        self.assertEqual(evidence.total_hits, 3)
        self.assertTrue(evidence.has_strong_targeted)
        self.assertEqual(evidence.evidence_class, "strong_targeted")

    def test_item_evidence_for_span_classifies_medium_weak_broad_and_invalid(self) -> None:
        telemetry_hits = {
            "context/projects/quant-pipeline.md": [
                prune.TelemetryEvidenceHit(
                    start_line=5,
                    end_line=8,
                    signal_count=2,
                    last_seen_at=None,
                    signal_type="read",
                    evidence_tier="medium",
                    span_kind="narrow",
                    protects_from_prune=False,
                    follow_through="used_for_orientation",
                    tier_reason="targeted read",
                    content_hash=None,
                ),
                prune.TelemetryEvidenceHit(
                    start_line=9,
                    end_line=120,
                    signal_count=3,
                    last_seen_at=None,
                    signal_type="read",
                    evidence_tier="medium",
                    span_kind="broad",
                    protects_from_prune=False,
                    follow_through="broad read",
                    tier_reason="broad span",
                    content_hash=None,
                ),
                prune.TelemetryEvidenceHit(
                    start_line=121,
                    end_line=122,
                    signal_count=1,
                    last_seen_at=None,
                    signal_type="memory_search_hit",
                    evidence_tier="weak",
                    span_kind="narrow",
                    protects_from_prune=False,
                    follow_through="search only",
                    tier_reason="raw search hit",
                    content_hash=None,
                ),
                prune.TelemetryEvidenceHit(
                    start_line=123,
                    end_line=124,
                    signal_count=1,
                    last_seen_at=None,
                    signal_type="unknown",
                    evidence_tier="invalid",
                    span_kind="narrow",
                    protects_from_prune=False,
                    follow_through="invalid",
                    tier_reason="bad source",
                    content_hash=None,
                ),
            ]
        }

        evidence = prune.item_evidence_for_span("context/projects/quant-pipeline.md", 1, 200, {}, telemetry_hits)

        self.assertEqual(evidence.telemetry_medium_targeted, 1)
        self.assertEqual(evidence.telemetry_broad_read_only, 1)
        self.assertEqual(evidence.telemetry_weak_only, 1)
        self.assertEqual(evidence.telemetry_invalid, 1)
        self.assertEqual(evidence.medium_signal_count, 2)
        self.assertEqual(evidence.weak_signal_count, 4)
        self.assertEqual(evidence.total_hits, 4)
        self.assertFalse(evidence.has_strong_targeted)
        self.assertTrue(evidence.has_medium_without_strong)
        self.assertEqual(evidence.evidence_class, "medium_targeted")

    def test_item_evidence_for_span_recovers_stale_span_by_content_hash(self) -> None:
        rel_path = "context/projects/quant-pipeline.md"
        content_hash = "hash-current-item"
        telemetry_hits = {
            rel_path: [
                prune.TelemetryEvidenceHit(
                    start_line=100,
                    end_line=120,
                    signal_count=3,
                    last_seen_at="2026-05-20T11:00:00Z",
                    signal_type="final_citation",
                    evidence_tier="strong",
                    span_kind="narrow",
                    protects_from_prune=True,
                    follow_through="quoted",
                    tier_reason="final citation",
                    content_hash=content_hash,
                    entry_key="stale-hit",
                )
            ]
        }
        index = prune.build_telemetry_evidence_indexes(telemetry_hits)
        stats = prune.empty_context_telemetry_match_stats()

        evidence = prune.item_evidence_for_span(
            rel_path,
            1,
            20,
            {},
            telemetry_hits,
            item_content_hash=content_hash,
            telemetry_index=index,
            match_stats=stats,
        )

        self.assertEqual(evidence.telemetry_match_source, "content_hash")
        self.assertEqual(evidence.content_hash_recovered_hits, 1)
        self.assertEqual(evidence.content_hash_recovered_strong_hits, 1)
        self.assertEqual(evidence.telemetry_strong_targeted, 1)
        self.assertEqual(evidence.strong_signal_count, 3)
        self.assertEqual(evidence.total_hits, 1)
        self.assertEqual(stats["content_hash_recovered_hits"], 1)
        self.assertEqual(stats["telemetry_item_match_source_counts"], {"content_hash": 1})

    def test_item_evidence_for_span_blocks_ambiguous_content_hash_fallback(self) -> None:
        rel_path = "context/projects/quant-pipeline.md"
        content_hash = "hash-duplicated-item"
        telemetry_hits = {
            rel_path: [
                prune.TelemetryEvidenceHit(
                    start_line=100,
                    end_line=120,
                    signal_count=3,
                    last_seen_at="2026-05-20T11:00:00Z",
                    signal_type="final_citation",
                    evidence_tier="strong",
                    span_kind="narrow",
                    protects_from_prune=True,
                    follow_through="quoted",
                    tier_reason="final citation",
                    content_hash=content_hash,
                    entry_key="ambiguous-hit",
                )
            ]
        }
        index = prune.build_telemetry_evidence_indexes(telemetry_hits)
        stats = prune.empty_context_telemetry_match_stats()

        evidence = prune.item_evidence_for_span(
            rel_path,
            1,
            20,
            {},
            telemetry_hits,
            item_content_hash=content_hash,
            telemetry_index=index,
            ambiguous_content_hashes={(rel_path, content_hash)},
            match_stats=stats,
        )

        self.assertEqual(evidence.telemetry_match_source, "ambiguous_content_hash")
        self.assertEqual(evidence.ambiguous_content_hash_hits, 1)
        self.assertEqual(evidence.content_hash_recovered_hits, 0)
        self.assertEqual(evidence.telemetry_strong_targeted, 0)
        self.assertEqual(evidence.total_hits, 0)
        self.assertEqual(stats["ambiguous_content_hash_matches"], 1)
        self.assertEqual(stats["telemetry_item_match_source_counts"], {"ambiguous_content_hash": 1})

    def test_item_evidence_for_span_marks_weak_or_broad_only_class(self) -> None:
        telemetry_hits = {
            "context/projects/quant-pipeline.md": [
                prune.TelemetryEvidenceHit(
                    start_line=5,
                    end_line=120,
                    signal_count=3,
                    last_seen_at=None,
                    signal_type="read",
                    evidence_tier="weak",
                    span_kind="broad",
                    protects_from_prune=False,
                    follow_through="broad read",
                    tier_reason="broad span",
                    content_hash=None,
                )
            ]
        }

        evidence = prune.item_evidence_for_span("context/projects/quant-pipeline.md", 1, 200, {}, telemetry_hits)

        self.assertEqual(evidence.telemetry_broad_read_only, 1)
        self.assertTrue(evidence.has_only_weak_or_broad)
        self.assertEqual(evidence.evidence_class, "weak_or_broad_only")

    def test_build_items_populates_strong_evidence_and_keeps_current_targeted_item(self) -> None:
        heading = "2026-04-01 Used implementation diary"
        body = "- old implementation detail with current targeted use\n" * 80
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 3,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.classification, "keep")
        self.assertEqual(item.reason, "recalled:1/3")
        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.strong_evidence_hits, 1)
        self.assertEqual(item.medium_evidence_hits, 0)
        self.assertEqual(item.weak_broad_evidence_hits, 0)

    def test_build_items_recovers_telemetry_after_line_shift_by_content_hash(self) -> None:
        heading = "2026-04-01 Shifted implementation diary"
        body = "- old implementation detail with shifted but hashed targeted use\n" * 80
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 3,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
                "contentHash": seed.text_hash,
                "contentHashSource": "current_context_span:v1",
            }
        )
        shifted_text = ("\n" * (seed.end_line + 5)) + text

        items, state = self.build(shifted_text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)
        report = prune.build_report(items, state, self.config(), run_bucket=RUN_BUCKET)

        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.telemetry_match_source, "content_hash")
        self.assertEqual(item.content_hash_recovered_hits, 1)
        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.strong_evidence_hits, 1)
        self.assertEqual(prune.LAST_CONTEXT_TELEMETRY_MATCH_STATS["content_hash_recovered_hits"], 1)
        self.assertIn("'content_hash': 1", report)
        self.assertIn("context telemetry content-hash recovered hits: 1", report)

    def test_telemetry_content_hash_recovers_line_shifted_match(self) -> None:
        heading = "2026-04-01 Line-shifted content-hash match"
        body = "- current text whose telemetry span can move safely\n" * 40
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 2,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
                "contentHash": seed.text_hash,
                "contentHashSource": "current_context_span:v1",
            }
        )

        shifted_items, state = self.build(("\n" * (seed.end_line + 5)) + text, self.state_for([seed.key]))
        shifted = self.find_item(shifted_items, "section", heading)
        report = prune.build_report(shifted_items, state, self.config(), run_bucket=RUN_BUCKET)

        self.assertEqual(shifted.telemetry_match_source, "content_hash")
        self.assertEqual(shifted.content_hash_recovered_hits, 1)
        self.assertEqual(shifted.evidence_class, "strong_targeted")
        self.assertIn("context telemetry content-hash recovered hits: 1", report)

    def test_ambiguous_content_hash_does_not_merge_state(self) -> None:
        bullet_text = "- Duplicate current point with ambiguous fingerprint"
        _old_key, _old_exact, _old_prefix, fingerprint_aliases = prune.item_keys(
            Path("context/projects/quant-pipeline.md"),
            "bullet",
            "2026-04-01",
            3,
            bullet_text,
        )
        state = {
            "version": 3,
            "identityMode": "content-primary",
            "fingerprints": {fingerprint_aliases[0]: ["old-a", "old-b"]},
            "items": {
                "old-a": {"firstSeenAt": OLD, "seenRuns": 5, "recallRuns": 1, "unrecalledRuns": 0, "maxCharCount": 900},
                "old-b": {"firstSeenAt": OLD, "seenRuns": 4, "recallRuns": 0, "unrecalledRuns": 4, "maxCharCount": 800},
            },
        }

        items, state = self.build(f"## 2026-04-01\n\n{bullet_text}\n", state)
        bullet = self.find_item(items, "bullet", "2026-04-01")

        self.assertEqual(bullet.seen_runs, 1)
        self.assertNotIn("migratedFrom", state["items"].get(bullet.key, {}))
        self.assertEqual(state["warningCounters"]["fingerprint_ambiguous"], 1)

    def test_stale_strong_evidence_does_not_create_indefinite_high_recall_immunity(self) -> None:
        heading = "2026-04-01 Previously used implementation diary"
        body = "- old implementation detail whose targeted citation is now stale\n" * 80
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 5,
                "lastSeenAt": "2026-04-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
            }
        )
        state = self.state_for([seed.key])
        state["items"][seed.key]["recallRuns"] = 4

        items, _ = self.build(text, state)
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.strong_evidence_hits, 1)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertNotEqual(item.reason, "high-recall-protected")

    def test_medium_evidence_blocks_hard_historical_prune(self) -> None:
        heading = "2026-04-01 Medium evidence implementation diary"
        body = "- old implementation detail with targeted but non-final evidence\n" * 80
        text = f"# Workbench Context\n\n## {heading}\n\n{body}"
        self.workbench_context_path.write_text(text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/workbench-context.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 2,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "medium",
                "spanKind": "narrow",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build_all(self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "medium_targeted")
        self.assertEqual(item.medium_evidence_hits, 1)
        self.assertEqual(item.classification, "review")
        self.assertEqual(item.reason, "medium-evidence-blocks-hard-prune")

    def test_medium_evidence_does_not_demote_project_spine_pressure_compression_candidate(self) -> None:
        heading = "2026-04-01 Pressure implementation diary"
        body = "- pressure detail with targeted medium evidence\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 2,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "medium",
                "spanKind": "narrow",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "medium_targeted")
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "project-spine-pressure-volatile-section-compress")
        apply_plan = prune.build_apply_plan(items)
        self.assertEqual(apply_plan["range_records"][0]["reason"], "project-spine-pressure-volatile-section-compress")
        self.assertEqual(apply_plan["range_records"][0]["evidence_class"], "medium_targeted")

    def test_weak_broad_evidence_does_not_demote_project_spine_pressure_compression_candidate(self) -> None:
        heading = "2026-04-01 Weak broad pressure implementation diary"
        body = "- pressure detail seen only through weak or broad evidence\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "weak_or_broad_only")
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "project-spine-pressure-volatile-section-compress")
        apply_plan = prune.build_apply_plan(items)
        self.assertEqual(apply_plan["range_records"][0]["reason"], "project-spine-pressure-volatile-section-compress")
        self.assertEqual(apply_plan["range_records"][0]["evidence_class"], "weak_or_broad_only")

    def test_medium_evidence_project_spine_pressure_candidate_still_compresses(self) -> None:
        heading = "2026-04-01 Medium evidence quant pressure diary"
        body = "- medium-evidence pressure detail still eligible for compression\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 2,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "medium",
                "spanKind": "narrow",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)
        apply_plan = prune.build_apply_plan(items)

        self.assertEqual(item.evidence_class, "medium_targeted")
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "project-spine-pressure-volatile-section-compress")
        self.assertEqual(apply_plan["range_records"][0]["evidence_class"], "medium_targeted")
        self.assertEqual(apply_plan["range_records"][0]["reason"], "project-spine-pressure-volatile-section-compress")

    def test_weak_broad_project_spine_pressure_candidate_still_compresses(self) -> None:
        heading = "2026-04-01 Weak broad quant pressure diary"
        body = "- weak broad pressure detail still eligible for compression\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "search",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)
        apply_plan = prune.build_apply_plan(items)

        self.assertEqual(item.evidence_class, "weak_or_broad_only")
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "project-spine-pressure-volatile-section-compress")
        self.assertEqual(apply_plan["range_records"][0]["evidence_class"], "weak_or_broad_only")
        self.assertEqual(apply_plan["range_records"][0]["reason"], "project-spine-pressure-volatile-section-compress")

    def test_strong_evidence_project_spine_pressure_candidate_is_kept(self) -> None:
        heading = "2026-04-01 Strong targeted quant pressure diary"
        body = "- strong targeted current pressure detail must stay intact\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 5,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "followThrough": "quoted_in_answer",
                "tierReason": "direct final citation",
                "protectsFromPrune": True,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)
        apply_plan = prune.build_apply_plan(items)

        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.classification, "keep")
        self.assertEqual(item.reason, "recalled:1/5")
        self.assertEqual(apply_plan["summary"]["quant_pipeline_apply_range_count"], 0)
        self.assertEqual(apply_plan["ranges_by_path"].get("context/projects/quant-pipeline.md", []), [])

    def test_weak_broad_evidence_does_not_reset_prune_gates(self) -> None:
        heading = "2026-04-01 Weak evidence implementation diary"
        body = "- old implementation detail seen only through broad search/read evidence\n" * 80
        text = f"# Workbench Context\n\n## {heading}\n\n{body}"
        self.workbench_context_path.write_text(text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/workbench-context.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build_all(self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "weak_or_broad_only")
        self.assertEqual(item.weak_broad_evidence_hits, 1)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "persistently-unused-historical")

    def test_strong_targeted_telemetry_keeps_item_live(self) -> None:
        heading = "2026-04-01 Strong targeted telemetry diary"
        body = "- old implementation detail with current final-citation use\n" * 80
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 4,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
            }
        )

        items, _ = self.build(text, self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.strong_evidence_hits, 1)
        self.assertEqual(item.recall_hits, 1)
        self.assertEqual(item.recall_signal_count, 4)
        self.assertEqual(item.classification, "keep")
        self.assertEqual(item.reason, "recalled:1/4")
        self.assertNotIn("context/projects/quant-pipeline.md", prune.candidate_ranges(items))

    def test_context_edit_metadata_does_not_pin_stale_item_by_itself(self) -> None:
        heading = "2026-04-01 Context edit metadata diary"
        body = "- old implementation detail touched by context-edit provenance only\n" * 80
        text = f"# Workbench Context\n\n## {heading}\n\n{body}"
        self.workbench_context_path.write_text(text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/workbench-context.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 3,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "context_edit",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build_all(self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "invalid_or_unknown")
        self.assertEqual(item.strong_evidence_hits, 0)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "persistently-unused-historical")

    def test_raw_search_and_broad_read_are_nonprotective_for_review_gates(self) -> None:
        search_heading = "2026-04-01 Raw search telemetry diary"
        broad_heading = "2026-04-02 Broad read telemetry diary"
        body = "- old implementation detail with weak or broad-only evidence\n" * 80
        text = f"# Workbench Context\n\n## {search_heading}\n\n{body}\n## {broad_heading}\n\n{body}"
        self.workbench_context_path.write_text(text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        search_seed = self.find_item(seed_items, "section", search_heading)
        broad_seed = self.find_item(seed_items, "section", broad_heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/workbench-context.md",
                "startLine": search_seed.start_line,
                "endLine": search_seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "memory_search_hit",
                "evidenceTier": "weak",
                "spanKind": "narrow",
                "protectsFromPrune": False,
            },
            {
                "path": "context/projects/workbench-context.md",
                "startLine": broad_seed.start_line,
                "endLine": broad_seed.end_line,
                "signalCount": 2,
                "lastSeenAt": "2026-05-01T10:01:00Z",
                "signalType": "read",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            },
        )

        items, _ = self.build_all(self.state_for([search_seed.key, broad_seed.key]))
        search_item = self.find_item(items, "section", search_heading)
        broad_item = self.find_item(items, "section", broad_heading)

        for item in (search_item, broad_item):
            self.assertEqual(item.evidence_class, "weak_or_broad_only")
            self.assertEqual(item.recall_hits, 0)
            self.assertEqual(item.classification, "prune_candidate")
            self.assertEqual(item.reason, "persistently-unused-historical")
        self.assertEqual(search_item.weak_broad_evidence_hits, 1)
        self.assertEqual(broad_item.weak_broad_evidence_hits, 1)

    def test_missing_telemetry_preserves_old_behavior(self) -> None:
        heading = "2026-04-01 Missing telemetry diary"
        body = "- old implementation detail with no telemetry evidence\n" * 80
        text = f"# Workbench Context\n\n## {heading}\n\n{body}"
        self.workbench_context_path.write_text(text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)

        items, _ = self.build_all(self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)

        self.assertEqual(item.evidence_class, "none")
        self.assertEqual(item.strong_evidence_hits, 0)
        self.assertEqual(item.medium_evidence_hits, 0)
        self.assertEqual(item.weak_broad_evidence_hits, 0)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "persistently-unused-historical")

    def test_shadow_policy_does_not_feed_current_classifier(self) -> None:
        heading = "2026-04-01 Shadow isolation telemetry diary"
        body = "stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "search-result-shadow-isolation",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call-shadow-isolation",
                    "isError": False,
                    "details": {
                        "results": [
                            {
                                "path": "context/projects/quant-pipeline.md",
                                "startLine": seed.start_line,
                                "endLine": seed.end_line,
                                "score": 0.8,
                            }
                        ]
                    },
                },
            }
        )
        shadow_state = self.mature_state_for_items([seed])
        items, state = self.build(text, json.loads(json.dumps(shadow_state)))
        item = self.find_item(items, "section", heading)
        classifications_before = {current.key: current.classification for current in items}
        ranges_before = prune.candidate_ranges(items)

        updated = prune.update_state(json.loads(json.dumps(state)), items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        report = prune.build_report(items, updated, self.config(), shadow_state=shadow_state, run_bucket=RUN_BUCKET)

        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual({current.key: current.classification for current in items}, classifications_before)
        self.assertEqual(prune.candidate_ranges(items), ranges_before)
        self.assertIn("proposed `review`/shadow:weak-only-review-before-prune", report)

    def test_build_items_maps_context_telemetry_to_recall_metrics(self) -> None:
        recalled_heading = "2026-04-01 Used implementation diary"
        unrecalled_heading = "2026-04-02 Unused implementation diary"
        recalled_body = "- old implementation detail with actual context usage\n" * 80
        unrecalled_body = "- old implementation detail without context usage\n" * 80
        text = f"# Quant Pipeline\n\n## {recalled_heading}\n\n{recalled_body}\n## {unrecalled_heading}\n\n{unrecalled_body}"
        recalled_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(recalled_heading)}"
        unrecalled_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(unrecalled_heading)}"
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "overlap": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 3,
                            "endLine": 20,
                            "signalCount": 3,
                            "lastSeenAt": "2026-05-20T10:00:00Z",
                            "protectsFromPrune": True,
                        },
                        "non-overlap": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 500,
                            "endLine": 510,
                            "signalCount": 99,
                            "lastSeenAt": "2026-05-20T10:01:00Z",
                            "protectsFromPrune": True,
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        items, _ = self.build(text, self.state_for([recalled_key, unrecalled_key]))

        recalled = self.find_item(items, "section", recalled_heading)
        self.assertEqual(recalled.recall_hits, 1)
        self.assertEqual(recalled.recall_signal_count, 3)
        self.assertEqual(recalled.last_recalled_at, "2026-05-20T10:00:00Z")
        self.assertEqual(recalled.classification, "keep")
        self.assertEqual(recalled.reason, "recalled:1/3")
        self.assertEqual(recalled.unrecalled_runs, 0)

        unrecalled = self.find_item(items, "section", unrecalled_heading)
        self.assertEqual(unrecalled.recall_hits, 0)
        self.assertEqual(unrecalled.recall_signal_count, 0)
        self.assertEqual(unrecalled.last_recalled_at, None)
        self.assertEqual(unrecalled.classification, "prune_candidate")
        self.assertEqual(prune.LAST_RECALL_LOAD_STATS["context_telemetry_entries_loaded"], 2)
        self.assertEqual(prune.LAST_RECALL_LOAD_STATS["warnings"], [])

    def test_materialized_search_and_memory_get_affect_only_overlapping_sections(self) -> None:
        search_heading = "2026-04-01 Search telemetry diary"
        memory_get_heading = "2026-04-02 Memory get telemetry diary"
        miss_heading = "2026-04-03 Unused telemetry diary"
        body = "- stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = (
            f"# Quant Pipeline\n\n## {search_heading}\n\n{body}\n"
            f"## {memory_get_heading}\n\n{body}\n"
            f"## {miss_heading}\n\n{body}"
        )
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        search_seed = self.find_item(seed_items, "section", search_heading)
        memory_get_seed = self.find_item(seed_items, "section", memory_get_heading)
        miss_seed = self.find_item(seed_items, "section", miss_heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call",
                    "isError": False,
                    "details": {
                        "results": [
                            {
                                "path": "context/projects/quant-pipeline.md",
                                "startLine": search_seed.start_line,
                                "endLine": search_seed.end_line,
                                "score": 0.8,
                            }
                        ]
                    },
                },
            },
            {
                "type": "message",
                "id": "assistant-memory-get",
                "timestamp": "2026-05-20T10:01:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "memory-get-call",
                            "name": "memory_get",
                            "arguments": {
                                "path": "context/projects/quant-pipeline.md",
                                "from": memory_get_seed.start_line,
                                "lines": memory_get_seed.end_line - memory_get_seed.start_line + 1,
                            },
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "memory-get-result",
                "timestamp": "2026-05-20T10:01:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_get",
                    "toolCallId": "memory-get-call",
                    "isError": False,
                    "details": {
                        "path": "context/projects/quant-pipeline.md",
                        "from": memory_get_seed.start_line,
                        "lines": memory_get_seed.end_line - memory_get_seed.start_line + 1,
                        "text": "raw excerpt should not persist",
                    },
                },
            },
        )

        items, _ = self.build(text, self.mature_state_for_items([search_seed, memory_get_seed, miss_seed]))

        search_item = self.find_item(items, "section", search_heading)
        self.assertEqual(search_item.recall_hits, 0)
        self.assertEqual(search_item.recall_signal_count, 0)
        self.assertEqual(search_item.classification, "prune_candidate")
        memory_get_item = self.find_item(items, "section", memory_get_heading)
        self.assertEqual(memory_get_item.recall_hits, 1)
        self.assertEqual(memory_get_item.recall_signal_count, 2)
        self.assertEqual(memory_get_item.classification, "keep")
        self.assertEqual(memory_get_item.reason, "recalled:1/2")
        miss_item = self.find_item(items, "section", miss_heading)
        self.assertEqual(miss_item.recall_hits, 0)
        self.assertEqual(miss_item.recall_signal_count, 0)
        self.assertEqual(miss_item.classification, "prune_candidate")

    def test_shadow_report_flags_weak_search_only_as_nonprotective(self) -> None:
        heading = "2026-04-01 Search-only telemetry diary"
        body = "stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "search-result",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "memory_search",
                    "toolCallId": "search-call",
                    "isError": False,
                    "details": {
                        "results": [
                            {
                                "path": "context/projects/quant-pipeline.md",
                                "startLine": seed.start_line,
                                "endLine": seed.end_line,
                                "score": 0.8,
                            }
                        ]
                    },
                },
            }
        )
        shadow_state = self.mature_state_for_items([seed])
        items, state = self.build(text, json.loads(json.dumps(shadow_state)))
        item = self.find_item(items, "section", heading)
        self.assertEqual(item.classification, "prune_candidate")
        classifications_before = {current.key: current.classification for current in items}
        ranges_before = prune.candidate_ranges(items)
        self.assertIn((item.start_line, item.end_line, item.kind), ranges_before.get("context/projects/quant-pipeline.md", []))

        updated = prune.update_state(json.loads(json.dumps(state)), items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        report = prune.build_report(items, updated, self.config(), shadow_state=shadow_state, run_bucket=RUN_BUCKET)

        self.assertEqual({current.key: current.classification for current in items}, classifications_before)
        self.assertEqual(prune.candidate_ranges(items), ranges_before)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertIn("## Shadow policy / dry-run comparison", report)
        self.assertIn("weak-only currently protected items: 0", report)
        self.assertIn("proposed `review`/shadow:weak-only-review-before-prune", report)

    def test_materialized_final_citation_protects_only_cited_section(self) -> None:
        cited_heading = "2026-04-01 Cited telemetry diary"
        miss_heading = "2026-04-02 Uncited telemetry diary"
        body = "- stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = f"# Quant Pipeline\n\n## {cited_heading}\n\n{body}\n## {miss_heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        cited_seed = self.find_item(seed_items, "section", cited_heading)
        miss_seed = self.find_item(seed_items, "section", miss_heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "assistant-citation",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Grounded note. Source: context/projects/quant-pipeline.md#L{cited_seed.start_line}-L{cited_seed.end_line}",
                        }
                    ],
                },
            }
        )

        items, _ = self.build(text, self.mature_state_for_items([cited_seed, miss_seed]))

        cited = self.find_item(items, "section", cited_heading)
        self.assertEqual(cited.recall_signal_count, 3)
        self.assertEqual(cited.classification, "keep")
        self.assertEqual(cited.reason, "recalled:1/3")
        miss = self.find_item(items, "section", miss_heading)
        self.assertEqual(miss.recall_hits, 0)
        self.assertEqual(miss.classification, "prune_candidate")

    def test_materialized_read_offset_limit_maps_bounded_section_only(self) -> None:
        read_heading = "2026-04-01 Read telemetry diary"
        miss_heading = "2026-04-02 Unread telemetry diary"
        body = "- stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = f"# Quant Pipeline\n\n## {read_heading}\n\n{body}\n## {miss_heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        read_seed = self.find_item(seed_items, "section", read_heading)
        miss_seed = self.find_item(seed_items, "section", miss_heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "assistant-read",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "read-call",
                            "name": "read",
                            "arguments": {
                                "path": "context/projects/quant-pipeline.md",
                                "offset": read_seed.start_line,
                                "limit": read_seed.end_line - read_seed.start_line + 1,
                            },
                        }
                    ],
                },
            },
            {
                "type": "message",
                "id": "read-result",
                "timestamp": "2026-05-20T10:00:01Z",
                "message": {
                    "role": "toolResult",
                    "toolName": "read",
                    "toolCallId": "read-call",
                    "isError": False,
                    "content": [{"type": "text", "text": "read result raw text should not persist"}],
                },
            },
        )

        items, _ = self.build(text, self.mature_state_for_items([read_seed, miss_seed]))

        read_item = self.find_item(items, "section", read_heading)
        self.assertEqual(read_item.recall_signal_count, 0)
        self.assertEqual(read_item.classification, "prune_candidate")
        miss = self.find_item(items, "section", miss_heading)
        self.assertEqual(miss.recall_hits, 0)
        self.assertEqual(miss.classification, "prune_candidate")

    def test_materialized_ambiguous_edit_warns_without_whole_file_protection(self) -> None:
        first_heading = "2026-04-01 First ambiguous edit diary"
        second_heading = "2026-04-02 Second ambiguous edit diary"
        first_body = ("- duplicate edited line\n" * 40)
        second_body = ("- duplicate edited line\n" * 40)
        text = f"# Quant Pipeline\n\n## {first_heading}\n\n{first_body}\n## {second_heading}\n\n{second_body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        first_seed = self.find_item(seed_items, "section", first_heading)
        second_seed = self.find_item(seed_items, "section", second_heading)
        payload = self.materialize_telemetry(
            {
                "type": "message",
                "id": "assistant-edit",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "edit-call",
                            "name": "edit",
                            "arguments": {
                                "path": "context/projects/quant-pipeline.md",
                                "edits": [{"oldText": "old", "newText": "duplicate edited line\n"}],
                            },
                        }
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
                    "toolCallId": "edit-call",
                    "isError": False,
                },
            },
        )

        self.assertEqual(payload["summary"]["entry_count"], 0)
        self.assertEqual([warning["reason"] for warning in payload["warnings"]], ["ambiguous-edit-newtext-span"])
        items, _ = self.build(text, self.mature_state_for_items([first_seed, second_seed]))

        for heading in [first_heading, second_heading]:
            item = self.find_item(items, "section", heading)
            self.assertEqual(item.recall_hits, 0)
            self.assertEqual(item.recall_signal_count, 0)
            self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(prune.LAST_RECALL_LOAD_STATS["context_telemetry_source_warnings"], 1)
        self.assertEqual(prune.LAST_RECALL_LOAD_STATS["context_telemetry_entries_loaded"], 0)

    def test_repeated_materialized_telemetry_reaches_existing_high_usage_protection(self) -> None:
        heading = "2026-04-01 Repeated telemetry diary"
        body = "- repeatedly used implementation detail in scripts/context_usage_prune.py\n" * 40
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.materialize_telemetry(
            {
                "type": "message",
                "id": "assistant-citation",
                "timestamp": "2026-05-20T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Grounded note. Source: context/projects/quant-pipeline.md#L{seed.start_line}-L{seed.end_line}",
                        }
                    ],
                },
            }
        )
        state = self.state_for([seed.key])
        for bucket in ["2026-05-01", "2026-05-02", "2026-05-03"]:
            items = prune.build_items(NOW, state, self.config(), bucket)
            item = self.find_item(items, "section", heading)
            self.assertTrue(item.reason.startswith("recalled:"))
            state = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), bucket)

        prune.CONTEXT_TELEMETRY_PATH.unlink()
        items = prune.build_items(NOW, state, self.config(), "2026-05-04")

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.recall_runs, prune.HIGH_USAGE_RECALL_RUNS)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "project-spine-pressure-volatile-section-compress")

    def test_missing_or_invalid_context_telemetry_preserves_old_pruning_behavior(self) -> None:
        heading = "2026-04-01 Missing invalid telemetry diary"
        body = "- stale implementation detail with enough words for pruning gates in scripts/context_usage_prune.py\n" * 35
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)

        missing_items, _ = self.build(text, self.mature_state_for_items([seed]))
        missing = self.find_item(missing_items, "section", heading)
        self.assertEqual(missing.recall_hits, 0)
        self.assertEqual(missing.classification, "prune_candidate")
        self.assertEqual(prune.LAST_RECALL_LOAD_STATS["warnings"], [])

        prune.CONTEXT_TELEMETRY_PATH.write_text("{not valid json", encoding="utf-8")
        invalid_items, _ = self.build(text, self.mature_state_for_items([seed]))
        invalid = self.find_item(invalid_items, "section", heading)
        self.assertEqual(invalid.recall_hits, 0)
        self.assertEqual(invalid.classification, "prune_candidate")
        warnings = prune.LAST_RECALL_LOAD_STATS["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["kind"], "context_telemetry")
        self.assertTrue(warnings[0]["reason"].startswith("invalid-telemetry:JSONDecodeError"))

    def test_stable_project_spine_anchor_sections_never_prune(self) -> None:
        stable_headings = [
            "Role",
            "Default folder / routing",
            "Stable orientation",
            "Objective function",
            "Scope / layer boundary",
            "Current architecture",
            "Active pipeline path",
            "Maturity / current posture",
            "Operational invariants",
        ]
        for heading in stable_headings:
            with self.subTest(heading=heading):
                huge_anchor = f"- {heading} stable anchor detail that must not become an apply range\n" * 1200
                text = f"# Quant Pipeline\n\n## {heading}\n\n{huge_anchor}\n\n## Current active implementation concerns\n\n- small live note\n"
                seed_items, _ = self.build(text, {"version": 2, "items": {}})
                state = self.state_for([item.key for item in seed_items])
                items, _ = self.build(text, state)

                anchor = self.find_item(items, "section", heading)
                self.assertTrue(prune.is_project_spine_stable_heading(heading))
                self.assertEqual(anchor.classification, "keep")
                self.assertTrue(anchor.pinned)
                self.assertEqual(anchor.reason, "pinned")
                self.assertFalse(any(item.classification == "prune_candidate" and item.section_heading == heading for item in items))
                self.assertFalse(prune.candidate_ranges(items))
                self.assertEqual(prune.build_apply_plan(items)["summary"]["range_count_total"], 0)

        self.assertTrue(prune.is_project_spine_volatile_heading("Current active implementation concerns"))
        self.assertFalse(prune.is_project_spine_stable_heading("Current active implementation concerns"))
        self.assertFalse(prune.is_project_spine_pinned_heading("Current active implementation concerns"))

    def test_current_active_implementation_concerns_remains_volatile(self) -> None:
        heading = "Current active implementation concerns"
        huge_bullet = "- mature volatile implementation detail " + ("extra detail " * 1200) + "\n"
        filler = "- soft-pressure filler\n" * 900
        text = f"# Quant Pipeline\n\n## Role\n\n- stable role anchor\n\n## {heading}\n\n{huge_bullet}{filler}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        bullet = max((item for item in seed_items if item.kind == "bullet" and item.section_heading == heading), key=lambda item: item.char_count)
        items, _ = self.build(text, self.state_for([bullet.key]))

        volatile = self.find_item(items, "section", heading)
        candidates = [item for item in self.find_items(items, "bullet", heading) if item.classification == "prune_candidate"]
        self.assertFalse(volatile.pinned)
        self.assertTrue(prune.is_project_spine_volatile_heading(heading))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].reason, "project-spine-pressure-volatile-bullet-compress")
        self.assertEqual(prune.candidate_ranges(items)["context/projects/quant-pipeline.md"][0][2], "bullet")

    def test_apply_plan_reports_quant_pipeline_byte_range_acceptance_fields(self) -> None:
        heading = "2026-04-01 Old quant-spine implementation diary"
        body = "- stale quant-spine detail selected for compression\n" * 80
        text = f"# Quant Pipeline\n\n## Role\n\n- stable role anchor\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section = self.find_item(seed_items, "section", heading)
        items, _ = self.build(text, self.state_for([section.key]))

        plan = prune.build_apply_plan(items)
        summary = plan["summary"]

        self.assertEqual(summary["quant_pipeline_apply_range_count"], 1)
        self.assertEqual(summary["quant_pipeline_prune_candidate_count"], 1)
        self.assertEqual(summary["quant_pipeline_stable_anchor_range_count"], 0)
        self.assertGreater(summary["quant_pipeline_source_bytes_before"], 0)
        self.assertLess(summary["quant_pipeline_source_bytes_after_planned"], summary["quant_pipeline_source_bytes_before"])
        self.assertLess(summary["quant_pipeline_source_bytes_delta_planned"], 0)
        self.assertEqual(summary["unsafe_apply_range_count"], 0)

    def test_apply_acceptance_blocks_decisions_and_outside_allowed_ranges(self) -> None:
        fake_plan = {
            "ranges_by_path": {},
            "range_records": [
                {
                    "path": "context/decisions.md",
                    "kind": "section",
                    "start_line": 1,
                    "end_line": 3,
                    "section_heading": "Decisions",
                    "reason": "synthetic",
                    "evidence_class": "none",
                },
                {
                    "path": "context/projects/not-allowed.md",
                    "kind": "section",
                    "start_line": 1,
                    "end_line": 2,
                    "section_heading": "Other",
                    "reason": "synthetic",
                    "evidence_class": "none",
                },
            ],
        }

        acceptance = prune.apply_acceptance_summary([], fake_plan)
        reasons = {reason for blocker in acceptance["hard_blockers"] for reason in blocker["blocker_reasons"]}

        self.assertTrue(acceptance["blocked"])
        self.assertEqual(acceptance["hard_blocker_count"], 2)
        self.assertIn("decisions_apply_range", reasons)
        self.assertIn("outside_apply_allowed", reasons)

    def test_decisions_file_remains_excluded_from_generic_prune_ranges(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## 2026-04-01 Old durable decisions\n\n"
            + "".join(f"- 2026-04-01 stale-looking durable decision detail {idx} must remain protected.\n" for idx in range(220))
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        decisions_keys = [item.key for item in seed_items if item.path == "context/decisions.md"]

        items, _ = self.build_all(self.state_for(decisions_keys))
        decisions_items = [item for item in items if item.path == "context/decisions.md"]
        plan = prune.build_apply_plan(items)

        self.assertTrue(decisions_items)
        self.assertTrue(all(item.pinned for item in decisions_items))
        self.assertTrue(all(item.classification == "keep" for item in decisions_items))
        self.assertTrue(all(item.reason == "pinned" for item in decisions_items))
        self.assertNotIn("context/decisions.md", plan["ranges_by_path"])
        self.assertFalse(any(record["path"] == "context/decisions.md" for record in plan["range_records"]))

    def test_apply_blocks_stable_anchor_range_even_if_misclassified(self) -> None:
        text = "# Quant Pipeline\n\n## Role\n\n" + ("- stable anchor detail that must not be removed\n" * 40)
        items, _ = self.build(text, {"version": 2, "items": {}})
        role = self.find_item(items, "section", "Role")
        role.classification = "prune_candidate"
        role.reason = "synthetic-misclassification"
        stamp = "unit-test-stable-anchor-block"

        with self.assertRaisesRegex(RuntimeError, "apply_blocked"):
            prune.apply_pruning(items, stamp, self.deterministic_local_config())

        self.assertEqual(self.project_path.read_text(), text)
        manifest = json.loads((prune.ARCHIVE_ROOT / stamp / "pre-apply-manifest.json").read_text())
        self.assertTrue(manifest["apply_blocked"])
        self.assertEqual(manifest["candidate_summary"]["quant_pipeline_stable_anchor_range_count"], 1)
        self.assertIn("stable_project_spine_anchor_range", manifest["apply_acceptance"]["hard_blockers"][0]["blocker_reasons"])

    def test_large_shrink_ratio_dry_run_reports_override_required(self) -> None:
        heading = "2026-04-01 Huge quant-spine diary"
        body = "- old quant-spine detail that would shrink too much in one apply pass\n" * 2500
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section = self.find_item(seed_items, "section", heading)
        items, _ = self.build(text, self.state_for([section.key]))

        manifest = prune.apply_pruning(items, "unit-test-large-shrink-dry-run", self.deterministic_local_config(), dry_run=True)

        self.assertEqual(self.project_path.read_text(), text)
        self.assertTrue(manifest["apply_blocked"])
        self.assertTrue(manifest["large_shrink_requires_override"])
        self.assertEqual(manifest["no_op_reason"], "large_shrink_requires_override")
        self.assertEqual(manifest["apply_acceptance"]["large_shrink_file_count"], 1)
        self.assertEqual(manifest["apply_acceptance"]["large_shrink_files"][0]["path"], "context/projects/quant-pipeline.md")

    def test_large_shrink_ratio_blocks_mutating_apply_without_override(self) -> None:
        heading = "2026-04-01 Huge quant-spine mutating diary"
        body = "- old quant-spine detail that would shrink too much in one mutating apply\n" * 2500
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section = self.find_item(seed_items, "section", heading)
        items, _ = self.build(text, self.state_for([section.key]))
        stamp = "unit-test-large-shrink-mutating"

        with self.assertRaisesRegex(RuntimeError, "apply_blocked"):
            prune.apply_pruning(items, stamp, self.deterministic_local_config())

        self.assertEqual(self.project_path.read_text(), text)
        manifest = json.loads((prune.ARCHIVE_ROOT / stamp / "pre-apply-manifest.json").read_text())
        self.assertTrue(manifest["large_shrink_requires_override"])
        self.assertFalse(Path(manifest["files"][0]["archive"]).exists())

    def test_large_shrink_ratio_override_allows_mutating_apply(self) -> None:
        heading = "2026-04-01 Huge quant-spine override diary"
        body = "- old quant-spine detail allowed through explicit large-shrink override\n" * 2500
        text = f"# Quant Pipeline\n\n## {heading}\n\n{body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section = self.find_item(seed_items, "section", heading)
        items, _ = self.build(text, self.state_for([section.key]))

        manifest = prune.apply_pruning(
            items,
            "unit-test-large-shrink-override",
            self.deterministic_local_config(),
            allow_large_shrink=True,
        )

        self.assertFalse(manifest["apply_blocked"])
        self.assertFalse(manifest["large_shrink_requires_override"])
        self.assertIn("Compressed archived detail", self.project_path.read_text())
        self.assertTrue(Path(manifest["files"][0]["archive"]).exists())

    def test_apply_cli_accepts_large_shrink_flags(self) -> None:
        args = prune.build_parser().parse_args(["apply", "--stamp", "unit", "--max-file-shrink-ratio", "0.2", "--allow-large-shrink"])

        self.assertEqual(args.max_file_shrink_ratio, 0.2)
        self.assertTrue(args.allow_large_shrink)

    def test_project_spine_budget_pressure_escalates_old_dated_sections_until_target(self) -> None:
        dated_heading = "2026-03-01 Old budget closure diary"
        role_body = "- stable role detail retained as anchor\n" * 2400
        dated_body = "- old quant implementation detail eligible for budget closure\n" * 700
        text = f"# Quant Pipeline\n\n## Role\n\n{role_body}\n\n## {dated_heading}\n\n{dated_body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        dated_seed = self.find_item(seed_items, "section", dated_heading)
        state = self.state_for([dated_seed.key])
        config = self.config()
        config.min_seen_runs_review = 99
        config.min_seen_runs_prune = 99
        config.min_unrecalled_runs_review = 99
        config.min_unrecalled_runs_prune = 99

        items = prune.build_items(NOW, state, config, RUN_BUCKET)
        dated = self.find_item(items, "section", dated_heading)
        plan = prune.build_apply_plan(items)
        budget = prune.build_hot_context_budget_summary(items)
        report = prune.build_report(items, {"version": 2, "items": {}}, config, budget_summary=budget)

        self.assertEqual(dated.classification, "prune_candidate")
        self.assertEqual(dated.reason, "project-spine-budget-pressure-dated-section-30d")
        self.assertLessEqual(plan["summary"]["project_spine_budget_projected_after_bytes"], prune.project_spine_budget_target_bytes())
        self.assertEqual(plan["summary"]["project_spine_budget_deficit_after_planning"], 0)
        self.assertEqual(plan["summary"]["project_spine_budget_escalated_candidate_count"], 1)
        self.assertIn("### Project-spine budget closure", report)
        self.assertIn("escalatedCandidates=1", report)

    def test_project_spine_budget_pressure_reports_deficit_when_strong_evidence_blocks_target(self) -> None:
        strong_heading = "2026-03-01 Strong evidence budget blocker"
        role_body = "- stable anchor detail that cannot be selected\n" * 1700
        strong_body = "- strong targeted current signal detail that must stay intact\n" * 900
        text = f"# Quant Pipeline\n\n## Role\n\n{role_body}\n\n## {strong_heading}\n\n{strong_body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        strong_seed = self.find_item(seed_items, "section", strong_heading)
        self.write_telemetry_entries(
            {
                "path": "context/projects/quant-pipeline.md",
                "startLine": strong_seed.start_line,
                "endLine": strong_seed.end_line,
                "signalCount": 5,
                "lastSeenAt": "2026-05-01T11:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "followThrough": "quoted_in_answer",
                "tierReason": "direct final citation",
                "protectsFromPrune": True,
            }
        )
        items, _ = self.build(text, self.state_for([item.key for item in seed_items]))
        strong = self.find_item(items, "section", strong_heading)
        plan = prune.build_apply_plan(items)
        reasons = {blocker.get("reason") for blocker in plan["summary"]["project_spine_budget_blockers"]}
        routes = {blocker.get("route") for blocker in plan["summary"]["project_spine_budget_blockers"]}

        self.assertEqual(strong.classification, "keep")
        self.assertEqual(strong.evidence_class, "strong_targeted")
        self.assertGreater(plan["summary"]["project_spine_budget_deficit_after_planning"], 0)
        self.assertIn("strong_targeted_current_or_unresolved", reasons)
        self.assertIn("stable_project_spine_anchor", reasons)
        self.assertIn("defer_recent_content", routes)
        self.assertIn("autonomous_anchor_summary", routes)

    def test_project_spine_budget_pressure_never_selects_stable_anchor(self) -> None:
        role_body = "- stable anchor detail over budget but protected\n" * 2800
        text = f"# Quant Pipeline\n\n## Role\n\n{role_body}"
        items, _ = self.build(text, {"version": 2, "items": {}})
        role = self.find_item(items, "section", "Role")
        plan = prune.build_apply_plan(items)
        blockers = plan["summary"]["project_spine_budget_blockers"]

        self.assertTrue(role.pinned)
        self.assertEqual(role.classification, "keep")
        self.assertEqual(plan["summary"]["quant_pipeline_apply_range_count"], 0)
        self.assertGreater(plan["summary"]["project_spine_budget_deficit_after_planning"], 0)
        self.assertTrue(any(blocker.get("reason") == "stable_project_spine_anchor" for blocker in blockers))

    def test_dated_project_spine_section_prunes_under_hard_pressure(self) -> None:
        dated_heading = "2026-04-01 Old implementation diary"
        dated_body = "- historical implementation detail that should archive cleanly\n" * 1200
        filler = "- current-state filler\n" * 2000
        text = f"# Quant Pipeline\n\n## Current active implementation concerns\n\n{filler}\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        dated = self.find_item(items, "section", dated_heading)
        self.assertEqual(dated.classification, "prune_candidate")
        self.assertEqual(dated.reason, "project-spine-pressure-volatile-section-compress")

    def test_dated_project_spine_section_prunes_below_hard_pressure_after_maturity(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- old implementation detail that is too bulky for the live spine\n" * 60
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        self.assertLess(len(text), prune.PROJECT_SPINE_SOFT_TARGET_CHARS)
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        dated = self.find_item(items, "section", dated_heading)
        self.assertGreaterEqual(dated.char_count, prune.PROJECT_SPINE_DATED_SECTION_CHARS)
        self.assertEqual(dated.classification, "prune_candidate")
        self.assertEqual(dated.reason, "project-spine-pressure-volatile-section-compress")

    def test_fresh_dated_project_spine_section_is_reviewed_below_hard_pressure(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- old implementation detail that should be surfaced before prune maturity\n" * 60
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        items, _ = self.build(text, {"version": 2, "items": {}})

        dated = self.find_item(items, "section", dated_heading)
        self.assertEqual(dated.classification, "review")
        self.assertEqual(dated.reason, "project-spine-dated-section-pressure-review")

    def test_soft_target_prunes_mature_volatile_bullets_before_hard_pressure(self) -> None:
        heading = "Current active implementation concerns"
        huge_bullet = "- mature volatile implementation detail " + ("extra detail " * 1200) + "\n"
        filler = "- soft-pressure filler\n" * 900
        text = f"# Quant Pipeline\n\n## {heading}\n\n{huge_bullet}{filler}"
        self.assertGreaterEqual(len(text), prune.PROJECT_SPINE_SOFT_TARGET_CHARS)
        self.assertLess(len(text), prune.PROJECT_SPINE_HARD_PRESSURE_CHARS)
        bullet_key = f"bullet:context/projects/quant-pipeline.md:{prune.slugify(heading)}:{prune.bullet_anchor(huge_bullet)}"
        items, _ = self.build(text, self.state_for([bullet_key]))

        candidates = [item for item in self.find_items(items, "bullet", heading) if item.classification == "prune_candidate"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].reason, "project-spine-pressure-volatile-bullet-compress")

    def test_huge_volatile_bullet_prunes_despite_recent_text_hash(self) -> None:
        heading = "Current active implementation concerns"
        huge_bullet = "- 2026-04-20 detailed implementation diary " + ("extra detail " * 3000) + "\n"
        filler = "- current-state filler\n" * 2000
        text = f"# Quant Pipeline\n\n## {heading}\n\n{huge_bullet}{filler}"
        bullet_key = f"bullet:context/projects/quant-pipeline.md:{prune.slugify(heading)}:{prune.bullet_anchor(huge_bullet)}"
        items, _ = self.build(text, self.state_for([bullet_key]))

        section = self.find_item(items, "section", heading)
        self.assertEqual(section.classification, "review")
        self.assertEqual(section.reason, "project-spine-pressure-oversized-review")

        candidates = [item for item in items if item.kind == "bullet" and item.classification == "prune_candidate"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].reason, "project-spine-pressure-volatile-bullet-compress")

    def test_oversized_volatile_content_is_reviewed_before_prune_maturity(self) -> None:
        heading = "Current active implementation concerns"
        huge_bullet = "- Fresh but huge implementation details " + ("extra detail " * 3000) + "\n"
        filler = "- current-state filler\n" * 2000
        text = f"# Quant Pipeline\n\n## {heading}\n\n{huge_bullet}{filler}"
        items, _ = self.build(text, {"version": 2, "items": {}})

        review_items = [item for item in self.find_items(items, "bullet", heading) if item.reason == "project-spine-pressure-oversized-review"]
        self.assertEqual(len(review_items), 1)
        self.assertEqual(review_items[0].classification, "review")

    def test_known_gaps_section_is_review_only_not_wholesale_pruned(self) -> None:
        heading = "Known gaps / likely follow-ups"
        bulky_gap = "- high-level gap with too much embedded detail " + ("extra detail " * 500) + "\n"
        filler = "- current-state filler\n" * 2500
        text = f"# Quant Pipeline\n\n## Current active implementation concerns\n\n{filler}\n\n## {heading}\n\n{bulky_gap}"
        section_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(heading)}"
        bullet_key = f"bullet:context/projects/quant-pipeline.md:{prune.slugify(heading)}:{prune.bullet_anchor(bulky_gap)}"
        items, _ = self.build(text, self.state_for([section_key, bullet_key]))

        section = self.find_item(items, "section", heading)
        self.assertEqual(section.classification, "review")
        self.assertEqual(section.reason, "project-spine-pressure-volatile-section-review-only")

        candidates = [item for item in self.find_items(items, "bullet", heading) if item.classification == "prune_candidate"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].reason, "project-spine-pressure-volatile-bullet-compress")

    def test_existing_compressed_notes_are_trimmed_and_do_not_inherit_parent_section_age(self) -> None:
        heading = "Current active implementation concerns"
        long_note = "- Compressed archived detail (9999 chars; dates: 2026-04-30; refs: a.py, b.py, c.py): " + ("summary detail " * 40) + "\n"
        text = f"# Quant Pipeline\n\n## {heading}\n\n{long_note}"
        parent_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(heading)}"
        items, _ = self.build(text, self.state_for([parent_key]))

        note = self.find_item(items, "bullet", heading)
        self.assertEqual(note.classification, "prune_candidate")
        self.assertEqual(note.reason, "compressed-archive-note-trim")
        self.assertEqual(note.age_days, 0.0)

        manifest = prune.apply_pruning(items, "unit-test", self.deterministic_local_config())
        self.assertEqual(len(manifest["files"]), 1)
        trimmed = self.project_path.read_text()
        self.assertIn("Compressed archived detail", trimmed)
        self.assertLessEqual(len(trimmed.splitlines()[4]), prune.COMPRESSED_NOTE_MAX_CHARS + 2)

    def test_apply_archives_before_deleting_allowed_project_spine_blocks(self) -> None:
        dated_heading = "2026-04-01 Old implementation diary"
        dated_body = "- old line that must be archived before deletion\n" * 1200
        filler = "- current-state filler\n" * 2000
        text = f"# Quant Pipeline\n\n## Current active implementation concerns\n\n{filler}\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        manifest = prune.apply_pruning(items, "unit-test", self.deterministic_local_config(), allow_large_shrink=True)
        self.assertEqual(len(manifest["files"]), 1)
        compressed = self.project_path.read_text()
        self.assertIn(dated_heading, compressed)
        self.assertIn("Compressed archived detail", compressed)
        self.assertNotIn("old line that must be archived before deletion\n- old line", compressed)

        archive = Path(manifest["files"][0]["archive"])
        archived = json.loads(archive.read_text())
        self.assertEqual(archived["removed"][0]["kind"], "section")
        self.assertIn(dated_heading, archived["removed"][0]["text"])
        self.assertEqual(manifest["no_op_reason"], "none")
        self.assertIn("candidate_summary", manifest)
        self.assertLess(manifest["source_bytes_delta_planned_total"], 0)
        self.assertIn("source_lines_delta_planned", manifest["files"][0])

    def test_apply_manifest_reports_candidate_range_dedupe_and_bytes(self) -> None:
        dated_heading = "2026-04-01 Old implementation diary"
        dated_body = "- old implementation detail that must be compressed\n" + ("  continuation with scripts/context_usage_prune.py and enough stale detail\n" * 12)
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section_seed = self.find_item(seed_items, "section", dated_heading)
        bullet_seed = self.find_item(seed_items, "bullet", dated_heading)
        items, _ = self.build(text, self.state_for([section_seed.key, bullet_seed.key]))

        section = self.find_item(items, "section", dated_heading)
        bullet = self.find_item(items, "bullet", dated_heading)
        self.assertEqual(section.classification, "prune_candidate")
        self.assertEqual(bullet.classification, "prune_candidate")
        self.assertEqual(prune.candidate_ranges(items), {"context/projects/quant-pipeline.md": [(section.start_line, section.end_line, section.kind)]})

        manifest = prune.apply_pruning(items, "unit-test-apply-plan-dry-run", self.deterministic_local_config(), dry_run=True)

        self.assertEqual(self.project_path.read_text(), text)
        summary = manifest["candidate_summary"]
        self.assertEqual(summary["candidate_count_total"], 2)
        self.assertEqual(summary["allowlisted_candidate_count"], 2)
        self.assertEqual(summary["section_candidate_count"], 1)
        self.assertEqual(summary["bullet_candidate_count"], 1)
        self.assertEqual(summary["range_count_total"], 1)
        self.assertEqual(summary["nested_deduped_count"], 1)
        self.assertEqual(summary["empty_range_count"], 0)
        self.assertEqual(summary["per_path"]["context/projects/quant-pipeline.md"]["candidate_count"], 2)
        self.assertEqual(summary["per_path"]["context/projects/quant-pipeline.md"]["range_count"], 1)
        self.assertEqual(summary["per_path"]["context/projects/quant-pipeline.md"]["nested_deduped_count"], 1)
        self.assertEqual(manifest["no_op_reason"], "none")
        self.assertEqual(len(manifest["range_records"]), 1)
        self.assertEqual(manifest["range_records"][0]["path"], "context/projects/quant-pipeline.md")
        self.assertEqual(manifest["range_records"][0]["text_hash"], section.text_hash)
        self.assertEqual(len(manifest["files"]), 1)
        record = manifest["files"][0]
        self.assertEqual(record["source_bytes_delta_planned"], record["source_bytes_after_planned"] - record["source_bytes_before"])
        self.assertEqual(record["source_lines_delta_planned"], record["source_lines_after_planned"] - record["source_lines_before"])
        self.assertEqual(manifest["source_bytes_before_total"], record["source_bytes_before"])
        self.assertEqual(manifest["source_bytes_after_planned_total"], record["source_bytes_after_planned"])
        self.assertEqual(manifest["source_bytes_delta_planned_total"], record["source_bytes_delta_planned"])
        self.assertTrue(Path(manifest["pre_apply_manifest"]).exists())

    def test_apply_manifest_reports_no_op_reason_for_no_candidates(self) -> None:
        manifest = prune.apply_pruning([], "unit-test-apply-plan-no-candidates", self.deterministic_local_config(), dry_run=True)

        self.assertEqual(manifest["files"], [])
        self.assertEqual(manifest["candidate_summary"]["candidate_count_total"], 0)
        self.assertEqual(manifest["candidate_summary"]["range_count_total"], 0)
        self.assertEqual(manifest["no_op_reason"], "no_prune_candidates")
        self.assertEqual(manifest["source_bytes_delta_planned_total"], 0)
        self.assertTrue(Path(manifest["pre_apply_manifest"]).exists())

    def test_apply_manifest_reports_no_op_reason_for_disallowed_candidates(self) -> None:
        item = prune.Item(
            key="disallowed",
            kind="section",
            path="context/decisions.md",
            section_heading="Old disallowed note",
            heading_level=2,
            start_line=1,
            end_line=3,
            char_count=600,
            text_hash="hash",
            explicit_dates=[],
            recall_hits=0,
            recall_signal_count=0,
            last_recalled_at=None,
            age_days=20,
            pinned=False,
            seen_runs=5,
            recall_runs=0,
            unrecalled_runs=5,
            classification="prune_candidate",
            reason="synthetic-disallowed-candidate",
        )

        manifest = prune.apply_pruning([item], "unit-test-apply-plan-disallowed", self.deterministic_local_config(), dry_run=True)

        self.assertEqual(manifest["files"], [])
        summary = manifest["candidate_summary"]
        self.assertEqual(summary["candidate_count_total"], 1)
        self.assertEqual(summary["allowlisted_candidate_count"], 0)
        self.assertEqual(summary["not_allowlisted_candidate_count"], 1)
        self.assertEqual(summary["range_count_total"], 0)
        self.assertEqual(summary["per_path"]["context/decisions.md"]["not_allowlisted_candidate_count"], 1)
        self.assertEqual(manifest["range_records"], [])
        self.assertEqual(manifest["no_op_reason"], "no_allowlisted_candidates")
        self.assertTrue(Path(manifest["pre_apply_manifest"]).exists())

    def test_budget_summary_reports_hot_doc_over_target(self) -> None:
        self.project_path.write_text("# Quant Pipeline\n\n" + ("project pressure detail\n" * 5200), encoding="utf-8")

        summary = prune.build_hot_context_budget_summary([])

        record = summary["hot_docs"]["context/projects/quant-pipeline.md"]
        self.assertGreater(record["bytes"], record["target_bytes"])
        self.assertLessEqual(record["bytes"], record["hard_bytes"])
        self.assertEqual(record["pressure_level"], "target")
        self.assertGreater(record["bytes_over_target"], 0)
        self.assertEqual(record["enforcement_mode"], "apply_allowed")

    def test_budget_summary_reports_active_live_heading_pressure(self) -> None:
        self.active_path.write_text(
            "# Active\n\n## Current focus\n\n" + ("focus pressure detail\n" * 500) + "\n## Immediate next actions\n\n- short\n",
            encoding="utf-8",
        )

        summary = prune.build_hot_context_budget_summary([])

        current = summary["active_live_headings"]["Current focus"]
        self.assertTrue(current["exists"])
        self.assertGreater(current["bytes"], current["target_bytes"])
        self.assertEqual(current["pressure_level"], "target")
        self.assertEqual(current["enforcement_mode"], "active_live_heading_summary")
        immediate = summary["active_live_headings"]["Immediate next actions"]
        self.assertEqual(immediate["pressure_level"], "none")

    def test_active_doc_heading_policy_helpers_identify_live_and_dated_headings(self) -> None:
        self.assertTrue(prune.is_active_doc(Path("context/active.md")))
        self.assertFalse(prune.is_active_doc(Path("context/projects/quant-pipeline.md")))
        self.assertTrue(prune.is_active_live_heading("Current focus"))
        self.assertTrue(prune.is_active_live_heading(" open questions "))
        self.assertFalse(prune.is_active_live_heading("Parking lot"))
        self.assertTrue(prune.is_active_dated_heading("2026-05-20 Follow-up state"))
        self.assertFalse(prune.is_active_dated_heading("Current focus"))
        self.assertEqual(prune.active_live_heading_budget("current focus")["summary_max_chars"], 2500)

    def test_active_section_pressure_helper_reports_recent_review_compress_and_strong_protection(self) -> None:
        text = "## 2026-04-01 Old active section\n\n" + ("- stale active detail\n" * 40)
        weak_broad = prune.ItemEvidence(telemetry_broad_read_only=1, weak_signal_count=1, total_hits=1)
        strong = prune.ItemEvidence(dream_strong_hits=1, strong_signal_count=1, total_hits=1)

        recent_ready, recent_reason = prune.active_section_pressure_ready(
            path_rel=Path("context/active.md"),
            kind="section",
            heading="2026-04-01 Old active section",
            text=text,
            doc_char_count=prune.ACTIVE_DOC_TARGET_BYTES + 1,
            item_age_days=2,
            seen_runs=5,
            unrecalled_runs=5,
            evidence=prune.ItemEvidence(),
            config=self.config(),
        )
        review_ready, review_reason = prune.active_section_pressure_ready(
            path_rel=Path("context/active.md"),
            kind="section",
            heading="2026-04-01 Old active section",
            text=text,
            doc_char_count=prune.ACTIVE_DOC_TARGET_BYTES + 1,
            item_age_days=5,
            seen_runs=5,
            unrecalled_runs=5,
            evidence=prune.ItemEvidence(),
            config=self.config(),
        )
        compress_ready, compress_reason = prune.active_section_pressure_ready(
            path_rel=Path("context/active.md"),
            kind="section",
            heading="2026-04-01 Old active section",
            text=text,
            doc_char_count=prune.ACTIVE_DOC_TARGET_BYTES + 1,
            item_age_days=12,
            seen_runs=5,
            unrecalled_runs=5,
            evidence=weak_broad,
            config=self.config(),
        )
        strong_ready, strong_reason = prune.active_section_pressure_ready(
            path_rel=Path("context/active.md"),
            kind="section",
            heading="2026-04-01 Old active section",
            text=text,
            doc_char_count=prune.ACTIVE_DOC_HARD_BYTES + 1,
            item_age_days=12,
            seen_runs=5,
            unrecalled_runs=5,
            evidence=strong,
            config=self.config(),
        )

        self.assertFalse(recent_ready)
        self.assertEqual(recent_reason, "active-hot-doc-recent-protected")
        self.assertTrue(review_ready)
        self.assertEqual(review_reason, "active-hot-doc-stale-dated-review")
        self.assertTrue(compress_ready)
        self.assertEqual(compress_reason, "active-hot-doc-stale-dated-weak-broad-compress")
        self.assertFalse(strong_ready)
        self.assertEqual(strong_reason, "active-hot-doc-strong-evidence-protected")

    def test_active_live_heading_budget_helper_reports_review_summarize_and_protected_live_headings(self) -> None:
        target_text = "## Current focus\n\n" + ("focus pressure detail\n" * 500)
        hard_doc_text = "## Immediate next actions\n\n- short action\n"
        target_ready, target_reason = prune.active_live_heading_budget_ready(
            path_rel=Path("context/active.md"),
            heading="current focus",
            text=target_text,
            doc_char_count=prune.ACTIVE_DOC_TARGET_BYTES + 1,
            item_age_days=10,
            evidence=prune.ItemEvidence(),
        )
        summarize_ready, summarize_reason = prune.active_live_heading_budget_ready(
            path_rel=Path("context/active.md"),
            heading="Immediate next actions",
            text=hard_doc_text,
            doc_char_count=prune.ACTIVE_DOC_HARD_BYTES + 1,
            item_age_days=10,
            evidence=prune.ItemEvidence(),
        )
        protected_ready, protected_reason = prune.active_live_heading_budget_ready(
            path_rel=Path("context/active.md"),
            heading="Watchouts",
            text="## Watchouts\n\n- short\n",
            doc_char_count=prune.ACTIVE_DOC_HARD_BYTES + 1,
            item_age_days=10,
            evidence=prune.ItemEvidence(),
        )
        strong_ready, strong_reason = prune.active_live_heading_budget_ready(
            path_rel=Path("context/active.md"),
            heading="Current focus",
            text=target_text,
            doc_char_count=prune.ACTIVE_DOC_HARD_BYTES + 1,
            item_age_days=2,
            evidence=prune.ItemEvidence(dream_strong_hits=1, strong_signal_count=1, total_hits=1),
        )

        self.assertTrue(target_ready)
        self.assertEqual(target_reason, "active-hot-doc-live-heading-budget-review")
        self.assertTrue(summarize_ready)
        self.assertEqual(summarize_reason, "active-hot-doc-live-heading-budget-summarize")
        self.assertFalse(protected_ready)
        self.assertEqual(protected_reason, "active-hot-doc-live-heading-protected")
        self.assertFalse(strong_ready)
        self.assertEqual(strong_reason, "active-hot-doc-strong-evidence-protected")

    def test_budget_summary_reports_active_live_heading_summary_limits(self) -> None:
        self.active_path.write_text(
            "# Active\n\n## Current focus\n\n" + ("focus pressure detail\n" * 500) + "\n## Immediate next actions\n\n- short\n",
            encoding="utf-8",
        )

        summary = prune.build_hot_context_budget_summary([])

        self.assertEqual(summary["hot_docs"]["context/active.md"]["target_bytes"], prune.ACTIVE_DOC_TARGET_BYTES)
        self.assertEqual(summary["hot_docs"]["context/active.md"]["hard_bytes"], prune.ACTIVE_DOC_HARD_BYTES)
        self.assertEqual(summary["active_live_headings"]["Current focus"]["summary_max_chars"], 2500)
        self.assertEqual(summary["active_live_headings"]["Immediate next actions"]["summary_max_chars"], 1500)

    def test_stale_active_dated_section_with_weak_broad_history_reviews_first(self) -> None:
        heading = "2026-04-25 Active follow-up"
        body = "- dated active detail awaiting review before compression\n" * 40
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        state = self.state_for([seed.key])
        state["items"][seed.key]["firstSeenAt"] = "2026-04-25T00:00:00Z"
        state["items"][seed.key]["lastSeenAt"] = "2026-04-25T00:00:00Z"
        self.write_telemetry_entries(
            {
                "path": "context/active.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build_all(state)

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.evidence_class, "weak_or_broad_only")
        self.assertEqual(item.classification, "review")
        self.assertEqual(item.reason, "active-hot-doc-stale-dated-weak-broad-review")

    def test_stale_active_dated_section_with_weak_broad_history_compresses_after_prune_maturity(self) -> None:
        heading = "2026-04-20 Active weak broad follow-up"
        body = "- dated active detail seen only through broad telemetry\n" * 45
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/active.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 1,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "read",
                "evidenceTier": "weak",
                "spanKind": "broad",
                "protectsFromPrune": False,
            }
        )

        items, _ = self.build_all(self.state_for([seed.key]))

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.evidence_class, "weak_or_broad_only")
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "active-hot-doc-stale-dated-weak-broad-compress")

    def test_high_recall_history_does_not_block_active_dated_compression_without_current_evidence(self) -> None:
        heading = "2026-04-20 Active high recall follow-up"
        body = "- dated active detail whose historical recall should not pin it forever\n" * 45
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        state = self.state_for([seed.key])
        state["items"][seed.key]["recallRuns"] = prune.HIGH_USAGE_RECALL_RUNS

        items, _ = self.build_all(state)

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.recall_hits, 0)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "active-hot-doc-stale-dated-compress")

    def test_strong_targeted_active_section_is_kept(self) -> None:
        heading = "2026-04-20 Active strong evidence follow-up"
        body = "- dated active detail with current targeted citation\n" * 45
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        self.write_telemetry_entries(
            {
                "path": "context/active.md",
                "startLine": seed.start_line,
                "endLine": seed.end_line,
                "signalCount": 4,
                "lastSeenAt": "2026-05-01T10:00:00Z",
                "signalType": "final_citation",
                "evidenceTier": "strong",
                "spanKind": "narrow",
                "protectsFromPrune": True,
            }
        )

        items, _ = self.build_all(self.state_for([seed.key]))

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.evidence_class, "strong_targeted")
        self.assertEqual(item.classification, "keep")
        self.assertEqual(item.reason, "active-hot-doc-strong-evidence-protected")

    def test_current_focus_heading_never_deletes_for_size_pressure(self) -> None:
        body = "- current focus pressure detail with live operational meaning\n" * 600
        self.active_path.write_text(f"# Active Workbench Context\n\n## Current focus\n\n{body}", encoding="utf-8")

        items, _ = self.build_all({"version": 2, "items": {}})

        current_focus = self.find_item(items, "section", "Current focus")
        self.assertEqual(current_focus.classification, "review")
        self.assertEqual(current_focus.reason, "active-hot-doc-live-heading-budget-summarize")
        self.assertNotIn("context/active.md", prune.candidate_ranges(items))

    def test_live_heading_summary_range_uses_deterministic_fallback_when_local_disabled(self) -> None:
        body = (
            "- Blocked: waiting on context_usage_prune.py validation cleanup since 2026-06-18\n"
            "- Next action: continue active heading replacement repair\n"
            "- Open question: pending validation review remains unresolved\n"
            + ("- transient current focus detail that should be summarized\n" * 600)
        )
        text = f"# Active Workbench Context\n\n## Current focus\n\n{body}"
        self.active_path.write_text(text, encoding="utf-8")
        items, _ = self.build_all({"version": 2, "items": {}})
        current_focus = self.find_item(items, "section", "Current focus")
        removed_hash = prune.sha256_text("\n".join(self.active_path.read_text().splitlines()[current_focus.start_line - 1 : current_focus.end_line]))[:12]

        manifest = prune.apply_pruning(
            items,
            "unit-test-live-heading-disabled",
            self.deterministic_local_config(),
            allow_large_shrink=True,
        )

        self.assertNotIn("context/active.md", prune.candidate_ranges(items))
        self.assertEqual(manifest["candidate_summary"]["candidate_count_total"], 0)
        self.assertEqual(manifest["candidate_summary"]["active_live_heading_summary_candidate_count"], 1)
        self.assertEqual(manifest["candidate_summary"]["requires_local_summary_range_count"], 1)
        self.assertEqual(manifest["range_records"][0]["requires_local_summary"], True)
        self.assertEqual(manifest["range_records"][0]["reason"], "active-hot-doc-live-heading-budget-summarize")
        self.assertEqual(manifest["active_live_heading_summary"]["range_count"], 1)
        self.assertEqual(manifest["active_live_heading_summary"]["applied"], 1)
        self.assertEqual(manifest["active_live_heading_summary"]["skipped"], 0)
        self.assertEqual(manifest["local_compression"]["fallback"], 1)
        self.assertEqual(manifest["files"][0]["path"], "context/active.md")
        rewritten = self.active_path.read_text()
        self.assertIn("Compressed local summary", rewritten)
        self.assertIn(f"sha256:{removed_hash}", rewritten)
        self.assertIn("Current focus:", rewritten)
        self.assertIn("Next actions:", rewritten)
        self.assertIn("Watchouts:", rewritten)
        self.assertIn("Open questions:", rewritten)
        self.assertNotIn("transient current focus detail that should be summarized\n- transient", rewritten)
        archived = json.loads(Path(manifest["files"][0]["archive"]).read_text())
        self.assertEqual(archived["removed"][0]["replacement_source"], "deterministic_active_fallback")
        self.assertEqual(archived["removed"][0]["text_sha256"][:12], removed_hash)

    def test_active_live_heading_validation_accepts_semantic_replacement_without_exact_markers(self) -> None:
        body = (
            "- Blocked: waiting on context_usage_prune.py validation cleanup since 2026-06-18\n"
            "- Next action: continue active heading replacement repair\n"
            "- Open question: pending validation review remains unresolved\n"
            + ("- transient current focus detail\n" * 600)
        )
        self.active_path.write_text(f"# Active Workbench Context\n\n## Current focus\n\n{body}", encoding="utf-8")
        items, _ = self.build_all({"version": 2, "items": {}})
        current_focus = self.find_item(items, "section", "Current focus")
        removed_text = "\n".join(self.active_path.read_text().splitlines()[current_focus.start_line - 1 : current_focus.end_line])
        archive_hash = prune.sha256_text(removed_text)
        replacement_lines = prune.compressed_replacement_lines(
            current_focus,
            removed_text,
            local_summary=(
                "Active work remains on context pruning repair. Continue replacement validation. "
                "Risk is validation coverage drift. Remaining issue needs review. Carryover since 2026-06-18."
            ),
            archive_hash=archive_hash,
        )

        valid, reason = prune.validate_active_live_heading_replacement(
            current_focus,
            removed_text,
            replacement_lines,
            archive_hash=archive_hash,
        )

        self.assertTrue(valid, reason)

    def test_active_live_heading_validation_rejects_missing_obligations(self) -> None:
        body = (
            "- Blocked: waiting on context_usage_prune.py validation cleanup since 2026-06-18\n"
            "- Next action: continue active heading replacement repair\n"
            "- Open question: pending validation review remains unresolved\n"
            + ("- transient current focus detail\n" * 600)
        )
        self.active_path.write_text(f"# Active Workbench Context\n\n## Current focus\n\n{body}", encoding="utf-8")
        items, _ = self.build_all({"version": 2, "items": {}})
        current_focus = self.find_item(items, "section", "Current focus")
        removed_text = "\n".join(self.active_path.read_text().splitlines()[current_focus.start_line - 1 : current_focus.end_line])
        archive_hash = prune.sha256_text(removed_text)
        replacement_lines = prune.compressed_replacement_lines(
            current_focus,
            removed_text,
            local_summary="Active work stays in the context pruning archive. Since 2026-06-18.",
            archive_hash=archive_hash,
        )

        valid, reason = prune.validate_active_live_heading_replacement(
            current_focus,
            removed_text,
            replacement_lines,
            archive_hash=archive_hash,
        )

        self.assertFalse(valid)
        self.assertIn("missing_required_categories", reason or "")
        self.assertIn("immediate_next_actions", reason or "")
        self.assertIn("watchouts", reason or "")
        self.assertIn("open_questions", reason or "")

    def test_oversized_current_focus_uses_local_or_deterministic_summary_for_autonomous_apply(self) -> None:
        body = (
            "- Blocked: waiting on context_usage_prune.py validation cleanup\n"
            "- Next action: keep active blocker and action markers in the summary\n"
            + ("- transient current focus detail that should be summarized\n" * 600)
        )
        self.active_path.write_text(f"# Active Workbench Context\n\n## Current focus\n\n{body}", encoding="utf-8")
        items, _ = self.build_all({"version": 2, "items": {}})
        current_focus = self.find_item(items, "section", "Current focus")
        removed_hash = prune.sha256_text("\n".join(self.active_path.read_text().splitlines()[current_focus.start_line - 1 : current_focus.end_line]))[:12]

        original = prune.call_local_compressor
        try:
            prune.call_local_compressor = lambda removed, item, config: "Blocked on context_usage_prune.py validation cleanup; Next action is to keep active blocker and action markers."
            manifest = prune.apply_pruning(
                items,
                "unit-test-live-heading-local",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
                allow_large_shrink=True,
            )
        finally:
            prune.call_local_compressor = original

        rewritten = self.active_path.read_text()
        self.assertIn("## Current focus", rewritten)
        self.assertIn("Compressed local summary", rewritten)
        self.assertIn(f"sha256:{removed_hash}", rewritten)
        self.assertIn("Blocked", rewritten)
        self.assertIn("Next action", rewritten)
        self.assertNotIn("transient current focus detail that should be summarized\n- transient", rewritten)
        self.assertEqual(manifest["active_live_heading_summary"]["applied"], 1)
        self.assertEqual(manifest["active_live_heading_summary"]["skipped"], 0)
        self.assertEqual(manifest["files"][0]["path"], "context/active.md")
        archived = json.loads(Path(manifest["files"][0]["archive"]).read_text())
        self.assertEqual(archived["removed"][0]["requires_local_summary"], True)
        self.assertEqual(archived["removed"][0]["replacement_source"], "local_model")
        self.assertEqual(archived["removed"][0]["text_sha256"][:12], removed_hash)

    def test_oversized_immediate_next_actions_summarizes_to_short_action_list(self) -> None:
        action_body = (
            "- Next action: finish Slice 3D active-doc tests\n"
            "- Next action: run verification and push the scoped commit\n"
            + ("- Next action: transient detail that should collapse into the short action list\n" * 420)
        )
        self.active_path.write_text(
            f"# Active Workbench Context\n\n## Current focus\n\n- short focus\n\n## Immediate next actions\n\n{action_body}",
            encoding="utf-8",
        )
        items, _ = self.build_all({"version": 2, "items": {}})
        next_actions = self.find_item(items, "section", "Immediate next actions")
        self.assertEqual(next_actions.classification, "review")
        self.assertEqual(next_actions.reason, "active-hot-doc-live-heading-budget-summarize")

        original = prune.call_local_compressor
        try:
            prune.call_local_compressor = lambda removed, item, config: "Next action: finish Slice 3D active-doc tests; Next action: run verification and push."
            manifest = prune.apply_pruning(
                items,
                "unit-test-immediate-next-actions-summary",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
                allow_large_shrink=True,
            )
        finally:
            prune.call_local_compressor = original

        rewritten = self.active_path.read_text()
        rewritten_next_actions = rewritten.split("## Immediate next actions", 1)[1]
        max_chars = prune.ACTIVE_LIVE_HEADING_BUDGETS["Immediate next actions"]["summary_max_chars"]
        self.assertIn("## Immediate next actions", rewritten)
        self.assertIn("Next action: finish Slice 3D active-doc tests", rewritten_next_actions)
        self.assertLessEqual(len(("## Immediate next actions" + rewritten_next_actions)), max_chars + prune.ACTIVE_LIVE_HEADING_SUMMARY_TOLERANCE_CHARS)
        self.assertNotIn("transient detail that should collapse\n- Next action: transient", rewritten_next_actions)
        self.assertEqual(manifest["active_live_heading_summary"]["applied"], 1)
        self.assertEqual(manifest["files"][0]["path"], "context/active.md")

    def test_active_apply_archives_before_replacing_section(self) -> None:
        heading = "2026-04-20 Active archive order follow-up"
        body = "- stale active implementation detail that should be archived before replacement\n" * 45
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        seed = self.find_item(seed_items, "section", heading)
        items, _ = self.build_all(self.state_for([seed.key]))
        item = self.find_item(items, "section", heading)
        self.assertEqual(item.classification, "prune_candidate")
        self.assertEqual(item.reason, "active-hot-doc-stale-dated-compress")

        write_events: list[Path] = []
        original_write_text = type(self.active_path).write_text

        def tracking_write_text(path_self: Path, *args: object, **kwargs: object) -> int:
            write_events.append(Path(path_self))
            return original_write_text(path_self, *args, **kwargs)

        with patch.object(type(self.active_path), "write_text", new=tracking_write_text):
            manifest = prune.apply_pruning(items, "unit-test-active-archive-before-replace", self.deterministic_local_config())

        archive_path = Path(manifest["files"][0]["archive"])
        self.assertIn(archive_path, write_events)
        self.assertIn(self.active_path, write_events)
        self.assertLess(write_events.index(archive_path), write_events.index(self.active_path))
        self.assertTrue(archive_path.exists())
        archived = json.loads(archive_path.read_text())
        self.assertIn("stale active implementation detail", archived["removed"][0]["text"])
        self.assertEqual(archived["removed"][0]["replacement_source"], "deterministic")
        self.assertIn("Compressed archived detail", self.active_path.read_text())

    def test_live_heading_validation_failure_leaves_source_unchanged(self) -> None:
        body = "- Blocked: preserve this explicit blocker marker\n" + ("- oversized live detail\n" * 700)
        text = f"# Active Workbench Context\n\n## Current focus\n\n{body}"
        self.active_path.write_text(text, encoding="utf-8")
        items, _ = self.build_all({"version": 2, "items": {}})

        original = prune.call_local_compressor
        original_fallback = prune.deterministic_active_fallback_summary
        try:
            invalid_summary = "Compact maintenance paragraph with ordinary context wording only."
            prune.call_local_compressor = lambda removed, item, config: invalid_summary
            prune.deterministic_active_fallback_summary = lambda item, removed: invalid_summary
            manifest = prune.apply_pruning(
                items,
                "unit-test-live-heading-validation-failed",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
            )
        finally:
            prune.call_local_compressor = original
            prune.deterministic_active_fallback_summary = original_fallback

        self.assertEqual(self.active_path.read_text(), text)
        self.assertEqual(manifest["files"], [])
        self.assertEqual(manifest["active_live_heading_summary"]["skipped"], 1)
        self.assertEqual(manifest["active_live_heading_summary"]["skip_reasons"], {"validation_failed": 1})
        self.assertIn("missing_required_categories", manifest["active_live_heading_summary"]["skipped_ranges"][0]["skip_detail"])
        self.assertEqual(manifest["no_op_reason"], "all_apply_ranges_skipped")

    def test_recent_active_content_under_three_days_is_protected_from_budget_pressure(self) -> None:
        heading = "2026-04-30 Recent active follow-up"
        body = "- recent active detail that should stay live during the protect window\n" * 45
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}", encoding="utf-8")

        items, _ = self.build_all({"version": 2, "items": {}})

        item = self.find_item(items, "section", heading)
        self.assertEqual(item.classification, "keep")
        self.assertEqual(item.reason, "active-hot-doc-recent-protected")

    def test_budget_summary_marks_decisions_autonomous_consolidation(self) -> None:
        (self.context / "decisions.md").write_text("# Decisions\n\n- durable choice\n", encoding="utf-8")

        summary = prune.build_hot_context_budget_summary([])

        record = summary["hot_docs"]["context/decisions.md"]
        self.assertEqual(record["target_bytes"], 15000)
        self.assertEqual(record["hard_bytes"], 18000)
        self.assertEqual(record["enforcement_mode"], "autonomous_consolidation")
        self.assertEqual(record["pressure_level"], "none")

    def test_non_prunable_size_debt_inventories_decisions(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## Safety\n\n"
            "- Do not exfiltrate private data.\n"
            "- Do not exfiltrate private data.\n"
            "- Durable routing rule should prefer Workbench context updates for active state.\n"
            "- Durable routing rule should prefer Workbench context updates for decisions state.\n"
            "## Testing\n\n"
            "- Verification should include tests or dry-run evidence.\n"
            + "".join(f"- safety boundary detail for consolidation pressure {idx}\n" for idx in range(430))
        )
        (self.context / "decisions.md").write_text(decisions_text, encoding="utf-8")
        items, _ = self.build_all()

        debt = prune.non_prunable_size_debt(items)
        record = debt["records"]["context/decisions.md"]

        self.assertTrue(debt["decisions_autonomous_consolidation_required"])
        self.assertEqual(record["apply_status"], "protected_autonomous_consolidation")
        self.assertEqual(record["consolidation_priority_bucket"], "high")
        self.assertEqual(record["section_count"], 3)
        self.assertGreater(record["bullet_count"], 400)
        self.assertEqual(record["likely_exact_duplicate_bullets"][0]["count"], 2)
        self.assertEqual(record["likely_same_prefix_durable_rules"][0]["count"], 2)
        inventory = record["invariant_inventory"]
        self.assertIn("Safety", inventory["headings_present"])
        self.assertGreaterEqual(len(inventory["safety_boundary_phrases"]), 1)
        self.assertGreaterEqual(len(inventory["workspace_routing_rules"]), 1)
        self.assertGreaterEqual(len(inventory["testing_rules"]), 1)

    def test_non_prunable_size_debt_reports_largest_decisions_sections(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## Small durable section\n\n"
            "- Keep this compact rule.\n"
            "## Large durable section\n\n"
            + "".join(f"- Durable decision expansion {idx} should stay represented.\n" for idx in range(80))
            + "## Medium durable section\n\n"
            + "".join(f"- Medium durable decision {idx}.\n" for idx in range(20))
        )
        (self.context / "decisions.md").write_text(decisions_text, encoding="utf-8")
        items, _ = self.build_all()

        record = prune.non_prunable_size_debt(items)["records"]["context/decisions.md"]
        largest = record["largest_sections"]

        self.assertEqual(largest[0]["heading"], "Large durable section")
        self.assertTrue(any(section["heading"] == "Large durable section" for section in largest))
        large = next(section for section in largest if section["heading"] == "Large durable section")
        small = next(section for section in largest if section["heading"] == "Small durable section")
        self.assertGreater(large["bytes"], small["bytes"])
        self.assertGreaterEqual(record["largest_bullets"][0]["bytes"], len("- Durable decision expansion 10 should stay represented.\n"))

    def test_report_renders_non_prunable_size_debt_section(self) -> None:
        (self.context / "decisions.md").write_text("# Decisions\n\n- durable choice\n", encoding="utf-8")
        items, _ = self.build_all()

        report = prune.build_report(items, {"version": 2, "items": {}}, self.config(), run_bucket=RUN_BUCKET)

        self.assertIn("## Non-prunable size debt", report)
        self.assertIn("decisions autonomous consolidation required: false", report)
        self.assertIn("### `context/decisions.md`", report)

    def test_decisions_plan_writes_patch_without_mutating_source(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## Workspace rules\n\n"
            "- Do not exfiltrate private data.\n"
            "- Do not exfiltrate private data.\n"
            "- Durable routing rule should prefer Workbench context updates for active state.\n"
            "- Durable routing rule should prefer Workbench context updates for decisions state.\n"
            "## Testing rules\n\n"
            "- Verification should include tests or dry-run evidence.\n"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")

        summary = prune.run_decisions_consolidation_plan(stamp="unit-decisions-plan")

        self.assertEqual(decisions_path.read_text(encoding="utf-8"), decisions_text)
        self.assertFalse(summary["source_mutated"])
        self.assertEqual(summary["exact_duplicate_group_count"], 1)
        self.assertEqual(summary["shared_prefix_group_count"], 1)
        self.assertEqual(summary["consolidation_group_count"], 2)
        self.assertEqual(summary["touched_paths"], ["context/decisions.md"])
        self.assertTrue(summary["patch_touches_only_decisions"])
        self.assertLess(summary["bytes_after_planned"], summary["bytes_before"])
        for key in ["input_path", "plan_path", "patch_path", "summary_path"]:
            self.assertTrue(Path(summary[key]).exists(), key)
        patch_text = Path(summary["patch_path"]).read_text(encoding="utf-8")
        self.assertIn("--- a/context/decisions.md", patch_text)
        self.assertIn("+++ b/context/decisions.md", patch_text)
        self.assertNotIn("context/active.md", patch_text)
        plan_text = Path(summary["plan_path"]).read_text(encoding="utf-8")
        self.assertIn("source refs:", plan_text)
        self.assertIn("prefix-1", plan_text)

    def test_decisions_plan_preserves_keep_markers_and_records_budget_deficit(self) -> None:
        large_body = "".join(f"- Durable safety boundary rule {idx} should stay explicit.\n" for idx in range(420))
        decisions_text = (
            "# Decisions\n\n"
            "## Safety\n\n"
            "<!-- openclaw:prune:keep -->\n"
            "- Do not exfiltrate private data.\n"
            f"{large_body}"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")

        summary = prune.run_decisions_consolidation_plan(stamp="unit-decisions-deficit")

        self.assertEqual(decisions_path.read_text(encoding="utf-8"), decisions_text)
        self.assertEqual(summary["consolidation_group_count"], 0)
        self.assertGreater(summary["budget_deficit_after_consolidation"], 0)
        rejected = summary["rejected_candidate_summary"]
        self.assertEqual(rejected["accepted_grouped_bullet_count"], 0)
        self.assertGreater(rejected["near_match_group_count"], 0)
        self.assertEqual(rejected["near_matches"][0]["reason"], "shared_prefix_below_safe_threshold")
        before = summary["invariant_inventory_before"]
        after = summary["invariant_inventory_after_planned"]
        self.assertEqual(len(before["explicit_keep_markers"]), 1)
        self.assertEqual(len(after["explicit_keep_markers"]), 1)
        self.assertIn("Safety", after["headings_present"])
        plan_text = Path(summary["plan_path"]).read_text(encoding="utf-8")
        self.assertIn("## Rejected Candidates / Near Matches", plan_text)
        self.assertIn("shared_prefix_below_safe_threshold", plan_text)

    def test_decisions_apply_archives_before_patch(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## Workspace rules\n\n"
            "- Do not exfiltrate private data.\n"
            "- Do not exfiltrate private data.\n"
            "- Durable routing rule should prefer Workbench context updates for active state.\n"
            "- Durable routing rule should prefer Workbench context updates for decisions state.\n"
            "## Testing rules\n\n"
            "- Verification should include tests or dry-run evidence.\n"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")

        manifest = prune.run_decisions_consolidation_apply(stamp="unit-decisions-apply")

        self.assertEqual(manifest["validation_status"], "passed")
        self.assertTrue(manifest["source_mutated"])
        archive_path = Path(str(manifest["archive_path"]))
        self.assertTrue(archive_path.exists())
        self.assertEqual(archive_path.read_text(encoding="utf-8"), decisions_text)
        self.assertTrue(Path(str(manifest["apply_manifest_path"])).exists())
        updated = decisions_path.read_text(encoding="utf-8")
        self.assertLess(len(updated), len(decisions_text))
        self.assertIn("Durable routing rule should prefer Workbench context updates for active state; decisions state.", updated)
        self.assertEqual(manifest["source_sha256_after"], prune.sha256_text(updated))

    def test_decisions_apply_rejects_hash_mismatch(self) -> None:
        decisions_text = "# Decisions\n\n- Durable choice stays.\n"
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")
        plan = prune.build_decisions_consolidation_plan("unit-hash-mismatch")
        decisions_path.write_text(decisions_text + "- New concurrent edit.\n", encoding="utf-8")

        status, failures = prune.validate_decisions_apply_plan(plan, min_shrink_bytes=0)

        self.assertEqual(status, "validation_failed")
        self.assertIn("source_hash_mismatch", failures)

    def test_decisions_apply_rejects_patch_touching_other_files(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "- Durable routing rule should prefer Workbench context updates for active state.\n"
            "- Durable routing rule should prefer Workbench context updates for decisions state.\n"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")
        plan = prune.build_decisions_consolidation_plan("unit-patch-scope")
        plan["summary"]["touched_paths"] = ["context/decisions.md", "context/active.md"]
        plan["summary"]["patch_touches_only_decisions"] = False

        status, failures = prune.validate_decisions_apply_plan(plan, min_shrink_bytes=0)

        self.assertEqual(status, "validation_failed")
        self.assertIn("patch_touches_other_files", failures)
        self.assertEqual(decisions_path.read_text(encoding="utf-8"), decisions_text)

    def test_decisions_apply_noops_when_safe_shrink_threshold_not_met(self) -> None:
        large_body = "".join(f"- Durable safety boundary rule {idx} should stay explicit.\n" for idx in range(420))
        decisions_text = (
            "# Decisions\n\n"
            "## Safety\n\n"
            "- Do not exfiltrate private data.\n"
            f"{large_body}"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")

        manifest = prune.run_decisions_consolidation_apply(stamp="unit-decisions-noop")

        self.assertEqual(manifest["validation_status"], "noop")
        self.assertEqual(manifest["no_op_reason"], "insufficient_safe_decisions_shrink")
        self.assertFalse(manifest["source_mutated"])
        self.assertEqual(decisions_path.read_text(encoding="utf-8"), decisions_text)
        self.assertIsNone(manifest["archive_path"])
        self.assertTrue(Path(str(manifest["apply_manifest_path"])).exists())

    def test_decisions_backlog_records_single_noop_without_review_artifact(self) -> None:
        result = {
            "validation_status": "noop",
            "no_op_reason": "insufficient_safe_decisions_shrink",
            "source_path": "context/decisions.md",
            "bytes_before": 22000,
            "bytes_after_planned": 21800,
            "bytes_delta_planned": -200,
            "budget_deficit_after_consolidation": 6800,
            "consolidation_group_count": 0,
            "min_shrink_bytes": 1000,
        }

        backlog = prune.record_decisions_consolidation_result(result, timestamp="2026-06-18T15:00:00Z")

        self.assertEqual(backlog["status"], "monitoring")
        self.assertEqual(backlog["repeated_count"], 1)
        self.assertEqual(backlog["recommended_action"], "manual_decisions_consolidation_review")
        self.assertTrue(Path(str(backlog["history_path"])).exists())
        self.assertIsNone(backlog["status_path"])
        self.assertFalse(prune.decisions_backlog_status_json_path().exists())
        history = json.loads(prune.decisions_backlog_history_path().read_text(encoding="utf-8"))
        self.assertEqual(len(history["history"]), 1)

    def test_decisions_backlog_emits_review_after_repeated_noops(self) -> None:
        result = {
            "validation_status": "noop",
            "no_op_reason": "insufficient_safe_decisions_shrink",
            "source_path": "context/decisions.md",
            "bytes_before": 22000,
            "bytes_after_planned": 21600,
            "bytes_delta_planned": -400,
            "budget_deficit_after_consolidation": 6600,
            "consolidation_group_count": 2,
            "min_shrink_bytes": 1000,
        }

        first = prune.record_decisions_consolidation_result(result, timestamp="2026-06-18T15:00:00Z")
        second = prune.record_decisions_consolidation_result(result, timestamp="2026-06-18T15:01:00Z")
        third = prune.record_decisions_consolidation_result(result, timestamp="2026-06-18T15:02:00Z")

        self.assertEqual(first["status"], "monitoring")
        self.assertEqual(second["status"], "monitoring")
        self.assertEqual(third["status"], "review_required")
        self.assertEqual(third["reason"], "repeated_insufficient_safe_shrink")
        self.assertEqual(third["repeated_count"], 3)
        self.assertEqual(third["safe_candidates"], 2)
        self.assertEqual(third["recommended_action"], "apply_or_stage_safe_deterministic_shrink")
        self.assertIn("safe_deterministic_decisions_shrink", third["allowed_forward_lanes"])

        status = json.loads(prune.decisions_backlog_status_json_path().read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "review_required")
        self.assertEqual(status["recommended_action"], "apply_or_stage_safe_deterministic_shrink")
        self.assertEqual(status["blocked_scope"]["source_path"], "context/decisions.md")
        markdown = prune.decisions_backlog_status_markdown_path().read_text(encoding="utf-8")
        self.assertIn("repeated count: 3", markdown)
        self.assertIn("apply_or_stage_safe_deterministic_shrink", markdown)

    def test_decisions_apply_preserves_invariant_inventory(self) -> None:
        decisions_text = (
            "# Decisions\n\n"
            "## Safety\n\n"
            "<!-- openclaw:prune:keep -->\n"
            "- Do not exfiltrate private data.\n"
            "- Do not exfiltrate private data.\n"
            "## Workspace rules\n\n"
            "- Use Workbench for implementation work.\n"
            "- Use Workbench for implementation work.\n"
        )
        decisions_path = self.context / "decisions.md"
        decisions_path.write_text(decisions_text, encoding="utf-8")

        manifest = prune.run_decisions_consolidation_apply(stamp="unit-decisions-invariants")

        self.assertEqual(manifest["validation_status"], "passed")
        updated = decisions_path.read_text(encoding="utf-8")
        after = prune.decisions_invariant_inventory_for_text(updated)
        self.assertIn("Safety", after["headings_present"])
        self.assertIn("Workspace rules", after["headings_present"])
        self.assertEqual(len(after["explicit_keep_markers"]), 1)
        self.assertGreaterEqual(len(after["safety_boundary_phrases"]), 1)

    def test_budget_summary_included_in_apply_manifest(self) -> None:
        dated_heading = "2026-04-01 Old implementation diary"
        dated_body = "- old implementation detail that must be compressed\n" + ("  continuation with stale detail\n" * 40)
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        section_seed = self.find_item(seed_items, "section", dated_heading)
        bullet_seed = self.find_item(seed_items, "bullet", dated_heading)
        items, _ = self.build(text, self.state_for([section_seed.key, bullet_seed.key]))

        manifest = prune.apply_pruning(items, "unit-test-budget-summary", self.deterministic_local_config(), dry_run=True)

        budget = manifest["budget_summary"]
        self.assertIn("hot_docs", budget)
        self.assertIn("context/projects/quant-pipeline.md", budget["hot_docs"])
        self.assertEqual(budget["apply_projection"]["range_records_count"], 1)
        project_record = budget["hot_docs"]["context/projects/quant-pipeline.md"]
        self.assertIn("projected_bytes_after_apply", project_record)
        self.assertIn("source_bytes_after_planned", project_record)
        self.assertLess(project_record["source_bytes_after_planned"], project_record["bytes"])

    def test_budget_summary_tracks_hot_markdown_separately_from_state_json(self) -> None:
        (self.context / "bootstrap.md").write_text("# Bootstrap\n", encoding="utf-8")
        self.active_path.write_text("# Active\n\n## Current focus\n\n- short\n\n## Immediate next actions\n\n- short\n", encoding="utf-8")
        (self.context / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        self.project_path.write_text("# Quant Pipeline\n", encoding="utf-8")
        self.workbench_context_path.write_text("# Workbench Context\n", encoding="utf-8")
        prune.STATE_PATH.write_text("x" * 300000, encoding="utf-8")

        summary = prune.build_hot_context_budget_summary([])

        self.assertTrue(summary["hot_markdown_budget_success"])
        self.assertFalse(summary["state_json_budget_success"])
        self.assertEqual(summary["state_files"]["context/state/context-pruning-state.json"]["pressure_level"], "target")
        self.assertGreater(summary["state_json_bytes_total"], summary["hot_markdown_bytes_total"])

    def test_protected_budget_debt_reports_stable_anchor_bytes_when_target_missed(self) -> None:
        self.project_path.write_text(
            "# Quant Pipeline\n\n## Objective function\n\n" + ("stable anchor pressure detail for budget debt\n" * 3000),
            encoding="utf-8",
        )
        items, _ = self.build_all()

        summary = prune.build_hot_context_budget_summary(items)
        debt = summary["protected_budget_debt"]

        self.assertIn(summary["hot_docs"]["context/projects/quant-pipeline.md"]["pressure_level"], {"target", "hard"})
        self.assertGreater(debt["protected_budget_debt_by_category"]["stable_project_spine_anchor"], 0)
        self.assertGreater(debt["protected_budget_debt_routes"]["autonomous_anchor_summary"], 0)
        self.assertEqual(debt["top_protected_spans"][0]["category"], "stable_project_spine_anchor")

    def test_protected_budget_debt_routes_explicit_keep_marker_to_autonomous_compaction(self) -> None:
        self.active_path.write_text(
            "# Active\n\n## Parking lot\n\n<!-- openclaw:prune:keep -->\n" + ("explicit keep pressure detail\n" * 900),
            encoding="utf-8",
        )
        items, _ = self.build_all()

        summary = prune.build_hot_context_budget_summary(items)
        debt = summary["protected_budget_debt"]

        self.assertIn(summary["hot_docs"]["context/active.md"]["pressure_level"], {"target", "hard"})
        self.assertGreater(debt["protected_budget_debt_by_category"]["explicit_keep_marker"], 0)
        self.assertGreater(debt["protected_budget_debt_routes"]["autonomous_keep_marker_compaction"], 0)

    def test_protected_budget_debt_marks_budget_success_false_when_only_protected_content_remains(self) -> None:
        (self.context / "decisions.md").write_text(
            "# Decisions\n\n" + ("- durable protected decision requiring consolidation\n" * 450),
            encoding="utf-8",
        )
        items, _ = self.build_all()

        summary = prune.build_hot_context_budget_summary(items)
        debt = summary["protected_budget_debt"]

        self.assertFalse(summary["hot_markdown_budget_success"])
        self.assertFalse(summary["budget_success"])
        self.assertFalse(debt["budget_success"])
        self.assertGreater(debt["protected_budget_debt_by_category"]["decisions_autonomous_consolidation"], 0)
        self.assertGreater(debt["protected_budget_debt_routes"]["autonomous_decisions_consolidation_patch"], 0)

    def test_stale_strong_evidence_is_not_indefinite_budget_exemption_without_unresolved_marker(self) -> None:
        active_text = "# Active\n\n## Old used evidence\n\n" + ("old recalled archival detail only\n" * 900)
        self.active_path.write_text(active_text, encoding="utf-8")
        end_line = len(active_text.splitlines())
        item = prune.Item(
            key="section:context/active.md:old-used-evidence",
            kind="section",
            path="context/active.md",
            section_heading="Old used evidence",
            heading_level=2,
            start_line=3,
            end_line=end_line,
            char_count=len(active_text.encode("utf-8")),
            text_hash="stale-strong",
            explicit_dates=[],
            recall_hits=1,
            recall_signal_count=5,
            last_recalled_at="2026-04-01T00:00:00Z",
            age_days=30,
            pinned=False,
            seen_runs=5,
            recall_runs=4,
            unrecalled_runs=0,
            classification="keep",
            reason="recalled:1/5",
        )

        summary = prune.build_hot_context_budget_summary([item])
        debt = summary["protected_budget_debt"]

        self.assertIn(summary["hot_docs"]["context/active.md"]["pressure_level"], {"target", "hard"})
        self.assertEqual(debt["protected_budget_debt_bytes_total"], 0)
        self.assertNotIn("strong_targeted_recent_or_unresolved", debt["protected_budget_debt_by_category"])
        self.assertGreater(debt["stale_strong_evidence_overflow_bytes_total"], 0)
        self.assertEqual(debt["stale_strong_evidence_overflow_spans"][0]["route"], "phase_3_4_budget_pressure")

    def test_compressed_archive_note_cap_reviews_excess_before_prune_window(self) -> None:
        heading = "Current active implementation concerns"
        notes = []
        for day in range(1, 11):
            notes.append(f"- Compressed archived detail (100 chars; dates: 2026-04-{day:02d}): note {day}\n")
        text = f"# Quant Pipeline\n\n## {heading}\n\n" + "".join(notes)
        items, _ = self.build(text, {"version": 2, "items": {}})

        capped = [item for item in self.find_items(items, "bullet", heading) if item.reason == "compressed-archive-note-cap-review"]
        self.assertEqual(len(capped), 5)
        self.assertEqual([item.explicit_dates[0] for item in sorted(capped, key=lambda i: i.start_line)], ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"])
        self.assertFalse(prune.candidate_ranges(items))

        manifest = prune.apply_pruning(items, "unit-test-cap", self.deterministic_local_config())
        self.assertEqual(len(manifest["files"]), 0)
        compressed = self.project_path.read_text()
        self.assertIn("note 1", compressed)
        self.assertIn("note 10", compressed)

    def test_compressed_section_gets_new_lifecycle_key_after_replacement(self) -> None:
        heading = "2026-04-01 Old implementation diary"
        compressed_note = "- Compressed local summary (2000 chars; dates: 2026-04-01; refs: scripts/context_usage_prune.py): durable compressed breadcrumb.\n"
        text = f"# Quant Pipeline\n\n## {heading}\n\n{compressed_note}"
        original_stable_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(heading)}"
        items, _ = self.build(text, self.state_for([original_stable_key]))

        section = self.find_item(items, "section", heading)
        self.assertIn(":compressed:", section.key)
        self.assertEqual(section.age_days, 0.0)
        self.assertEqual(section.classification, "keep")
        self.assertEqual(section.reason, "compressed-archive-note-recent")

    def test_compressed_section_prunes_after_unused_window(self) -> None:
        heading = "2026-04-01 Old implementation diary"
        compressed_note = "- Compressed archived detail (2000 chars; dates: 2026-04-01; refs: scripts/context_usage_prune.py): durable compressed breadcrumb.\n"
        text = f"# Quant Pipeline\n\n## {heading}\n\n{compressed_note}"
        seed_items, _ = self.build(text, {"version": 2, "items": {}})
        compressed_key = self.find_item(seed_items, "section", heading).key
        stale_state = self.state_for([compressed_key])
        stale_state["items"][compressed_key]["firstSeenAt"] = "2026-04-01T00:00:00Z"
        stale_state["items"][compressed_key]["lastSeenAt"] = "2026-04-01T00:00:00Z"
        items, _ = self.build(text, stale_state)

        section = self.find_item(items, "section", heading)
        self.assertEqual(section.classification, "prune_candidate")
        self.assertEqual(section.reason, "compressed-archive-note-aged-unused")

        manifest = prune.apply_pruning(items, "unit-test-compressed-aged", self.deterministic_local_config())
        self.assertEqual(len(manifest["files"]), 1)
        self.assertNotIn(heading, self.project_path.read_text())
        archived = json.loads(Path(manifest["files"][0]["archive"]).read_text())
        self.assertEqual(archived["removed"][0]["replacement_source"], "none")

    def test_high_recall_dated_project_spine_items_do_not_block_pressure_compression(self) -> None:
        dated_heading = "2026-04-01 Frequently used implementation diary"
        dated_body = "- frequently reused detail in scripts/context_usage_prune.py\n" * 80
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        state = self.state_for([state_key])
        state["items"][state_key]["firstSeenAt"] = "2026-04-01T00:00:00Z"
        state["items"][state_key]["lastSeenAt"] = "2026-04-01T00:00:00Z"
        state["items"][state_key]["recallRuns"] = prune.HIGH_USAGE_RECALL_RUNS
        items, _ = self.build(text, state)

        section = self.find_item(items, "section", dated_heading)
        self.assertEqual(section.classification, "prune_candidate")
        self.assertEqual(section.reason, "project-spine-pressure-volatile-section-compress")
        self.assertIn((section.start_line, section.end_line, section.kind), prune.candidate_ranges(items).get("context/projects/quant-pipeline.md", []))

    def test_context_telemetry_preserves_existing_recall_policy_order(self) -> None:
        recalled_heading = "Old recalled follow-up"
        prior_recall_heading = "Old prior recall follow-up"
        gathering_heading = "Old gathering-history follow-up"
        body = "- stale active detail with enough text to cross size gates in scripts/context_usage_prune.py\n" * 40
        self.active_path.write_text(
            f"# Active Workbench Context\n\n"
            f"## {recalled_heading}\n\n{body}\n"
            f"## {prior_recall_heading}\n\n{body}\n"
            f"## {gathering_heading}\n\n{body}",
            encoding="utf-8",
        )
        config = prune.AuditConfig(
            stale_days=10,
            dormant_days=5,
            recent_grace_days=3,
            min_seen_runs_review=2,
            min_seen_runs_prune=3,
            min_unrecalled_runs_review=2,
            min_unrecalled_runs_prune=3,
        )
        seed_items = prune.build_items(NOW, {"version": 2, "items": {}}, config, RUN_BUCKET)
        recalled_seed = self.find_item(seed_items, "section", recalled_heading)
        prior_seed = self.find_item(seed_items, "section", prior_recall_heading)
        gathering_seed = self.find_item(seed_items, "section", gathering_heading)
        state = {"version": 2, "items": {}}
        for item, recall_runs, unrecalled_runs, seen_runs in [
            (recalled_seed, 0, 4, 4),
            (prior_seed, prune.HIGH_USAGE_RECALL_RUNS, 4, 4),
            (gathering_seed, 0, 0, 0),
        ]:
            state["items"][item.key] = {
                "firstSeenAt": "2026-04-01T00:00:00Z",
                "lastSeenAt": "2026-04-01T00:00:00Z",
                "seenRuns": seen_runs,
                "recallRuns": recall_runs,
                "unrecalledRuns": unrecalled_runs,
                "maxCharCount": item.char_count,
            }
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "recalled-now": {
                            "path": "context/active.md",
                            "startLine": recalled_seed.start_line,
                            "endLine": recalled_seed.end_line,
                            "signalCount": 2,
                            "lastSeenAt": "2026-05-20T10:00:00Z",
                            "protectsFromPrune": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        items = prune.build_items(NOW, state, config, RUN_BUCKET)

        recalled = self.find_item(items, "section", recalled_heading)
        self.assertEqual(recalled.classification, "keep")
        self.assertEqual(recalled.reason, "recalled:1/2")
        self.assertEqual(recalled.unrecalled_runs, 0)

        prior_recall = self.find_item(items, "section", prior_recall_heading)
        self.assertEqual(prior_recall.recall_hits, 0)
        self.assertEqual(prior_recall.recall_signal_count, 0)
        self.assertEqual(prior_recall.classification, "keep")
        self.assertEqual(prior_recall.reason, "high-recall-protected")

        gathering = self.find_item(items, "section", gathering_heading)
        self.assertEqual(gathering.recall_hits, 0)
        self.assertEqual(gathering.recall_signal_count, 0)
        self.assertEqual(gathering.seen_runs, 1)
        self.assertEqual(gathering.unrecalled_runs, 1)
        self.assertEqual(gathering.classification, "keep")
        self.assertEqual(gathering.reason, "gathering-history")

    def test_local_compression_replaces_candidate_by_default(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- case-20260415-abcdef12 durable detail in evaluator/foo.py that needs a tightened summary\n" * 60
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        original = prune.call_local_compressor
        try:
            prune.call_local_compressor = lambda removed, item, config: "Run-aware Brier diary compressed to the durable takeaway for case-20260415-abcdef12 and evaluator/foo.py."
            manifest = prune.apply_pruning(items, "unit-test-local")
        finally:
            prune.call_local_compressor = original

        compressed = self.project_path.read_text()
        self.assertIn("Compressed local summary", compressed)
        self.assertIn("case-20260415-abcdef12", compressed)
        self.assertEqual(manifest["local_compression"]["attempted"], 1)
        self.assertEqual(manifest["local_compression"]["succeeded"], 1)
        archive = Path(manifest["files"][0]["archive"])
        archived = json.loads(archive.read_text())
        self.assertEqual(archived["removed"][0]["replacement_source"], "local_model")

    def test_local_compression_priority_reserves_qwen_lane_for_apply_run(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- case-20260415-abcdef12 durable detail in evaluator/foo.py that needs a tightened summary\n" * 60
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        original = prune.call_local_compressor
        seen_priority_file = []
        try:
            def fake_local(removed: str, item: prune.Item, config: prune.LocalCompressionConfig) -> str:
                self.assertTrue(config.priority)
                self.assertTrue(prune.model_priority_path(config.model).exists())
                seen_priority_file.append(True)
                return "Priority-reserved compression retained case-20260415-abcdef12 and evaluator/foo.py."

            prune.call_local_compressor = fake_local
            manifest = prune.apply_pruning(items, "unit-test-local-priority")
        finally:
            prune.call_local_compressor = original

        self.assertTrue(seen_priority_file)
        self.assertTrue(manifest["local_compression"]["priority"])
        self.assertTrue(manifest["local_compression"]["priority_reserved"])
        self.assertFalse(prune.model_priority_path("qwen3.5:4b").exists())

    def test_non_priority_lock_waits_behind_priority_reservation(self) -> None:
        with prune.LocalModelPriorityReservation("qwen3.5:4b"):
            with self.assertRaises(TimeoutError):
                with prune.LocalModelLock("qwen3.5:4b", 0.0):
                    pass
            with prune.LocalModelLock("qwen3.5:4b", 0.0, priority=True):
                lock_payload = json.loads((prune.MODEL_LOCK_ROOT / "qwen.lock").read_text())
                self.assertTrue(lock_payload["priority"])

        self.assertFalse(prune.model_priority_path("qwen3.5:4b").exists())

    def test_local_compression_can_replace_active_hot_doc_candidate(self) -> None:
        heading = "Old live follow-up"
        body = "- stale active detail about scripts/context_usage_prune.py that should be compacted\n" * 80
        self.active_path.write_text(f"# Active Workbench Context\n\n## {heading}\n\n{body}")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        state_key = self.find_item(seed_items, "section", heading).key
        items, _ = self.build_all(self.state_for([state_key]))

        candidate = self.find_item(items, "section", heading)
        self.assertEqual(candidate.classification, "prune_candidate")
        self.assertEqual(candidate.reason, "persistently-unused-active-hot-doc")

        original = prune.call_local_compressor
        try:
            prune.call_local_compressor = lambda removed, item, config: "Stale active follow-up compressed with scripts/context_usage_prune.py retained."
            manifest = prune.apply_pruning(
                items,
                "unit-test-active-local",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
            )
        finally:
            prune.call_local_compressor = original

        compressed = self.active_path.read_text()
        self.assertIn("Compressed local summary", compressed)
        self.assertIn("scripts/context_usage_prune.py", compressed)
        self.assertEqual(manifest["files"][0]["path"], "context/active.md")
        self.assertEqual(manifest["local_compression"]["succeeded"], 1)

    def test_local_compression_can_replace_workbench_context_historical_candidate(self) -> None:
        heading = "2026-04-01 Old context-pruning implementation diary"
        body = "- old Workbench context detail in scripts/context_usage_prune.py that is no longer hot\n" * 80
        self.workbench_context_path.write_text(f"# Workbench Context System\n\n## {heading}\n\n{body}")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        state_key = self.find_item(seed_items, "section", heading).key
        stale_state = self.state_for([state_key])
        stale_state["items"][state_key]["firstSeenAt"] = "2026-04-01T00:00:00Z"
        stale_state["items"][state_key]["lastSeenAt"] = "2026-04-01T00:00:00Z"
        items, _ = self.build_all(stale_state)

        candidate = self.find_item(items, "section", heading)
        self.assertEqual(candidate.classification, "prune_candidate")
        self.assertEqual(candidate.reason, "persistently-unused-historical")

        original = prune.call_local_compressor
        try:
            prune.call_local_compressor = lambda removed, item, config: "Historical Workbench context-pruning diary compressed; scripts/context_usage_prune.py remains the relevant implementation ref."
            manifest = prune.apply_pruning(
                items,
                "unit-test-workbench-context-local",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
            )
        finally:
            prune.call_local_compressor = original

        compressed = self.workbench_context_path.read_text()
        self.assertIn("Compressed local summary", compressed)
        self.assertIn("scripts/context_usage_prune.py", compressed)
        self.assertEqual(manifest["files"][0]["path"], "context/projects/workbench-context.md")
        self.assertEqual(manifest["local_compression"]["succeeded"], 1)

    def test_workbench_context_stable_section_remains_pinned_not_pruned(self) -> None:
        heading = "Goal"
        body = "stable Workbench context orientation without historical dates\n" * 100
        self.workbench_context_path.write_text(f"# Workbench Context System\n\n## {heading}\n\n{body}")
        seed_items, _ = self.build_all({"version": 2, "items": {}})
        state_key = self.find_item(seed_items, "section", heading).key
        items, _ = self.build_all(self.state_for([state_key]))

        goal = self.find_item(items, "section", heading)
        self.assertEqual(goal.classification, "keep")
        self.assertEqual(goal.reason, "pinned")
        self.assertNotIn((goal.start_line, goal.end_line, goal.kind), prune.candidate_ranges(items).get("context/projects/workbench-context.md", []))

    def test_local_compression_falls_back_when_lock_or_model_fails(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- old implementation detail that is too bulky for the live spine\n" * 60
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        original = prune.call_local_compressor
        try:
            def fail_local(*args, **kwargs):
                raise TimeoutError("local model lock busy")
            prune.call_local_compressor = fail_local
            manifest = prune.apply_pruning(
                items,
                "unit-test-local-fallback",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
            )
        finally:
            prune.call_local_compressor = original

        compressed = self.project_path.read_text()
        self.assertIn("Compressed archived detail", compressed)
        self.assertNotIn("Compressed local summary", compressed)
        self.assertEqual(manifest["local_compression"]["attempted"], 1)
        self.assertEqual(manifest["local_compression"]["fallback"], 1)
        self.assertIn("local model lock busy", manifest["local_compression"]["errors"][0]["error"])

    def test_optional_local_compression_falls_back_when_summary_does_not_shrink(self) -> None:
        dated_heading = "2026-04-15 Compact implementation diary"
        dated_body = "- old implementation detail that is just large enough for local compression\n" * 9
        text = f"# Quant Pipeline\n\n## {dated_heading}\n\n{dated_body}"
        state_key = f"section:context/projects/quant-pipeline.md:{prune.slugify(dated_heading)}"
        items, _ = self.build(text, self.state_for([state_key]))

        original = prune.call_local_compressor
        try:
            def non_shrinking_local(*args, **kwargs):
                return "local summary that is intentionally too long to shrink the removed block. " * 30
            prune.call_local_compressor = non_shrinking_local
            manifest = prune.apply_pruning(
                items,
                "unit-test-local-non-shrinking",
                prune.LocalCompressionConfig(
                    enabled=True,
                    model="qwen3.5:4b",
                    ollama_url="http://127.0.0.1:11434/api/generate",
                    max_blocks=1,
                    timeout_seconds=1,
                    lock_timeout_seconds=0.0,
                    max_summary_chars=700,
                ),
            )
        finally:
            prune.call_local_compressor = original

        compressed = self.project_path.read_text()
        self.assertIn("Compressed archived detail", compressed)
        self.assertNotIn("Compressed local summary", compressed)
        self.assertEqual(manifest["local_compression"]["attempted"], 1)
        self.assertEqual(manifest["local_compression"]["succeeded"], 0)
        self.assertEqual(manifest["local_compression"]["fallback"], 1)
        self.assertEqual(manifest["local_compression"]["errors"][0]["error"], "local_compression_non_shrinking")

    def test_priority_request_ignores_dead_pid_reservation(self) -> None:
        path = prune.model_priority_path("qwen3.5:4b")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "created_at": prune.now_iso(),
                    "created_at_epoch": datetime.now(timezone.utc).timestamp(),
                    "model": "qwen3.5:4b",
                    "owner": "unit-test",
                    "pid": 999999,
                },
                sort_keys=True,
            )
            + "\n"
        )

        self.assertFalse(prune.priority_request_active(path))
        self.assertFalse(path.exists())

    def test_priority_request_keeps_live_pid_reservation(self) -> None:
        path = prune.model_priority_path("qwen3.5:4b")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "created_at": prune.now_iso(),
                    "created_at_epoch": datetime.now(timezone.utc).timestamp(),
                    "model": "qwen3.5:4b",
                    "owner": "unit-test",
                    "pid": os.getpid(),
                },
                sort_keys=True,
            )
            + "\n"
        )
        try:
            self.assertTrue(prune.priority_request_active(path))
        finally:
            path.unlink(missing_ok=True)

    def test_local_summary_validation_rejects_new_refs(self) -> None:
        with self.assertRaises(ValueError):
            prune.normalize_local_summary(
                "Summary invents case-20260502-deadbeef and scripts/new_file.py.",
                "Original only mentions case-20260415-abcdef12.",
                700,
            )

    def test_local_summary_validation_rejects_reasoning_text(self) -> None:
        with self.assertRaises(ValueError):
            prune.normalize_local_summary(
                "Thinking Process: analyze the request, then produce a final compressed summary.",
                "Original only mentions scripts/context_usage_prune.py.",
                700,
            )

    def test_local_compression_prompt_disables_thinking_and_omits_container_path(self) -> None:
        item = prune.Item(
            key="k",
            kind="section",
            path="context/projects/workbench-context.md",
            section_heading="2026-04-01 Old note",
            heading_level=2,
            start_line=1,
            end_line=3,
            char_count=600,
            text_hash="h",
            explicit_dates=[],
            recall_hits=0,
            recall_signal_count=0,
            last_recalled_at=None,
            age_days=10,
            pinned=False,
            seen_runs=3,
            recall_runs=0,
            unrecalled_runs=3,
            classification="prune_candidate",
            reason="persistently-unused-historical",
        )
        _system, prompt = prune.build_local_compression_prompt(item, "source mentions scripts/context_usage_prune.py", 700)
        self.assertIn("/no_think", prompt)
        self.assertIn("Discard transient/debug/scratch/command-rerun details", prompt)
        self.assertNotIn("context/projects/workbench-context.md", prompt)

    def test_state_tombstones_are_archived_and_garbage_collected(self) -> None:
        state = {
            "version": 2,
            "items": {
                "old-missing": {
                    "kind": "section",
                    "path": "context/projects/quant-pipeline.md",
                    "lastSeenAt": "2026-04-01T00:00:00Z",
                    "firstMissingAt": "2026-04-10T00:00:00Z",
                    "lastMissingAt": "2026-04-30T00:00:00Z",
                }
            },
        }

        updated = prune.update_state(state, [], NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        self.assertNotIn("old-missing", updated["items"])
        self.assertEqual(updated["lastTombstoneGcRemoved"], 1)
        archive = Path(updated["lastTombstoneArchive"])
        self.assertTrue(archive.exists())
        archived = json.loads(archive.read_text())
        self.assertIn("old-missing", archived["removed"])

    def test_report_surfaces_bounded_evidence_diagnostics(self) -> None:
        strong_items = [
            self.synthetic_item(
                f"strong-{idx}",
                heading=f"Strong evidence {idx}",
                classification="keep",
                reason="recalled:1/1",
                evidence_class="strong_targeted",
                strong=1,
                char_count=1000 + idx,
                start_line=idx * 10 + 1,
            )
            for idx in range(12)
        ]
        medium_pressure = self.synthetic_item(
            "medium-pressure",
            heading="Medium pressure",
            classification="prune_candidate",
            reason="project-spine-pressure-volatile-section-compress",
            evidence_class="medium_targeted",
            medium=1,
            char_count=800,
            start_line=200,
        )
        weak_active = self.synthetic_item(
            "weak-active",
            path="context/active.md",
            heading="Weak active",
            classification="prune_candidate",
            reason="persistently-unused-active-hot-doc",
            evidence_class="weak_or_broad_only",
            weak_broad=1,
            char_count=700,
            start_line=300,
        )
        invalid_unknown = self.synthetic_item(
            "invalid-unknown",
            heading="Invalid evidence",
            classification="keep",
            reason="small-or-benign",
            evidence_class="invalid_or_unknown",
            char_count=100,
            start_line=400,
        )
        items = strong_items + [medium_pressure, weak_active, invalid_unknown]
        state = {"version": 2, "updatedAt": NOW.isoformat().replace("+00:00", "Z"), "items": {}}

        report = prune.build_report(items, state, self.config(), shadow_state=state, run_bucket=RUN_BUCKET)

        self.assertIn("## Evidence diagnostics", report)
        self.assertIn("'strong_targeted': 12", report)
        self.assertIn("'medium_targeted': 1", report)
        self.assertIn("'weak_or_broad_only': 1", report)
        self.assertIn("'invalid_or_unknown': 1", report)
        self.assertIn("strong-targeted protected items: 12", report)
        self.assertIn("medium-evidence pressure/compression eligible items: 1", report)
        self.assertIn("weak/broad review-eligible items: 1", report)
        self.assertIn("invalid/unknown evidence items: 1", report)
        strong_section = report.split("### Top strong protected evidence items", 1)[1].split("### Weak/broad stale active candidates", 1)[0]
        self.assertEqual(strong_section.count("\n- `"), 10)
        self.assertIn("Strong evidence 11", strong_section)
        self.assertNotIn("Strong evidence 0", strong_section)
        weak_section = report.split("### Weak/broad stale active candidates", 1)[1].split("### Medium project-spine pressure candidates", 1)[0]
        self.assertIn("`context/active.md`", weak_section)
        medium_section = report.split("### Medium project-spine pressure candidates", 1)[1].split("## Hot context budget pressure", 1)[0]
        self.assertIn("project-spine-pressure-volatile-section-compress", medium_section)
        self.assertLessEqual(strong_section.count("\n- `"), 10)
        self.assertLessEqual(weak_section.count("\n- `"), 10)
        self.assertLessEqual(medium_section.count("\n- `"), 10)

    def test_report_names_recall_as_optional_telemetry(self) -> None:
        text = "# Quant Pipeline\n\n## Current active implementation concerns\n\n- small live note\n"
        items, state = self.build(text, {"version": 2, "items": {}})
        state = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        report = prune.build_report(items, state, self.config())

        self.assertIn("dream recall entries loaded: 0", report)
        self.assertIn("context telemetry protective entries loaded: 0 / 0 seen", report)
        self.assertIn("context telemetry covered files: 0", report)
        self.assertIn("items with recall telemetry: 0", report)
        self.assertIn("items with context telemetry: 0", report)
        self.assertIn("items kept because recalled now: 0", report)
        self.assertIn("items high-recall protected: 0", report)
        self.assertIn("telemetry warnings (source/loader): 0/0", report)
        self.assertIn("deterministic retention policy plus recall telemetry", report)

    def test_report_surfaces_context_telemetry_usage_counters(self) -> None:
        text = "# Quant Pipeline\n\n## 2026-04-01 Used diary\n\n- small live note\n"
        prune.CONTEXT_TELEMETRY_PATH.write_text(
            json.dumps(
                {
                    "entries": {
                        "overlap": {
                            "path": "context/projects/quant-pipeline.md",
                            "startLine": 3,
                            "endLine": 3,
                            "signalCount": 3,
                            "lastSeenAt": "2026-05-20T10:00:00Z",
                        }
                    },
                    "warnings": [{"kind": "context_edit", "reason": "edit-newtext-not-found"}],
                }
            ),
            encoding="utf-8",
        )
        items, state = self.build(text, {"version": 2, "items": {}})
        state = prune.update_state(state, items, NOW.isoformat().replace("+00:00", "Z"), RUN_BUCKET)
        report = prune.build_report(items, state, self.config())

        self.assertIn("context telemetry protective entries loaded: 0 / 1 seen", report)
        self.assertIn("context telemetry covered files: 0", report)
        self.assertIn("items with recall telemetry: 0", report)
        self.assertIn("items with context telemetry: 0", report)
        self.assertIn("items kept because recalled now: 0", report)
        self.assertIn("items high-recall protected: 0", report)
        self.assertIn("telemetry warnings (source/loader): 1/0", report)


if __name__ == "__main__":
    unittest.main()
