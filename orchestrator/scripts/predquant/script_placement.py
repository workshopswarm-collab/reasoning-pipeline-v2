"""Static runtime script placement checks for ADS v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT_PLACEMENT_MAP = ORCHESTRATOR_ROOT / "plans" / "autonomous-decomposition-swarm-script-placement-map.md"
SCRIPT_PLACEMENT_SCAN_SCHEMA_VERSION = "ads-script-placement-scan/v1"
SCRIPT_PLACEMENT_FIXTURE_ID = "FIX-039"
SCRIPT_PLACEMENT_BLOCKER_ID = "BLK-032"

OWNER_ROOTS = {
    "Orchestrator": Path("/Users/agent2/.openclaw/orchestrator/scripts"),
    "ADS Decomposer": Path("/Users/agent2/.openclaw/decomposer/scripts"),
    "ADS Researcher Swarm": Path("/Users/agent2/.openclaw/researcher-swarm/scripts"),
    "SCAE": Path("/Users/agent2/.openclaw/SCAE/scripts"),
}

SCRIPT_OWNER_HEADINGS = {
    "Orchestrator Scripts": "Orchestrator",
    "Decomposer Scripts": "ADS Decomposer",
    "Researcher Swarm Scripts": "ADS Researcher Swarm",
    "SCAE Scripts": "SCAE",
}

FEATURE_ID_RE = re.compile(r"\b[A-Z]+-\d{3}\b")


class ScriptPlacementError(ValueError):
    """Raised when the script placement map cannot be parsed safely."""


@dataclass(frozen=True)
class ScriptPlacementRow:
    planned_path: str
    expected_owner: str
    owning_features: tuple[str, ...]
    purpose: str
    line_number: int


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _strip_code_cell(cell: str) -> str:
    cell = cell.strip()
    if cell.startswith("`") and cell.endswith("`"):
        return cell[1:-1].strip()
    return cell


def parse_script_placement_map(map_path: Path | str = DEFAULT_SCRIPT_PLACEMENT_MAP) -> list[ScriptPlacementRow]:
    """Parse planned script rows from the canonical placement map."""

    path = Path(map_path)
    if not path.exists():
        raise ScriptPlacementError(f"script placement map does not exist: {path}")

    rows: list[ScriptPlacementRow] = []
    current_owner: str | None = None
    in_planned_paths = False

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped == "## Planned Script Paths":
            in_planned_paths = True
            current_owner = None
            continue
        if in_planned_paths and stripped.startswith("## ") and stripped != "## Planned Script Paths":
            break
        if not in_planned_paths:
            continue
        if stripped.startswith("### "):
            heading = stripped.removeprefix("### ").strip()
            current_owner = SCRIPT_OWNER_HEADINGS.get(heading)
            if current_owner is None:
                raise ScriptPlacementError(f"unrecognized script owner heading on line {line_number}: {heading}")
            continue
        if not stripped.startswith("| `"):
            continue

        if current_owner is None:
            raise ScriptPlacementError(f"planned script row appears before an owner heading on line {line_number}")
        cells = _markdown_cells(line)
        if len(cells) != 3:
            raise ScriptPlacementError(f"planned script row must have three cells on line {line_number}")
        planned_path = _strip_code_cell(cells[0])
        if not planned_path.startswith("/"):
            raise ScriptPlacementError(f"planned script path must be absolute on line {line_number}: {planned_path}")
        rows.append(
            ScriptPlacementRow(
                planned_path=planned_path,
                expected_owner=current_owner,
                owning_features=tuple(FEATURE_ID_RE.findall(cells[1])),
                purpose=cells[2],
                line_number=line_number,
            )
        )

    if not rows:
        raise ScriptPlacementError(f"no planned script paths found in {path}")
    return rows


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def owner_for_path(path: Path | str, owner_roots: dict[str, Path] | None = None) -> str | None:
    """Return the runtime owner root containing a planned path, if known."""

    roots = owner_roots or OWNER_ROOTS
    candidate = Path(path).expanduser()
    for owner, root in roots.items():
        if _path_is_relative_to(candidate, root):
            return owner
    return None


def build_script_placement_report(
    *,
    map_path: Path | str = DEFAULT_SCRIPT_PLACEMENT_MAP,
    owner_roots: dict[str, Path] | None = None,
    require_existing_paths: bool = True,
) -> dict[str, Any]:
    """Build a fail-closed static scan report for planned ADS runtime script paths."""

    roots = owner_roots or OWNER_ROOTS
    rows = parse_script_placement_map(map_path)

    owner_counts: dict[str, int] = {owner: 0 for owner in roots}
    missing_paths: list[dict[str, Any]] = []
    unknown_owner_paths: list[dict[str, Any]] = []
    owner_mismatches: list[dict[str, Any]] = []
    duplicate_paths: list[dict[str, Any]] = []
    seen_paths: dict[str, int] = {}

    for row in rows:
        owner_counts.setdefault(row.expected_owner, 0)
        owner_counts[row.expected_owner] += 1
        actual_owner = owner_for_path(row.planned_path, roots)

        if actual_owner is None:
            unknown_owner_paths.append(
                {
                    "planned_path": row.planned_path,
                    "expected_owner": row.expected_owner,
                    "line_number": row.line_number,
                }
            )
        elif actual_owner != row.expected_owner:
            owner_mismatches.append(
                {
                    "planned_path": row.planned_path,
                    "expected_owner": row.expected_owner,
                    "actual_owner": actual_owner,
                    "line_number": row.line_number,
                }
            )

        if require_existing_paths and not Path(row.planned_path).exists():
            missing_paths.append(
                {
                    "planned_path": row.planned_path,
                    "expected_owner": row.expected_owner,
                    "owning_features": list(row.owning_features),
                    "line_number": row.line_number,
                }
            )

        if row.planned_path in seen_paths:
            duplicate_paths.append(
                {
                    "planned_path": row.planned_path,
                    "first_line_number": seen_paths[row.planned_path],
                    "duplicate_line_number": row.line_number,
                }
            )
        else:
            seen_paths[row.planned_path] = row.line_number

    status = "passed"
    if missing_paths or unknown_owner_paths or owner_mismatches or duplicate_paths:
        status = "failed"

    return {
        "schema_version": SCRIPT_PLACEMENT_SCAN_SCHEMA_VERSION,
        "fixture_id": SCRIPT_PLACEMENT_FIXTURE_ID,
        "blocker_id": SCRIPT_PLACEMENT_BLOCKER_ID,
        "status": status,
        "map_path": str(Path(map_path)),
        "checked_path_count": len(rows),
        "owner_counts": owner_counts,
        "missing_path_count": len(missing_paths),
        "owner_mismatch_count": len(owner_mismatches),
        "unknown_owner_path_count": len(unknown_owner_paths),
        "duplicate_path_count": len(duplicate_paths),
        "missing_paths": missing_paths,
        "owner_mismatches": owner_mismatches,
        "unknown_owner_paths": unknown_owner_paths,
        "duplicate_paths": duplicate_paths,
        "require_existing_paths": require_existing_paths,
        "scan_authority": "static_diagnostic_only",
        "live_cutover_ready": status == "passed",
    }
