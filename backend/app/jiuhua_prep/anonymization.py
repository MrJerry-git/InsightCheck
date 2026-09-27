"""匿名标识与批次溯源字段（H11）。

沿用 ImportService 的 uuid5 确定性 ID 模式：同一盐值下同一来源标识
映射到同一匿名码；盐值由项目保管，不进入数据文件与 Git。
"""

from __future__ import annotations

import uuid

ANONYMIZATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "insightcheck/jiuhua-anonymization")

SOURCE_DATASET = "jiuhua"
SOURCE_KIND = "partner_observational"
ADAPTER_VERSION = "jiuhua-prep-v0（数据未到达，模板阶段）"


def anonymize_identifier(source_id: str, salt: str) -> str:
    """确定性匿名码：uuid5(namespace, salt + source_id)。

    同一 (salt, source_id) 恒定映射；盐值缺失或为空直接拒绝，
    不允许无盐生成可回溯的匿名码。
    """
    if not salt.strip():
        raise ValueError("必须提供项目盐值；无盐匿名码禁止生成")
    if not source_id.strip():
        raise ValueError("来源标识不能为空")
    return str(uuid.uuid5(ANONYMIZATION_NAMESPACE, f"{salt.strip()}:{source_id.strip()}"))


def batch_provenance(batch_note: str | None = None) -> dict[str, str]:
    """批次溯源字段：对齐 ImportBatch.source_dataset/source_kind 约定。"""
    provenance = {
        "source_dataset": SOURCE_DATASET,
        "source_kind": SOURCE_KIND,
        "adapter_version": ADAPTER_VERSION,
    }
    if batch_note:
        provenance["batch_note"] = batch_note
    return provenance
