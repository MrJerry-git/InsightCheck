"""H02 检查—发现—健康问题/疾病关联目录：结构约束与真实数据一致性。"""

import pytest

from app.exam_dictionary import (
    DictionaryValidationError,
    ExamDictionary,
    FindingCatalog,
    load_builtin_associations,
    load_builtin_catalog,
)


@pytest.fixture(scope="module")
def associations() -> FindingCatalog:
    return load_builtin_associations()


@pytest.fixture(scope="module")
def dictionary() -> ExamDictionary:  # noqa: F821
    return load_builtin_catalog()


def test_builtin_associations_load_with_version(associations: FindingCatalog) -> None:
    assert associations.VERSION == "finding-catalog-v1"
    assert len(associations.as_dicts()) >= 30


def test_association_ids_are_unique(associations: FindingCatalog) -> None:
    ids = [a["association_id"] for a in associations.as_dicts()]
    assert len(ids) == len(set(ids))


def test_relation_type_never_claims_diagnosis(associations: FindingCatalog) -> None:
    allowed = {"abnormality_suggests", "finding_observation", "risk_factor"}
    for payload in associations.as_dicts():
        assert payload["relation_type"] in allowed
        assert "确诊" not in payload["condition_name"], payload["association_id"]


def test_every_entry_has_source_and_pending_review(associations: FindingCatalog) -> None:
    for payload in associations.as_dicts():
        assert payload["source"], payload["association_id"]
        assert payload["source_version"], payload["association_id"]
        assert payload["review_status"] == "pending_review"


def test_associations_for_exam_sorted_and_filtered(associations: FindingCatalog) -> None:
    alt_rows = associations.associations_for_exam("1742-6")
    assert [a.association_id for a in alt_rows] == sorted(a.association_id for a in alt_rows)
    assert len(alt_rows) >= 1
    low_glucose = associations.conditions_for_exam("1558-6", "low")
    assert all(a.direction == "low" for a in low_glucose)


def test_builtin_catalog_cross_validation(
    associations: FindingCatalog, dictionary: ExamDictionary
) -> None:
    problems = associations.validate_against(dictionary)
    assert problems == [], "\n".join(problems)


def test_validate_against_flags_unknown_exam_code(dictionary: ExamDictionary) -> None:
    from app.exam_dictionary.catalog import parse_association

    bad = parse_association(
        {
            "association_id": "FA-TEST-UNKNOWN",
            "exam_code": "IC:M-NOT-REGISTERED",
            "condition_code": "E11.9",
            "condition_name": "示例",
            "relation_type": "abnormality_suggests",
            "direction": "high",
            "evidence_note": "示例",
            "source": "测试",
            "source_version": "1.0",
        },
        "test",
    )
    broken = FindingCatalog([bad])
    problems = broken.validate_against(dictionary)
    assert problems and "未登记" in problems[0]


def test_direction_matches_value_type(dictionary: ExamDictionary) -> None:
    for payload in load_builtin_associations().as_dicts():
        entry = dictionary.lookup_by_code(payload["exam_code"])
        assert entry is not None
        if entry.value_type == "numeric":
            assert payload["direction"] in ("high", "low", "any")
        if entry.value_type == "qualitative":
            assert payload["direction"] in ("qualitative_positive", "any")
        if entry.value_type in ("text", "structured"):
            assert payload["direction"] == "text_contains"


def test_text_associations_carry_pattern(
    associations: FindingCatalog, dictionary: ExamDictionary
) -> None:
    for association in associations.associations_for_exam("IC:M-ECG-CONCLUSION"):
        assert association.direction == "text_contains"
        assert association.text_pattern


def test_duplicate_association_id_rejected() -> None:
    from app.exam_dictionary.catalog import parse_association

    raw = {
        "association_id": "FA-DUP",
        "exam_code": "1742-6",
        "condition_code": "R74.0",
        "condition_name": "示例",
        "relation_type": "abnormality_suggests",
        "direction": "high",
        "evidence_note": "示例",
        "source": "测试",
        "source_version": "1.0",
    }
    with pytest.raises(DictionaryValidationError) as excinfo:
        FindingCatalog([parse_association(raw, "a"), parse_association(raw, "b")])
    assert "重复" in str(excinfo.value)
