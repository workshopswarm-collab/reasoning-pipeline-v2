#!/usr/bin/env python3
from __future__ import annotations

import io
import importlib.util
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "git_origin_main_guard.py"

spec = importlib.util.spec_from_file_location("git_origin_main_guard_for_tests", GUARD_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not import {GUARD_PATH}")
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
    return proc


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class GitRepoFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.remote = root / "remote.git"
        self.primary = root / "primary"
        self.other = root / "other"

    def init(self) -> None:
        run_git(self.root, "init", "--bare", str(self.remote))
        self.primary.mkdir()
        run_git(self.primary, "init", "-b", "main")
        run_git(self.primary, "config", "user.email", "test@example.com")
        run_git(self.primary, "config", "user.name", "Test User")
        write(self.primary / "tracked.txt", "base\n")
        run_git(self.primary, "add", "tracked.txt")
        run_git(self.primary, "commit", "-m", "base")
        run_git(self.primary, "remote", "add", "origin", str(self.remote))
        run_git(self.primary, "push", "-u", "origin", "main")

    def clone_other(self) -> None:
        run_git(self.root, "clone", str(self.remote), str(self.other))
        run_git(self.other, "config", "user.email", "test@example.com")
        run_git(self.other, "config", "user.name", "Test User")

    def push_remote_commit(self, filename: str = "remote.txt") -> None:
        if not self.other.exists():
            self.clone_other()
        write(self.other / filename, "remote\n")
        run_git(self.other, "add", filename)
        run_git(self.other, "commit", "-m", "remote change")
        run_git(self.other, "push", "origin", "main")

    def local_commit(self, filename: str = "local.txt") -> None:
        write(self.primary / filename, "local\n")
        run_git(self.primary, "add", filename)
        run_git(self.primary, "commit", "-m", "local change")


class GitOriginMainGuardTests(unittest.TestCase):
    def test_status_reports_ahead_behind_and_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-git-guard-") as tmpdir:
            fixture = GitRepoFixture(Path(tmpdir))
            fixture.init()
            fixture.local_commit()
            fixture.push_remote_commit()
            write(fixture.primary / "dirty.txt", "dirty\n")
            run_git(fixture.primary, "fetch", "origin")

            status = guard.inspect_status(fixture.primary)

            self.assertEqual(status.branch, "main")
            self.assertEqual(status.ahead, 1)
            self.assertEqual(status.behind, 1)
            self.assertTrue(status.dirty)
            self.assertGreaterEqual(status.dirty_path_count, 1)

    def test_reconcile_main_snapshots_dirty_state_and_resets_to_origin(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-git-guard-") as tmpdir:
            fixture = GitRepoFixture(Path(tmpdir))
            fixture.init()
            fixture.local_commit()
            fixture.push_remote_commit()
            write(fixture.primary / "dirty.txt", "dirty\n")
            label = "local-main-before-origin-reconcile-test"

            result = guard.reconcile_main(fixture.primary, apply=True, label=label)

            status = guard.inspect_status(fixture.primary)
            self.assertFalse(status.dirty)
            self.assertEqual(status.ahead, 0)
            self.assertEqual(status.behind, 0)
            self.assertTrue(status.local_head_is_origin_main)
            self.assertFalse(result["snapshot"]["created_branch"])
            self.assertEqual(run_git(fixture.primary, "branch", "--list", "backup/*").stdout, "")

            snapshot_dir = Path(result["snapshot"]["snapshot_dir"])
            self.assertEqual(snapshot_dir.name, label)
            self.assertTrue(snapshot_dir.exists())
            self.assertTrue(str(snapshot_dir).startswith(str((fixture.primary / ".git").resolve())))

            untracked_tar = Path(result["snapshot"]["untracked_tar"])
            with tarfile.open(untracked_tar) as archive:
                self.assertIn("dirty.txt", archive.getnames())

            restored = Path(tmpdir) / "restored-from-bundle"
            run_git(fixture.root, "clone", result["snapshot"]["head_bundle"], str(restored))
            self.assertEqual((restored / "local.txt").read_text(encoding="utf-8"), "local\n")

    def test_pre_push_hook_rejects_non_fast_forward_main_push(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-git-guard-") as tmpdir:
            fixture = GitRepoFixture(Path(tmpdir))
            fixture.init()
            fixture.local_commit()
            fixture.push_remote_commit()
            remote_oid = run_git(fixture.primary, "ls-remote", "origin", "refs/heads/main").stdout.split()[0]
            local_oid = run_git(fixture.primary, "rev-parse", "HEAD").stdout.strip()
            hook_input = f"refs/heads/main {local_oid} refs/heads/main {remote_oid}\n"

            self.assertEqual(guard.pre_push_hook(fixture.primary, stdin_text=hook_input), 1)

            previous_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(hook_input)
                self.assertEqual(
                    guard.main(["--repo", str(fixture.primary), "pre-push-hook", "origin", str(fixture.remote)]),
                    1,
                )
            finally:
                sys.stdin = previous_stdin

    def test_pre_push_hook_rejects_non_main_branch_publish(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-git-guard-") as tmpdir:
            fixture = GitRepoFixture(Path(tmpdir))
            fixture.init()
            local_oid = run_git(fixture.primary, "rev-parse", "HEAD").stdout.strip()
            hook_input = f"refs/heads/topic {local_oid} refs/heads/topic {guard.ZERO_OID}\n"

            self.assertEqual(guard.pre_push_hook(fixture.primary, stdin_text=hook_input), 1)

    def test_push_head_pushes_fast_forward_worktree_and_syncs_primary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openclaw-git-guard-") as tmpdir:
            fixture = GitRepoFixture(Path(tmpdir))
            fixture.init()
            integration = Path(tmpdir) / "integration"
            guard.add_origin_main_worktree(fixture.primary, integration, apply=True)
            run_git(integration, "config", "user.email", "test@example.com")
            run_git(integration, "config", "user.name", "Test User")
            write(integration / "integration.txt", "integration\n")
            run_git(integration, "add", "integration.txt")
            run_git(integration, "commit", "-m", "integration change")

            result = guard.push_head_to_main(integration, apply=True)

            self.assertEqual(result["action"], "push-head-to-main")
            self.assertIn("primary_sync", result)
            primary_status = guard.inspect_status(fixture.primary, do_fetch=True)
            self.assertFalse(primary_status.dirty)
            self.assertEqual(primary_status.ahead, 0)
            self.assertEqual(primary_status.behind, 0)
            self.assertEqual((fixture.primary / "integration.txt").read_text(encoding="utf-8"), "integration\n")


if __name__ == "__main__":
    unittest.main()
