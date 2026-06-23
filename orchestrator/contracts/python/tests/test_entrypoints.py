from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

CONTRACTS_PYTHON = Path(__file__).resolve().parents[1]
if str(CONTRACTS_PYTHON) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_PYTHON))

from openclaw_contracts.entrypoints import all_entrypoints, resolve_entrypoint


class EntrypointResolverTests(unittest.TestCase):
    def test_current_layout_entrypoints_resolve(self) -> None:
        missing: list[str] = []
        for entrypoint in all_entrypoints():
            try:
                resolved = resolve_entrypoint(entrypoint.id)
            except FileNotFoundError:
                missing.append(entrypoint.id)
                continue
            self.assertTrue(resolved.exists(), entrypoint.id)
        self.assertEqual(missing, [])

    def test_synthetic_layout_prefers_first_candidates_without_roles_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for entrypoint in all_entrypoints():
                first = entrypoint.candidates[0].resolve(openclaw_base=base)
                if entrypoint.kind == "directory":
                    first.mkdir(parents=True, exist_ok=True)
                else:
                    first.parent.mkdir(parents=True, exist_ok=True)
                    first.write_text("# fake entrypoint\n")

            for entrypoint in all_entrypoints():
                resolved = resolve_entrypoint(entrypoint.id, openclaw_base=base)
                expected = entrypoint.candidates[0].resolve(openclaw_base=base)
                self.assertEqual(resolved, expected)
                self.assertNotIn("/roles/", resolved.as_posix())

    def test_entrypoints_have_no_legacy_roles_fallbacks(self) -> None:
        for entrypoint in all_entrypoints():
            for candidate in entrypoint.candidates:
                self.assertNotIn("/roles/", f"/{candidate.relative}")

    def test_device_b_entrypoints_prefer_top_level_scripts(self) -> None:
        self.assertEqual(
            resolve_entrypoint("device_b.intake_filter"),
            Path(__file__).resolve().parents[4] / "device-b" / "scripts" / "1_intake_filter.py",
        )
        self.assertEqual(
            resolve_entrypoint("device_b.db_ingest"),
            Path(__file__).resolve().parents[4] / "device-b" / "scripts" / "3_db_ingest_script.py",
        )

    def test_unknown_entrypoint_is_an_error(self) -> None:
        with self.assertRaises(KeyError):
            resolve_entrypoint("missing.entrypoint")


if __name__ == "__main__":
    unittest.main()
