import json
from pathlib import Path

import pytest
from pydantic import ValidationError

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")
pytest.importorskip("lightgbm")

from app.ml.contracts import ModelArtifactMetadata, TrainingDataset  # noqa: E402
from app.ml.risk import (  # noqa: E402
    ALGORITHMS,
    ARTIFACT_PIPELINE_FILENAME,
    BaselineExperimentRegistration,
    BaselineRiskAdapter,
    RiskAssessmentStatus,
    RiskFeatureSpec,
    RiskModelCard,
    RiskModelUnavailableError,
    RiskPredictionRequest,
    RiskTaskKind,
    RiskUnavailableReason,
    RiskWarning,
    load_risk_model,
    require_risk_model,
)
from app.research.risk_baseline import TaskSpec, run  # noqa: E402


def feature_specs(**changes):
    payload = {
        "name": "x",
        "source": "synthetic fixture generator",
        "unit": "unitless",
        "review_status": "reviewed",
    }
    payload.update(changes)
    return (
        RiskFeatureSpec(**payload),
        RiskFeatureSpec(
            name="z",
            source="synthetic fixture generator",
            unit="unitless",
            review_status="reviewed",
        ),
    )


def card(**changes):
    payload = {
        "model_version": "fixture-risk-v1",
        "algorithm": "logistic",
        "feature_pipeline_version": "fixture-features-v1",
        "risk_code": "fixture-outcome",
        "task_kind": RiskTaskKind.SAME_ROUND_FINDING,
        "task_id": "synthetic-engineering-test",
        "task_version": "1",
        "review_status": "FROZEN",
        "outcome_definition": "artificial binary fixture",
        "negative_definition": "artificial fixture label zero",
        "availability_assumptions": "no real clinical times",
        "review_record": "engineering fixture only; no clinical validity",
        "data_source_kind": "synthetic",
        "is_synthetic": True,
        "required_features": feature_specs(),
        "applicable_populations": ("fixture-population",),
        "population_definition": "synthetic fixture only; no real population",
        "limitations": ("engineering fixture; not a clinical model",),
        "training_split_sha256": "0" * 64,
    }
    payload.update(changes)
    return RiskModelCard(**payload)


def dataset(size: int = 200):
    rng = np.random.default_rng(7)
    records = tuple(
        {"x": float(rng.normal()), "z": float(rng.normal())} for _ in range(size)
    )
    return TrainingDataset(
        records=records,
        labels=tuple(index % 2 for index in range(size)),
        dataset_version="fixture-v1",
    )


def request(**changes):
    payload = {
        "subject_id": "fixture-1",
        "features": {"x": 0.25, "z": -0.75},
        "feature_pipeline_version": "fixture-features-v1",
        "population": "fixture-population",
        "trace_id": "trace-1",
    }
    payload.update(changes)
    return RiskPredictionRequest(**payload)


def trained(tmp_path: Path, algorithm: str = "logistic"):
    adapter = BaselineRiskAdapter(card(algorithm=algorithm))
    metadata = adapter.train(dataset())
    adapter.save(tmp_path / f"artifact-{algorithm}", metadata)
    return require_risk_model(tmp_path / f"artifact-{algorithm}")


def test_algorithm_list_matches_offline_baseline():
    from app.research.risk_baseline import estimators

    assert tuple(ALGORITHMS) == tuple(estimators(1))


def test_card_rejects_unsafe_declarations():
    with pytest.raises(ValidationError, match="False"):
        card(clinical_use=True)
    with pytest.raises(ValueError, match="is_synthetic must match"):
        card(data_source_kind="public_observational")
    with pytest.raises(ValueError, match="forbidden feature"):
        card(required_features=feature_specs(name="candx_days"), forbidden_features=("candx_days",))
    with pytest.raises(ValueError, match="split manifest hash"):
        card(training_split_sha256=None)


