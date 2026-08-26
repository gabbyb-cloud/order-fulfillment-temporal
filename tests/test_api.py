"""
API-layer tests: verifies authentication behavior and endpoint contracts
for the FastAPI service.

Unlike test_order_workflow.py (which tests the Temporal workflow directly),
these tests go through the actual HTTP layer, including the API key auth
dependency applied in main.py.

Requires: Temporal server running locally (docker-compose up -d) and a
valid ORDER_API_KEY set in .env, since the app's lifespan connects to
Temporal on startup.

Run with: pytest tests/test_api.py -v
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from api.main import app, API_KEY


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_rejects_missing_key(client):
    response = client.get("/health")
    assert response.status_code == 403


def test_health_rejects_wrong_key(client):
    response = client.get("/health", headers={"X-API-Key": "definitely-wrong-key"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid API key"


def test_health_accepts_correct_key(client):
    response = client.get("/health", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_orders_endpoint_rejects_missing_key(client):
    response = client.get("/orders/some-fake-id")
    assert response.status_code == 403


def test_orders_endpoint_accepts_correct_key(client):
    response = client.get("/orders/some-fake-id", headers={"X-API-Key": API_KEY})
    # Auth passed, so this should NOT be a 401/403 — it becomes a
    # business-logic "not found" response instead.
    assert response.status_code not in (401, 403)