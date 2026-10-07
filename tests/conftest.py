import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def factory(**overrides):
        config = dict(db_path=str(tmp_path / f"gateway-{len(clients)}.db"), rate_limit=1000)
        config.update(overrides)
        client = TestClient(create_app(Settings(**config)))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def fetch_trace(client, response):
    trace_id = response.headers["X-Trace-ID"]
    return client.get(f"/v1/traces/{trace_id}").json()
