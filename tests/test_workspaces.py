"""Phase 4 isolated worktree and audited patch tests."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forge.apps.api import app, get_sandbox_executor, get_worktree_manager
from forge.core.contracts import ExecutionResult, Patch
from forge.sandbox import SandboxError
from forge.workspaces import AuditedPatchManager, GitWorktreeManager


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(("git", "-C", str(root), *arguments), check=True, capture_output=True)


def _committed_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "forge@example.com")
    _git(root, "config", "user.name", "Forge Tests")
    (root / "service.py").write_text("def register(email: str) -> str:\n    return email\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_service.py").write_text(
        "from service import register\n\ndef test_register() -> None:\n"
        "    assert register('A@example.com') == 'A@example.com'\n"
    )
    (root / "README.txt").write_text("original\n")
    (root / ".gitattributes").write_text("*.txt filter=evil\n")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "initial")
    return root


def _ready_task(client: TestClient, root: Path) -> str:
    repository = client.post("/repositories/register", json={"path": str(root)}).json()
    assert client.post(f"/repositories/{repository['id']}/index").status_code == 200
    task = client.post(
        "/tasks",
        json={"repository_id": repository["id"], "objective": "Fix registration"},
    ).json()
    assert client.post(f"/tasks/{task['id']}/plan").status_code == 200
    return task["id"]


def test_workspace_disables_hooks_and_materializes_committed_files(tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    hook_marker = tmp_path / "hook-ran"
    filter_marker = tmp_path / "filter-ran"
    hook = root / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch '{hook_marker}'\n")
    hook.chmod(0o755)
    _git(
        root,
        "config",
        "filter.evil.smudge",
        f"sh -c \"touch '{filter_marker}'; cat\"",
    )

    manager = GitWorktreeManager(tmp_path / "worktrees")
    workspace = manager.create(root, "workspace-one")

    assert (workspace.path / "service.py").read_text().startswith("def register")
    assert (workspace.path / "README.txt").read_text() == "original\n"
    assert not hook_marker.exists()
    assert not filter_marker.exists()
    manager.remove(root, workspace.path)
    assert not workspace.path.exists()


def test_workspace_api_applies_and_audits_optimistic_patches(
    client: TestClient, tmp_path: Path
) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "managed-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        created = client.post(f"/tasks/{task_id}/workspace")
        assert created.status_code == 201
        workspace = created.json()
        workspace_path = Path(workspace["path"])
        assert workspace["status"] == "ACTIVE"

        original = (workspace_path / "service.py").read_bytes()
        before_hash = hashlib.sha256(original).hexdigest()
        replacement = "def register(email: str) -> str:\n    return email.lower()\n"
        applied = client.post(
            f"/tasks/{task_id}/patches",
            json={
                "file_path": "service.py",
                "operation": "UPDATE",
                "before_hash": before_hash,
                "content": replacement,
                "reason": "Normalize registration email",
            },
        )
        assert applied.status_code == 201
        patch = applied.json()
        assert patch["before_hash"] == before_hash
        assert patch["after_hash"] == hashlib.sha256(replacement.encode()).hexdigest()
        assert (workspace_path / "service.py").read_text() == replacement
        assert (root / "service.py").read_bytes() == original

        conflict = client.post(
            f"/tasks/{task_id}/patches",
            json={
                "file_path": "service.py",
                "operation": "UPDATE",
                "before_hash": before_hash,
                "content": "unexpected\n",
                "reason": "Use a stale hash",
            },
        )
        assert conflict.status_code == 409
        assert (workspace_path / "service.py").read_text() == replacement

        escaped = client.post(
            f"/tasks/{task_id}/patches",
            json={
                "file_path": "../escape.py",
                "operation": "CREATE",
                "content": "unsafe\n",
                "reason": "Escape workspace",
            },
        )
        assert escaped.status_code == 422
        assert not (tmp_path / "escape.py").exists()

        records = client.get(f"/tasks/{task_id}/patches").json()
        assert [item["id"] for item in records] == [patch["id"]]

        removed = client.delete(f"/tasks/{task_id}/workspace")
        assert removed.status_code == 200
        assert removed.json()["status"] == "REMOVED"
        assert not workspace_path.exists()
        assert len(client.get(f"/tasks/{task_id}/patches").json()) == 1
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_workspace_rejects_stale_plan(client: TestClient, tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "stale-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        (root / "service.py").write_text("def changed() -> None:\n    pass\n")
        repository_id = client.get(f"/tasks/{task_id}").json()["repository_id"]
        client.post(f"/repositories/{repository_id}/index")

        response = client.post(f"/tasks/{task_id}/workspace")

        assert response.status_code == 409
        assert response.json()["detail"] == "Task plan is stale and must be refreshed"
        assert not (tmp_path / "stale-worktrees").exists()
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_workspace_rejects_commit_made_after_index(client: TestClient, tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "advanced-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        (root / "service.py").write_text("def register() -> str:\n    return 'changed'\n")
        _git(root, "add", "service.py")
        _git(root, "commit", "--quiet", "-m", "advance after planning")

        response = client.post(f"/tasks/{task_id}/workspace")

        assert response.status_code == 409
        assert response.json()["detail"] == "Repository index is stale and must be refreshed"
        assert not (tmp_path / "advanced-worktrees").exists()
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_worktree_manager_rejects_dirty_source(tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    (root / "untracked.txt").write_text("not committed\n")
    manager = GitWorktreeManager(tmp_path / "dirty-worktrees")

    with pytest.raises(ValueError, match="must be clean"):
        manager.create(root, "dirty")

    assert not (tmp_path / "dirty-worktrees" / "dirty").exists()


def test_patch_update_preserves_executable_mode(client: TestClient, tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    script = root / "run.py"
    script.write_text("#!/usr/bin/env python3\nprint('old')\n")
    script.chmod(0o755)
    _git(root, "add", "run.py")
    _git(root, "commit", "--quiet", "-m", "add executable")
    manager = GitWorktreeManager(tmp_path / "mode-worktrees")
    workspace = manager.create(root, "mode-test")
    try:
        target = workspace.path / "run.py"
        before_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        AuditedPatchManager().apply(
            workspace.path,
            Patch(
                Path("run.py"),
                "UPDATE",
                before_hash,
                "Update executable",
                b"#!/usr/bin/env python3\nprint('new')\n",
            ),
        )
        mode = os.stat(target).st_mode
        assert mode & 0o111
    finally:
        manager.remove(root, workspace.path)


def test_execution_api_runs_only_planned_commands(client: TestClient, tmp_path: Path) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "execution-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        workspace = client.post(f"/tasks/{task_id}/workspace").json()

        denied = client.post(
            f"/tasks/{task_id}/executions",
            json={"argv": ["python", "-c", "print('not planned')"]},
        )
        assert denied.status_code == 403

        executed = client.post(
            f"/tasks/{task_id}/executions",
            json={"argv": ["python", "-m", "pytest"]},
        )
        assert executed.status_code == 201
        result = executed.json()
        assert result["status"] == "FINISHED"
        assert result["exit_code"] == 0
        assert "1 passed" in result["stdout"]
        assert result["timed_out"] is False
        assert client.get(f"/tasks/{task_id}").json()["status"] == "READY"
        assert not (Path(workspace["path"]) / ".pytest_cache").exists()

        records = client.get(f"/tasks/{task_id}/executions").json()
        assert [item["id"] for item in records] == [result["id"]]
        client.delete(f"/tasks/{task_id}/workspace")
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_verification_passes_all_gates_and_marks_task_verified(
    client: TestClient, tmp_path: Path
) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "verified-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        client.post(f"/tasks/{task_id}/workspace")

        response = client.post(f"/tasks/{task_id}/verify")

        assert response.status_code == 201
        verification = response.json()
        assert verification["status"] == "PASSED"
        assert verification["summary"] == "All 1 verification commands passed."
        assert verification["failed_attempts"] == 0
        assert len(verification["executions"]) == 1
        assert verification["executions"][0]["exit_code"] == 0
        assert client.get(f"/tasks/{task_id}").json()["status"] == "VERIFIED"
        assert client.post(f"/tasks/{task_id}/verify").status_code == 409
        assert len(client.get(f"/tasks/{task_id}/verifications").json()) == 1
        client.delete(f"/tasks/{task_id}/workspace")
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_failed_verification_passes_after_audited_repair(
    client: TestClient, tmp_path: Path
) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "successful-repair-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        workspace = client.post(f"/tasks/{task_id}/workspace").json()
        target = Path(workspace["path"]) / "service.py"
        broken = "def register(email: str) -> str:\n    return email.lower()\n"
        client.post(
            f"/tasks/{task_id}/patches",
            json={
                "file_path": "service.py",
                "operation": "UPDATE",
                "before_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                "content": broken,
                "reason": "Initial implementation",
            },
        )
        assert client.post(f"/tasks/{task_id}/verify").json()["status"] == "FAILED"

        repaired = "def register(email: str) -> str:\n    return email\n"
        patch = client.post(
            f"/tasks/{task_id}/patches",
            json={
                "file_path": "service.py",
                "operation": "UPDATE",
                "before_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                "content": repaired,
                "reason": "Repair failed registration behavior",
            },
        )
        assert patch.status_code == 201

        passed = client.post(f"/tasks/{task_id}/verify").json()
        assert passed["status"] == "PASSED"
        assert passed["attempt_number"] == 2
        assert passed["failed_attempts"] == 1
        assert client.get(f"/tasks/{task_id}").json()["status"] == "VERIFIED"
        client.delete(f"/tasks/{task_id}/workspace")
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_failed_verification_requires_a_patch_and_exhausts_repair_budget(
    client: TestClient, tmp_path: Path
) -> None:
    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "repair-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    try:
        task_id = _ready_task(client, root)
        workspace = client.post(f"/tasks/{task_id}/workspace").json()
        target = Path(workspace["path"]) / "service.py"

        for attempt_number in range(1, 4):
            content = (
                "def register(email: str) -> str:\n"
                f"    return email.lower()  # failed repair {attempt_number}\n"
            )
            patched = client.post(
                f"/tasks/{task_id}/patches",
                json={
                    "file_path": "service.py",
                    "operation": "UPDATE",
                    "before_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "content": content,
                    "reason": f"Repair attempt {attempt_number}",
                },
            )
            assert patched.status_code == 201

            failed = client.post(f"/tasks/{task_id}/verify")
            assert failed.status_code == 201
            result = failed.json()
            assert result["status"] == "FAILED"
            assert result["failed_attempts"] == attempt_number
            assert result["failed_attempts_remaining"] == 3 - attempt_number
            if attempt_number == 1:
                unchanged = client.post(f"/tasks/{task_id}/verify")
                assert unchanged.status_code == 409
                assert "new audited patch" in unchanged.json()["detail"]

        assert client.get(f"/tasks/{task_id}").json()["status"] == "BLOCKED"
        attempts = client.get(f"/tasks/{task_id}/verifications").json()
        assert [item["attempt_number"] for item in attempts] == [1, 2, 3]
        client.delete(f"/tasks/{task_id}/workspace")
    finally:
        app.dependency_overrides.pop(get_worktree_manager, None)


def test_verification_infrastructure_error_is_retryable(client: TestClient, tmp_path: Path) -> None:
    class FailingExecutor:
        def run(self, root: Path, argv: tuple[str, ...]) -> ExecutionResult:
            raise SandboxError("isolator unavailable")

    root = _committed_project(tmp_path)
    manager = GitWorktreeManager(tmp_path / "retry-worktrees")
    app.dependency_overrides[get_worktree_manager] = lambda: manager
    app.dependency_overrides[get_sandbox_executor] = lambda: FailingExecutor()
    try:
        task_id = _ready_task(client, root)
        client.post(f"/tasks/{task_id}/workspace")

        errored = client.post(f"/tasks/{task_id}/verify")

        assert errored.status_code == 201
        assert errored.json()["status"] == "ERROR"
        assert errored.json()["failed_attempts"] == 0
        assert client.get(f"/tasks/{task_id}").json()["status"] == "READY"

        app.dependency_overrides.pop(get_sandbox_executor, None)
        retried = client.post(f"/tasks/{task_id}/verify")
        assert retried.status_code == 201
        assert retried.json()["status"] == "PASSED"
        assert retried.json()["attempt_number"] == 2
        client.delete(f"/tasks/{task_id}/workspace")
    finally:
        app.dependency_overrides.pop(get_sandbox_executor, None)
        app.dependency_overrides.pop(get_worktree_manager, None)
