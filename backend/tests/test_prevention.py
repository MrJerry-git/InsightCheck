from copy import deepcopy
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.prevention import PreventionRequest, Visit
from app.services.prevent_equations import calculate
from app.services.prevention import assess


def case():
    today = date.today().isoformat()
    return dict(label="test", sex="female", known_cvd=False, pregnant=False,
                symptomatic=False, source="synthetic", source_note="test only", as_of=today,
                visits=[dict(date=today, age=50, sbp=160, bp_tx=True, total_c=200,
                             hdl_c=45, chol_unit="mg/dL", statin=False, dm=True,
                             smoking=False, egfr=90, bmi=35, glucose_status="diabetes")])


@pytest.mark.parametrize("sex,hba1c,expected", [
    ("female", None, [[.147, .092, .081], [.530, .354, .390]]),
    ("male", None, [[.163, .102, .106], [.514, .349, .424]]),
    ("female", 9.2, [[.165, .103, .107], [.541, .356, .449]]),
    ("male", 9.2, [[.187, .112, .130], [.524, .340, .457]]),
])
def test_upstream_reference_cases(sex, hba1c, expected):
    """Independent expected values from preventr test-estimate_risk.R (3 dp)."""
    visit = Visit(**(case()["visits"][0] | {"hba1c": hba1c}))
    result = calculate(visit, sex)
    for values, reference in zip(result["horizons"].values(), expected, strict=True):
        assert list(values.values()) == pytest.approx(reference, abs=.0005)


def test_unit_equivalence_and_age_boundary():
    visit = Visit(**case()["visits"][0])
    equivalent = visit.model_copy(update={"chol_unit": "mmol/L",
                                         "total_c": 200 * .02586, "hdl_c": 45 * .02586})
    assert calculate(visit, "male") == calculate(equivalent, "male")
    assert set(calculate(visit.model_copy(update={"age": 60}), "male")["horizons"]) == {"10"}


@pytest.mark.parametrize("change", [
    {"age": 29}, {"bmi": 40}, {"egfr": 14}, {"sbp": 201}, {"hba1c": 4}, {"hba1c": 16},
])
def test_out_of_model_range_no_fabricated_risk(change):
    body = case()
    body["visits"][0].update(change)
    result = assess(PreventionRequest(**body))
    assert result["risk"] is None and result["blockers"]


@pytest.mark.parametrize("field", ["known_cvd", "pregnant", "symptomatic"])
def test_exclusions(field):
    body = case() | {field: True}
    assert assess(PreventionRequest(**body))["risk"] is None


def test_normal_does_not_automatically_repeat_annually():
    body = case()
    body["visits"][0].update(dm=False, glucose_status="normal", hba1c=5.2)
    item = assess(PreventionRequest(**body))["recommendations"][0]
    assert item["within_next_year"] is False
    body["visits"][0].update(glucose_status="prediabetes", hba1c=6)
    assert assess(PreventionRequest(**body))["recommendations"][0]["within_next_year"] is True


def test_missing_or_inconsistent_glucose_never_means_no_test():
    body = case()
    body["visits"][0].update(dm=False, glucose_status="unknown")
    assert "补充" in assess(PreventionRequest(**body))["recommendations"][0]["decision"]
    body["visits"][0].update(glucose_status="normal", hba1c=7)
    assert "复核" in assess(PreventionRequest(**body))["recommendations"][0]["decision"]


def test_previous_prediabetes_not_erased_by_missing_recent_status():
    body = case()
    earlier = deepcopy(body["visits"][0])
    earlier.update(date="2025-01-01", age=49, dm=False, glucose_status="prediabetes", hba1c=6)
    body["visits"][0].update(dm=False, glucose_status="unknown", hba1c=5.5)
    body["visits"].append(earlier)
    assert "每年" in assess(PreventionRequest(**body))["recommendations"][0]["reason"]


def test_duplicate_future_and_conflicting_records_rejected():
    body = case()
    body["visits"].append(deepcopy(body["visits"][0]))
    with pytest.raises(ValidationError):
        PreventionRequest(**body)
    body = case()
    body["visits"][0]["date"] = "2099-01-01"
    with pytest.raises(ValidationError):
        PreventionRequest(**body)
    body = case()
    body["visits"][0]["glucose_status"] = "normal"
    with pytest.raises(ValidationError):
        PreventionRequest(**body)


def test_api_validation_save_reload_and_immutability(test_app):
    with TestClient(test_app) as client:
        body = case()
        response = client.post("/api/v1/prevention/reports", json=body)
        assert response.status_code == 201
        stored = response.json()
        assert client.get(f"/api/v1/prevention/reports/{stored['id']}").json() == stored
        body["visits"][0]["age"] = 60
        client.post("/api/v1/prevention/assess", json=body).raise_for_status()
        assert client.get(f"/api/v1/prevention/reports/{stored['id']}").json() == stored
        assert len(client.get("/api/v1/prevention/reports").json()) == 1
        del body["visits"][0]["smoking"]
        assert client.post("/api/v1/prevention/assess", json=body).status_code == 422
        assert client.get("/api/v1/prevention/reports/missing").status_code == 404
