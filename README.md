# Forge

Forge is a foundation for a controlled software engineering agent. Phase 6 safely profiles and
indexes local Git repositories, creates deterministic engineering plans, allocates isolated Git
worktrees, applies hash-guarded file changes, and executes planned Python validation commands in an
offline Linux namespace sandbox. Complete gate runs drive bounded, audited repair cycles. Forge does
**not** call models or modify the registered source tree.

## Requirements

Python 3.12 or newer. SQLite is bundled with Python. Install in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Run

```bash
.venv/bin/uvicorn forge.apps.api:app --reload
.venv/bin/forge inspect /path/to/git/repository
.venv/bin/forge register /path/to/git/repository
.venv/bin/forge index REPOSITORY_ID
.venv/bin/forge search REPOSITORY_ID "UserService"
.venv/bin/forge task REPOSITORY_ID "Fix duplicate registration"
.venv/bin/forge plan TASK_ID
.venv/bin/forge show-plan TASK_ID
.venv/bin/forge workspace TASK_ID
.venv/bin/forge apply-patch TASK_ID path/to/file.py UPDATE --before-hash HASH --content-file replacement.py --reason "Implement planned change"
.venv/bin/forge execute TASK_ID 0
.venv/bin/forge executions TASK_ID
.venv/bin/forge remove-workspace TASK_ID
.venv/bin/forge status TASK_ID
```

API examples:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/repositories/register -H 'content-type: application/json' -d '{"path":"/absolute/path/to/repository"}'
curl -X POST http://127.0.0.1:8000/repositories/REPOSITORY_ID/index
curl 'http://127.0.0.1:8000/repositories/REPOSITORY_ID/symbols?query=UserService'
curl 'http://127.0.0.1:8000/repositories/REPOSITORY_ID/search?query=registration'
curl 'http://127.0.0.1:8000/repositories/REPOSITORY_ID/dependents?module=app.database'
curl -X POST http://127.0.0.1:8000/tasks -H 'content-type: application/json' -d '{"repository_id":"REPOSITORY_ID","objective":"Fix duplicate registration"}'
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/plan
curl http://127.0.0.1:8000/tasks/TASK_ID/plan
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/workspace
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/patches -H 'content-type: application/json' -d '{"file_path":"src/example.py","operation":"UPDATE","before_hash":"SHA256","content":"replacement source","reason":"Implement the planned change"}'
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/executions -H 'content-type: application/json' -d '{"argv":["python","-m","pytest"]}'
curl http://127.0.0.1:8000/tasks/TASK_ID/executions
curl -X POST http://127.0.0.1:8000/tasks/TASK_ID/verify
curl http://127.0.0.1:8000/tasks/TASK_ID/verifications
curl -X DELETE http://127.0.0.1:8000/tasks/TASK_ID/workspace
```

The database URL defaults to `sqlite:///./forge.db`. Copy `.env.example` to `.env` to configure it. The SQLite path is relative to the process working directory.

## Development

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest
```

See [architecture](docs/architecture.md), [repository intelligence](docs/repository-intelligence.md),
[planning](docs/planning.md), [isolated workspaces](docs/workspaces.md),
[sandbox execution](docs/sandbox.md), [verification and repair](docs/verification.md),
[security](docs/security.md), and the [roadmap](docs/roadmap.md).