def test_card_warnings_keep_synthetic_and_internal_split_labels():
    warnings = card().warnings
    assert RiskWarning.SYNTHETIC_ARTIFACT_ENGINEERING_ONLY in warnings
    assert RiskWarning.NO_CLINICAL_USE in warnings
    assert RiskWarning.INTERNAL_SPLIT_NOT_EXTERNAL_VALIDATION in warnings
    assert RiskWarning.UNCALIBRATED in warnings


@pytest.mark.parametrize("algorithm", ["logistic", "lightgbm"])
def test_save_then_load_reproduces_predictions(tmp_path, algorithm):
    adapter = BaselineRiskAdapter(card(algorithm=algorithm))
    metadata = adapter.train(dataset())
    target = tmp_path / f"artifact-{algorithm}"
    adapter.save(target, metadata)
    assert len(adapter.card.artifact_sha256) == 64

    loaded = require_risk_model(target)
    assert loaded.card == adapter.card
    assert loaded.warnings == adapter.card.warnings
    features = {"x": 0.4, "z": -0.2}
    assert loaded.predict("fixture-1", features)[0].probability == pytest.approx(
        adapter.predict("fixture-1", features)[0].probability
    )
    assert (target / ARTIFACT_PIPELINE_FILENAME).is_file()


def test_save_refuses_to_overwrite_and_metadata_must_match(tmp_path):
    adapter = BaselineRiskAdapter(card())
    metadata = adapter.train(dataset())
    with pytest.raises(ValueError, match="metadata does not match"):
        adapter.save(tmp_path / "artifact", ModelArtifactMetadata("other", "other", "now"))
    adapter.save(tmp_path / "artifact", metadata)
    with pytest.raises(ValueError, match="already exists"):
        adapter.save(tmp_path / "artifact", metadata)


def test_missing_artifact_is_reported_not_fabricated(tmp_path):
    loaded = load_risk_model(tmp_path / "absent")
    assert loaded.model is None
    assert loaded.available is False
    assert loaded.availability.reason is RiskUnavailableReason.ARTIFACT_MISSING


def test_tampered_artifact_is_rejected(tmp_path):
    trained(tmp_path)
    pipeline_path = tmp_path / "artifact-logistic" / ARTIFACT_PIPELINE_FILENAME
    pipeline_path.write_bytes(pipeline_path.read_bytes() + b"tampered")
    loaded = load_risk_model(tmp_path / "artifact-logistic")
    assert loaded.model is None
    assert loaded.availability.reason is RiskUnavailableReason.ARTIFACT_INVALID


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"features": {"x": 0.1}}, RiskUnavailableReason.FEATURE_MISSING),
        (
            {"features": {"x": 0.1, "z": 0.2, "extra": 1.0}},
            RiskUnavailableReason.FEATURE_SET_MISMATCH,
        ),
        ({"features": {"x": "high", "z": 0.2}}, RiskUnavailableReason.FEATURE_NOT_NUMERIC),
        ({"features": {"x": float("inf"), "z": 0.2}}, RiskUnavailableReason.FEATURE_NOT_NUMERIC),
        ({"features": {"x": True, "z": 0.2}}, RiskUnavailableReason.FEATURE_NOT_NUMERIC),
        ({"feature_pipeline_version": "other"}, RiskUnavailableReason.FEATURE_VERSION_MISMATCH),
        ({"population": "some-other-population"}, RiskUnavailableReason.POPULATION_NOT_APPLICABLE),
    ],
)
def test_unavailable_inputs_return_status_without_probability(tmp_path, payload, reason):
    model = trained(tmp_path)
    assessment = model.assess(request(**payload))
    assert assessment.status is RiskAssessmentStatus.UNAVAILABLE
    assert assessment.reason is reason
    assert assessment.prediction is None
    assert assessment.model_version == "fixture-risk-v1"
    if "features" in payload:
        with pytest.raises(RiskModelUnavailableError) as error:
            model.predict("fixture-1", payload["features"])
        assert error.value.reason is reason


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_nan_and_none_are_missing_markers_for_imputing_fields(tmp_path, missing):
    model = trained(tmp_path)
    assessment = model.assess(request(features={"x": missing, "z": -0.4}))
    assert assessment.status is RiskAssessmentStatus.AVAILABLE
    assert 0.0 <= assessment.prediction.probability <= 1.0


