from __future__ import annotations

from datetime import date
from enum import Enum as PythonEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin
from app.models.enums import (
    AIReportType,
    CostLevel,
    ExamResultStatus,
    Gender,
    MatchStatus,
    MetricStatus,
    NormalizationStatus,
    PlanTier,
    RecommendationDecision,
    RecommendationStatus,
    RuleAction,
)


def enum_column(enum_class: type[PythonEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda enum_type: [item.value for item in enum_type],
    )


class Patient(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint("height IS NULL OR (height > 0 AND height <= 300)", name="height_range"),
    )

    anonymous_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    gender: Mapped[Gender] = mapped_column(enum_column(Gender, "gender"), default=Gender.UNKNOWN)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)

    health_checks: Mapped[list[HealthCheck]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
    lesion_tracks: Mapped[list[LesionTrack]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
    risk_predictions: Mapped[list[RiskPrediction]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
    ai_reports: Mapped[list[AIReport]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )


class HealthCheck(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "health_checks"
    __table_args__ = (Index("ix_health_checks_patient_date", "patient_id", "check_date"),)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    check_date: Mapped[date] = mapped_column(Date, index=True)
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)

    patient: Mapped[Patient] = relationship(back_populates="health_checks")
    lab_metrics: Mapped[list[LabMetric]] = relationship(
        back_populates="health_check", cascade="all, delete-orphan", passive_deletes=True
    )
    imaging_exams: Mapped[list[ImagingExam]] = relationship(
        back_populates="health_check", cascade="all, delete-orphan", passive_deletes=True
    )
    exam_histories: Mapped[list[ExamHistory]] = relationship(
        back_populates="health_check", cascade="all, delete-orphan", passive_deletes=True
    )


class MetricDictionary(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "metric_dictionaries"
    __table_args__ = (
        CheckConstraint(
            "valid_min IS NULL OR valid_max IS NULL OR valid_min <= valid_max",
            name="valid_range_order",
        ),
    )

    metric_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    standard_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    unit_conversions: Mapped[dict[str, dict[str, float]]] = mapped_column(JSON, default=dict)
    valid_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(64))


class LabMetric(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "lab_metrics"
    __table_args__ = (
        CheckConstraint(
            "reference_min IS NULL OR reference_max IS NULL OR reference_min <= reference_max",
            name="reference_range_order",
        ),
        Index("ix_lab_metrics_check_code", "health_check_id", "metric_code"),
    )

    health_check_id: Mapped[str] = mapped_column(
        ForeignKey("health_checks.id", ondelete="CASCADE"), index=True
    )
    metric_code: Mapped[str] = mapped_column(
        ForeignKey("metric_dictionaries.metric_code", ondelete="RESTRICT"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(200))
    canonical_name: Mapped[str] = mapped_column(String(200))
    original_value: Mapped[str] = mapped_column(String(100))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    standard_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[MetricStatus] = mapped_column(
        enum_column(MetricStatus, "metric_status"), default=MetricStatus.UNKNOWN
    )
    normalization_status: Mapped[NormalizationStatus] = mapped_column(
        enum_column(NormalizationStatus, "normalization_status")
    )
    normalization_version: Mapped[str] = mapped_column(String(64))

    health_check: Mapped[HealthCheck] = relationship(back_populates="lab_metrics")


class ImagingExam(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "imaging_exams"
    __table_args__ = (Index("ix_imaging_exams_check_date", "health_check_id", "exam_date"),)

    health_check_id: Mapped[str] = mapped_column(
        ForeignKey("health_checks.id", ondelete="CASCADE"), index=True
    )
    exam_type: Mapped[str] = mapped_column(String(100), index=True)
    body_part: Mapped[str] = mapped_column(String(100), index=True)
    report_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_date: Mapped[date] = mapped_column(Date)

    health_check: Mapped[HealthCheck] = relationship(back_populates="imaging_exams")
    lesions: Mapped[list[Lesion]] = relationship(
        back_populates="imaging_exam", cascade="all, delete-orphan", passive_deletes=True
    )


class Lesion(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "lesions"
    __table_args__ = (CheckConstraint("size_mm IS NULL OR size_mm >= 0", name="size_nonnegative"),)

    imaging_exam_id: Mapped[str] = mapped_column(
        ForeignKey("imaging_exams.id", ondelete="CASCADE"), index=True
    )
    lesion_type: Mapped[str] = mapped_column(String(100), index=True)
    original_location: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(100), index=True)
    size_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    imaging_exam: Mapped[ImagingExam] = relationship(back_populates="lesions")
    observation: Mapped[LesionObservation | None] = relationship(
        back_populates="lesion", uselist=False, passive_deletes=True
    )


class LesionTrack(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "lesion_tracks"
    __table_args__ = (
        CheckConstraint("first_seen <= last_seen", name="date_order"),
        Index("ix_lesion_tracks_patient_type", "patient_id", "lesion_type"),
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    canonical_lesion_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    lesion_type: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(100), index=True)
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)

    patient: Mapped[Patient] = relationship(back_populates="lesion_tracks")
    observations: Mapped[list[LesionObservation]] = relationship(
        back_populates="lesion_track", cascade="all, delete-orphan", passive_deletes=True
    )


class LesionObservation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "lesion_observations"
    __table_args__ = (
        CheckConstraint("size_mm IS NULL OR size_mm >= 0", name="size_nonnegative"),
        CheckConstraint("match_confidence >= 0 AND match_confidence <= 1", name="confidence_range"),
        Index("ix_lesion_observations_track_date", "lesion_track_id", "exam_date"),
    )

    lesion_track_id: Mapped[str] = mapped_column(
        ForeignKey("lesion_tracks.id", ondelete="CASCADE"), index=True
    )
    lesion_id: Mapped[str] = mapped_column(
        ForeignKey("lesions.id", ondelete="CASCADE"), unique=True, index=True
    )
    exam_date: Mapped[date] = mapped_column(Date)
    size_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match_confidence: Mapped[float] = mapped_column(Float)
    match_status: Mapped[MatchStatus] = mapped_column(enum_column(MatchStatus, "match_status"))

    lesion_track: Mapped[LesionTrack] = relationship(back_populates="observations")
    lesion: Mapped[Lesion] = relationship(back_populates="observation")


class ExamItem(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "exam_items"
    __table_args__ = (
        CheckConstraint(
            "recommended_interval_months IS NULL OR recommended_interval_months > 0",
            name="interval_positive",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    radiation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    cost_level: Mapped[CostLevel] = mapped_column(enum_column(CostLevel, "cost_level"))
    recommended_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    exam_histories: Mapped[list[ExamHistory]] = relationship(back_populates="exam_item")
    medical_rules: Mapped[list[MedicalRule]] = relationship(back_populates="exam_item")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(
        back_populates="exam_item"
    )


class ExamHistory(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "exam_histories"
    __table_args__ = (
        UniqueConstraint("health_check_id", "exam_item_id", name="uq_exam_history_check_item"),
    )

    health_check_id: Mapped[str] = mapped_column(
        ForeignKey("health_checks.id", ondelete="CASCADE"), index=True
    )
    exam_item_id: Mapped[str] = mapped_column(
        ForeignKey("exam_items.id", ondelete="RESTRICT"), index=True
    )
    result_status: Mapped[ExamResultStatus] = mapped_column(
        enum_column(ExamResultStatus, "exam_result_status")
    )

    health_check: Mapped[HealthCheck] = relationship(back_populates="exam_histories")
    exam_item: Mapped[ExamItem] = relationship(back_populates="exam_histories")


class MedicalRule(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "medical_rules"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
        CheckConstraint("length(trim(source)) > 0", name="source_nonempty"),
        UniqueConstraint("rule_code", "version", name="uq_medical_rule_code_version"),
    )

    rule_code: Mapped[str] = mapped_column(String(100), index=True)
    rule_type: Mapped[str] = mapped_column(String(100), index=True)
    exam_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_items.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    action: Mapped[RuleAction] = mapped_column(enum_column(RuleAction, "rule_action"))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(300))
    version: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)

    exam_item: Mapped[ExamItem | None] = relationship(back_populates="medical_rules")


class RiskPrediction(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_predictions"
    __table_args__ = (
        CheckConstraint("probability >= 0 AND probability <= 1", name="probability_range"),
        Index("ix_risk_predictions_patient_code", "patient_id", "risk_code"),
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    as_of_health_check_id: Mapped[str | None] = mapped_column(
        ForeignKey("health_checks.id", ondelete="SET NULL"), nullable=True
    )
    risk_code: Mapped[str] = mapped_column(String(100), index=True)
    probability: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    feature_pipeline_version: Mapped[str] = mapped_column(String(64))
    risk_model_version: Mapped[str] = mapped_column(String(64))
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trace_id: Mapped[str] = mapped_column(String(100), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    patient: Mapped[Patient] = relationship(back_populates="risk_predictions")


class Recommendation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "recommendations"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    as_of_health_check_id: Mapped[str | None] = mapped_column(
        ForeignKey("health_checks.id", ondelete="SET NULL"), nullable=True
    )
    plan_tier: Mapped[PlanTier] = mapped_column(enum_column(PlanTier, "plan_tier"))
    status: Mapped[RecommendationStatus] = mapped_column(
        enum_column(RecommendationStatus, "recommendation_status"),
        default=RecommendationStatus.DRAFT,
    )
    feature_pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommendation_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(100), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    patient: Mapped[Patient] = relationship(back_populates="recommendations")
    items: Mapped[list[RecommendationItem]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan", passive_deletes=True
    )
    ai_reports: Mapped[list[AIReport]] = relationship(back_populates="recommendation")


class RecommendationItem(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "recommendation_items"
    __table_args__ = (
        CheckConstraint(
            "model_score IS NULL OR (model_score >= 0 AND model_score <= 1)",
            name="model_score_range",
        ),
        CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 1)",
            name="final_score_range",
        ),
        CheckConstraint("rank IS NULL OR rank > 0", name="rank_positive"),
        UniqueConstraint(
            "recommendation_id", "exam_item_id", name="uq_recommendation_item_exam_item"
        ),
    )

    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), index=True
    )
    exam_item_id: Mapped[str] = mapped_column(
        ForeignKey("exam_items.id", ondelete="RESTRICT"), index=True
    )
    model_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[RecommendationDecision] = mapped_column(
        enum_column(RecommendationDecision, "recommendation_decision")
    )
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    applied_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    recommendation: Mapped[Recommendation] = relationship(back_populates="items")
    exam_item: Mapped[ExamItem] = relationship(back_populates="recommendation_items")


class AIReport(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_reports"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    recommendation_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_type: Mapped[AIReportType] = mapped_column(enum_column(AIReportType, "ai_report_type"))
    content: Mapped[str] = mapped_column(Text)
    llm_model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(64))
    source_trace_id: Mapped[str] = mapped_column(String(100), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    patient: Mapped[Patient] = relationship(back_populates="ai_reports")
    recommendation: Mapped[Recommendation | None] = relationship(back_populates="ai_reports")
