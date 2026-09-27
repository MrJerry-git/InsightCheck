"""模型任务注册表与适配器槽位。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.ml.risk.contracts import RiskUnavailableReason

REGISTRY_VERSION = "model-task-registry-v1"


class TaskKind(StrEnum):
    RISK_MODEL = "risk_model"
    RANKING_MODEL = "ranking_model"


class TaskStatus(StrEnum):
    AWAITING_DATA = "awaiting_data"
    IN_DEVELOPMENT = "in_development"
    INTEGRATED = "integrated"
    RETIRED = "retired"


class TaskAdapter(Protocol):
    """可替换适配器接口：风险模型/排序模型各一个槽位。"""

    adapter_name: str

    def is_ready(self) -> bool: ...


class UnavailableTaskAdapter:
    """缺省适配器：显式不可用，不返回任何分数。"""

    adapter_name = "none"

    def is_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class ModelTaskRegistration:
    """一次模型任务登记：目标/人群/输入/时间窗/输出/来源/版本/状态。"""

    task_id: str
    task_kind: TaskKind
    disease_goal: str
    population: str
    input_features: tuple[str, ...]
    time_horizon: str
    output_spec: str
    data_source: str  # synthetic / public_observational / partner_observational
    source_version: str
    status: TaskStatus
    unavailable_reason: RiskUnavailableReason | None = None
    source_doc: str | None = None

    def __post_init__(self) -> None:
        if self.status == TaskStatus.INTEGRATED and self.unavailable_reason is not None:
            raise ValueError(
                f"任务 {self.task_id} 已接入（integrated）但保留了不可用原因，请清理状态"
            )
        if self.status == TaskStatus.AWAITING_DATA and self.unavailable_reason is None:
            raise ValueError(f"任务 {self.task_id} 处于 awaiting_data 必须登记不可用原因")
        if self.status == TaskStatus.RETIRED and self.unavailable_reason is None:
            raise ValueError(f"任务 {self.task_id} 已退役必须登记不可用原因")

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_kind": self.task_kind.value,
            "disease_goal": self.disease_goal,
            "population": self.population,
            "input_features": list(self.input_features),
            "time_horizon": self.time_horizon,
            "output_spec": self.output_spec,
            "data_source": self.data_source,
            "source_version": self.source_version,
            "status": self.status.value,
            "unavailable_reason": (
                self.unavailable_reason.value if self.unavailable_reason else None
            ),
            "source_doc": self.source_doc,
        }


@dataclass(frozen=True)
class TaskAvailability:
    """任务可用性：available=False 时给出明确原因（供 C07 展示）。"""

    task_id: str
    available: bool
    status: TaskStatus
    reason: str | None
    adapter_name: str

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "available": self.available,
            "status": self.status.value,
            "reason": self.reason,
            "adapter_name": self.adapter_name,
        }


class ModelTaskRegistry:
    """模型任务注册表：登记、适配器槽位与可用性查询。"""

    VERSION = REGISTRY_VERSION

    def __init__(self) -> None:
        self._tasks: dict[str, ModelTaskRegistration] = {}
        self._adapters: dict[str, TaskAdapter] = {}

    def register(self, task: ModelTaskRegistration, adapter: TaskAdapter | None = None) -> None:
        if task.task_id in self._tasks:
            raise ValueError(f"任务重复登记：{task.task_id}")
        self._tasks[task.task_id] = task
        self._adapters[task.task_id] = adapter or UnavailableTaskAdapter()

    def replace_adapter(self, task_id: str, adapter: TaskAdapter) -> None:
        if task_id not in self._tasks:
            raise ValueError(f"未知任务：{task_id}")
        self._adapters[task_id] = adapter

    def get(self, task_id: str) -> ModelTaskRegistration | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[ModelTaskRegistration]:
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]

    def availability(self, task_id: str) -> TaskAvailability:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"未知任务：{task_id}")
        adapter = self._adapters[task_id]
        if task.status != TaskStatus.INTEGRATED:
            reason = task.unavailable_reason.value if task.unavailable_reason else task.status.value
            return TaskAvailability(
                task_id=task.task_id,
                available=False,
                status=task.status,
                reason=reason,
                adapter_name=adapter.adapter_name,
            )
        if not adapter.is_ready():
            return TaskAvailability(
                task_id=task.task_id,
                available=False,
                status=task.status,
                reason=RiskUnavailableReason.MODEL_NOT_LOADED.value,
                adapter_name=adapter.adapter_name,
            )
        return TaskAvailability(
            task_id=task.task_id,
            available=True,
            status=task.status,
            reason=None,
            adapter_name=adapter.adapter_name,
        )

    def as_dicts(self) -> list[dict]:
        return [task.as_dict() for task in self.list_tasks()]


def load_builtin_registry() -> ModelTaskRegistry:
    """内置首批任务：NLST 风险（待数据）、DeepFM 排序（开发中）、合作方队列（待数据）。"""
    from app.ml.tasks.builtin import BUILTIN_TASK_REGISTRATIONS  # 延迟导入避免循环

    registry = ModelTaskRegistry()
    for task in BUILTIN_TASK_REGISTRATIONS:
        registry.register(task)
    return registry
