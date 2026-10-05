# Forge

Forge is a foundation for a controlled software engineering agent. Phase 2 safely profiles local Git repositories and incrementally indexes Python files, symbols, imports, and module relationships. It does **not** run repository code, call models, edit source files, or execute repository commands.

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
```

The database URL defaults to `sqlite:///./forge.db`. Copy `.env.example` to `.env` to configure it. The SQLite path is relative to the process working directory.

## Development

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest
```

See [architecture](docs/architecture.md), [repository intelligence](docs/repository-intelligence.md), [security](docs/security.md), and the [roadmap](docs/roadmap.md).
