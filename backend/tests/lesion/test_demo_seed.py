from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HealthCheck, Lesion, Patient
from app.services.lesion_demo_seed_service import LesionMatchingDemoSeedService


def test_four_year_lesion_demo_seed_is_exact_and_idempotent(db_session: Session) -> None:
    first = LesionMatchingDemoSeedService(db_session).run()
    second = LesionMatchingDemoSeedService(db_session).run()

    patient = db_session.scalar(
        select(Patient).where(Patient.anonymous_code == "DEMO-LESION-PATIENT-001")
    )
    checks = db_session.scalars(
        select(HealthCheck)
        .where(HealthCheck.patient_id == patient.id)
        .order_by(HealthCheck.check_date)
    ).all()
    lesions = db_session.scalars(
        select(Lesion)
        .join(Lesion.imaging_exam)
        .join(HealthCheck)
        .where(HealthCheck.patient_id == patient.id)
        .order_by(HealthCheck.check_date)
    ).all()

    assert first.to_dict() == second.to_dict()
    assert [item.check_date.year for item in checks] == [2023, 2024, 2025, 2026]
    assert all(item.is_demo for item in checks)
    assert [item.size_mm for item in lesions] == [5.0, 5.3, 5.8, 6.2]
    assert all(item.description and "DEMO DATA" in item.description for item in lesions)
