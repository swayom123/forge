# Roadmap

Phase 1 delivered the service, CLI, persistence, identity scanner, contracts, and tests. Phase 2
added bounded repository profiling, incremental Python AST indexing, and search.

Phase 3 delivers structured issue understanding, acceptance criteria, task decomposition,
evidence-backed affected-file estimation, verification plans, persisted plans, and index freshness
checks. Planning is deterministic and uses only the task objective, persisted repository profile,
and AST index. Planned tasks become `READY`, but no code is executed or changed.

Phase 4 delivers isolated, detached Git worktrees and immutable patch audit records. Worktrees are
pinned to committed `HEAD`, materialized without checkout hooks or content filters, and permitted
only for current editable plans. File changes require optimistic SHA-256 hashes and cannot escape
the managed workspace. The registered source tree is never modified.

Phase 5 delivers policy-approved validation commands in a fail-closed Bubblewrap sandbox. Commands
must exactly match the persisted plan, run without a shell or network, see only an ephemeral overlay
of the task workspace and trusted Python runtime, and have configurable resource, duration, and
output limits. Results and lifecycle states are persisted, but tasks are not marked complete.

Phase 6 delivers complete automated verification gates and bounded repair cycles. Every planned
command runs with ordered evidence. Failures require a new non-no-op audited patch before retry and
exhaustion moves the task to `BLOCKED`; infrastructure errors remain retryable. Passing moves a task
to `VERIFIED`, reserving `COMPLETED` for the later independent-review gate.

Later phases will add independent review, model routing, and evaluation. No task may be marked
complete until implemented verification and review gates actually run.
