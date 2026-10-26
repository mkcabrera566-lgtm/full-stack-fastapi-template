import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from app.core.security import create_access_token
from app.models import Ticket, TicketPublic, User

URL = "/api/v1/tickets/"
PAYLOAD = {
    "title": "Cannot log in",
    "description": "Password reset email never arrives",
}


def create_ticket(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(URL, headers=headers, json=PAYLOAD)
    assert response.status_code == 201, response.text
    ticket = response.json()
    assert isinstance(ticket, dict)
    return ticket


def test_ticket_lifecycle(
    client: TestClient, headers: dict[str, dict[str, str]], users: dict[str, User]
) -> None:
    ticket = create_ticket(client, headers["owner"])
    ticket_url = f"{URL}{ticket['id']}"
    assert uuid.UUID(ticket["id"])
    assert ticket["owner_id"] == str(users["owner"].id)
    assert ticket["status"] == "open"
    assert ticket["priority"] == "medium"
    created_at = datetime.fromisoformat(ticket["created_at"])
    assert abs(datetime.now(UTC) - created_at.replace(tzinfo=UTC)) < timedelta(
        seconds=10
    )
    assert client.get(ticket_url, headers=headers["owner"]).json() == ticket
    for state in ["in_progress", "resolved", "in_progress", "resolved", "closed"]:
        response = client.patch(
            ticket_url, headers=headers["owner"], json={"status": state}
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == state
        assert response.json()["created_at"] == ticket["created_at"]
    response = client.delete(ticket_url, headers=headers["owner"])
    assert response.status_code == 200
    assert client.get(ticket_url, headers=headers["owner"]).status_code == 404


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_ownership_and_missing_ticket(
    client: TestClient, headers: dict[str, dict[str, str]], method: str
) -> None:
    ticket = create_ticket(client, headers["owner"])
    kwargs = {"json": {"title": "Edited by admin"}} if method == "patch" else {}
    response = client.request(
        method, f"{URL}{ticket['id']}", headers=headers["other"], **kwargs
    )
    assert response.status_code == 403
    assert client.get(f"{URL}{ticket['id']}", headers=headers["owner"]).json() == ticket
    assert (
        client.request(
            method, f"{URL}{uuid.uuid4()}", headers=headers["owner"], **kwargs
        ).status_code
        == 404
    )
    assert (
        client.request(
            method, f"{URL}{ticket['id']}", headers=headers["admin"], **kwargs
        ).status_code
        == 200
    )


def test_list_isolation_count_and_pagination(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    first = create_ticket(client, headers["owner"])
    second = create_ticket(client, headers["owner"])
    create_ticket(client, headers["other"])
    response = client.get(URL, headers=headers["owner"])
    assert response.status_code == 200
    assert response.json() == {"data": [second, first], "count": 2}
    assert client.get(URL, headers=headers["other"]).json()["count"] == 1
    assert client.get(URL, headers=headers["admin"]).json()["count"] == 3
    assert client.get(
        URL, headers=headers["owner"], params={"skip": 1, "limit": 1}
    ).json() == {"data": [first], "count": 2}
    assert client.get(URL, headers=headers["owner"], params={"skip": 5}).json() == {
        "data": [],
        "count": 2,
    }


@pytest.mark.parametrize("params", [{"skip": -1}, {"limit": 0}, {"limit": 101}])
def test_reject_invalid_pagination(
    client: TestClient, headers: dict[str, dict[str, str]], params: dict[str, int]
) -> None:
    assert client.get(URL, headers=headers["owner"], params=params).status_code == 422


@pytest.mark.parametrize(
    "method,path",
    [("post", ""), ("get", ""), ("get", "id"), ("patch", "id"), ("delete", "id")],
)
def test_every_ticket_endpoint_requires_authentication(
    client: TestClient, method: str, path: str
) -> None:
    url = URL + (str(uuid.uuid4()) if path else "")
    assert client.request(method, url, json=PAYLOAD).status_code == 401


def test_real_login_and_invalid_credentials(
    client: TestClient, users: dict[str, User], headers: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        "/api/v1/login/access-token",
        data={"username": users["owner"].email, "password": "test-password-123"},
    )
    assert response.status_code == 200
    token_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.post(URL, headers=token_headers, json=PAYLOAD).status_code == 201
    assert (
        client.get(URL, headers={"Authorization": "Bearer invalid"}).status_code == 403
    )
    assert client.get(URL, headers=headers["inactive"]).status_code == 400
    expired = create_access_token(users["owner"].id, timedelta(seconds=-1))
    assert (
        client.get(URL, headers={"Authorization": f"Bearer {expired}"}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 256},
        {"description": ""},
        {"description": " \n "},
        {"description": "x" * 10001},
        {"priority": "critical"},
        {"priority": None},
        {"title": None},
        {"description": None},
        {"owner_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"status": "closed"},
        {"unexpected": True},
    ],
)
def test_create_validation(
    client: TestClient, headers: dict[str, dict[str, str]], payload: dict[str, Any]
) -> None:
    body = PAYLOAD | payload if payload else {}
    response = client.post(URL, headers=headers["owner"], json=body)
    assert response.status_code == 422, response.text
    assert client.get(URL, headers=headers["owner"]).json()["count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"title": None},
        {"description": None},
        {"priority": None},
        {"status": None},
        {"title": "   "},
        {"title": "x" * 256},
        {"description": ""},
        {"description": "x" * 10001},
        {"priority": "invalid"},
        {"status": "invalid"},
        {"owner_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"unexpected": True},
    ],
)
def test_patch_validation_has_no_side_effects(
    client: TestClient, headers: dict[str, dict[str, str]], payload: dict[str, Any]
) -> None:
    ticket = create_ticket(client, headers["owner"])
    url = f"{URL}{ticket['id']}"
    assert client.patch(url, headers=headers["owner"], json=payload).status_code == 422
    assert client.get(url, headers=headers["owner"]).json() == ticket


def test_partial_updates_and_trimmed_text(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        URL,
        headers=headers["owner"],
        json={"title": "  Hello  ", "description": "  Details\n", "priority": "urgent"},
    )
    assert response.status_code == 201
    ticket = response.json()
    assert ticket["title"] == "Hello"
    assert ticket["description"] == "Details"
    url = f"{URL}{ticket['id']}"
    assert client.patch(url, headers=headers["owner"], json={}).json() == ticket
    response = client.patch(
        url, headers=headers["owner"], json={"title": "  New title ", "priority": "low"}
    )
    assert response.status_code == 200
    assert response.json() == ticket | {"title": "New title", "priority": "low"}


@pytest.mark.parametrize(
    "initial,target,allowed",
    [
        ("open", "open", True),
        ("open", "in_progress", True),
        ("open", "resolved", False),
        ("open", "closed", False),
        ("in_progress", "open", False),
        ("in_progress", "in_progress", True),
        ("in_progress", "resolved", True),
        ("in_progress", "closed", False),
        ("resolved", "open", False),
        ("resolved", "in_progress", True),
        ("resolved", "resolved", True),
        ("resolved", "closed", True),
        ("closed", "open", False),
        ("closed", "in_progress", False),
        ("closed", "resolved", False),
        ("closed", "closed", True),
    ],
)
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_status_transition_matrix(
    client: TestClient,
    db: Session,
    headers: dict[str, dict[str, str]],
    initial: str,
    target: str,
    allowed: bool,
    role: str,
) -> None:
    from app.models import Ticket, TicketStatus

    ticket = create_ticket(client, headers["owner"])
    row = db.get(Ticket, uuid.UUID(ticket["id"]))
    assert row is not None
    row.status = TicketStatus(initial)
    db.add(row)
    db.commit()
    url = f"{URL}{ticket['id']}"
    response = client.patch(
        url, headers=headers[role], json={"status": target, "title": "Changed"}
    )
    assert response.status_code == (200 if allowed else 409), response.text
    actual = client.get(url, headers=headers["owner"]).json()
    assert actual["status"] == (target if allowed else initial)
    assert actual["title"] == ("Changed" if allowed else PAYLOAD["title"])


@pytest.mark.parametrize("path", ["/api/v1/users/me", "/api/v1/users/{id}"])
def test_deleting_user_cascades_tickets(
    client: TestClient,
    db: Session,
    headers: dict[str, dict[str, str]],
    users: dict[str, User],
    path: str,
) -> None:
    from app.models import Ticket

    ticket = create_ticket(client, headers["owner"])
    other_ticket = create_ticket(client, headers["other"])
    role = "owner" if path.endswith("/me") else "admin"
    response = client.delete(path.format(id=users["owner"].id), headers=headers[role])
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Ticket, uuid.UUID(ticket["id"])) is None
    assert db.get(Ticket, uuid.UUID(other_ticket["id"])) is not None


def test_existing_items_still_work(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    response = client.post(
        "/api/v1/items/", headers=headers["owner"], json={"title": "Old item"}
    )
    assert response.status_code == 200
    url = f"/api/v1/items/{response.json()['id']}"
    assert client.get(url, headers=headers["owner"]).status_code == 200
    assert (
        client.put(url, headers=headers["owner"], json={"title": "Updated"}).json()[
            "title"
        ]
        == "Updated"
    )
    assert client.delete(url, headers=headers["owner"]).status_code == 200


@pytest.mark.parametrize("priority", ["low", "medium", "high", "urgent"])
def test_valid_text_boundaries_and_priorities(
    client: TestClient, headers: dict[str, dict[str, str]], priority: str
) -> None:
    body = {"title": "x" * 255, "description": "d" * 10000, "priority": priority}
    response = client.post(URL, headers=headers["owner"], json=body)
    assert response.status_code == 201
    assert all(response.json()[key] == value for key, value in body.items())
    url = f"{URL}{response.json()['id']}"
    response = client.patch(
        url, headers=headers["owner"], json={"description": " New details "}
    )
    assert response.status_code == 200
    assert response.json()["description"] == "New details"
    assert response.json()["title"] == body["title"]


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_invalid_ticket_id_returns_validation_error(
    client: TestClient, headers: dict[str, dict[str, str]], method: str
) -> None:
    response = client.request(
        method, f"{URL}not-a-uuid", headers=headers["owner"], json={}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_post_persists_after_request(
    persistent_client: TestClient,
    persistent_engine: Engine,
    persistent_headers: dict[str, dict[str, str]],
    role: str,
) -> None:
    response = persistent_client.post(
        URL, headers=persistent_headers[role], json=PAYLOAD
    )
    assert response.status_code == 201, response.text
    ticket = response.json()
    # The request Session is already closed. NullPool opens a new DBAPI connection.
    with Session(persistent_engine) as observer:
        stored = observer.get(Ticket, uuid.UUID(ticket["id"]))
        assert stored is not None, "POST returned success without committing the ticket"
        assert TicketPublic.model_validate(stored).model_dump(mode="json") == ticket


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_patch_persists_after_request(
    persistent_client: TestClient,
    persistent_engine: Engine,
    persistent_headers: dict[str, dict[str, str]],
    persisted_ticket: dict[str, Any],
    role: str,
) -> None:
    changes = {
        "title": "Committed new title",
        "description": "Committed new description",
        "priority": "urgent",
        "status": "in_progress",
    }
    response = persistent_client.patch(
        f"{URL}{persisted_ticket['id']}", headers=persistent_headers[role], json=changes
    )
    assert response.status_code == 200, response.text
    expected = persisted_ticket | changes
    assert response.json() == expected
    with Session(persistent_engine) as observer:
        stored = observer.get(Ticket, uuid.UUID(persisted_ticket["id"]))
        assert stored is not None
        assert TicketPublic.model_validate(stored).model_dump(mode="json") == expected


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_delete_persists_after_request(
    persistent_client: TestClient,
    persistent_engine: Engine,
    persistent_headers: dict[str, dict[str, str]],
    persisted_ticket: dict[str, Any],
    role: str,
) -> None:
    ticket_id = uuid.UUID(persisted_ticket["id"])
    with Session(persistent_engine) as before:
        assert before.get(Ticket, ticket_id) is not None
    response = persistent_client.delete(
        f"{URL}{ticket_id}", headers=persistent_headers[role]
    )
    assert response.status_code == 200, response.text
    with Session(persistent_engine) as observer:
        assert observer.get(Ticket, ticket_id) is None, "DELETE did not commit"


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_invalid_transition_preserves_all_persisted_fields(
    persistent_client: TestClient,
    persistent_engine: Engine,
    persistent_headers: dict[str, dict[str, str]],
    persisted_ticket: dict[str, Any],
    role: str,
) -> None:
    url = f"{URL}{persisted_ticket['id']}"
    response = persistent_client.patch(
        url,
        headers=persistent_headers[role],
        json={
            "title": "Must not persist",
            "description": "Must not partially commit",
            "priority": "urgent",
            "status": "closed",
        },
    )
    assert response.status_code == 409, response.text
    with Session(persistent_engine) as observer:
        stored = observer.get(Ticket, uuid.UUID(persisted_ticket["id"]))
        assert stored is not None
        assert (
            TicketPublic.model_validate(stored).model_dump(mode="json")
            == persisted_ticket
        )

    # A later valid request must not inherit edits from the failed request's Session.
    response = persistent_client.patch(
        url, headers=persistent_headers[role], json={"status": "in_progress"}
    )
    assert response.status_code == 200, response.text
    with Session(persistent_engine) as observer:
        stored = observer.get(Ticket, uuid.UUID(persisted_ticket["id"]))
        assert stored is not None
        assert TicketPublic.model_validate(stored).model_dump(mode="json") == (
            persisted_ticket | {"status": "in_progress"}
        )
