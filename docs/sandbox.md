# Sandboxed validation commands

Phase 5 executes only exact argument vectors already present in a task's persisted verification
plan. A task must be `READY` and have an active managed workspace. Commands never pass through a
shell, and the executor currently permits only the trusted Python runtime used by Forge.

Linux Bubblewrap creates new user, mount, PID, IPC, UTS, cgroup, and network namespaces. The task
workspace is exposed through a temporary overlay, so tests can write caches and temporary outputs
without changing the audited workspace. The sandbox can read the trusted Python runtime and system
libraries but cannot see the host home directory or registered source checkout. It receives an
empty temporary directory, minimal deterministic environment, no credentials, and no network.

`prlimit` applies configurable CPU, address-space, file-size, process-count, and open-file limits.
Forge separately enforces wall-clock timeout, argument bounds, and bounded stdout/stderr capture.
Timeouts terminate the complete process group. Missing isolation binaries or namespace startup
failures are reported as sandbox errors rather than command results.

Every attempt accepted by policy receives a persistent execution record. Records include the exact
arguments, lifecycle status, exit code, bounded stdout/stderr, duration, timeout flag, and output
truncation flag. Running a command temporarily moves its task to `RUNNING`; completion, failure, or
timeout returns it to `READY`. Phase 6 composes these primitive executions into complete verification
attempts and repair budgets; neither phase marks tasks complete without later independent review.

This boundary reduces exposure to untrusted project code but does not protect against vulnerabilities
in the host kernel or Bubblewrap itself. Production deployments should add host-level isolation and
seccomp appropriate to their threat model.
