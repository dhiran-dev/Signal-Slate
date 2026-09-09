"""Unit tests for FastAPI health endpoint."""

from fastapi.testclient import TestClient
from signal_slate.main import app

client = TestClient(app)


def test_health_contract():
    """GET /health must return HTTP 200 with status ok and project balmy-coral-508014-p7."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "ok",
        "project": "balmy-coral-508014-p7",
    }
