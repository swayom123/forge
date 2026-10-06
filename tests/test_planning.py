"""Phase 3 issue understanding and index-grounded planning tests."""

from pathlib import Path

from fastapi.testclient import TestClient


def _registered_project(client: TestClient, tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "planned"
    (root / ".git").mkdir(parents=True)
    (root / "src" / "demo").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
dependencies = ["pytest"]
[tool.ruff]
[tool.mypy]
""".strip()
    )
    (root / "src" / "demo" / "users.py").write_text(
        """def register_user(email: str) -> str:
    return email

def find_user(email: str) -> str:
    return email
"""
    )
    (root / "tests" / "test_users.py").write_text(
        """from demo.users import register_user

def test_register_user() -> None:
    assert register_user("a@example.com")
"""
    )
    repository = client.post("/repositories/register", json={"path": str(root)}).json()
    return root, repository["id"]


def test_plan_requires_an_index(client: TestClient, tmp_path: Path) -> None:
    _, repository_id = _registered_project(client, tmp_path)
    task = client.post(
        "/tasks",
        json={"repository_id": repository_id, "objective": "Fix registration"},
    ).json()

    response = client.post(f"/tasks/{task['id']}/plan")

    assert response.status_code == 409
    assert response.json()["detail"] == "Repository must be indexed before planning"


def test_plan_is_structured_persisted_and_grounded_in_index(
    client: TestClient, tmp_path: Path
) -> None:
    _, repository_id = _registered_project(client, tmp_path)
    assert client.post(f"/repositories/{repository_id}/index").status_code == 200
    task = client.post(
        "/tasks",
        json={
            "repository_id": repository_id,
            "objective": (
                "Fix duplicate registration in src/demo/users.py. "
                "Must preserve existing lookup behavior."
            ),
        },
    ).json()

    response = client.post(f"/tasks/{task['id']}/plan")

    assert response.status_code == 200
    plan = response.json()
    assert (
        plan["issue"]["summary"] == "Fix duplicate registration in src/demo/users.py. "
        "Must preserve existing lookup behavior."
    )
    assert "registration" in plan["issue"]["keywords"]
    assert plan["issue"]["explicit_paths"] == ["src/demo/users.py"]
    assert plan["issue"]["constraints"] == ["Must preserve existing lookup behavior."]
    affected = {item["path"]: item for item in plan["affected_files"]}
    assert affected["src/demo/users.py"]["confidence"] == "high"
    assert "explicitly named in the objective" in affected["src/demo/users.py"]["evidence"]
    assert "tests/test_users.py" in affected
    assert ["python", "-m", "ruff", "check", "."] in plan["validation_commands"]
    assert ["python", "-m", "pytest"] in plan["validation_commands"]
    assert plan["stale"] is False
    assert len(plan["context_fingerprint"]) == 64

    stored = client.get(f"/tasks/{task['id']}/plan")
    assert stored.status_code == 200
    assert stored.json()["context_fingerprint"] == plan["context_fingerprint"]
    assert client.get(f"/tasks/{task['id']}").json()["status"] == "READY"


def test_plan_reports_stale_after_index_content_changes(client: TestClient, tmp_path: Path) -> None:
    root, repository_id = _registered_project(client, tmp_path)
    client.post(f"/repositories/{repository_id}/index")
    task = client.post(
        "/tasks",
        json={"repository_id": repository_id, "objective": "Fix registration"},
    ).json()
    original = client.post(f"/tasks/{task['id']}/plan").json()

    (root / "src" / "demo" / "users.py").write_text(
        "def register_user(email: str) -> str:\n    return email.lower()\n"
    )
    client.post(f"/repositories/{repository_id}/index")

    stale = client.get(f"/tasks/{task['id']}/plan").json()
    assert stale["stale"] is True
    assert stale["context_fingerprint"] == original["context_fingerprint"]

    refreshed = client.post(f"/tasks/{task['id']}/plan").json()
    assert refreshed["stale"] is False
    assert refreshed["context_fingerprint"] != original["context_fingerprint"]


def test_plan_reports_stale_after_profile_only_changes(client: TestClient, tmp_path: Path) -> None:
    root, repository_id = _registered_project(client, tmp_path)
    client.post(f"/repositories/{repository_id}/index")
    task = client.post(
        "/tasks",
        json={"repository_id": repository_id, "objective": "Review registration"},
    ).json()
    client.post(f"/tasks/{task['id']}/plan")

    (root / "pyproject.toml").write_text("[project]\ndependencies = []\n")
    client.post(f"/repositories/{repository_id}/index")

    assert client.get(f"/tasks/{task['id']}/plan").json()["stale"] is True
