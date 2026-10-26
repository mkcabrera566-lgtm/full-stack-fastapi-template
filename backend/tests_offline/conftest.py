from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from sqlite3 import Connection
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.models import Ticket, TicketPublic, User


@pytest.fixture
def db() -> Generator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Connection, _record: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db: Session) -> Generator[TestClient]:
    from app.api.deps import get_db
    from app.main import app

    def override_db() -> Generator[Session]:
        yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def users(db: Session) -> dict[str, User]:
    from app.core.security import get_password_hash

    password_hash = get_password_hash("test-password-123")
    result = {
        "owner": User(email="owner@example.com", hashed_password=password_hash),
        "other": User(email="other@example.com", hashed_password=password_hash),
        "admin": User(
            email="admin@example.com", hashed_password=password_hash, is_superuser=True
        ),
        "inactive": User(
            email="inactive@example.com", hashed_password=password_hash, is_active=False
        ),
    }
    db.add_all(result.values())
    db.commit()
    for user in result.values():
        db.refresh(user)
    return result


@pytest.fixture
def headers(users: dict[str, User]) -> dict[str, dict[str, str]]:
    from app.core.security import create_access_token

    return {
        role: {
            "Authorization": f"Bearer {create_access_token(user.id, timedelta(minutes=5))}"
        }
        for role, user in users.items()
    }


@pytest.fixture
def persistent_engine(tmp_path: Path) -> Generator[Engine]:
    # NullPool closes each physical connection instead of sharing transaction state.
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'tickets.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Connection, _record: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        SQLModel.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def persistent_client(persistent_engine: Engine) -> Generator[TestClient]:
    from app.api.deps import get_db
    from app.main import app

    def override_db() -> Generator[Session]:
        # Match production: every HTTP request owns and closes its Session.
        with Session(persistent_engine) as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def persistent_users(persistent_engine: Engine) -> dict[str, UUID]:
    from app.core.security import get_password_hash

    password_hash = get_password_hash("persistent-test-password")
    users = {
        role: User(
            email=f"persistent-{role}@example.com",
            hashed_password=password_hash,
            is_superuser=role == "admin",
        )
        for role in ("owner", "admin")
    }
    user_ids = {role: user.id for role, user in users.items()}
    with Session(persistent_engine) as session:
        session.add_all(users.values())
        session.commit()
    return user_ids


@pytest.fixture
def persistent_headers(persistent_users: dict[str, UUID]) -> dict[str, dict[str, str]]:
    from app.core.security import create_access_token

    return {
        role: {
            "Authorization": f"Bearer {create_access_token(user_id, timedelta(minutes=5))}"
        }
        for role, user_id in persistent_users.items()
    }


@pytest.fixture
def persisted_ticket(
    persistent_engine: Engine, persistent_users: dict[str, UUID]
) -> dict[str, Any]:
    # Seed directly so a broken POST cannot mask the PATCH/DELETE persistence checks.
    with Session(persistent_engine) as session:
        ticket = Ticket(
            title="Original title",
            description="Original description",
            owner_id=persistent_users["owner"],
        )
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return TicketPublic.model_validate(ticket).model_dump(mode="json")
