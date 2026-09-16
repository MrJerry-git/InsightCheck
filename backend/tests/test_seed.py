from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AIReport,
    HealthCheck,
    Recommendation,
    RecommendationItem,
    RiskPrediction,
)
from app.services.seed_service import DemoSeedService


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_demo_seed_is_explicit_and_idempotent(db_session: Session) -> None:
    first = DemoSeedService(db_session).run()
    second = DemoSeedService(db_session).run()

    assert first.to_dict() == second.to_dict()
    assert second.health_check_count == 4
    assert second.lab_metric_count == 4
    assert second.imaging_exam_count == 4
    assert second.lesion_observation_count == 4
    assert all(db_session.scalars(select(HealthCheck.is_demo)).all())


def test_demo_seed_does_not_fabricate_model_outputs(db_session: Session) -> None:
    DemoSeedService(db_session).run()

    assert _count(db_session, RiskPrediction) == 0
    assert _count(db_session, Recommendation) == 0
    assert _count(db_session, RecommendationItem) == 0
    assert _count(db_session, AIReport) == 0
