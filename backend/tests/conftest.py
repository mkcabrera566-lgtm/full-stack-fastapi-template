from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.models import Item, User


@pytest.fixture(scope="session", autouse=True)
def db(request: pytest.FixtureRequest) -> Generator[Session]:
    if not request.config.getoption("--run-postgres-tests"):
        pytest.skip(
            "PostgreSQL integration tests require --run-postgres-tests and TEST_DATABASE_URL"
        )
    from app.core.db import engine, init_db

    with Session(engine) as session:
        init_db(session)
        yield session
        statement = delete(Item)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    from tests.utils.utils import get_superuser_token_headers

    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    from app.core.config import settings
    from tests.utils.user import authentication_token_from_email

    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