def test_available_assessment_carries_versions_and_warnings(tmp_path):
    model = trained(tmp_path)
    assessment = model.assess(request())
    assert assessment.status is RiskAssessmentStatus.AVAILABLE
    assert 0.0 <= assessment.prediction.probability <= 1.0
    assert assessment.prediction.risk_model_version == "fixture-risk-v1"
    assert assessment.prediction.feature_pipeline_version == "fixture-features-v1"
    assert assessment.prediction.trace_id == "trace-1"
    assert RiskWarning.SYNTHETIC_ARTIFACT_ENGINEERING_ONLY in assessment.warnings
    payload = json.loads(assessment.model_dump_json())
    assert payload["status"] == "available"
    assert payload["prediction"]["risk_code"] == "fixture-outcome"


def test_blocked_review_blocks_training_and_inference(tmp_path):
    adapter = BaselineRiskAdapter(card(review_status="BLOCKED"))
    with pytest.raises(RiskModelUnavailableError) as error:
        adapter.train(dataset())
    assert error.value.reason is RiskUnavailableReason.REVIEW_NOT_FROZEN

    model = trained(tmp_path)
    model.card = model.card.model_copy(update={"review_status": "BLOCKED"})
    assessment = model.assess(request())
    assert assessment.reason is RiskUnavailableReason.REVIEW_NOT_FROZEN
    assert assessment.prediction is None


def test_model_not_loaded_reports_reason():
    assessment = BaselineRiskAdapter(card()).assess(request())
    assert assessment.status is RiskAssessmentStatus.UNAVAILABLE
    assert assessment.reason is RiskUnavailableReason.MODEL_NOT_LOADED


@pytest.mark.parametrize(
    "problem", ["unknown_label", "extra_feature", "missing_feature", "single_class", "not_numeric"]
)
def test_training_rejects_unusable_datasets(problem):
    size = 200
    rng = np.random.default_rng(3)
    records = [{"x": float(rng.normal()), "z": float(rng.normal())} for _ in range(size)]
    labels = [index % 2 for index in range(size)]
    if problem == "unknown_label":
        labels[0] = -1
    elif problem == "extra_feature":
        records[0] = {**records[0], "candx_days": 1.0}
    elif problem == "missing_feature":
        records[0] = {"x": 0.1}
    elif problem == "single_class":
        labels = [1] * size
    else:
        records[0] = {"x": "unavailable", "z": 0.1}
    adapter = BaselineRiskAdapter(card())
    with pytest.raises(ValueError):
        adapter.train(
            TrainingDataset(
                records=tuple(records), labels=tuple(labels), dataset_version="fixture-v1"
            )
        )


def test_reject_missing_policy_refuses_blank_values(tmp_path):
    specs = (
        RiskFeatureSpec(
            name="x",
            source="fixture",
            unit="unitless",
            missing_policy="reject",
            review_status="reviewed",
        ),
        RiskFeatureSpec(name="z", source="fixture", unit="unitless", review_status="reviewed"),
    )
    adapter = BaselineRiskAdapter(card(required_features=specs))
    adapter.train(
        TrainingDataset(
            records=tuple(
                {"x": float(index), "z": float(index % 3)} for index in range(1, 201)
            ),
            labels=tuple(index % 2 for index in range(200)),
            dataset_version="fixture-v1",
        )
    )
    assert adapter.assess(request(features={"x": None, "z": 0.1})).reason is (
        RiskUnavailableReason.FEATURE_MISSING
    )
    assert adapter.assess(request(features={"x": 1.0, "z": None})).status is (
        RiskAssessmentStatus.AVAILABLE
    )


