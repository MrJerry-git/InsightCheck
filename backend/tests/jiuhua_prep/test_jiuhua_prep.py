"""H11 九华数据接入准备：映射模板、质量摘要、匿名标识。"""

import pytest

from app.jiuhua_prep import (
    FieldMappingRegistry,
    MappingValidationError,
    anonymize_identifier,
    batch_provenance,
    load_mapping_template,
    summarize_quality,
)


@pytest.fixture(scope="module")
def registry() -> FieldMappingRegistry:
    return FieldMappingRegistry.load_builtin()


def test_builtin_template_loads_all_unverified(registry: FieldMappingRegistry) -> None:
    entries = registry.entries()
    assert len(entries) >= 12
    for entry in entries:
        assert entry.verification_status == "unverified", entry.source_field
        assert entry.source_description, entry.source_field


def test_identifiers_must_be_anonymized(registry: FieldMappingRegistry) -> None:
    entry = registry.lookup("person_id")
    assert entry is not None
    assert entry.value_type == "identifier"
    assert entry.target_entity == "patient"
    assert "anonymize" in (entry.notes or "") + entry.source_description


def test_unknown_source_fields_queued_not_guessed(registry: FieldMappingRegistry) -> None:
    unknown = registry.unknown_source_fields(["person_id", "mystery_col", "", "  "])
    assert unknown == ["mystery_col"]


def test_quality_summary_counts_and_missing_rates(registry: FieldMappingRegistry) -> None:
    rows = [
        {"person_id": "A001", "result": "7.2", "unit": "mmol/L"},
        {"person_id": "A002", "result": "", "unit": "mmol/L"},
        {"person_id": "", "result": "正常", "unit": ""},
    ]
    summary = summarize_quality(rows, registry)
    assert summary.row_count == 3
    by_name = {f.source_field: f for f in summary.fields}
    assert by_name["person_id"].missing_rate == pytest.approx(1 / 3)
    assert by_name["result"].missing_rate == pytest.approx(1 / 3)
    assert by_name["person_id"].registered is True
    assert by_name["unit"].sample_values == ["mmol/L"]
    assert summary.unknown_fields == []


def test_label_followup_fields_marked_to_be_verified(registry: FieldMappingRegistry) -> None:
    rows = [{"person_id": "A001", "followup_label": "阳性"}]
    summary = summarize_quality(rows, registry)
    followup = summary.fields[0]
    assert followup.label_followup_status == "to_be_verified"
    assert followup.registered is False  # 模板未登记标签字段
    assert summary.notes and "to_be_verified" in summary.notes[0]


def test_anonymize_identifier_is_deterministic_and_salt_guarded() -> None:
    first = anonymize_identifier("A001", "project-salt")
    second = anonymize_identifier("A001", "project-salt")
    assert first == second
    assert first != "A001"
    assert anonymize_identifier("A001", "other-salt") != first
    with pytest.raises(ValueError):
        anonymize_identifier("A001", "  ")
    with pytest.raises(ValueError):
        anonymize_identifier(" ", "salt")


def test_batch_provenance_fields() -> None:
    provenance = batch_provenance("2026Q4 示例批次")
    assert provenance["source_dataset"] == "jiuhua"
    assert provenance["source_kind"] == "partner_observational"
    assert "未到达" in provenance["adapter_version"]
    assert provenance["batch_note"] == "2026Q4 示例批次"


def test_template_validation_rejects_unknown_target(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"entries": [{"source_field": "x", "source_description": "d",'
        ' "target_entity": "patient", "target_field": "not_a_field",'
        ' "value_type": "text", "verification_status": "unverified"}]}',
        encoding="utf-8",
    )
    with pytest.raises(MappingValidationError) as excinfo:
        load_mapping_template(bad)
    assert "未知目标" in str(excinfo.value)


def test_template_validation_rejects_invalid_status(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"entries": [{"source_field": "x", "source_description": "d",'
        ' "target_entity": "patient", "target_field": "sex",'
        ' "value_type": "qualitative", "verification_status": "checked"}]}',
        encoding="utf-8",
    )
    with pytest.raises(MappingValidationError) as excinfo:
        load_mapping_template(bad)
    assert "verification_status" in str(excinfo.value)


def test_empty_rows_yield_empty_summary(registry: FieldMappingRegistry) -> None:
    summary = summarize_quality([], registry)
    assert summary.row_count == 0
    assert summary.fields == []
