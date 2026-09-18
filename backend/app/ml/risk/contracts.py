"""在线风险制品契约：模型卡、推理请求与显式不可用状态。

正常请求只加载已审核制品并推理，拟合留在离线程序（`app.research.risk_baseline`）。
制品缺失、特征不符、版本不符或人群不适用时必须返回明确不可用状态，不得回退为虚构概率。
完整说明见 `docs/RISK_MODEL_ARTIFACT.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.contracts import FeatureRecord, RiskPrediction

ARTIFACT_CARD_FILENAME = "model_card.json"
ARTIFACT_METADATA_FILENAME = "metadata.json"
ARTIFACT_PIPELINE_FILENAME = "pipeline.joblib"
REPORT_FILENAME = "report.json"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
# 必须与 app.research.risk_baseline.estimators() 的键一致；由测试守护。
ALGORITHMS = ("logistic", "random_forest", "lightgbm")
RiskAlgorithm = Literal["logistic", "random_forest", "lightgbm"]


class RiskSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RiskTaskKind(StrEnum):
    """任务定义必须二选一并写清，不能把横断面分类包装成纵向预测。"""

    SAME_ROUND_FINDING = "same_round_finding_classification"
    FUTURE_EVENT = "future_event_prediction"


class RiskValidationKind(StrEnum):
    INTERNAL_RANDOM_SPLIT = "internal_random_split"
    TEMPORAL_HOLDOUT = "temporal_holdout"
    EXTERNAL_SITE = "external_site"


class RiskDataKind(StrEnum):
    SYNTHETIC = "synthetic"
    PUBLIC_OBSERVATIONAL = "public_observational"
    PARTNER_OBSERVATIONAL = "partner_observational"


class RiskAssessmentStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class RiskUnavailableReason(StrEnum):
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_UNREADABLE = "artifact_unreadable"
    ARTIFACT_INVALID = "artifact_invalid"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    MODEL_NOT_LOADED = "model_not_loaded"
    REVIEW_NOT_FROZEN = "review_not_frozen"
    FEATURE_MISSING = "feature_missing"
    FEATURE_NOT_NUMERIC = "feature_not_numeric"
    FEATURE_SET_MISMATCH = "feature_set_mismatch"
    FEATURE_VERSION_MISMATCH = "feature_version_mismatch"
    POPULATION_NOT_APPLICABLE = "population_not_applicable"


class RiskWarning(StrEnum):
    SYNTHETIC_ARTIFACT_ENGINEERING_ONLY = "synthetic_artifact_engineering_only"
    NO_CLINICAL_USE = "no_clinical_use"
    INTERNAL_SPLIT_NOT_EXTERNAL_VALIDATION = "internal_split_is_not_external_validation"
    UNCALIBRATED = "uncalibrated_probability"
    DIRTY_WORKING_TREE = "code_commit_was_not_clean"


class RiskModelUnavailableError(RuntimeError):
    """`RiskModel` 接口签名无法返回状态时使用；服务层应改用 `assess()`。"""

    def __init__(self, reason: RiskUnavailableReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


class RiskFeatureSpec(RiskSchema):
    """模型必需输入字段：来源、单位、缺失策略与人工核验状态。"""

    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=50)
    missing_policy: Literal["reject", "train_median_impute"] = "train_median_impute"
    review_status: Literal["reviewed", "structure_only", "not_reviewed"] = "not_reviewed"


class RiskModelCard(RiskSchema):
    """制品随附的模型定义：输入、输出、适用范围、版本与限制。"""

    model_version: str = Field(min_length=1, max_length=100)
    algorithm: RiskAlgorithm
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    risk_code: str = Field(min_length=1, max_length=64)
    task_kind: RiskTaskKind
    task_id: str = Field(min_length=1, max_length=100)
    task_version: str = Field(min_length=1, max_length=32)
    review_status: Literal["DRAFT", "BLOCKED", "FROZEN"]
    outcome_definition: str = Field(min_length=1)
    negative_definition: str = Field(min_length=1)
    availability_assumptions: str = Field(min_length=1)
    review_record: str = Field(min_length=1)
    data_source_kind: RiskDataKind
    is_synthetic: bool
    validation_kind: RiskValidationKind = RiskValidationKind.INTERNAL_RANDOM_SPLIT
    calibrated: bool = False
    clinical_use: Literal[False] = False
    forbidden_features: tuple[str, ...] = ()
    required_features: tuple[RiskFeatureSpec, ...] = Field(min_length=1)
    applicable_populations: tuple[str, ...] = Field(min_length=1)
    population_definition: str = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    training_dataset_version: str | None = None
    training_dataset_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    data_manifest_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    training_split_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    code_commit: str | None = Field(default=None, max_length=64)
    code_dirty: bool = False
    dependencies: dict[str, str] = Field(default_factory=dict)
    # 由 save() 写入，作为制品可追溯信息；加载时以 metadata.json 为准。
    trained_at_iso: str | None = None
    artifact_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def check_consistency(self) -> RiskModelCard:
        if self.is_synthetic != (self.data_source_kind is RiskDataKind.SYNTHETIC):
            raise ValueError("is_synthetic must match data_source_kind")
        names = [feature.name for feature in self.required_features]
        if len(set(names)) != len(names):
            raise ValueError("duplicate required feature")
        prohibited = set(self.forbidden_features) | {"subject_id", "label"}
        if prohibited.intersection(names):
            raise ValueError("forbidden feature requested")
        if self.validation_kind is RiskValidationKind.INTERNAL_RANDOM_SPLIT:
            if self.training_split_sha256 is None:
                raise ValueError("internal split requires the reviewed split manifest hash")
        elif self.training_split_sha256 is None:
            raise ValueError("validation requires the recorded partition hash")
        if not set(self.applicable_populations):
            raise ValueError("applicable populations must not be empty")
        return self

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(feature.name for feature in self.required_features)

    @property
    def is_frozen(self) -> bool:
        """只有 FROZEN 任务可以训练与推理；各处就绪判断统一引用这里。"""
        return self.review_status == "FROZEN"

    @property
    def warnings(self) -> tuple[RiskWarning, ...]:
        found = [RiskWarning.NO_CLINICAL_USE]
        if self.is_synthetic:
            found.append(RiskWarning.SYNTHETIC_ARTIFACT_ENGINEERING_ONLY)
        if self.validation_kind is RiskValidationKind.INTERNAL_RANDOM_SPLIT:
            found.append(RiskWarning.INTERNAL_SPLIT_NOT_EXTERNAL_VALIDATION)
        if not self.calibrated:
            found.append(RiskWarning.UNCALIBRATED)
        if self.code_dirty:
            found.append(RiskWarning.DIRTY_WORKING_TREE)
        return tuple(found)


class RiskPredictionRequest(RiskSchema):
    """服务层输入。population 必填：未声明人群不能视为适用。

    协议层不拒绝 `NaN`：它是与 `None` 等价的缺失标记，是否可缺失由各字段的
    `missing_policy` 决定，由适配器给出原因码，避免协议层静默接受或抛出与契约不符的错误。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=True)

    subject_id: str = Field(min_length=1, max_length=100)
    features: FeatureRecord
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    population: str = Field(min_length=1, max_length=100)
    trace_id: str = Field(min_length=1, max_length=100)
    evidence_refs: tuple[str, ...] = ()


