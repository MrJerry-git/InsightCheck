"""体检类别与指标字典（H01）及检查—发现—健康问题/疾病关联目录（H02）。

纯计算模块：不访问数据库。内容文件位于 data/，每条记录带来源与版本，
未经医学审核的条目 review_status 一律为 pending_review。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第二节、第三节。
"""

from app.exam_dictionary.catalog import (
    DictionaryValidationError,
    ExamDictionary,
    FindingCatalog,
    load_builtin_associations,
    load_builtin_catalog,
)
from app.exam_dictionary.schemas import (
    CatalogEntry,
    FindingAssociation,
    InstitutionPackage,
    ReferenceRange,
    UnitConversion,
    UnmappedMetric,
)

__all__ = [
    "CatalogEntry",
    "DictionaryValidationError",
    "ExamDictionary",
    "FindingAssociation",
    "FindingCatalog",
    "InstitutionPackage",
    "ReferenceRange",
    "UnmappedMetric",
    "UnitConversion",
    "load_builtin_associations",
    "load_builtin_catalog",
]