def test_evaluate_reports_engineering_metrics(tmp_path):
    model = trained(tmp_path)
    result = model.evaluate(dataset())
    assert result.model_version == "fixture-risk-v1"
    assert result.dataset_version == "fixture-v1"
    assert {"roc_auc", "brier", "confusion_tp", "sensitivity"} <= set(result.metrics)


def experiment(tmp_path: Path, status: str = "FROZEN"):
    """跑一次真实离线基线，并按需把报告状态改写成未冻结用于失败路径测试。"""
    folder = tmp_path / "experiment"
    spec = TaskSpec(
        task_id="synthetic-engineering-test",
        version="1",
        status="FROZEN",
        source_kind="synthetic",
        features=["x", "z"],
        forbidden_features=["candx_days"],
        outcome_definition="artificial binary fixture",
        negative_definition="artificial fixture label zero",
        availability_assumptions="no real clinical times",
        review_record="engineering fixture only; no clinical validity",
        data_manifest_sha256="0" * 64,
        dataset_sha256="0" * 64,
    )
    frame = pd.DataFrame(
        {
            "subject_id": [f"synthetic-{index}" for index in range(200)],
            "label": [index % 2 for index in range(200)],
            "x": np.linspace(-2, 2, 200),
            "z": np.cos(np.arange(200)),
        }
    )
    report = run(frame, spec, folder)
    if status != "FROZEN":
        report["task"]["status"] = status
        (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return folder, spec


def registration(**changes):
    payload = {
        "algorithm": "logistic",
        "risk_code": "fixture-outcome",
        "task_kind": RiskTaskKind.SAME_ROUND_FINDING,
        "feature_pipeline_version": "fixture-features-v1",
        "population_definition": "synthetic fixture only",
        "applicable_populations": ("fixture-population",),
        "limitations": ("engineering fixture; not a clinical model",),
        "required_features": feature_specs(),
    }
    payload.update(changes)
    return BaselineExperimentRegistration(**payload)


def test_registration_carries_the_frozen_offline_task(tmp_path):
    folder, _ = experiment(tmp_path)
    adapter, metadata = BaselineRiskAdapter.from_baseline_experiment(folder, registration())
    assert adapter.card.review_status == "FROZEN"
    assert adapter.card.task_id == "synthetic-engineering-test"
    assert adapter.card.outcome_definition == "artificial binary fixture"
    assert adapter.card.availability_assumptions == "no real clinical times"
    assert adapter.card.is_synthetic is True
    assert len(adapter.card.training_split_sha256) == 64
    assert adapter.card.data_manifest_sha256 == "0" * 64
    assert metadata.extra["task_id"] == "synthetic-engineering-test"

    target = tmp_path / "registered"
    adapter.save(target, metadata)
    loaded = require_risk_model(target)
    assert loaded.card == adapter.card
    assert loaded.assess(request()).status is RiskAssessmentStatus.AVAILABLE


def test_registration_refuses_unreviewed_or_mismatched_experiments(tmp_path):
    folder, _ = experiment(tmp_path / "blocked", status="BLOCKED")
    with pytest.raises(RiskModelUnavailableError) as error:
        BaselineRiskAdapter.from_baseline_experiment(folder, registration())
    assert error.value.reason is RiskUnavailableReason.REVIEW_NOT_FROZEN

    folder, _ = experiment(tmp_path / "mismatch")
    wrong = feature_specs(name="scr_days1")
    with pytest.raises(RiskModelUnavailableError) as error:
        BaselineRiskAdapter.from_baseline_experiment(folder, registration(required_features=wrong))
    assert error.value.reason is RiskUnavailableReason.FEATURE_SET_MISMATCH

    with pytest.raises(RiskModelUnavailableError) as error:
        BaselineRiskAdapter.from_baseline_experiment(tmp_path / "absent", registration())
    assert error.value.reason is RiskUnavailableReason.ARTIFACT_MISSING
