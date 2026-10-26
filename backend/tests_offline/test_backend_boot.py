import runpy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_backend_import_without_built_frontend() -> None:
    # Import must also work on a fresh backend-only checkout without frontend assets.
    main_path = Path(__file__).parents[1] / "app" / "main.py"
    with patch.object(Path, "is_dir", return_value=False):
        app = runpy.run_path(str(main_path))["app"]

    assert app.openapi()["paths"]["/api/v1/users/me"]
    with TestClient(app) as client:
        assert client.get("/api/v1/does-not-exist").status_code == 404
