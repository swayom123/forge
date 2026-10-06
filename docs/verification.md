# Verification gates and bounded repair cycles

Phase 6 runs every validation command from the persisted task plan as one ordered verification
attempt. Individual manual executions remain diagnostic evidence but do not satisfy the complete
gate. A task must be `READY` with an active workspace and at least one automated command.

Each attempt records its number, lifecycle status, workspace patch fingerprint, summary, and links
to every command execution in order. A gate passes only when the result count matches the plan and
every command exits successfully without timing out. Passing moves the task to `VERIFIED`, not
`COMPLETED`; independent acceptance-criteria review remains a later phase.

A failed gate returns the task to `READY` while budget remains. Forge rejects an unchanged retry:
the caller must apply a new audited, non-no-op patch first. The patch fingerprint covers the base
commit and complete immutable patch chain. After the configured number of failed attempts, the task
moves to `BLOCKED`. The default failure budget is three.

Sandbox startup and isolation failures produce an `ERROR` attempt, return the task to `READY`, and
do not consume the failed-repair budget. They may be retried against the same patch state. Command
timeouts and nonzero exits are repository verification failures and do consume the budget.

Phase 6 diagnoses failures at command granularity but does not generate repairs itself. Repairs are
submitted through the existing audited patch API, preserving a reviewable human-or-future-agent
loop. Validation uses Forge's trusted Python environment; required project dependencies must
already be available there because the sandbox has no network or package-install step.
