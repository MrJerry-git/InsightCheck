"""九华数据接入准备（H11）。

模板与契约三件套：字段映射模板、质量摘要工具、匿名标识与批次溯源。
本模块**不处理任何真实数据**：全部映射条目 verification_status=unverified，
标签与随访字段是否存在一律标 to_be_verified。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第十一节与 docs/JIUHUA_DATA_PREP.md。
"""

from app.jiuhua_prep.anonymization import anonymize_identifier, batch_provenance
from app.jiuhua_prep.mapping import (
    FieldMappingRegistry,
    MappingValidationError,
    load_mapping_template,
)
from app.jiuhua_prep.quality import QualitySummary, summarize_quality

__all__ = [
    "FieldMappingRegistry",
    "MappingValidationError",
    "QualitySummary",
    "anonymize_identifier",
    "batch_provenance",
    "load_mapping_template",
    "summarize_quality",
]
