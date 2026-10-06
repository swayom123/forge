# Isolated workspaces and patch records

Phase 4 gives an editable, current `READY` task one detached Git worktree. Workspace creation is
allowed for implementation, debugging, testing, and documentation tasks. A plan must exist and its
profile/index fingerprint must still be current. The registered checkout must be clean, and its live
profile and indexed Python hashes must still exactly match the stored index.

The workspace is pinned to the registered repository's committed `HEAD`. Forge asks Git to create
the administrative worktree with `--no-checkout`, loads the index with `read-tree`, and writes only
regular committed blobs obtained through `cat-file`. This avoids checkout hooks and configured
content filters. Repositories containing committed symlinks, submodules, non-UTF-8 paths, or trees
over configured limits are rejected instead of being partially materialized.

Patch operations are `CREATE`, `UPDATE`, and `DELETE`. Updates and deletes require the caller's
expected SHA-256 hash; a mismatch returns a conflict without touching the file. Creates require an
absent target. Writes use a same-directory temporary file and atomic replacement while preserving
an updated file's permission bits.

Successful mutations create immutable database records containing the workspace, relative path,
operation, reason, timestamp, and before/after hashes. File contents are not stored in the audit
record. Workspace removal deletes the isolated copy and marks it removed while retaining all patch
records.

Phase 4 does not execute repository code or planned validation commands, commit changes, merge
branches, or modify the registered source checkout.
