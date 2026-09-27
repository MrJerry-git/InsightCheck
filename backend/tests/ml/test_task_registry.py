"""H09 模型任务注册与可替换适配器。"""

import pytest

from app.ml.risk.artifact import BaselineRiskAdapter
from app.ml.risk.contracts import RiskUnavailableReason
from app.ml.tasks import (
    ModelTaskRegistration,
    ModelTaskRegistry,
    TaskKind,
    TaskStatus,
    UnavailableTaskAdapter,
    load_builtin_registry,
)


class ReadyAdapter:
    adapter_name = "ready-fake"

    def is_ready(self) -> bool:
        return True


def make_task(
    task_id: str = "t1", status: TaskStatus = TaskStatus.AWAITING_DATA
) -> ModelTaskRegistration:
    return ModelTaskRegistration(
        task_id=task_id,
        task_kind=TaskKind.RISK_MODEL,
        disease_goal="测试疾病",
        population="测试人群",
        input_features=("feature_a", "feature_b"),
        time_horizon="5-year",
        output_spec="疾病风险概率（0-1）",
        data_source="synthetic",
        source_version="1.0",
        status=status,
        unavailable_reason=(
            RiskUnavailableReason.REVIEW_NOT_FROZEN if status == TaskStatus.AWAITING_DATA else None
        ),
    )


def test_builtin_registry_lists_three_tasks_sorted() -> None:
    registry = load_builtin_registry()
    ids = [t.task_id for t in registry.list_tasks()]
    assert ids == sorted(ids)
    assert "lung-cancer-future-event-nlst" in ids
    assert "exam-item-matching-deepfm" in ids
    assert "partner-cohort-risk-models" in ids


def test_builtin_tasks_are_all_explicitly_unavailable() -> None:
    registry = load_builtin_registry()
    for task in registry.list_tasks():
        availability = registry.availability(task.task_id)
        assert availability.available is False
        assert availability.reason, task.task_id
        assert availability.adapter_name == "none"


def test_registration_validation_rules() -> None:
    with pytest.raises(ValueError):
        ModelTaskRegistration(
            task_id="bad",
            task_kind=TaskKind.RISK_MODEL,
            disease_goal="d",
            population="p",
            input_features=("f",),
            time_horizon="1y",
            output_spec="o",
            data_source="synthetic",
            source_version="1.0",
            status=TaskStatus.AWAITING_DATA,
            unavailable_reason=None,
        )
    with pytest.raises(ValueError):
        ModelTaskRegistration(
            task_id="bad2",
            task_kind=TaskKind.RISK_MODEL,
            disease_goal="d",
            population="p",
            input_features=("f",),
            time_horizon="1y",
            output_spec="o",
            data_source="synthetic",
            source_version="1.0",
            status=TaskStatus.INTEGRATED,
            unavailable_reason=RiskUnavailableReason.ARTIFACT_MISSING,
        )


def test_duplicate_registration_rejected() -> None:
    registry = ModelTaskRegistry()
    registry.register(make_task("dup"))
    with pytest.raises(ValueError) as excinfo:
        registry.register(make_task("dup"))
    assert "重复" in str(excinfo.value)


def test_availability_reflects_adapter_state() -> None:
    registry = ModelTaskRegistry()
    registry.register(make_task("live", TaskStatus.INTEGRATED))
    assert registry.availability("live").available is False
    assert registry.availability("live").reason == RiskUnavailableReason.MODEL_NOT_LOADED.value
    registry.replace_adapter("live", ReadyAdapter())
    availability = registry.availability("live")
    assert availability.available is True
    assert availability.reason is None
    assert availability.adapter_name == "ready-fake"


def test_adapter_can_be_swapped_and_default_is_unavailable() -> None:
    registry = ModelTaskRegistry()
    registry.register(make_task("swap"), adapter=ReadyAdapter())
    assert registry.availability("swap").adapter_name == "ready-fake"
    registry.replace_adapter("swap", UnavailableTaskAdapter())
    assert registry.availability("swap").adapter_name == "none"
    assert registry.availability("swap").available is False


def test_wrapped_baseline_risk_adapter_satisfies_protocol() -> None:
    class BaselineArtifactAdapter:
        adapter_name = "baseline-risk-artifact"

        def __init__(self) -> None:
            self._baseline = BaselineRiskAdapter()

        def is_ready(self) -> bool:
            return bool(self._baseline.is_ready)

    registry = ModelTaskRegistry()
    registry.register(make_task("risk", TaskStatus.INTEGRATED), BaselineArtifactAdapter())
    # 无制品目录时不可用，且原因为 model_not_loaded（LightGBM 接入路径保留）
    availability = registry.availability("risk")
    assert availability.available is False
    assert availability.adapter_name == "baseline-risk-artifact"


def test_unknown_task_raises() -> None:
    registry = ModelTaskRegistry()
    with pytest.raises(ValueError):
        registry.availability("ghost")


def test_as_dict_shape_for_t08() -> None:
    registry = load_builtin_registry()
    payload = registry.as_dicts()
    first = payload[0]
    for key in (
        "task_id",
        "task_kind",
        "disease_goal",
        "population",
        "input_features",
        "time_horizon",
        "output_spec",
        "data_source",
        "source_version",
        "status",
        "unavailable_reason",
        "source_doc",
    ):
        assert key in first
    nlst = next(t for t in payload if t["task_id"] == "lung-cancer-future-event-nlst")
    assert nlst["status"] == "awaiting_data"
    assert nlst["unavailable_reason"] == "review_not_frozen"
    assert nlst["source_doc"] == "docs/RISK_TASK_NLST.md"
