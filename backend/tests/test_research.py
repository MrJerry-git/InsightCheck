import json

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("lightgbm")
pytest.importorskip("pyarrow")

import joblib  # noqa: E402
import numpy as np  # noqa: E402

from app.research.nlst import KEYS, TABLES, audit, download, missing  # noqa: E402
from app.research.risk_baseline import (  # noqa: E402
    TaskSpec,
    estimators,
    metrics,
    run,
    split_subjects,
    validate_data,
)


def task(**changes):
    return TaskSpec(
        **{
            "task_id": "synthetic-engineering-test",
            "version": "1",
            "status": "FROZEN",
            "source_kind": "synthetic",
            "features": ["x", "z"],
            "forbidden_features": ["candx_days"],
            "outcome_definition": "artificial binary fixture",
            "negative_definition": "artificial fixture label zero",
            "availability_assumptions": "no real clinical times",
            "review_record": "engineering fixture only; no clinical validity",
            "data_manifest_sha256": "0" * 64,
            "dataset_sha256": "0" * 64,
            **changes,
        }
    )


def dataset():
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "subject_id": [f"synthetic-{n}" for n in range(100)],
            "label": [0, 1] * 50,
            "x": rng.normal(size=100),
            "z": rng.normal(size=100),
        }
    )


def test_unfrozen_task_fails_before_writes(tmp_path):
    with pytest.raises(ValueError, match="FROZEN"):
        run(dataset(), task(status="BLOCKED"), tmp_path / "experiment")
    assert not (tmp_path / "experiment").exists()


def test_download_rejects_changed_cached_source(tmp_path):
    (tmp_path / "nlst_prsn.parquet").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="cached source hash differs"):
        download(tmp_path)


@pytest.mark.parametrize("mismatch", ["manifest", "dataset"])
def test_cli_rejects_unreviewed_file_hashes(tmp_path, monkeypatch, mismatch):
    from app.research.nlst import sha256
    from app.research.risk_baseline import main

    data_path = tmp_path / "cohort.parquet"
    dataset().to_parquet(data_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    spec = task(
        data_manifest_sha256=sha256(manifest), dataset_sha256=sha256(data_path)
    ).model_dump()
    spec["data_manifest_sha256" if mismatch == "manifest" else "dataset_sha256"] = "f" * 64
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(spec))
    output = tmp_path / "run"
    monkeypatch.setattr(
        "sys.argv",
        [
            "risk_baseline",
            "--task",
            str(task_path),
            "--data",
            str(data_path),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(ValueError, match="differs from the reviewed task"):
        main()
    assert not output.exists()


@pytest.mark.parametrize("problem", ["repeat", "unknown", "extra", "infinite"])
def test_invalid_dataset_rejected(problem):
    frame = dataset()
    if problem == "repeat":
        frame.loc[1, "subject_id"] = frame.loc[0, "subject_id"]
    elif problem == "unknown":
        frame.loc[0, "label"] = -1
    elif problem == "extra":
        frame["candx_days"] = 100
    else:
        frame.loc[0, "x"] = np.inf
    with pytest.raises(ValueError):
        validate_data(frame, task())


def test_split_subject_isolation_and_order_stability():
    first = split_subjects(validate_data(dataset(), task()), 42)
    shuffled = split_subjects(validate_data(dataset().sample(frac=1), task()), 42)
    groups = {key: set(value.subject_id) for key, value in first.items()}
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & (groups["test"] | groups["train"])
    assert groups == {key: set(value.subject_id) for key, value in shuffled.items()}


def test_imputer_learns_training_only():
    model = estimators(42)["logistic"]
    frame = dataset()
    frame.loc[:20, "x"] = np.nan
    model.fit(frame[["x", "z"]], frame.label)
    expected = frame.x.median()
    model.predict_proba(pd.DataFrame({"x": [1e9, np.nan], "z": [0, 0]}))
    assert model.named_steps["impute"].statistics_[0] == pytest.approx(expected)


def test_metrics_have_explicit_threshold_and_confusion():
    result = metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.7, 0.6, 0.9]))
    assert result["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 0, "tp": 2}
    assert result["sensitivity"] == 1
    assert result["specificity"] == 0.5


def test_three_baselines_save_reload_and_preserve_output(tmp_path):
    target = tmp_path / "run"
    report = run(dataset(), task(), target)
    assert set(report["models"]) == {"logistic", "random_forest", "lightgbm"}
    assert report["clinical_use"] is False
    assert report["task"]["source_kind"] == "synthetic"
    assert len(report["split_sha256"]) == 64
    predictions = pd.read_csv(target / "predictions.csv")
    frame = dataset().set_index("subject_id")
    for name in report["models"]:
        artifact = joblib.load(target / f"{name}.joblib")  # Locally generated test artifact.
        expected = predictions[predictions.model == name]
        actual = artifact["pipeline"].predict_proba(frame.loc[expected.subject_id, ["x", "z"]])[
            :, 1
        ]
        np.testing.assert_allclose(actual, expected.probability)
    assert json.loads((target / "report.json").read_text())["seed"] == 20260916
    with pytest.raises(ValueError, match="already exists"):
        run(dataset(), task(), target)


def test_nlst_special_missing_and_aggregate_audit(tmp_path):
    assert missing(pd.Series([None, ".N", ".E", ".", "", "0", "12"])).tolist() == [
        True,
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    for table in TABLES:
        row = {key: "0" for key in KEYS[table]}
        row.update(pid="PRIVATE-SUBJECT-ID", dataset_version="fixture")
        pd.DataFrame([row]).to_parquet(tmp_path / f"{table}.parquet")
    pd.DataFrame(
        [
            {
                "collection_id": "nlst",
                "short_table_name": "nlst_prsn",
                "column": "canc_free_days",
                "column_label": "fixture restriction",
            }
        ]
    ).to_parquet(tmp_path / "clinical_index.parquet")
    report = audit(tmp_path)
    assert "PRIVATE-SUBJECT-ID" not in json.dumps(report)
    assert report["outcome_field_presence"]["fup_days"] is False
    assert report["tables"]["nlst_prsn"]["duplicate_key_rows"] == 0
