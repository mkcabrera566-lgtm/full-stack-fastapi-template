"""Run offline tests everywhere; append original integration tests only by opt-in."""

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="coverage")
    args = parser.parse_args()
    env = os.environ.copy()
    env["FASTAPI_ENV"] = "development"
    commands = [["run", "-m", "pytest", "tests_offline/"]]
    if "TEST_DATABASE_URL" in env:
        commands.append(
            ["run", "--append", "-m", "pytest", "tests/", "--run-postgres-tests"]
        )
    commands.extend([["report"], ["html", "--title", args.title]])
    for command in commands:
        result = subprocess.run([sys.executable, "-m", "coverage", *command], env=env)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