class RiskAssessment(RiskSchema):
    """服务层输出：可用时带风险概率，不可用时带明确原因，绝不返回虚构概率。"""

    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, arbitrary_types_allowed=True
    )

    status: RiskAssessmentStatus
    subject_id: str
    trace_id: str
    model_version: str | None = None
    feature_pipeline_version: str | None = None
    risk_code: str | None = None
    population: str | None = None
    reason: RiskUnavailableReason | None = None
    detail: str = ""
    prediction: RiskPrediction | None = None
    warnings: tuple[RiskWarning, ...] = ()

    @model_validator(mode="after")
    def check_status(self) -> RiskAssessment:
        if self.status is RiskAssessmentStatus.AVAILABLE:
            if self.prediction is None:
                raise ValueError("available assessment requires a prediction")
            if self.reason is not None:
                raise ValueError("available assessment must not carry an unavailable reason")
        else:
            if self.prediction is not None:
                raise ValueError("unavailable assessment must not carry a probability")
            if self.reason is None:
                raise ValueError("unavailable assessment requires a reason")
        return self


class BaselineExperimentRegistration(RiskSchema):
    """把离线实验目录固化为在线制品时必须人工填写的字段。

    这些字段不能由程序从数据推断：任务类型、人群适用范围和字段来源都必须先经审核。
    """

    algorithm: RiskAlgorithm
    risk_code: str = Field(min_length=1, max_length=64)
    task_kind: RiskTaskKind
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    population_definition: str = Field(min_length=1)
    applicable_populations: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    required_features: tuple[RiskFeatureSpec, ...] = Field(min_length=1)
    model_version: str | None = Field(default=None, min_length=1, max_length=100)


@dataclass(frozen=True, slots=True)
class RiskModelAvailability:
    """加载结果摘要；不可用时给出原因，不抛出异常。"""

    status: RiskAssessmentStatus
    reason: RiskUnavailableReason | None
    detail: str
    model_version: str | None = None
    feature_pipeline_version: str | None = None

    @property
    def available(self) -> bool:
        return self.status is RiskAssessmentStatus.AVAILABLE
