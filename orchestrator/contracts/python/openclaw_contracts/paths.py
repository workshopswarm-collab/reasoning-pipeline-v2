from __future__ import annotations

from pathlib import Path


def orchestrator_root() -> Path:
    """Return the current Orchestrator repo/workspace root."""

    return Path(__file__).resolve().parents[3]


def openclaw_root() -> Path:
    """Return the top-level `.openclaw` workspace root."""

    return orchestrator_root().parent


def resolve_root(root_name: str, *, openclaw_base: Path | None = None) -> Path:
    """Resolve a named migration root for production code and tests."""

    base = openclaw_base.resolve() if openclaw_base is not None else openclaw_root()
    if root_name == "openclaw":
        return base
    if root_name == "orchestrator":
        return base / "orchestrator"
    raise KeyError(f"unknown OpenClaw root: {root_name}")


def display_path(path: Path, *, openclaw_base: Path | None = None) -> str:
    """Render a path relative to a useful workspace root when possible."""

    base = openclaw_base.resolve() if openclaw_base is not None else openclaw_root()
    orch = base / "orchestrator"
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(orch))
    except ValueError:
        pass
    try:
        return str(resolved.relative_to(base))
    except ValueError:
        return str(path)
