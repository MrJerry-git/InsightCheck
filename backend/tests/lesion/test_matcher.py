from datetime import date

from app.features.lesion.matcher import LesionMatcher
from app.features.lesion.schemas import (
    LesionMatchingConfig,
    LesionMatchingRequest,
    LesionMatchStatus,
    LesionTrackCandidate,
    StructuredLesion,
    TrackPresenceStatus,
)


def lesion(
    lesion_id: str,
    exam_date: date,
    *,
    location: str | None = "右肺上叶",
    size_mm: float = 5.0,
    organ: str = "肺",
    grade: str | None = "实性",
) -> StructuredLesion:
    return StructuredLesion(
        lesion_id=lesion_id,
        exam_date=exam_date,
        lesion_type="肺结节",
        organ=organ,
        body_part="胸部",
        location=location,
        size_mm=size_mm,
        grade=grade,
    )


def test_identical_location_and_continuous_size_are_matched() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[lesion("new-1", date(2024, 6, 1), size_mm=5.3)],
        complete_body_parts=["胸部"],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.MATCHED
    assert result.matched_track_id == "track-1"
    assert result.confidence >= 0.80
    assert "病灶类型一致" in result.reasons
    assert "位置均属于右肺上叶" in result.reasons
    assert any(reason.startswith("尺寸变化连续") for reason in result.reasons)


def test_small_size_change_keeps_high_confidence() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[lesion("new-1", date(2024, 6, 1), size_mm=5.4)],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.MATCHED
    assert result.confidence >= 0.90


def test_same_organ_but_different_lobe_is_not_auto_matched() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-upper",
                observations=[lesion("old-upper", date(2023, 6, 1))],
            )
        ],
        current_lesions=[lesion("new-lower", date(2024, 6, 1), location="右肺下叶", size_mm=5.1)],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status != LesionMatchStatus.MATCHED
    assert result.matched_track_id is None
    assert any("位置冲突" in reason for reason in result.reasons)


def test_one_previous_track_cannot_match_two_lesions_in_same_exam() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[
            lesion("new-best", date(2024, 6, 1), size_mm=5.1),
            lesion("new-second", date(2024, 6, 1), size_mm=5.2),
        ],
    )

    results = LesionMatcher().match(request).matches

    assert sum(item.status == LesionMatchStatus.MATCHED for item in results) == 1
    assert len({item.matched_track_id for item in results if item.matched_track_id}) == 1
    unassigned = next(item for item in results if item.status != LesionMatchStatus.MATCHED)
    assert unassigned.status == LesionMatchStatus.NEW_LESION
    assert any("避免一对多错配" in reason for reason in unassigned.reasons)


def test_extreme_size_change_reduces_confidence_instead_of_forcing_match() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[lesion("new-1", date(2024, 6, 1), size_mm=25.0)],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.NEED_REVIEW
    assert result.matched_track_id is None
    assert result.confidence < 0.80
    assert any("尺寸变化幅度过大" in reason for reason in result.reasons)


def test_lesion_without_previous_track_is_new() -> None:
    result = (
        LesionMatcher()
        .match(
            LesionMatchingRequest(
                current_exam_date=date(2024, 6, 1),
                current_lesions=[lesion("new-1", date(2024, 6, 1))],
            )
        )
        .matches[0]
    )

    assert result.status == LesionMatchStatus.NEW_LESION
    assert result.matched_track_id is None
    assert result.confidence == 0


