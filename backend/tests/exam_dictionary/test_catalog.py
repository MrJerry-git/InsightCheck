"""H01 体检字典目录：加载校验、查询、扩展登记、待映射队列与机构套餐。"""

import json
from pathlib import Path

import pytest

from app.exam_dictionary import (
    DictionaryValidationError,
    ExamDictionary,
    load_builtin_catalog,
)

H01_REQUIRED_CATEGORIES = (
    "basic_info",
    "physical_exam",
    "blood_routine",
    "urine_stool",
    "biochemistry",
    "metabolism_lipids",
    "ecg_function",
    "imaging",
    "extended",
)


@pytest.fixture(scope="module")
def dictionary() -> ExamDictionary:
    return load_builtin_catalog()


def test_builtin_catalog_loads_with_version(dictionary: ExamDictionary) -> None:
    assert dictionary.VERSION == "exam-dictionary-v1"
    assert len(dictionary) >= 60


def test_every_category_from_task_section_two_is_covered(dictionary: ExamDictionary) -> None:
    present = {entry.category for entry in dictionary.entries_by_kind("metric")} | {
        entry.category for entry in dictionary.entries_by_kind("exam_item")
    }
    for category in H01_REQUIRED_CATEGORIES:
        assert category in present, f"缺少类别覆盖：{category}"


def test_every_entry_has_source_version_and_review_status(dictionary: ExamDictionary) -> None:
    for code in dictionary.all_codes():
        entry = dictionary.lookup_by_code(code)
        assert entry is not None
        assert entry.source, f"{code} 缺少来源"
        assert entry.source_version, f"{code} 缺少来源版本"
        assert entry.review_status == "pending_review", f"{code} 不得宣称医学审核通过"


def test_value_type_constraints_hold(dictionary: ExamDictionary) -> None:
    for code in dictionary.all_codes():
        entry = dictionary.lookup_by_code(code)
        assert entry is not None
        if entry.value_type == "numeric":
            assert entry.standard_unit, f"数值条目 {code} 缺少标准单位"
        if entry.value_type == "qualitative":
            assert entry.qualitative_values, f"定性条目 {code} 缺少允许值"
        for rng in entry.reference_ranges:
            assert rng.source, f"{code} 的参考区间缺少出处"
            assert rng.population, f"{code} 的参考区间缺少适用条件"


def test_lookup_by_display_name_and_alias(dictionary: ExamDictionary) -> None:
    alt = dictionary.lookup("丙氨酸氨基转移酶")
    assert alt is not None and alt.code == "1742-6"
    assert dictionary.lookup("谷丙转氨酶") is not None
    assert dictionary.lookup("alt") is not None
    assert dictionary.lookup("  ALT（谷丙转氨酶） ") is None  # 整串匹配，不做自动解释


def test_lookup_by_code(dictionary: ExamDictionary) -> None:
    entry = dictionary.lookup_by_code("718-7")
    assert entry is not None and entry.value_type == "numeric"
    assert dictionary.lookup_by_code("NOT-REGISTERED") is None
    assert dictionary.lookup_by_code("") is None


def test_entries_by_category_is_sorted(dictionary: ExamDictionary) -> None:
    codes = [e.code for e in dictionary.entries_by_category("blood_routine")]
    assert codes == sorted(codes)
    assert len(codes) >= 5


def test_register_unknown_and_resolve_roundtrip(dictionary: ExamDictionary) -> None:
    registered = dictionary.register_unknown(
        "血浆D-二聚体", context="示例导入", batch="batch-1"
    )
    assert registered.status == "pending_mapping"
    dictionary.register_unknown("血浆D-二聚体", batch="batch-2")  # 去重
    queue = dictionary.unmapped_queue()
    assert len(queue) == 1
    assert queue[0].raw_name == "血浆D-二聚体"
    assert queue[0].first_seen_batch == "batch-1"
    # 未登记编码不能当作补映射目标，且失败不改动队列
    with pytest.raises(DictionaryValidationError):
        dictionary.resolve_unmapped("血浆D-二聚体", "IC:M-NOT-THERE")
    assert len(dictionary.unmapped_queue()) == 1
    # 从未登记过的名称返回 False，不影响队列
    assert dictionary.resolve_unmapped("从未出现的未知项", "2160-0") is False
    assert len(dictionary.unmapped_queue()) == 1
    assert dictionary.resolve_unmapped("血浆D-二聚体", "2160-0") is True
    assert dictionary.unmapped_queue() == ()


def test_register_unknown_rejects_blank(dictionary: ExamDictionary) -> None:
    with pytest.raises(DictionaryValidationError):
        dictionary.register_unknown("   ")


