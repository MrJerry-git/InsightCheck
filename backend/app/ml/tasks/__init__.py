"""模型任务注册与可替换适配器（H09）。

纯计算模块：登记疾病风险/排序模型任务的目标、人群、输入、时间窗、
输出、来源、版本与状态；适配器槽位可替换，保留 LightGBM（风险）与
DeepFM（排序）接入路径。未接入的任务返回显式不可用状态，
不产生虚构疾病概率。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第十节。
"""

from app.ml.tasks.builtin import BUILTIN_TASK_REGISTRATIONS
from app.ml.tasks.registry import (
    ModelTaskRegistration,
    ModelTaskRegistry,
    TaskAdapter,
    TaskAvailability,
    TaskKind,
    TaskStatus,
    UnavailableTaskAdapter,
    load_builtin_registry,
)

__all__ = [
    "BUILTIN_TASK_REGISTRATIONS",
    "ModelTaskRegistration",
    "ModelTaskRegistry",
    "TaskAdapter",
    "TaskAvailability",
    "TaskKind",
    "TaskStatus",
    "UnavailableTaskAdapter",
    "load_builtin_registry",
]
