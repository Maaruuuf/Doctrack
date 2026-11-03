import os
import tempfile

# Configure an isolated database BEFORE the app is imported
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "Admin@12345"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from backend.main import app
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def auth(client):
    admin = _login(client, "admin", "Admin@12345")
    for username, role in (("mgr", "manager"), ("stf", "staff")):
        r = client.post("/auth/users", headers=admin, json={
            "username": username, "full_name": f"{username.upper()} User",
            "password": "Password@123", "role": role})
        assert r.status_code == 201, r.text
    return {
        "admin": admin,
        "manager": _login(client, "mgr", "Password@123"),
        "staff": _login(client, "stf", "Password@123"),
    }
