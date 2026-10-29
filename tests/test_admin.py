import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import create_app  # noqa: E402


def make(tmp_path, password="S3cure-admin-pass"):
    return create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "t.db"), "GOOGLE_CLIENT_ID": "", "YOUTUBE_API_KEY": "",
        "YOUTUBE_IDS_FILE": str(tmp_path / "ids.csv"), "CURATED_SEED_FILE": str(tmp_path / "seed.csv"),
        "ADMIN_USERNAME": "boss", "ADMIN_PASSWORD": password,
    })


def token(client, path="/admin/login"):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', client.get(path).get_data(as_text=True)).group(1)


def login(client, user="boss", pw="S3cure-admin-pass"):
    return client.post("/admin/login", data={"csrf": token(client), "username": user, "password": pw})


@pytest.fixture()
def client(tmp_path):
    return make(tmp_path).test_client()


def test_admin_pages_need_login(client):
    for path in ("/admin", "/admin/users"):
        r = client.get(path)
        assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_normal_user_is_not_admin(client):
    client.post("/api/signup", json={"name": "Muthu", "email": "m@example.com", "password": "secret1"})
    assert client.get("/admin").status_code == 302


def test_wrong_password_and_csrf(client):
    assert b"Wrong username or password" in login(client, pw="nope").data
    r = client.post("/admin/login", data={"csrf": "bad", "username": "boss", "password": "S3cure-admin-pass"})
    assert b"Session expired" in r.data


def test_login_dashboard_users_and_delete(client):
    client.post("/api/signup", json={"name": "Muthu", "email": "m@example.com", "password": "secret1"})
    client.get("/logout")
    assert login(client).status_code == 302
    page = client.get("/admin").get_data(as_text=True)
    assert "Overview" in page and "Registered users" in page
    assert "m@example.com" in client.get("/admin/users").get_data(as_text=True)
    assert "Muthu" in client.get("/admin/users?q=muth").get_data(as_text=True)
    tok = token(client, "/admin/users")
    assert client.post("/admin/users/1/delete", data={"csrf": "wrong"}).status_code == 302
    assert "m@example.com" in client.get("/admin/users").get_data(as_text=True)
    client.post("/admin/users/1/delete", data={"csrf": tok})
    assert "m@example.com" not in client.get("/admin/users").get_data(as_text=True)


def test_logout_closes_admin(client):
    login(client)
    client.post("/admin/logout", data={"csrf": token(client, "/admin")})
    assert client.get("/admin").status_code == 302


def test_throttle_after_five_failures(client):
    for _ in range(5):
        login(client, pw="bad")
    r = login(client)               # even the right password is refused now
    assert r.status_code == 429


def test_admin_disabled_without_password(tmp_path):
    c = make(tmp_path, password="").test_client()
    assert b"not set up" in c.get("/admin/login").data
    assert c.post("/admin/login", data={"username": "boss", "password": ""}).status_code == 200
    assert c.get("/admin").status_code == 302
