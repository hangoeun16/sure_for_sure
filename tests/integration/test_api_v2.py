from pathlib import Path

from backend.main import app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_health() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_encounter_listing_and_analysis_use_current_pipeline(monkeypatch) -> None:
    monkeypatch.setenv("SURE_FOR_SURE_DATASET", str(ROOT / "examples" / "input.example.json"))
    monkeypatch.setenv("SURE_FOR_SURE_PROVIDER", "stub")
    client = TestClient(app)
    listing = client.get("/api/encounters")
    assert listing.status_code == 200
    record_id = listing.json()[0]["id"]
    analysis = client.post(f"/api/analyze/{record_id}")
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["divergences"]
    assert payload["ced_results"]
    assert payload["actions"]


def test_unknown_configured_encounter_returns_404(monkeypatch) -> None:
    monkeypatch.setenv("SURE_FOR_SURE_DATASET", str(ROOT / "examples" / "input.example.json"))
    response = TestClient(app).post("/api/analyze/not-present")
    assert response.status_code == 404


def test_malformed_direct_request_returns_422() -> None:
    response = TestClient(app).post("/api/analyze", json={"id": "missing-fields"})
    assert response.status_code == 422


def test_invalid_extra_top_level_field_returns_422() -> None:
    payload = {
        "id": "bad-extra",
        "metadata": {},
        "patient_context": {},
        "encounter_fhir": {},
        "transcript": "PT: Hello.",
        "note": "",
        "after_visit_summary": "",
        "after_visit_summary_provenance": {},
        "unexpected": True,
    }
    response = TestClient(app).post("/api/analyze", json=payload)
    assert response.status_code == 422