def test_extension_registration_merges_new_entries(tmp_path: Path) -> None:
    extra = tmp_path / "extra_metrics.json"
    extra.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "code": "IC:M-D-DIMER",
                        "entry_kind": "metric",
                        "display_name": "D-二聚体",
                        "aliases": ["D-dimer"],
                        "category": "extended",
                        "system": "hematology",
                        "value_type": "numeric",
                        "standard_unit": "mg/L",
                        "source": "扩展登记示例",
                        "source_version": "1.0",
                        "review_status": "pending_review",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    merged = ExamDictionary.load_with_extensions([extra])
    assert merged.lookup_by_code("IC:M-D-DIMER") is not None
    assert merged.lookup("D-二聚体") is not None
    # 内置条目仍在
    assert merged.lookup_by_code("718-7") is not None


def test_extension_registration_rejects_duplicate_codes(tmp_path: Path) -> None:
    extra = tmp_path / "dup.json"
    extra.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "code": "718-7",
                        "entry_kind": "metric",
                        "display_name": "血红蛋白重复登记",
                        "category": "blood_routine",
                        "system": "hematology",
                        "value_type": "numeric",
                        "standard_unit": "g/L",
                        "source": "示例",
                        "source_version": "1.0",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(DictionaryValidationError) as excinfo:
        ExamDictionary.load_with_extensions([extra])
    assert "编码重复" in str(excinfo.value)


def test_loader_rejects_numeric_entry_without_unit(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "code": "IC:M-BAD",
                        "entry_kind": "metric",
                        "display_name": "坏条目",
                        "category": "extended",
                        "system": "general",
                        "value_type": "numeric",
                        "source": "示例",
                        "source_version": "1.0",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(DictionaryValidationError) as excinfo:
        ExamDictionary.load_with_extensions([bad])
    assert "standard_unit" in str(excinfo.value)


def test_demo_package_validates_against_dictionary(dictionary: ExamDictionary) -> None:
    package_path = (
        Path(__file__).parents[2]
        / "app"
        / "exam_dictionary"
        / "data"
        / "packages"
        / "demo_package.json"
    )
    package = dictionary.load_package(package_path)
    assert package.package_id == "demo-basic-checkup"
    for code in package.exam_item_codes:
        assert dictionary.lookup_by_code(code) is not None


def test_package_with_unknown_code_is_rejected(dictionary: ExamDictionary, tmp_path: Path) -> None:
    bad = tmp_path / "bad_package.json"
    bad.write_text(
        json.dumps(
            {
                "package_id": "broken",
                "version": "1.0",
                "institution": "示例",
                "exam_item_codes": ["IC:EX-NOT-REGISTERED"],
                "source": "示例",
                "source_version": "1.0",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(DictionaryValidationError) as excinfo:
        dictionary.load_package(bad)
    assert "未登记编码" in str(excinfo.value)


def test_as_dict_roundtrip_fields(dictionary: ExamDictionary) -> None:
    entry = dictionary.lookup_by_code("1742-6")
    assert entry is not None
    payload = entry.as_dict()
    assert payload["code"] == "1742-6"
    assert payload["reference_ranges"][0]["source"].startswith("WS/T 404-2012")
    assert payload["aliases"] == ["ALT", "谷丙转氨酶", "GPT"]


# ---- 参考区间边界校验（审查 P2）：拒绝倒置、布尔与非有限值 ----

def _entry_with_range(min_value: object, max_value: object) -> dict:
    return {
        "entries": [
            {
                "code": "IC:M-RANGE-CHECK",
                "entry_kind": "metric",
                "display_name": "参考区间校验条目",
                "category": "extended",
                "system": "general",
                "value_type": "numeric",
                "standard_unit": "mmol/L",
                "reference_ranges": [
                    {
                        "population": "成人",
                        "min_value": min_value,
                        "max_value": max_value,
                        "unit": "mmol/L",
                        "source": "审查回归示例",
                        "source_version": "1.0",
                    }
                ],
                "source": "审查回归示例",
                "source_version": "1.0",
            }
        ]
    }


def test_inverted_reference_range_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "inverted.json"
    bad.write_text(json.dumps(_entry_with_range(10, 1), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DictionaryValidationError) as excinfo:
        ExamDictionary.load_with_extensions([bad])
    assert "min_value 不能大于 max_value" in str(excinfo.value)


def test_boolean_reference_bound_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bool.json"
    bad.write_text(json.dumps(_entry_with_range(True, 6.1), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DictionaryValidationError) as excinfo:
        ExamDictionary.load_with_extensions([bad])
    assert "min_value 必须是有限数字或 null" in str(excinfo.value)


def test_non_finite_reference_bound_is_rejected(tmp_path: Path) -> None:
    import math

    bad = tmp_path / "nan.json"
    bad.write_text(json.dumps(_entry_with_range(float("nan"), 6.1), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DictionaryValidationError) as excinfo:
        ExamDictionary.load_with_extensions([bad])
    assert "min_value 必须是有限数字" in str(excinfo.value)


def test_valid_reference_range_still_parses(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_entry_with_range(3.9, 6.1), ensure_ascii=False), encoding="utf-8")
    merged = ExamDictionary.load_with_extensions([good])
    entry = merged.lookup_by_code("IC:M-RANGE-CHECK")
    assert entry is not None
    assert entry.reference_ranges[0].min_value == 3.9
    assert entry.reference_ranges[0].max_value == 6.1
