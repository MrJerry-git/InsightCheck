from enum import StrEnum


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNKNOWN = "unknown"


class MetricStatus(StrEnum):
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    UNKNOWN = "unknown"


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
