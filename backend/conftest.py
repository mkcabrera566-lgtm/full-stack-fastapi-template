"""Keep default pytest runs isolated from configured application databases."""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-postgres-tests",
        action="store_true",
        help="Run original integration tests against explicit TEST_DATABASE_URL (destructive).",
    )


def pytest_configure(config: pytest.Config) -> None:
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    if config.getoption("--run-postgres-tests"):
        test_url = os.environ.get("TEST_DATABASE_URL")
        if not test_url:
            raise pytest.UsageError(
                "--run-postgres-tests requires TEST_DATABASE_URL pointing to a disposable database"
            )
        patch.setenv("DATABASE_URL", test_url)
        return

    # These process-local settings never change .env or open a PostgreSQL connection.
    for name, value in {
        "DATABASE_URL": "postgresql+psycopg://offline:offline@127.0.0.1:1/offline",
        "SECRET_KEY": "offline-test-secret-key-at-least-thirty-two-characters",
        "PROJECT_NAME": "Offline API tests",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "offline-test-password",
        "FASTAPI_ENV": "development",
    }.items():
        patch.setenv(name, value)


def pytest_sessionstart(session: pytest.Session) -> None:
    if not session.config.getoption("--run-postgres-tests"):
        from sqlalchemy import event

        from app.core.db import engine

        def forbid_postgres_connection(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "PostgreSQL connections are forbidden in offline tests"
            )

        event.listen(engine, "do_connect", forbid_postgres_connection)
        session.config.add_cleanup(
            lambda: event.remove(engine, "do_connect", forbid_postgres_connection)
        )
