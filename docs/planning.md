# Index-grounded planning

Phase 3 turns a pending task into a reviewable plan without invoking a model or executing repository
code. Planning requires a previously indexed repository and moves the task to `READY`.

The planner produces:

- normalized issue summary, task type, keywords, explicitly named indexed paths, and constraints;
- ordered implementation or investigation steps appropriate to the task type;
- acceptance criteria derived from the request and available verification gates;
- up to eight affected-file estimates with confidence and concrete index evidence; and
- argument-vector validation commands derived from the stored repository profile.

Affected-file ranking considers explicit paths, path terms, symbol names, qualified names, imports,
and files importing a likely affected module. An estimate is omitted when the index has no supporting
evidence; the planner does not invent a file location.

Each plan stores a SHA-256 fingerprint over the deterministic profile and ordered indexed file
hashes. The read endpoint reports `stale: true` when a later index update changes that context. A
second planning request refreshes the plan and fingerprint.

Plans are proposals, not proof of completed work. Phase 3 never applies a patch, runs a validation
command, or marks a task complete.
