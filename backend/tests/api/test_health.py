"""
Health API Endpoint Tests
"""


def test_health_check(client):
    """Verify that the health check endpoint returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "ClosureIQ" in data["service"]


def test_api_v1_health_check(client):
    """Verify health check under API v1 prefix."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
