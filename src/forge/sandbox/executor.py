"""Bubblewrap-backed command execution with bounded resources and output."""

import os
import signal
import subprocess
import sys
import sysconfig
import threading
import time
from pathlib import Path
from typing import BinaryIO

from forge.core.contracts import ExecutionResult


class SandboxError(ValueError):
    """Raised when a command cannot be safely executed."""


class BubblewrapSandboxExecutor:
    """Execute Python validation commands in an ephemeral, offline filesystem."""

    def __init__(
        self,
        bwrap_path: Path = Path("/usr/bin/bwrap"),
        prlimit_path: Path = Path("/usr/bin/prlimit"),
        timeout_seconds: int = 120,
        cpu_seconds: int = 60,
        memory_bytes: int = 1_073_741_824,
        file_bytes: int = 52_428_800,
        output_bytes: int = 1_000_000,
        max_processes: int = 64,
        max_open_files: int = 256,
    ) -> None:
        self.bwrap_path = bwrap_path
        self.prlimit_path = prlimit_path
        self.timeout_seconds = timeout_seconds
        self.cpu_seconds = cpu_seconds
        self.memory_bytes = memory_bytes
        self.file_bytes = file_bytes
        self.output_bytes = output_bytes
        self.max_processes = max_processes
        self.max_open_files = max_open_files

    def run(self, root: Path, argv: tuple[str, ...]) -> ExecutionResult:
        """Run one validated Python argv without a shell or persistent workspace writes."""
        workspace = root.resolve(strict=True)
        if not workspace.is_dir() or workspace.is_symlink():
            raise SandboxError("Sandbox root must be a real directory")
        self._validate_configuration()
        command = self._command(workspace, argv)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        truncation = [False, False]
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin"},
                start_new_session=True,
            )
        except OSError as exc:
            raise SandboxError(f"Unable to start sandbox: {type(exc).__name__}") from exc
        if process.stdout is None or process.stderr is None:  # pragma: no cover - Popen contract
            process.kill()
            raise SandboxError("Sandbox output pipes were not created")
        readers = (
            threading.Thread(
                target=self._capture,
                args=(process.stdout, stdout_chunks, truncation, 0),
                daemon=True,
            ),
            threading.Thread(
                target=self._capture,
                args=(process.stderr, stderr_chunks, truncation, 1),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        for reader in readers:
            reader.join(timeout=5)
        duration_ms = round((time.monotonic() - started) * 1000)
        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        if process.returncode != 0 and not timed_out and not stdout:
            if stderr.startswith(("bwrap:", "prlimit:", "/usr/bin/prlimit:")):
                raise SandboxError(f"Sandbox isolation failed: {stderr.strip()[:500]}")
        return ExecutionResult(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_truncated=any(truncation),
        )

    def _validate_configuration(self) -> None:
        for executable, label in (
            (self.bwrap_path, "bubblewrap"),
            (self.prlimit_path, "prlimit"),
        ):
            if not executable.is_absolute() or not executable.is_file():
                raise SandboxError(f"Configured {label} executable is unavailable")
        try:
            self.prlimit_path.relative_to("/usr")
        except ValueError as exc:
            raise SandboxError("Configured prlimit executable must be under /usr") from exc
        limits = (
            self.timeout_seconds,
            self.cpu_seconds,
            self.memory_bytes,
            self.file_bytes,
            self.output_bytes,
            self.max_processes,
            self.max_open_files,
        )
        if any(value < 1 for value in limits):
            raise SandboxError("Sandbox limits must all be positive")

    def _command(self, workspace: Path, argv: tuple[str, ...]) -> tuple[str, ...]:
        if not argv or len(argv) > 64:
            raise SandboxError("Command must contain between 1 and 64 arguments")
        if any(not argument or "\0" in argument or len(argument) > 4096 for argument in argv):
            raise SandboxError("Command contains an invalid argument")
        if sum(map(len, argv)) > 16_384:
            raise SandboxError("Command arguments exceed the size limit")
        if argv[0] not in {"python", "python3"}:
            raise SandboxError("Only the trusted Python runtime may be invoked")

        base_prefix = Path(sys.base_prefix).resolve(strict=True)
        environment_prefix = Path(sys.prefix).resolve(strict=True)
        executable = Path(sys.executable).resolve(strict=True)
        try:
            executable_relative = executable.relative_to(base_prefix)
        except ValueError as exc:
            raise SandboxError("Python executable is outside its base runtime") from exc
        sandbox_python = Path("/opt/python") / executable_relative
        purelib = Path(sysconfig.get_path("purelib")).resolve(strict=True)
        mounts: list[str] = ["--ro-bind", str(base_prefix), "/opt/python"]
        if environment_prefix != base_prefix:
            try:
                purelib_relative = purelib.relative_to(environment_prefix)
            except ValueError as exc:
                raise SandboxError("Python packages are outside the environment prefix") from exc
            mounts.extend(("--ro-bind", str(environment_prefix), "/opt/venv"))
            sandbox_purelib = Path("/opt/venv") / purelib_relative
        else:
            sandbox_purelib = Path("/opt/python") / purelib.relative_to(base_prefix)

        isolation = [
            str(self.bwrap_path),
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--hostname",
            "forge-sandbox",
            "--ro-bind",
            "/usr",
            "/usr",
            *self._compatibility_mounts(),
            *mounts,
            "--overlay-src",
            str(workspace),
            "--tmp-overlay",
            "/workspace",
            "--size",
            str(self.file_bytes),
            "--tmpfs",
            "/tmp",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--chdir",
            "/workspace",
            "--clearenv",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "PATH",
            "/opt/python/bin:/usr/bin:/bin",
            "--setenv",
            "PYTHONPATH",
            str(sandbox_purelib),
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--setenv",
            "PYTHONHASHSEED",
            "0",
            "--setenv",
            "LC_ALL",
            "C.UTF-8",
        ]
        cpu_hard = self.cpu_seconds + 1
        isolation.extend(
            (
                str(self.prlimit_path),
                f"--cpu={self.cpu_seconds}:{cpu_hard}",
                f"--as={self.memory_bytes}:{self.memory_bytes}",
                f"--fsize={self.file_bytes}:{self.file_bytes}",
                f"--nproc={self.max_processes}:{self.max_processes}",
                f"--nofile={self.max_open_files}:{self.max_open_files}",
                "--",
                str(sandbox_python),
                *argv[1:],
            )
        )
        return tuple(isolation)

    @staticmethod
    def _compatibility_mounts() -> tuple[str, ...]:
        arguments: list[str] = []
        for value in ("/bin", "/lib", "/lib64"):
            path = Path(value)
            if not path.exists():
                continue
            if path.is_symlink():
                arguments.extend(("--symlink", os.readlink(path), value))
            else:
                arguments.extend(("--ro-bind", value, value))
        return tuple(arguments)

    def _capture(
        self,
        stream: BinaryIO,
        chunks: list[bytes],
        truncation: list[bool],
        index: int,
    ) -> None:
        captured = 0
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = self.output_bytes - captured
            if remaining > 0:
                chunks.append(chunk[:remaining])
                captured += min(len(chunk), remaining)
            if len(chunk) > remaining:
                truncation[index] = True
