#!/usr/bin/env python3
"""Guard local main against stale GitHub/main reconciliation mistakes.

This tool makes the preferred OpenClaw workflow executable:

- treat origin/main as canonical
- snapshot dirty local main before resetting it
- create integration worktrees from origin/main
- push only clean, fast-forward HEADs to GitHub main
- install a local pre-push hook that rejects unsafe main pushes
"""
from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess
import sys
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ZERO_OID = "0" * 40
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
HOOK_MARKER = "openclaw-git-origin-main-guard"


class GuardError(RuntimeError):
    """Expected guard failure with a user-readable message."""


@dataclass
class GitResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class RepoStatus:
    repo_root: str
    branch: str
    head: str
    origin_main: str | None
    ahead: int
    behind: int
    dirty: bool
    dirty_path_count: int
    can_fast_forward_to_origin_main: bool
    local_head_is_origin_main: bool


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def git(repo: Path, args: Iterable[str], *, check: bool = True, input_text: str | None = None) -> GitResult:
    argv = ["git", *args]
    proc = subprocess.run(
        argv,
        cwd=repo,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result = GitResult(args=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and proc.returncode != 0:
        raise GuardError(f"{' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return result


def repo_root(path: Path) -> Path:
    result = git(path, ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def current_branch(repo: Path) -> str:
    result = git(repo, ["branch", "--show-current"])
    return result.stdout.strip() or "DETACHED"


def rev_parse(repo: Path, ref: str, *, required: bool = True) -> str | None:
    result = git(repo, ["rev-parse", "--verify", ref], check=False)
    if result.returncode != 0:
        if required:
            raise GuardError(f"missing git ref: {ref}")
        return None
    return result.stdout.strip()


def has_dirty_worktree(repo: Path) -> bool:
    return bool(git(repo, ["status", "--porcelain=v1"]).stdout.strip())


def dirty_path_count(repo: Path) -> int:
    output = git(repo, ["status", "--porcelain=v1"]).stdout
    return sum(1 for line in output.splitlines() if line.strip())


def fetch(repo: Path, remote: str = DEFAULT_REMOTE) -> None:
    git(repo, ["fetch", remote])


def ahead_behind(repo: Path, remote_ref: str) -> tuple[int, int]:
    result = git(repo, ["rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"])
    left, right = result.stdout.strip().split()
    return int(left), int(right)


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return git(repo, ["merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode == 0


def guard_state_dir(repo: Path) -> Path:
    common_dir = Path(git(repo, ["rev-parse", "--git-common-dir"]).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    return common_dir.resolve() / "openclaw-git-origin-main-guard"


def snapshot_dir_for(repo: Path, label: str | None) -> Path:
    base = guard_state_dir(repo).resolve()
    name = label or utc_stamp()
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise GuardError("snapshot label must be a relative path without '..'")
    target = (base / name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise GuardError("snapshot label escapes guard snapshot directory")
    if target.exists():
        raise GuardError(f"snapshot already exists: {target}")
    return target


def write_git_output(repo: Path, args: list[str], path: Path) -> int:
    result = git(repo, args)
    path.write_text(result.stdout, encoding="utf-8")
    return len(result.stdout)


def untracked_files(repo: Path) -> list[Path]:
    output = git(repo, ["ls-files", "--others", "--exclude-standard", "-z"]).stdout
    return [Path(item) for item in output.split("\0") if item]


def tar_untracked_files(repo: Path, paths: list[Path], archive_path: Path) -> None:
    with tarfile.open(archive_path, "w") as archive:
        for rel_path in paths:
            full_path = repo / rel_path
            if full_path.exists():
                archive.add(full_path, arcname=str(rel_path))


def inspect_status(repo: Path, *, remote: str = DEFAULT_REMOTE, branch: str = DEFAULT_BRANCH, do_fetch: bool = False) -> RepoStatus:
    root = repo_root(repo)
    if do_fetch:
        fetch(root, remote)
    remote_ref = f"{remote}/{branch}"
    origin_main = rev_parse(root, remote_ref, required=False)
    ahead, behind = ahead_behind(root, remote_ref) if origin_main else (0, 0)
    head = rev_parse(root, "HEAD")
    return RepoStatus(
        repo_root=str(root),
        branch=current_branch(root),
        head=head or "",
        origin_main=origin_main,
        ahead=ahead,
        behind=behind,
        dirty=has_dirty_worktree(root),
        dirty_path_count=dirty_path_count(root),
        can_fast_forward_to_origin_main=bool(head and origin_main and is_ancestor(root, head, origin_main)),
        local_head_is_origin_main=bool(head and origin_main and head == origin_main),
    )


def snapshot_local_main(
    repo: Path,
    *,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    label: str | None = None,
) -> dict[str, object]:
    root = repo_root(repo)
    status = inspect_status(root, remote=remote, branch=branch)
    if status.branch != branch:
        raise GuardError(f"snapshot requires current branch {branch!r}; current branch is {status.branch!r}")

    target = snapshot_dir_for(root, label)
    target.mkdir(parents=True)

    (target / "status-before.json").write_text(json.dumps(asdict(status), indent=2, sort_keys=True), encoding="utf-8")
    write_git_output(root, ["status", "--branch", "--short"], target / "status-before.txt")
    staged_bytes = write_git_output(root, ["diff", "--binary", "--cached"], target / "staged.patch")
    unstaged_bytes = write_git_output(root, ["diff", "--binary"], target / "unstaged.patch")

    untracked = untracked_files(root)
    untracked_archive = target / "untracked.tar"
    if untracked:
        tar_untracked_files(root, untracked, untracked_archive)
    (target / "untracked-files.txt").write_text(
        "".join(f"{path.as_posix()}\n" for path in untracked),
        encoding="utf-8",
    )

    head_bundle = target / "local-head.bundle"
    bundle_created = status.ahead > 0 or not status.local_head_is_origin_main
    if bundle_created:
        git(root, ["bundle", "create", str(head_bundle), "HEAD"])

    return {
        "snapshot_dir": str(target),
        "head": status.head,
        "origin_main": status.origin_main,
        "staged_patch": str(target / "staged.patch"),
        "staged_patch_bytes": staged_bytes,
        "unstaged_patch": str(target / "unstaged.patch"),
        "unstaged_patch_bytes": unstaged_bytes,
        "untracked_tar": str(untracked_archive) if untracked else None,
        "untracked_count": len(untracked),
        "head_bundle": str(head_bundle) if bundle_created else None,
        "created_branch": False,
    }


def reconcile_main(
    repo: Path,
    *,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    apply: bool = False,
    label: str | None = None,
) -> dict[str, object]:
    root = repo_root(repo)
    fetch(root, remote)
    status = inspect_status(root, remote=remote, branch=branch)
    if status.branch != branch:
        raise GuardError(f"reconcile requires current branch {branch!r}; current branch is {status.branch!r}")
    needs_snapshot = status.dirty or status.ahead > 0
    plan: dict[str, object] = {
        "action": "reconcile-main",
        "apply": apply,
        "status_before": asdict(status),
        "would_snapshot": needs_snapshot,
        "would_reset_to": status.origin_main,
    }
    if not apply:
        return plan

    if needs_snapshot:
        plan["snapshot"] = snapshot_local_main(root, remote=remote, branch=branch, label=label)
    git(root, ["switch", branch])
    git(root, ["reset", "--hard", f"{remote}/{branch}"])
    git(root, ["clean", "-fd"])
    status_after = inspect_status(root, remote=remote, branch=branch)
    plan["status_after"] = asdict(status_after)
    if status_after.dirty or not status_after.local_head_is_origin_main:
        raise GuardError("reconcile did not leave local main clean at origin/main")
    return plan


def add_origin_main_worktree(repo: Path, path: Path, *, remote: str = DEFAULT_REMOTE, branch: str = DEFAULT_BRANCH, apply: bool = False) -> dict[str, object]:
    root = repo_root(repo)
    fetch(root, remote)
    target = path.expanduser().resolve()
    plan = {
        "action": "add-origin-main-worktree",
        "apply": apply,
        "path": str(target),
        "base": rev_parse(root, f"{remote}/{branch}"),
    }
    if target.exists():
        raise GuardError(f"worktree path already exists: {target}")
    if not apply:
        return plan
    git(root, ["worktree", "add", "--detach", str(target), f"{remote}/{branch}"])
    return plan


def find_branch_worktree(repo: Path, *, branch: str = DEFAULT_BRANCH) -> Path | None:
    result = git(repo, ["worktree", "list", "--porcelain"])
    current_path: Path | None = None
    for raw in result.stdout.splitlines():
        if raw.startswith("worktree "):
            current_path = Path(raw.removeprefix("worktree ")).resolve()
        elif raw == f"branch refs/heads/{branch}" and current_path is not None:
            return current_path
    return None


def require_clean_fast_forward_push(repo: Path, *, remote: str = DEFAULT_REMOTE, branch: str = DEFAULT_BRANCH) -> dict[str, object]:
    root = repo_root(repo)
    fetch(root, remote)
    if has_dirty_worktree(root):
        raise GuardError("refusing to push from a dirty worktree")
    head = rev_parse(root, "HEAD") or ""
    remote_ref = f"{remote}/{branch}"
    remote_head = rev_parse(root, remote_ref) or ""
    if head == remote_head:
        raise GuardError(f"nothing to push: HEAD already equals {remote_ref}")
    if not is_ancestor(root, remote_head, head):
        raise GuardError(f"refusing stale/non-fast-forward push: {remote_ref} is not an ancestor of HEAD")
    return {"head": head, "remote_head": remote_head, "remote_ref": remote_ref}


def push_head_to_main(
    repo: Path,
    *,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    apply: bool = False,
    sync_primary: Path | None = None,
) -> dict[str, object]:
    root = repo_root(repo)
    push_plan = require_clean_fast_forward_push(root, remote=remote, branch=branch)
    plan: dict[str, object] = {"action": "push-head-to-main", "apply": apply, **push_plan}
    if not apply:
        return plan
    git(root, ["push", remote, f"HEAD:{branch}"])
    fetch(root, remote)
    primary = sync_primary or find_branch_worktree(root, branch=branch)
    if primary is not None:
        plan["primary_sync"] = reconcile_main(primary, remote=remote, branch=branch, apply=True)
    return plan


def install_pre_push_hook(repo: Path, *, apply: bool = False) -> dict[str, object]:
    root = repo_root(repo)
    hook_path = Path(git(root, ["rev-parse", "--git-path", "hooks/pre-push"]).stdout.strip())
    if not hook_path.is_absolute():
        hook_path = root / hook_path
    hook_text = f"""#!/bin/sh
# {HOOK_MARKER}
repo_root=$(git rev-parse --show-toplevel) || exit 1
exec python3 "$repo_root/maintenance/git_origin_main_guard.py" pre-push-hook "$@"
"""
    plan: dict[str, object] = {"action": "install-pre-push-hook", "apply": apply, "hook_path": str(hook_path)}
    existing = hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""
    if existing == hook_text:
        plan["status"] = "already_installed"
        return plan
    if existing and HOOK_MARKER not in existing:
        backup = hook_path.with_name(f"pre-push.backup-{utc_stamp()}")
        plan["backup_path"] = str(backup)
        if apply:
            shutil.copy2(hook_path, backup)
    plan["status"] = "would_install" if not apply else "installed"
    if not apply:
        return plan
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(hook_text, encoding="utf-8")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return plan


def pre_push_hook(repo: Path, *, stdin_text: str) -> int:
    root = repo_root(repo)
    errors: list[str] = []
    for raw in stdin_text.splitlines():
        parts = raw.split()
        if len(parts) != 4:
            continue
        local_ref, local_oid, remote_ref, remote_oid = parts
        if remote_ref.startswith("refs/heads/") and remote_ref != "refs/heads/main" and local_oid != ZERO_OID:
            errors.append(f"refusing to publish non-main branch {remote_ref}")
            continue
        if remote_ref != "refs/heads/main":
            continue
        if local_oid == ZERO_OID:
            errors.append("refusing to delete GitHub main")
            continue
        if remote_oid != ZERO_OID and not is_ancestor(root, remote_oid, local_oid):
            errors.append("refusing non-fast-forward push to GitHub main")
        if current_branch(root) == "main" and has_dirty_worktree(root):
            errors.append("refusing push to GitHub main from dirty local main")
    if errors:
        for error in errors:
            print(f"openclaw git guard: {error}", file=sys.stderr)
        print("Use maintenance/git_origin_main_guard.py status or push-head after reconciling.", file=sys.stderr)
        return 1
    return 0


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard OpenClaw origin/main workflow")
    parser.add_argument("--repo", default=".", help="Repository/worktree path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Report local-vs-origin/main safety state")
    status_parser.add_argument("--fetch", action="store_true", help="Fetch origin before status")

    reconcile_parser = subparsers.add_parser("reconcile-main", help="Snapshot dirty local main to files and reset it to origin/main")
    reconcile_parser.add_argument("--apply", action="store_true", help="Actually snapshot/reset; otherwise dry-run")
    reconcile_parser.add_argument("--label", help="Explicit snapshot directory label")

    worktree_parser = subparsers.add_parser("add-worktree", help="Create a detached worktree based on origin/main")
    worktree_parser.add_argument("path")
    worktree_parser.add_argument("--apply", action="store_true")

    push_parser = subparsers.add_parser("push-head", help="Push clean fast-forward HEAD to GitHub main")
    push_parser.add_argument("--apply", action="store_true")
    push_parser.add_argument("--sync-primary", help="Primary checkout to reconcile after successful push")

    hook_parser = subparsers.add_parser("install-hook", help="Install local pre-push guard hook")
    hook_parser.add_argument("--apply", action="store_true")

    hook_runtime_parser = subparsers.add_parser("pre-push-hook", help=argparse.SUPPRESS)
    hook_runtime_parser.add_argument("hook_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    try:
        if args.command == "status":
            print_json(asdict(inspect_status(repo, do_fetch=bool(args.fetch))))
        elif args.command == "reconcile-main":
            print_json(reconcile_main(repo, apply=bool(args.apply), label=args.label))
        elif args.command == "add-worktree":
            print_json(add_origin_main_worktree(repo, Path(args.path), apply=bool(args.apply)))
        elif args.command == "push-head":
            sync_primary = Path(args.sync_primary).expanduser().resolve() if args.sync_primary else None
            print_json(push_head_to_main(repo, apply=bool(args.apply), sync_primary=sync_primary))
        elif args.command == "install-hook":
            print_json(install_pre_push_hook(repo, apply=bool(args.apply)))
        elif args.command == "pre-push-hook":
            return pre_push_hook(repo, stdin_text=sys.stdin.read())
        else:
            parser.error(f"unsupported command: {args.command}")
    except GuardError as exc:
        print(f"openclaw git guard: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
