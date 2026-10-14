import pytest
from fastapi.testclient import TestClient

from tamadesk.core import db
from tamadesk.core.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAMADESK_HOME", str(tmp_path))
    get_settings.cache_clear()
    from tamadesk.api.app import create_app

    with TestClient(create_app(scheduler=False)) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def conn(client):
    """A connection to the test desk's database (the `client` fixture's fresh data folder)."""
    c = db.connect(get_settings().db_path)
    yield c
    c.close()
