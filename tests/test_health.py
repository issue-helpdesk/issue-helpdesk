import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import __version__
from app.db.session import get_db
from app.main import app

client = TestClient(app)
DB_DOWN = OperationalError("SELECT 1", {}, Exception("connection refused"))


class FakeSession:
    def __init__(self, error=None):
        self.error = error

    def execute(self, statement):
        if self.error:
            raise self.error


def use_db(session):
    app.dependency_overrides[get_db] = lambda: session


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_live_returns_up():
    res = client.get("/api/v1/health/live")

    assert res.status_code == 200
    assert res.json() == {"status": "UP", "version": __version__}


def test_live_ignores_db_down():
    use_db(FakeSession(error=DB_DOWN))

    res = client.get("/api/v1/health/live")

    assert res.status_code == 200


def test_ready_returns_up_when_db_ok():
    use_db(FakeSession())

    res = client.get("/api/v1/health/ready")

    assert res.status_code == 200
    assert res.json() == {"status": "UP", "database": "UP", "version": __version__}


def test_ready_returns_503_when_db_down():
    use_db(FakeSession(error=DB_DOWN))

    res = client.get("/api/v1/health/ready")

    assert res.status_code == 503
    assert res.json() == {"status": "DOWN", "database": "DOWN", "version": __version__}
