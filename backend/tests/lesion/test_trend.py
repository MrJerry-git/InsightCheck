from datetime import date

import pytest

from app.features.lesion.schemas import (
    GradeChange,
    LesionMatchStatus,
    LesionTrendRequest,
    StructuredLesion,
    TrackPresenceStatus,
)
from app.features.lesion.trend import LesionTrendAnalyzer


def observation(lesion_id: str, year: int, size_mm: float, grade: str = "G1") -> StructuredLesion:
    return StructuredLesion(
        lesion_id=lesion_id,
        exam_date=date(year, 6, 1),
        lesion_type="肺结节",
        organ="肺",
        body_part="胸部",
        location="右肺上叶",
        size_mm=size_mm,
        grade=grade,
    )


def test_four_year_demo_track_produces_explainable_growth_features() -> None:
    result = LesionTrendAnalyzer().analyze(
        LesionTrendRequest(
            track_id="demo-track",
            observations=[
                observation("lesion-2023", 2023, 5.0, "G1"),
                observation("lesion-2024", 2024, 5.3, "G1"),
                observation("lesion-2025", 2025, 5.8, "G2"),
                observation("lesion-2026", 2026, 6.2, "G2"),
            ],
            evaluation_date=date(2026, 6, 1),
            initial_match_status=LesionMatchStatus.NEW_LESION,
            presence_status=TrackPresenceStatus.CONTINUING,
        )
    )

    assert result.absolute_size_change == pytest.approx(1.2)
    assert result.relative_size_change == pytest.approx(0.24)
    assert result.growth_rate == pytest.approx(0.4)
    assert result.grade_change == GradeChange.INCREASED
    assert result.continuous_occurrences == 4
    assert result.months_since_last_exam == 0
    assert result.new_lesion is False
    assert result.disappeared is False
    assert result.stable is False
    assert result.growing is True
    assert result.shrinking is False
