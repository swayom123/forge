"""CLI behavior tests."""

from pathlib import Path

from typer.testing import CliRunner

from forge.apps.cli import app

runner = CliRunner()


def test_inspect_accepts_positional_repository_path(tmp_path: Path) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / ".git").mkdir()

    result = runner.invoke(app, ["inspect", str(repository)])

    assert result.exit_code == 0
    assert f'"root": "{repository}"' in result.stdout
    assert '"is_git_repository": true' in result.stdout