def test_low_confidence_candidate_requires_review_and_is_not_merged() -> None:
    current = lesion(
        "new-1",
        date(2024, 6, 1),
        location="右肺下叶",
        size_mm=25.0,
        grade="磨玻璃",
    )
    request = LesionMatchingRequest(
        current_exam_date=current.exam_date,
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[current],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.NEED_REVIEW
    assert 0.55 <= result.confidence < 0.80
    assert result.candidate_track_id == "track-1"
    assert result.matched_track_id is None


def test_missing_location_does_not_crash_or_auto_match() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-1",
                observations=[lesion("old-1", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[lesion("new-1", date(2024, 6, 1), location=None, size_mm=5.1)],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.NEED_REVIEW
    assert result.matched_track_id is None
    assert result.confidence < 0.80
    assert any("位置缺失" in reason for reason in result.reasons)


def test_confidence_property_always_stays_in_unit_interval() -> None:
    previous_track = LesionTrackCandidate(
        track_id="track-property",
        observations=[lesion("old", date(2023, 1, 1), size_mm=5.0)],
    )
    locations = [None, "右肺上叶", "右肺下叶", "未收录部位"]
    sizes = [0.0, 5.0, 5.4, 50.0]
    grades = [None, "实性", "磨玻璃"]

    for index, (location, size_mm, grade) in enumerate(
        (location, size_mm, grade)
        for location in locations
        for size_mm in sizes
        for grade in grades
    ):
        current = lesion(
            f"current-{index}",
            date(2024, 1, 1),
            location=location,
            size_mm=size_mm,
            grade=grade,
        )
        result = (
            LesionMatcher()
            .match(
                LesionMatchingRequest(
                    current_exam_date=current.exam_date,
                    previous_tracks=[previous_track],
                    current_lesions=[current],
                )
            )
            .matches[0]
        )

        assert 0 <= result.confidence <= 1


def test_missing_next_year_observation_is_disappeared_only_for_complete_scope() -> None:
    track = LesionTrackCandidate(
        track_id="track-1",
        observations=[lesion("old-1", date(2023, 6, 1))],
    )

    complete_result = LesionMatcher().match(
        LesionMatchingRequest(
            current_exam_date=date(2024, 6, 1),
            previous_tracks=[track],
            current_lesions=[],
            complete_body_parts=["胸部"],
        )
    )
    incomplete_result = LesionMatcher().match(
        LesionMatchingRequest(
            current_exam_date=date(2024, 6, 1),
            previous_tracks=[track],
            current_lesions=[],
            complete_body_parts=[],
        )
    )

    assert complete_result.track_presence[0].status == TrackPresenceStatus.DISAPPEARED
    assert complete_result.track_presence[0].disappeared is True
    assert incomplete_result.track_presence[0].status == TrackPresenceStatus.UNRESOLVED
    assert incomplete_result.track_presence[0].disappeared is False


def test_review_candidate_keeps_track_unresolved_not_disappeared() -> None:
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="track-review",
                observations=[lesion("old", date(2023, 6, 1))],
            )
        ],
        current_lesions=[lesion("current", date(2024, 6, 1), location="右肺下叶")],
        complete_body_parts=["胸部"],
    )

    result = LesionMatcher().match(request)

    assert result.matches[0].status == LesionMatchStatus.NEED_REVIEW
    assert result.track_presence[0].status == TrackPresenceStatus.UNRESOLVED
    assert result.track_presence[0].disappeared is False


def test_weights_and_thresholds_are_centralized_in_config() -> None:
    config = LesionMatchingConfig()

    assert config.weights.model_dump() == {
        "lesion_type": 0.35,
        "organ": 0.20,
        "location": 0.20,
        "size": 0.15,
        "grade": 0.10,
    }
    assert config.matched_threshold == 0.80
    assert config.review_threshold == 0.55


def test_latest_observation_in_previous_track_is_used() -> None:
    track = LesionTrackCandidate(
        track_id="track-history",
        observations=[
            lesion("old-outlier", date(2022, 6, 1), size_mm=25.0),
            lesion("old-latest", date(2023, 6, 1), size_mm=5.0),
        ],
    )
    request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[track],
        current_lesions=[lesion("current", date(2024, 6, 1), size_mm=5.3)],
    )

    result = LesionMatcher().match(request).matches[0]

    assert result.status == LesionMatchStatus.MATCHED
    assert result.confidence >= 0.90
    assert result.candidate_track_id == "track-history"


def test_long_time_interval_reduces_confidence() -> None:
    annual_request = LesionMatchingRequest(
        current_exam_date=date(2024, 6, 1),
        previous_tracks=[
            LesionTrackCandidate(
                track_id="annual",
                observations=[lesion("old-annual", date(2023, 6, 1), size_mm=5.0)],
            )
        ],
        current_lesions=[lesion("current", date(2024, 6, 1), size_mm=5.3)],
    )
    long_gap_request = annual_request.model_copy(
        update={
            "previous_tracks": [
                LesionTrackCandidate(
                    track_id="long-gap",
                    observations=[lesion("old-long", date(2020, 6, 1), size_mm=5.0)],
                )
            ]
        }
    )

    annual = LesionMatcher().match(annual_request).matches[0]
    long_gap = LesionMatcher().match(long_gap_request).matches[0]

    assert long_gap.confidence < annual.confidence
    assert any("检查间隔较长" in reason for reason in long_gap.reasons)
