import pytest
from fastapi.testclient import TestClient

from tamadesk.core.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAMADESK_HOME", str(tmp_path))
    get_settings.cache_clear()
    from tamadesk.api.app import create_app

    with TestClient(create_app(scheduler=False)) as c:
        yield c
    get_settings.cache_clear()
