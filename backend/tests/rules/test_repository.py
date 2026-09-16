import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import MedicalRule
from app.models.enums import RuleAction


def test_database_rejects_blank_rule_source(db_session: Session) -> None:
    db_session.add(
        MedicalRule(
            rule_code="SOURCE.BLANK",
            rule_type="AGE",
            condition_json={"allowed_min_age": 18},
            action=RuleAction.BLOCK,
            priority=50,
            source="   ",
            version="invalid-v1",
            enabled=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
