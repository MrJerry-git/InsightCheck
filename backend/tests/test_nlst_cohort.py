import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from app.research.nlst import EXPECTED_SHA256  # noqa: E402
from app.research.nlst_cohort import (  # noqa: E402
    ADAPTER_VERSION,
    COHORT_ID,
    DATASET_VERSION,
    FIELD_MAPPING,
    KEYS,
    MODELING_APPROVED_COLUMNS,
    OUTPUT_FILES,
    TABLES,
    TASK_STATUS,
    build,
    emit_labels,
    excluded_conflicts,
    label_refusal,
    mapping_document,
    write,
)


def _tables():
    version = DATASET_VERSION
    people = pd.DataFrame(
        [
            {
                "pid": "P1",
                "age": "60",
                "gender": "1",
                "race": "1",
                "cigsmok": "2",
                "scr_days1": "120",
                "dataset_version": version,
            },
            {
                "pid": "P2",
                "age": "65",
                "gender": "2",
                "race": "1",
                "cigsmok": "1",
                "scr_days1": ".N",
                "dataset_version": version,
            },
            {
                "pid": "P3",
                "age": "70",
                "gender": "1",
                "race": ".",
                "cigsmok": "2",
                "scr_days1": "130",
                "dataset_version": version,
            },
        ]
    )
    screen = pd.DataFrame(
        [
            {"pid": "P1", "study_yr": 0, "dataset_version": version},
            {"pid": "P1", "study_yr": 1, "dataset_version": version},
            {"pid": "P2", "study_yr": 1, "dataset_version": version},
        ]
    )
    abnormality = pd.DataFrame(
        [
            {
                "pid": "P1",
                "study_yr": 1,
                "sct_ab_num": "1",
                "sct_long_dia": "8",
                "sct_perp_dia": "6",
                "dataset_version": version,
            },
            {
                "pid": "P1",
                "study_yr": 1,
                "sct_ab_num": "2",
                "sct_long_dia": "12",
                "sct_perp_dia": "9",
                "dataset_version": version,
            },
            {
                "pid": "P2",
                "study_yr": 1,
                "sct_ab_num": "1",
                "sct_long_dia": ".N",
                "sct_perp_dia": ".N",
                "dataset_version": version,
            },
        ]
    )
    comparison = pd.DataFrame(
        [
            {"pid": "P1", "study_yr": 1, "sct_ab_num": "1", "dataset_version": version},
            {"pid": "P1", "study_yr": 1, "sct_ab_num": "9", "dataset_version": version},
        ]
    )
    cancer = pd.DataFrame([{"pid": "P1", "lc_order": "1", "dataset_version": version}])
    dictionary = pd.DataFrame(
        [
            {
                "collection_id": "nlst",
                "short_table_name": "nlst_prsn",
                "column": "scr_days1",
                "column_label": "fixture label",
            }
        ]
    )
    return {
        "nlst_prsn": people,
        "nlst_screen": screen,
        "nlst_ctab": abnormality,
        "nlst_ctabc": comparison,
        "nlst_canc": cancer,
        "clinical_index": dictionary,
    }


def snapshot(tmp_path: Path) -> Path:
    directory = tmp_path / "raw"
    directory.mkdir(exist_ok=True)
    for name, frame in _tables().items():
        frame.to_parquet(directory / f"{name}.parquet")
    return directory


def test_build_columns_match_the_declared_mapping(tmp_path):
    frame, _ = build(snapshot(tmp_path), verify=False)
    assert list(frame.columns) == [mapping.column for mapping in FIELD_MAPPING]
    assert "label" not in frame.columns
    assert set(KEYS).issubset(TABLES)


def test_subject_ids_are_namespaced_and_sorted(tmp_path):
    frame, quality = build(snapshot(tmp_path), verify=False)
    assert frame.subject_id.tolist() == [f"{COHORT_ID}:P1", f"{COHORT_ID}:P2", f"{COHORT_ID}:P3"]
    assert quality["subjects"] == 3
    assert COHORT_ID + ":" in quality["subject_id_policy"]


