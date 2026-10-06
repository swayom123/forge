# Repository intelligence security

Repositories are untrusted data. Phase 2 reads selected files but never imports modules, invokes Git, runs package scripts, executes build commands, or follows repository instructions.

Traversal excludes Git metadata, virtual environments, dependency trees, caches, build outputs, binary files, oversized files, and non-regular files. Directory and file symlinks are skipped, including links targeting files outside the repository. A configurable policy limits file count and per-file size. Reads check that file size has not changed since admission.

The index stores metadata, hashes, symbols, imports, docstrings, signatures, and parse errors. It does not persist complete source files. Source text search reads only paths already admitted to the index and checks containment, symlink state, and indexed size again.

Phase 3 planning reads only the task objective, persisted profile, and persisted index records. It
does not read source files, follow repository instructions, call a model, or run planned validation
commands. A fingerprint over the profile and indexed file hashes marks saved plans stale after the
repository context changes.

Phase 4 invokes a narrow set of Git builtins to create and remove isolated worktrees. Global and
system Git configuration, credential helpers, interactive prompts, filesystem monitors, and hooks
are disabled. Worktrees use `--no-checkout`; Forge loads regular committed blobs directly, so Git
content filters are not invoked. Symlinks, submodules, unsupported tree entries, excessive file
counts, and excessive aggregate sizes fail workspace creation.
The registered checkout must be clean and must still match its persisted profile and file hashes,
preventing a workspace from being created from code different from the plan's retrieved context.

Patch paths must be relative, remain under the managed worktree, and cannot contain `.git`, `..`,
or symlinks. Updates and deletes require the current SHA-256 hash, writes are atomic, content is
bounded, and audit records retain hashes and reasons rather than full file contents. Removing a
workspace is destructive to that isolated copy but leaves the registered repository and audit
records intact.

Phase 5 runs only exact planned Python validation commands. Bubblewrap removes network access and
host-home visibility, drops capabilities, creates Linux namespaces, and exposes the workspace
through a disposable overlay. The child receives a minimal environment with no inherited secrets.
`prlimit` and a host timeout constrain CPU, memory, file size, processes, descriptors, and elapsed
time; stdout and stderr are drained continuously but persisted only to configured bounds. Missing
or failed isolation primitives cause execution to fail closed. Captured command output is sensitive
local data and may itself contain repository secrets.

The sandbox is not a virtual machine and does not mitigate a host-kernel or Bubblewrap
vulnerability. A production deployment should add a dedicated low-privilege account, seccomp,
cgroups, storage quotas, and an outer VM or container boundary based on its threat model.

Phase 6 permits retries only after an audited patch changes the workspace patch chain. No-op updates
are rejected, failed command runs consume a configured budget, and exhausted tasks become
`BLOCKED`. Isolation infrastructure errors are recorded separately and do not consume the repair
budget. A successful automated gate produces `VERIFIED`, not `COMPLETED`, because automated command
success alone does not establish every behavioral acceptance criterion.

The local API still has no authentication. It should bind to a trusted interface because registered
paths and source-derived metadata are sensitive. Secret detection and provider-boundary redaction
are required before a later phase sends any retrieved content to an external model.
