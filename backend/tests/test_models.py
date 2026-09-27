from app.models import Base, Patient

EXPECTED_TABLES = {
    "accounts",
    "auth_sessions",
    "prevention_reports",
    "ai_reports",
    "exam_histories",
    "exam_item_prices",
    "exam_items",
    "health_checks",
    "imaging_exams",
    "import_batches",
    "imported_records",
    "lab_metrics",
    "lesion_observations",
    "lesion_tracks",
    "lesions",
    "medical_rules",
    "metric_dictionaries",
    "patients",
    "recommendation_items",
    "recommendations",
    "record_revisions",
    "risk_predictions",
}


def test_all_phase_two_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_patient_model_excludes_direct_identifiers() -> None:
    patient_columns = set(Patient.__table__.columns.keys())

    assert "anonymous_code" in patient_columns
    assert {"identity_card", "id_card", "phone", "address"}.isdisjoint(patient_columns)