def test_absent_round_is_unknown_and_never_filled_with_zero(tmp_path):
    frame, quality = build(snapshot(tmp_path), verify=False)
    indexed = frame.set_index("subject_id")
    absent = indexed.loc[f"{COHORT_ID}:P3"]
    assert bool(absent.screen_observed_t1) is False
    assert pd.isna(absent.ab_records_t1)
    assert absent.ct_screen_rounds == 0
    observed = indexed.loc[f"{COHORT_ID}:P1"]
    assert bool(observed.screen_observed_t1) is True
    assert observed.ab_records_t1 == 2
    assert observed.ab_number_t1_max == 2
    assert observed.ab_long_dia_t1_max == 12
    assert quality["coverage"]["screen_observed"] == {"t0": 1, "t1": 2, "t2": 0}


def test_special_missing_codes_are_unknown_not_zero(tmp_path):
    frame, _ = build(snapshot(tmp_path), verify=False)
    indexed = frame.set_index("subject_id")
    assert pd.isna(indexed.loc[f"{COHORT_ID}:P2", "index_scr_days"])
    assert pd.isna(indexed.loc[f"{COHORT_ID}:P3", "race"])
    assert indexed.loc[f"{COHORT_ID}:P1", "index_scr_days"] == 120


def test_unmatched_comparison_rows_are_counted(tmp_path):
    frame, quality = build(snapshot(tmp_path), verify=False)
    indexed = frame.set_index("subject_id")
    assert indexed.loc[f"{COHORT_ID}:P1", "ctabc_records_t1"] == 2
    assert indexed.loc[f"{COHORT_ID}:P1", "ctabc_unmatched_t1"] == 1
    assert quality["coverage"]["ctabc_unmatched_t1_total"] == 1


def test_quality_summary_holds_no_identifiers_or_labels(tmp_path):
    _, quality = build(snapshot(tmp_path), verify=False)
    text = json.dumps(quality, ensure_ascii=False)
    assert "P1" not in text and "P2" not in text and "P3" not in text
    assert quality["adapter_version"] == ADAPTER_VERSION
    assert quality["label_column"] is None
    assert quality["task_status"] == TASK_STATUS
    assert quality["clinical_use"] is False
    assert quality["privacy"].startswith("aggregate counts only")
    assert quality["columns"][0]["column"] == "subject_id"


def test_only_reviewed_fields_are_approved_for_modeling():
    assert MODELING_APPROVED_COLUMNS == ("index_scr_days",)
    assert excluded_conflicts() == []
    approved = {m.column for m in FIELD_MAPPING if m.role == "feature"}
    assert approved == set(MODELING_APPROVED_COLUMNS)
    for mapping in FIELD_MAPPING:
        if mapping.role == "descriptive":
            assert mapping.semantics in {"structure_only", "reviewed"}


def test_label_generation_is_refused():
    with pytest.raises(ValueError, match="refused"):
        emit_labels()
    assert TASK_STATUS in label_refusal()


def test_unreviewed_snapshot_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="snapshot hash differs"):
        build(snapshot(tmp_path), verify=True)


def test_unexpected_dataset_version_is_rejected(tmp_path):
    directory = snapshot(tmp_path)
    frame = pd.read_parquet(directory / "nlst_prsn.parquet")
    frame["dataset_version"] = "2099.01.01"
    frame.to_parquet(directory / "nlst_prsn.parquet")
    with pytest.raises(ValueError, match="unexpected dataset versions"):
        build(directory, verify=False)


def test_write_produces_documented_files_and_refuses_overwrite(tmp_path):
    directory = snapshot(tmp_path)
    output = tmp_path / "processed"
    quality = write(directory, output, verify=False)
    assert len(quality["features_sha256"]) == 64
    assert (output / OUTPUT_FILES["features"]).is_file()
    assert (output / OUTPUT_FILES["mapping"]).is_file()
    written = json.loads((output / OUTPUT_FILES["quality"]).read_text(encoding="utf-8"))
    assert written["rows"] == 3
    assert written["files"]["nlst_prsn"]["reference_sha256"] == EXPECTED_SHA256["nlst_prsn"]
    assert written["files"]["nlst_prsn"]["matches_reference_snapshot"] is False
    assert "P1" not in json.dumps(written, ensure_ascii=False)
    with pytest.raises(ValueError, match="output already exists"):
        write(directory, output, verify=False)


def test_mapping_document_is_committable(tmp_path):
    document = mapping_document()
    assert len(document["columns"]) == len(FIELD_MAPPING)
    assert document["privacy"] == "no subject identifiers"
    assert document["modeling_approved_columns"] == list(MODELING_APPROVED_COLUMNS)
    assert any(entry["table"] == "nlst_canc" for entry in document["excluded_fields"])
