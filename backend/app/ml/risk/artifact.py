"""风险制品加载与预测适配器（v1：Logistic、随机森林、LightGBM）。

边界：

- 拟合在离线程序 `app.research.risk_baseline` 完成；在线请求只 `load()` 可信制品并推理。
- 适配器不重新划分受检者、不生成标签、不编造随访，也不输出临床阈值或诊断结论。
- 任务未冻结、制品缺失、特征不符/版本不符、人群不适用时返回明确不可用状态。
- `joblib` 制品只用于本机可信来源；不加载来历不明的模型文件。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

from pydantic import ValidationError

from app.ml.contracts import (
    EvaluationResult,
    FeatureRecord,
    FeatureValue,
    ModelArtifactMetadata,
    RiskPrediction,
    TrainingDataset,
)
from app.ml.interfaces import RiskModel
from app.ml.risk.contracts import (
    ARTIFACT_CARD_FILENAME,
    ARTIFACT_METADATA_FILENAME,
    ARTIFACT_PIPELINE_FILENAME,
    BaselineExperimentRegistration,
    RiskAssessment,
    RiskAssessmentStatus,
    RiskDataKind,
    RiskFeatureSpec,
    RiskModelAvailability,
    RiskModelCard,
    RiskModelUnavailableError,
    RiskPredictionRequest,
    RiskUnavailableReason,
    RiskValidationKind,
    RiskWarning,
)

DEFAULT_SEED = 20260916  # 与 app.research.risk_baseline.run 的默认种子一致。


@dataclass(frozen=True, slots=True)
class LoadedRiskModel:
    """加载结果；不可用时给出原因而不是抛异常。"""

    availability: RiskModelAvailability
    model: BaselineRiskAdapter | None

    @property
    def available(self) -> bool:
        return self.model is not None


class _FeatureProblem(Exception):
    """内部信号：映射为服务层的不可用原因或被训练路径拒绝。"""

    def __init__(self, reason: RiskUnavailableReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _research() -> SimpleNamespace:
    """延迟导入研究依赖，使制品缺失时无需安装 research extra 也能返回明确状态。"""
    try:
        import joblib
        import numpy as np
        import pandas as pd

        from app.research import risk_baseline
    except ImportError as error:
        raise RiskModelUnavailableError(
            RiskUnavailableReason.DEPENDENCY_UNAVAILABLE,
            f"artifact IO and inference need the research extra: {error}",
        ) from error
    return SimpleNamespace(joblib=joblib, np=np, pd=pd, risk_baseline=risk_baseline)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _as_number(name: str, value: FeatureValue, policy: str) -> float | None:
    if value is None:
        if policy == "reject":
            raise _FeatureProblem(
                RiskUnavailableReason.FEATURE_MISSING,
                f"{name} declares missing_policy=reject and has no value",
            )
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _FeatureProblem(RiskUnavailableReason.FEATURE_NOT_NUMERIC, f"{name} must be numeric")
    try:
        number = float(value)
    except ValueError as error:
        raise _FeatureProblem(
            RiskUnavailableReason.FEATURE_NOT_NUMERIC, f"{name} must be numeric"
        ) from error
    if math.isnan(number):
        # NaN 与 None 同为缺失标记，仍按该字段的缺失策略处理。
        return _as_number(name, None, policy)
    if not math.isfinite(number):
        raise _FeatureProblem(RiskUnavailableReason.FEATURE_NOT_NUMERIC, f"{name} must be finite")
    return number


def feature_vector(card: RiskModelCard, features: FeatureRecord) -> dict[str, float | None]:
    """按模型卡校验输入；不补齐、不猜测、不接受未声明字段。"""
    names = card.feature_names
    declared, provided = set(names), set(features)
    missing = sorted(declared - provided)
    if missing:
        raise _FeatureProblem(
            RiskUnavailableReason.FEATURE_MISSING, f"missing required features: {missing}"
        )
    unexpected = sorted(provided - declared)
    if unexpected:
        raise _FeatureProblem(
            RiskUnavailableReason.FEATURE_SET_MISMATCH,
            f"undeclared features are not accepted: {unexpected}",
        )
    policies = {spec.name: spec.missing_policy for spec in card.required_features}
    return {name: _as_number(name, features[name], policies[name]) for name in names}


def _assert_pipeline_contract(card: RiskModelCard, pipeline: Any) -> None:
    if not hasattr(pipeline, "predict_proba"):
        raise RiskModelUnavailableError(
            RiskUnavailableReason.ARTIFACT_INVALID, "artifact does not expose predict_proba"
        )
    fitted = getattr(pipeline, "feature_names_in_", None)
    if fitted is not None and list(fitted) != list(card.feature_names):
        raise RiskModelUnavailableError(
            RiskUnavailableReason.ARTIFACT_INVALID,
            "artifact was fitted on different features than the model card declares",
        )


class BaselineRiskAdapter(RiskModel):
    """离线基线制品的加载与预测适配器。"""

    def __init__(self, card: RiskModelCard | None = None, seed: int = DEFAULT_SEED) -> None:
        self.card = card
        self.seed = seed
        self._pipeline: Any = None
        self._metadata: ModelArtifactMetadata | None = None

    @property
    def is_ready(self) -> bool:
        return self.card is not None and self._pipeline is not None

    @property
    def model_version(self) -> str | None:
        return self.card.model_version if self.card else None

    @property
    def feature_pipeline_version(self) -> str | None:
        return self.card.feature_pipeline_version if self.card else None

    def train(self, dataset: TrainingDataset) -> ModelArtifactMetadata:
        """离线拟合；调用方必须已经保留已审核的受检者级划分。"""
        modules = _research()
        card = self._require_ready_card()
        frame, labels = self._dataset_frame(dataset, modules.pd)
        pipeline = modules.risk_baseline.estimators(self.seed)[card.algorithm]
        pipeline.fit(frame[list(card.feature_names)], labels)
        _assert_pipeline_contract(card, pipeline)
        self._pipeline = pipeline
        self._metadata = ModelArtifactMetadata(
            model_version=card.model_version,
            feature_pipeline_version=card.feature_pipeline_version,
            created_at_iso=datetime.now(UTC).isoformat(),
            extra={
                "algorithm": card.algorithm,
                "risk_code": card.risk_code,
                "task_id": card.task_id,
                "dataset_version": dataset.dataset_version,
                "is_synthetic": str(card.is_synthetic).lower(),
                "preprocessing": "app.research.risk_baseline median impute + standard scale",
                "split_policy": "reviewed subject-level split preserved; adapter never re-splits",
            },
        )
        return self._metadata

    def predict(self, subject_id: str, features: FeatureRecord) -> Sequence[RiskPrediction]:
        """接口约定的推理入口；不可用情况抛出携带原因码的异常。"""
        pipeline, card = self._ready_parts()
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("subject_id is required")
        try:
            values = feature_vector(card, features)
        except _FeatureProblem as problem:
            raise RiskModelUnavailableError(problem.reason, problem.detail) from problem
        probability = self._probability(pipeline, values)
        return (
            RiskPrediction(
                subject_id=subject_id,
                risk_code=card.risk_code,
                probability=probability,
                risk_model_version=card.model_version,
                feature_pipeline_version=card.feature_pipeline_version,
                trace_id=f"risk-{hashlib.sha256(subject_id.encode()).hexdigest()[:16]}",
                evidence_refs=(f"model_card:{card.model_version}",),
            ),
        )

    def evaluate(self, dataset: TrainingDataset) -> EvaluationResult:
        modules = _research()
        pipeline, card = self._ready_parts()
        frame, labels = self._dataset_frame(dataset, modules.pd)
        probabilities = pipeline.predict_proba(frame[list(card.feature_names)])[:, 1]
        raw = modules.risk_baseline.metrics(modules.np.asarray(labels), probabilities)
        metrics: dict[str, float] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                metrics.update({f"confusion_{name}": float(count) for name, count in value.items()})
            else:
                metrics[key] = float(value)
        return EvaluationResult(
            metrics=metrics,
            dataset_version=dataset.dataset_version,
            model_version=card.model_version,
        )

    def save(self, artifact_path: Path, metadata: ModelArtifactMetadata) -> None:
        modules = _research()
        pipeline, card = self._ready_parts()
        if self._metadata is None or metadata != self._metadata:
            raise ValueError("metadata does not match the trained model")
        target = Path(artifact_path)
        if (target / ARTIFACT_PIPELINE_FILENAME).exists():
            raise ValueError("artifact already exists; preserve it and write to a new path")
        target.mkdir(parents=True, exist_ok=True)
        pipeline_path = target / ARTIFACT_PIPELINE_FILENAME
        modules.joblib.dump(pipeline, pipeline_path)
        stored = card.model_copy(
            update={
                "artifact_sha256": _sha256(pipeline_path),
                "trained_at_iso": metadata.created_at_iso,
            }
        )
        (target / ARTIFACT_CARD_FILENAME).write_text(
            json.dumps(stored.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target / ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(asdict(metadata), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.card = stored

    @classmethod
    def load(cls, artifact_path: Path) -> Self:
        modules = _research()
        directory = Path(artifact_path)
        for filename in (
            ARTIFACT_CARD_FILENAME,
            ARTIFACT_METADATA_FILENAME,
            ARTIFACT_PIPELINE_FILENAME,
        ):
            if not (directory / filename).is_file():
                raise RiskModelUnavailableError(
                    RiskUnavailableReason.ARTIFACT_MISSING, f"artifact file is missing: {filename}"
                )
        try:
            card = RiskModelCard.model_validate_json(
                (directory / ARTIFACT_CARD_FILENAME).read_text(encoding="utf-8")
            )
        except (ValidationError, ValueError) as error:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID, f"model card is invalid: {error}"
            ) from error
        metadata = cls._read_metadata(directory / ARTIFACT_METADATA_FILENAME)
        if (
            metadata.model_version != card.model_version
            or metadata.feature_pipeline_version != card.feature_pipeline_version
        ):
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID,
                "model card and metadata record different versions",
            )
        pipeline_path = directory / ARTIFACT_PIPELINE_FILENAME
        if card.artifact_sha256 is None or _sha256(pipeline_path) != card.artifact_sha256:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID,
                "artifact hash differs from the model card; preserve and review before use",
            )
        try:
            pipeline = modules.joblib.load(pipeline_path)
        except Exception as error:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID, f"artifact cannot be deserialized: {error}"
            ) from error
        _assert_pipeline_contract(card, pipeline)
        model = cls(card)
        model._pipeline = pipeline
        model._metadata = metadata
        return model

    @classmethod
    def from_baseline_experiment(
        cls,
        experiment_dir: Path,
        registration: BaselineExperimentRegistration,
    ) -> tuple[Self, ModelArtifactMetadata]:
        """把已完成的 `app.research.risk_baseline.run` 目录固化为在线制品。"""
        modules = _research()
        directory = Path(experiment_dir)
        report_path = directory / "report.json"
        if not report_path.is_file():
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_MISSING, "offline experiment report.json is missing"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        task = report.get("task")
        if not isinstance(task, dict):
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID,
                "experiment report has no task specification",
            )
        if task.get("status") != "FROZEN":
            raise RiskModelUnavailableError(
                RiskUnavailableReason.REVIEW_NOT_FROZEN,
                "only a FROZEN offline task may be registered as an artifact",
            )
        pipeline_path = directory / f"{registration.algorithm}.joblib"
        if not pipeline_path.is_file():
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_MISSING, "the selected baseline file is missing"
            )
        payload = modules.joblib.load(pipeline_path)
        pipeline = payload["pipeline"] if isinstance(payload, dict) else payload
        names = [spec.name for spec in registration.required_features]
        if names != list(task.get("features", [])):
            raise RiskModelUnavailableError(
                RiskUnavailableReason.FEATURE_SET_MISMATCH,
                "declared features differ from the frozen task features",
            )
        dirty = bool(report.get("code_dirty"))
        limitations = list(registration.limitations)
        if dirty:
            limitations.append(
                "offline run recorded a dirty working tree; "
                "repeat it from a clean commit before use"
            )
        card = RiskModelCard(
            model_version=registration.model_version
            or f"{task['task_id']}-{registration.algorithm}-v{task['version']}",
            algorithm=registration.algorithm,
            feature_pipeline_version=registration.feature_pipeline_version,
            risk_code=registration.risk_code,
            task_kind=registration.task_kind,
            task_id=str(task["task_id"]),
            task_version=str(task["version"]),
            review_status="FROZEN",
            outcome_definition=str(task["outcome_definition"]),
            negative_definition=str(task["negative_definition"]),
            availability_assumptions=str(task["availability_assumptions"]),
            review_record=str(task["review_record"]),
            data_source_kind=str(task["source_kind"]),
            is_synthetic=str(task["source_kind"]) == RiskDataKind.SYNTHETIC.value,
            validation_kind=RiskValidationKind.INTERNAL_RANDOM_SPLIT,
            calibrated=False,
            forbidden_features=tuple(task.get("forbidden_features", [])),
            required_features=registration.required_features,
            applicable_populations=registration.applicable_populations,
            population_definition=registration.population_definition,
            limitations=tuple(limitations),
            training_dataset_version=str(task["version"]),
            training_dataset_sha256=report.get("normalized_dataset_sha256"),
            training_split_sha256=report.get("split_sha256"),
            data_manifest_sha256=str(task.get("data_manifest_sha256") or "") or None,
            code_commit=str(report.get("code_commit") or "") or None,
            code_dirty=dirty,
            dependencies={
                str(key): str(value) for key, value in (report.get("dependencies") or {}).items()
            },
        )
        _assert_pipeline_contract(card, pipeline)
        model = cls(card)
        model._pipeline = pipeline
        model._metadata = ModelArtifactMetadata(
            model_version=card.model_version,
            feature_pipeline_version=card.feature_pipeline_version,
            created_at_iso=datetime.now(UTC).isoformat(),
            extra={
                "algorithm": card.algorithm,
                "risk_code": card.risk_code,
                "task_id": card.task_id,
                "is_synthetic": str(card.is_synthetic).lower(),
                "registration": "app.ml.risk.from_baseline_experiment from a completed offline run",
                "split_policy": "reviewed subject-level split preserved; adapter never re-splits",
            },
        )
        return model, model._metadata

    def assess(self, request: RiskPredictionRequest) -> RiskAssessment:
        """服务层合规入口：任何不可用情况都返回状态与原因，不返回概率。"""
        card = self.card
        if card is None or self._pipeline is None:
            return self._unavailable(
                request,
                RiskUnavailableReason.MODEL_NOT_LOADED,
                "no risk artifact is loaded; load a reviewed artifact before serving",
            )
        if card.review_status != "FROZEN":
            return self._unavailable(
                request,
                RiskUnavailableReason.REVIEW_NOT_FROZEN,
                f"task review status is {card.review_status}; inference is blocked until FROZEN",
            )
        if request.feature_pipeline_version != card.feature_pipeline_version:
            return self._unavailable(
                request,
                RiskUnavailableReason.FEATURE_VERSION_MISMATCH,
                "request feature pipeline version differs from the artifact",
            )
        if request.population not in card.applicable_populations:
            return self._unavailable(
                request,
                RiskUnavailableReason.POPULATION_NOT_APPLICABLE,
                f"population is outside {list(card.applicable_populations)}; "
                "no applicability evidence exists for it",
            )
        try:
            values = feature_vector(card, request.features)
        except _FeatureProblem as problem:
            return self._unavailable(request, problem.reason, problem.detail)
        try:
            probability = self._probability(self._pipeline, values)
        except RiskModelUnavailableError as error:
            return self._unavailable(request, error.reason, error.detail)
        prediction = RiskPrediction(
            subject_id=request.subject_id,
            risk_code=card.risk_code,
            probability=probability,
            risk_model_version=card.model_version,
            feature_pipeline_version=card.feature_pipeline_version,
            trace_id=request.trace_id,
            evidence_refs=request.evidence_refs or (f"model_card:{card.model_version}",),
        )
        return RiskAssessment(
            status=RiskAssessmentStatus.AVAILABLE,
            subject_id=request.subject_id,
            trace_id=request.trace_id,
            model_version=card.model_version,
            feature_pipeline_version=card.feature_pipeline_version,
            risk_code=card.risk_code,
            population=request.population,
            prediction=prediction,
            warnings=card.warnings,
        )

    @property
    def warnings(self) -> tuple[RiskWarning, ...]:
        return self.card.warnings if self.card else ()

    def _probability(self, pipeline: Any, values: dict[str, float | None]) -> float:
        modules = _research()
        frame = modules.pd.DataFrame([values], columns=list(values))
        try:
            probability = float(pipeline.predict_proba(frame)[:, 1][0])
        except Exception as error:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID,
                f"artifact cannot score the declared features: {error}",
            ) from error
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID, "artifact returned a non-probability score"
            )
        return probability

    def _dataset_frame(self, dataset: TrainingDataset, pd: Any) -> tuple[Any, list[int]]:
        card = self._require_ready_card()
        if len(dataset.records) != len(dataset.labels):
            raise ValueError("records and labels must have the same length")
        if not dataset.records:
            raise ValueError("training dataset is empty")
        rows: list[dict[str, float | None]] = []
        labels: list[int] = []
        for index, (record, label) in enumerate(
            zip(dataset.records, dataset.labels, strict=True)
        ):
            if isinstance(label, bool) or label not in (0, 1):
                raise ValueError("labels must be known binary outcomes; unknown is not negative")
            try:
                rows.append(feature_vector(card, record))
            except _FeatureProblem as problem:
                raise ValueError(f"record {index}: {problem.detail}") from problem
            labels.append(int(label))
        if len(set(labels)) != 2:
            raise ValueError("both classes are required before fitting")
        frame = pd.DataFrame(rows, columns=list(card.feature_names)).astype("float64")
        if frame.isna().all().any():
            raise ValueError("a feature is entirely missing; revise the task before fitting")
        return frame, labels

    def _ready_parts(self) -> tuple[Any, RiskModelCard]:
        card = self._require_ready_card()
        if self._pipeline is None:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.MODEL_NOT_LOADED,
                "no risk artifact is loaded; train offline or load a reviewed artifact",
            )
        return self._pipeline, card

    def _require_ready_card(self) -> RiskModelCard:
        if self.card is None:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.MODEL_NOT_LOADED,
                "a model card is required before training or serving",
            )
        if self.card.review_status != "FROZEN":
            raise RiskModelUnavailableError(
                RiskUnavailableReason.REVIEW_NOT_FROZEN,
                "task must be FROZEN after data and outcome review; "
                "the adapter never fills review records",
            )
        return self.card

    def _unavailable(
        self, request: RiskPredictionRequest, reason: RiskUnavailableReason, detail: str
    ) -> RiskAssessment:
        card = self.card
        return RiskAssessment(
            status=RiskAssessmentStatus.UNAVAILABLE,
            subject_id=request.subject_id,
            trace_id=request.trace_id,
            model_version=card.model_version if card else None,
            feature_pipeline_version=card.feature_pipeline_version if card else None,
            risk_code=card.risk_code if card else None,
            population=request.population,
            reason=reason,
            detail=detail,
            warnings=card.warnings if card else (),
        )

    @staticmethod
    def _read_metadata(path: Path) -> ModelArtifactMetadata:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return ModelArtifactMetadata(**payload)
        except (TypeError, ValueError) as error:
            raise RiskModelUnavailableError(
                RiskUnavailableReason.ARTIFACT_INVALID, f"artifact metadata is invalid: {error}"
            ) from error


def load_risk_model(artifact_path: Path) -> LoadedRiskModel:
    """加载制品并返回可用性摘要；缺失或损坏时不抛异常。"""
    try:
        model = BaselineRiskAdapter.load(artifact_path)
    except RiskModelUnavailableError as error:
        return LoadedRiskModel(
            availability=RiskModelAvailability(
                status=RiskAssessmentStatus.UNAVAILABLE, reason=error.reason, detail=error.detail
            ),
            model=None,
        )
    assert model.card is not None  # load() always sets a validated card
    return LoadedRiskModel(
        availability=RiskModelAvailability(
            status=RiskAssessmentStatus.AVAILABLE,
            reason=None,
            detail="",
            model_version=model.card.model_version,
            feature_pipeline_version=model.card.feature_pipeline_version,
        ),
        model=model,
    )


def require_risk_model(artifact_path: Path) -> BaselineRiskAdapter:
    """加载制品；不可用时抛出 `RiskModelUnavailableError`。"""
    loaded = load_risk_model(artifact_path)
    if loaded.model is None:
        reason = loaded.availability.reason or RiskUnavailableReason.ARTIFACT_INVALID
        raise RiskModelUnavailableError(reason, loaded.availability.detail)
    return loaded.model


def describe_feature_specs(specs: Sequence[RiskFeatureSpec]) -> dict[str, dict[str, str]]:
    """导出字段契约，便于文档和审核对照。"""
    return {
        spec.name: {
            "source": spec.source,
            "unit": spec.unit,
            "missing_policy": spec.missing_policy,
            "review_status": spec.review_status,
        }
        for spec in specs
    }
