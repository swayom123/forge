"""API persistence and validation tests."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_register_and_queue_task(client: TestClient, tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / ".git").mkdir()
    response = client.post("/repositories/register", json={"path": str(repo)})
    assert response.status_code == 201
    repository = response.json()
    assert repository["path"] == str(repo)
    assert client.get(f"/repositories/{repository['id']}").status_code == 200
    assert (
        client.post("/repositories/register", json={"path": str(repo)}).json()["id"]
        == repository["id"]
    )

    response = client.post(
        "/tasks", json={"repository_id": repository["id"], "objective": "Fix registration"}
    )
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "PENDING"
    assert task["trace_id"]
    assert client.get(f"/tasks/{task['id']}").json() == task


def test_reject_non_git_root_and_unknown_repository(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/repositories/register", json={"path": str(tmp_path)}).status_code == 422
    assert (
        client.post("/tasks", json={"repository_id": "missing", "objective": "x"}).status_code
        == 404
    )


def test_index_profile_and_search_endpoints(client: TestClient, tmp_path: Path) -> None:
    repo = tmp_path / "indexed"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')
    (repo / "main.py").write_text("def health_check() -> str:\n    return 'healthy'\n")
    registered = client.post("/repositories/register", json={"path": str(repo)}).json()

    update = client.post(f"/repositories/{registered['id']}/index")
    assert update.status_code == 200
    assert update.json()["indexed_files"] == 1
    assert update.json()["profile"]["frameworks"] == ["FastAPI"]

    profile = client.get(f"/repositories/{registered['id']}/profile")
    assert profile.status_code == 200
    assert profile.json()["languages"] == ["Python"]
    symbols = client.get(f"/repositories/{registered['id']}/symbols", params={"query": "health"})
    assert symbols.json()[0]["name"] == "health_check"
    text = client.get(f"/repositories/{registered['id']}/search", params={"query": "healthy"})
    assert text.json()[0]["file_path"] == "main.py"
