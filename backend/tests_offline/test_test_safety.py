import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_offline_run_blocks_application_database_connections(
    request: pytest.FixtureRequest,
) -> None:
    if request.config.getoption("--run-postgres-tests"):
        pytest.skip("Connection prohibition applies only in offline mode")
    from app.core.db import engine

    with pytest.raises(AssertionError, match="PostgreSQL connections are forbidden"):
        engine.connect()


def test_postgres_tests_require_explicit_disposable_database_url() -> None:
    env = os.environ.copy()
    env.pop("TEST_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--run-postgres-tests",
            "--collect-only",
            "tests",
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 4
    assert "requires TEST_DATABASE_URL" in result.stderr
