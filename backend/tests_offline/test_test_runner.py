import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).parents[1] / "scripts" / "test_backend.py"


@pytest.mark.parametrize("postgres", [False, True])
def test_test_runner_selects_suites_and_appends_coverage(
    tmp_path: Path, postgres: bool
) -> None:
    calls = tmp_path / "calls.jsonl"
    # Replace only the external coverage CLI; never execute a database test in this test.
    (tmp_path / "coverage.py").write_text(
        "import json, os, sys\n"
        "with open(os.environ['RUNNER_CALLS'], 'a') as output:\n"
        "    output.write(json.dumps([sys.argv[1:], os.environ.get('FASTAPI_ENV')]) + '\\n')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(PYTHONPATH=str(tmp_path), RUNNER_CALLS=str(calls))
    env.pop("TEST_DATABASE_URL", None)
    if postgres:
        env["TEST_DATABASE_URL"] = "postgresql://test:test@localhost:1/disposable"
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--title", "Example coverage"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    expected = [[["run", "-m", "pytest", "tests_offline/"], "development"]]
    if postgres:
        expected.append(
            [
                ["run", "--append", "-m", "pytest", "tests/", "--run-postgres-tests"],
                "development",
            ]
        )
    expected.extend(
        [
            [["report"], "development"],
            [["html", "--title", "Example coverage"], "development"],
        ]
    )
    assert [json.loads(line) for line in calls.read_text().splitlines()] == expected


def test_test_runner_stops_after_failed_suite(tmp_path: Path) -> None:
    calls = tmp_path / "calls.jsonl"
    (tmp_path / "coverage.py").write_text(
        "import json, os, sys\n"
        "with open(os.environ['RUNNER_CALLS'], 'a') as output:\n"
        "    output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(PYTHONPATH=str(tmp_path), RUNNER_CALLS=str(calls))
    env["TEST_DATABASE_URL"] = "postgresql://test:test@localhost:1/disposable"
    result = subprocess.run(
        [sys.executable, str(RUNNER)], env=env, capture_output=True, timeout=30
    )
    assert result.returncode == 7
    assert len(calls.read_text().splitlines()) == 1
