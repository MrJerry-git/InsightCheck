import pytest

from app.features.lesion.terminology import LesionTerminology


@pytest.mark.parametrize("term", ["右上肺", "右肺上叶", "RUL"])
def test_right_upper_lobe_aliases_share_one_region(term: str) -> None:
    result = LesionTerminology().normalize_location(term)

    assert result.matched is True
    assert result.canonical_location == "RIGHT_UPPER_LOBE"
