"""Phase 5 namespace, resource, and output boundary tests."""

from pathlib import Path

import pytest

from forge.sandbox import BubblewrapSandboxExecutor, SandboxError


def test_sandbox_has_no_network_or_host_visibility_and_discards_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "outside-secret"
    secret.write_text("sensitive")
    executor = BubblewrapSandboxExecutor(timeout_seconds=5)
    code = (
        "import socket; from pathlib import Path; "
        f"print(Path({str(secret)!r}).exists()); "
        "Path('ephemeral').write_text('created'); "
        "sock = socket.socket(); print(sock.connect_ex(('1.1.1.1', 53)))"
    )

    result = executor.run(workspace, ("python", "-c", code))

    lines = result.stdout.splitlines()
    assert result.exit_code == 0
    assert lines[0] == "False"
    assert lines[1] != "0"
    assert not (workspace / "ephemeral").exists()


def test_sandbox_times_out_and_truncates_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    timeout_executor = BubblewrapSandboxExecutor(timeout_seconds=1)

    timed_out = timeout_executor.run(workspace, ("python", "-c", "import time; time.sleep(10)"))

    assert timed_out.timed_out is True
    assert timed_out.exit_code != 0
    assert timed_out.duration_ms < 5_000

    bounded_executor = BubblewrapSandboxExecutor(timeout_seconds=5, output_bytes=128)
    bounded = bounded_executor.run(workspace, ("python", "-c", "print('x' * 10000)"))
    assert bounded.output_truncated is True
    assert len(bounded.stdout.encode()) == 128


def test_sandbox_rejects_untrusted_executables_and_missing_isolator(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SandboxError, match="trusted Python"):
        BubblewrapSandboxExecutor().run(workspace, ("sh", "-c", "true"))
    with pytest.raises(SandboxError, match="bubblewrap"):
        BubblewrapSandboxExecutor(bwrap_path=tmp_path / "missing").run(workspace, ("python", "-V"))
