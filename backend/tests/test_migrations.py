import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models import Base


def test_initial_migration_builds_all_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-test.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database_path) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
            )
        }
    assert actual_tables == set(Base.metadata.tables)
