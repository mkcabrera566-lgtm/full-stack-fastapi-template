from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token


@pytest.mark.parametrize(
    "subject", ["not-a-uuid", "", "00000000-0000-0000-0000-000000000000"]
)
def test_token_subject_is_validated_before_database_lookup(
    client: TestClient, subject: str
) -> None:
    token = create_access_token(subject, timedelta(minutes=5))
    response = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == (404 if subject.startswith("00000000") else 403)
