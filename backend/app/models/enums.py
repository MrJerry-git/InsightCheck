from enum import StrEnum


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNKNOWN = "unknown"


class AccountRole(StrEnum):
    """登录账号角色。只读角色不能修改业务数据，管理员另有管理接口权限。"""

    ADMIN = "admin"
    DOCTOR = "doctor"
    VIEWER = "viewer"

    @property
    def can_write(self) -> bool:
        return self is not AccountRole.VIEWER

    @property
    def can_manage(self) -> bool:
        return self is AccountRole.ADMIN


class MetricStatus(StrEnum):
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    UNKNOWN = "unknown"


class ValueType(StrEnum):
    """指标值类型：数值走趋势图，定性与文字只做状态/原文对照。"""

    NUMERIC = "numeric"
    QUALITATIVE = "qualitative"
    TEXT = "text"


class NormalizationStatus(StrEnum):
    NORMALIZED = "normalized"
    UNMAPPED_METRIC = "unmapped_metric"
    INVALID_VALUE = "invalid_value"
    UNSUPPORTED_UNIT = "unsupported_unit"
    IMPLAUSIBLE_VALUE = "implausible_value"
    INVALID_REFERENCE = "invalid_reference"


class CostLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExamResultStatus(StrEnum):
    COMPLETED = "completed"
    NORMAL = "normal"
    ABNORMAL = "abnormal"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    CANDIDATE = "candidate"
    MANUAL_CONFIRMED = "manual_confirmed"
    REJECTED = "rejected"
    UNMATCHED = "unmatched"


class RuleAction(StrEnum):
    ALLOW = "ALLOW"
    BOOST = "BOOST"
    REDUCE = "REDUCE"
    DEFER = "DEFER"
    BLOCK = "BLOCK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PlanTier(StrEnum):
    SIMPLIFIED = "simplified"
    STANDARD = "standard"
    DEEP = "deep"


class RecommendationStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    CONFIRMED = "confirmed"


class RecommendationDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REQUIRE_REVIEW = "require_review"


class AIReportType(StrEnum):
    HEALTH_SUMMARY = "health_summary"
    RECOMMENDATION_EXPLANATION = "recommendation_explanation"
    CHAT_SUMMARY = "chat_summary"


class ImportTaskStatus(StrEnum):
    """导入任务状态：上传 → 解析 → 待校对 → 已入库，失败与取消可追踪。"""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PREVIEW_READY = "preview_ready"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class PlanStatus(StrEnum):
    """方案状态：草稿 → 待审核 → 已确认；编辑后回到草稿并生成新修订。"""

    DRAFT = "draft"
    REVIEW = "review"
    CONFIRMED = "confirmed"


class AnalysisStatus(StrEnum):
    """分析运行状态。模型未接入不阻断规则路径，只在结果里标记未评估。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
