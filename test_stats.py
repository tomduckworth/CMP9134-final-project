from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_recon_mission_success():
    """Test 1: A successful Recon mission (Type 1)."""
    payload = {
        "type": 1,
        "dist": 50.0,
        "batt": 10.0
    }
    response = client.post("/api/mission_stats", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["mission"] == "recon"
    assert data["final_score"] == 50.0


def test_transport_mission_heavy_payload():
    """Test 2: A successful Transport mission with a heavy payload."""
    payload = {
        "type": 2,
        "dist": 100.0,
        "batt": 5.0,
        "payload_weight": 60.0
    }
    response = client.post("/api/mission_stats", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["mission"] == "transport"
    assert data["final_score"] == 94.0


def test_missing_required_key():
    """Test 3: Missing 'batt' key (Expect 422 validation error)."""
    payload = {
        "type": 1,
        "dist": 50.0
    }
    response = client.post("/api/mission_stats", json=payload)
    # Refactored to match FastAPI's automatic validation schema
    assert response.status_code == 422
    assert "detail" in response.json()


def test_score_capping():
    """Test 4: Score exceeds 100 (caps at 100)."""
    payload = {
        "type": 1,
        "dist": 200.0,
        "batt": 2.0
    }
    response = client.post("/api/mission_stats", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["final_score"] == 100.0