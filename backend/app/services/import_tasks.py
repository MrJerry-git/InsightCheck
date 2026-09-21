"""T03：文件导入任务——上传、解析、逐字段校对与事务性入库。

设计约束（见 docs/TEAM_TASKS_V2.md T03）：

* 上传不等于入库：任务先进入待校对状态，只有显式确认才写入业务表。
* 逐字段错误、重复记录与原文位置都要能返回给前端，而不是只给一句“失败”。
* 未映射指标不丢弃：保留原始名称与数值，标记为待映射，不自动解释。
* 同一份文件重复上传要能被识别；同日同指标冲突不静默覆盖。
* 原始文件只在任务存续期间临时存放，确认、取消或失败后清理。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import HealthCheck, ImportTask, LabMetric, MetricDictionary, Patient
from app.models.enums import ImportTaskStatus, MetricStatus, NormalizationStatus, ValueType
from app.services.record_revisions import RecordRevisionService

MAX_BYTES = 8 * 1024 * 1024
TABULAR_SUFFIXES = frozenset({".csv", ".txt"})
MODEL_SUFFIXES = frozenset({".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"})
SUPPORTED_SUFFIXES = TABULAR_SUFFIXES | MODEL_SUFFIXES

TABULAR_COLUMNS = (
    "date",
    "metric_code",
    "original_name",
    "value",
    "unit",
    "reference_min",
    "reference_max",
)

# 模型提取字段到目录编码的固定映射；目录里没有的编码按未映射保留原文。
MODEL_FIELD_CODES: dict[str, tuple[str, str, str]] = {
    "sbp": ("SBP", "收缩压", "mmHg"),
    "total_c": ("TC", "总胆固醇", "mmol/L"),
    "hdl_c": ("HDL_C", "高密度脂蛋白胆固醇", "mmol/L"),
    "bmi": ("BMI", "体质指数", "kg/m2"),
    "egfr": ("EGFR", "估算肾小球滤过率", "mL/min/1.73m2"),
    "hba1c": ("HBA1C", "糖化血红蛋白", "%"),
    "fasting_glucose": ("FPG", "空腹血糖", "mmol/L"),
}

# 阻断入库的字段级问题；其余问题只提示，不阻塞同一任务的其它行。
BLOCKING_ISSUES = frozenset(
    {"invalid_date", "future_date", "before_birth", "invalid_value", "reference_range_invalid"}
)


class ImportTaskError(Exception):
    """导入任务的领域错误，由路由映射为状态码。"""

    def __init__(self, message: str, status_code: int = 422, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class StoredPayload:
    filename: str
    content_type: str | None
    size_bytes: int
    payload_sha256: str
    suffix: str
    raw: bytes


def payload_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    text = ("" if value is None else str(value)).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ImportTaskService:
    """导入任务的完整生命周期；事务边界在本服务内管理。"""

    def __init__(self, db: Session, *, storage_dir: str | None = None) -> None:
        self.db = db
        settings = get_settings()
        self._storage_dir = Path(storage_dir or settings.import_task_storage_dir)

    # ---- 上传与解析 -------------------------------------------------------
    def create_task(
        self,
        *,
        patient: Patient,
        filename: str,
        content_type: str | None,
        raw: bytes,
        request_id: str | None = None,
        actor_account_id: str | None = None,
    ) -> ImportTask:
        if request_id:
            existing = self.db.scalar(select(ImportTask).where(ImportTask.request_id == request_id))
            if existing is not None:
                same = existing.patient_id == patient.id and existing.payload_sha256 == (
                    payload_digest(raw)
                )
                if not same:
                    raise ImportTaskError("同一 request_id 对应不同文件或档案", status_code=409)
                return existing
        stored = self._validate_upload(filename=filename, content_type=content_type, raw=raw)
        task = ImportTask(
            patient_id=patient.id,
            filename=stored.filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            payload_sha256=stored.payload_sha256,
            parser="tabular" if stored.suffix in TABULAR_SUFFIXES else "smart_import",
            request_id=request_id,
            status=ImportTaskStatus.UPLOADED,
            created_by_account_id=actor_account_id,
        )
        self.db.add(task)
        self.db.flush()
        task.temporary_path = str(self._write_temporary(task.id, stored.raw))
        duplicate = self._find_confirmed_duplicate(task)
        if duplicate is not None:
            task.duplicate_of_task_id = duplicate.id
        self.db.commit()
        try:
            self.parse(task)
        except ImportTaskError:
            self.db.refresh(task)
            raise
        self.db.refresh(task)
        return task

    def _validate_upload(
        self, *, filename: str, content_type: str | None, raw: bytes
    ) -> StoredPayload:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ImportTaskError(
                "支持 CSV/TXT、PDF、DOCX 与 PNG/JPEG/WebP 图片", status_code=415
            )
        if not raw:
            raise ImportTaskError("文件为空", status_code=422)
        if len(raw) > MAX_BYTES:
            raise ImportTaskError("单文件最大 8 MB，请拆分后再上传", status_code=413)
        return StoredPayload(
            filename=Path(filename).name[:200],
            content_type=content_type,
            size_bytes=len(raw),
            payload_sha256=payload_digest(raw),
            suffix=suffix,
            raw=raw,
        )

    def _write_temporary(self, task_id: str, raw: bytes) -> Path:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        path = self._storage_dir / f"{task_id}.bin"
        path.write_bytes(raw)
        return path

    def _find_confirmed_duplicate(self, task: ImportTask) -> ImportTask | None:
        statement = (
            select(ImportTask)
            .where(
                ImportTask.patient_id == task.patient_id,
                ImportTask.payload_sha256 == task.payload_sha256,
                ImportTask.status == ImportTaskStatus.CONFIRMED,
                ImportTask.id != task.id,
            )
            .order_by(ImportTask.created_at.desc())
        )
        return self.db.scalar(statement)

    def parse(self, task: ImportTask) -> ImportTask:
        """解析任务内容；失败时任务进入 failed，保留原文与重试入口。"""

        task.status = ImportTaskStatus.PARSING
        task.attempts += 1
        self.db.commit()
        try:
            rows = self._parse(task)
        except ImportTaskError as exc:
            task.status = ImportTaskStatus.FAILED
            task.error_message = exc.message
            self.db.commit()
            raise
        except (httpx.HTTPError, ValidationError, ValueError, KeyError, OSError) as exc:
            task.status = ImportTaskStatus.FAILED
            task.error_message = f"解析失败：{type(exc).__name__}"
            self.db.commit()
            raise ImportTaskError("解析失败，请检查文件内容或稍后重试", status_code=422) from exc
        warnings = list(task.warnings or [])
        if task.duplicate_of_task_id:
            warnings.append("该文件此前已确认入库，本次需要显式同意后才会重复写入")
        task.draft = {"rows": rows, "parser": task.parser}
        task.warnings = warnings
        task.status = ImportTaskStatus.PREVIEW_READY
        task.error_message = None
        self.db.commit()
        self.db.refresh(task)
        return task

    def _parse(self, task: ImportTask) -> list[dict[str, Any]]:
        raw = self._read_temporary(task)
        if task.parser == "tabular":
            return self._parse_tabular(task, raw)
        return self._parse_with_model(task, raw)

    def _read_temporary(self, task: ImportTask) -> bytes:
        if not task.temporary_path or not Path(task.temporary_path).exists():
            raise ImportTaskError("原始文件已清理，无法重新解析，请重新上传", status_code=409)
        return Path(task.temporary_path).read_bytes()

    def _parse_tabular(self, task: ImportTask, raw: bytes) -> list[dict[str, Any]]:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportTaskError("文件必须是 UTF-8 编码的 CSV 或 TXT") from exc
        reader = csv.reader(io.StringIO(text))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            raise ImportTaskError("文件中没有可解析的数据行")
        header = [cell.strip().lower() for cell in rows[0]]
        if "date" not in header or "value" not in header:
            raise ImportTaskError(
                "CSV/TXT 需要表头列：date,metric_code,original_name,value,unit,"
                "reference_min,reference_max"
            )
        index = {name: header.index(name) for name in TABULAR_COLUMNS if name in header}
        parsed: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for line_no, row in enumerate(rows[1:], start=2):
            values = {
                name: (row[position].strip() if position < len(row) else "")
                for name, position in index.items()
            }
            built = self._build_row(task, values, source_ref=f"第 {line_no} 行")
            key = (built["date"] or "", built["metric_code"] or built["original_name"])
            if key in seen:
                built["issues"].append(issue("duplicate_in_file", "同一文件内出现重复记录"))
            seen.add(key)
            parsed.append(built)
        if not parsed:
            raise ImportTaskError("文件中没有可解析的数据行")
        for position, row in enumerate(parsed, start=1):
            row["row_id"] = f"r{position}"
        return parsed

    def _parse_with_model(self, task: ImportTask, raw: bytes) -> list[dict[str, Any]]:
        """PDF/DOCX/图片走本机 Qwen 提取；模型不可用时明确失败，不伪造结果。"""

        from app.schemas.smart_import import ImportFile, ImportRequest
        from app.services.smart_import import extract

        body = ImportRequest(
            text="",
            file=ImportFile(name=task.filename, content=base64.b64encode(raw).decode("ascii")),
        )
        try:
            result = extract(body)
        except httpx.HTTPError as exc:
            raise ImportTaskError(
                "本地模型服务不可用，请启动 Ollama 后重试", status_code=503
            ) from exc
        draft = result.get("draft", {})
        parsed: list[dict[str, Any]] = []
        for visit_index, visit in enumerate(draft.get("visits", [])):
            visit_date = visit.get("date")
            for field, (code, name, unit) in MODEL_FIELD_CODES.items():
                value = visit.get(field)
                if value is None:
                    continue
                built = self._build_row(
                    task,
                    {
                        "date": visit_date or "",
                        "metric_code": code,
                        "original_name": name,
                        "value": str(value),
                        "unit": unit,
                        "reference_min": "",
                        "reference_max": "",
                    },
                    source_ref=f"visits.{visit_index}.{field}",
                )
                parsed.append(built)
        for warning in draft.get("warnings", []):
            task.warnings = [*(task.warnings or []), warning]
        if not parsed:
            raise ImportTaskError("模型没有提取到可确认的检查记录")
        for position, row in enumerate(parsed, start=1):
            row["row_id"] = f"r{position}"
        return parsed

    def _build_row(
        self, task: ImportTask, values: dict[str, Any], *, source_ref: str
    ) -> dict[str, Any]:
        patient = self.db.get(Patient, task.patient_id)
        definitions = {
            item.metric_code: item for item in self.db.scalars(select(MetricDictionary)).all()
        }
        code = (values.get("metric_code") or "").strip().upper() or None
        original_name = (values.get("original_name") or "").strip()
        raw_value = (values.get("value") or "").strip()
        unit = (values.get("unit") or "").strip() or None
        issues: list[dict[str, str]] = []

        parsed_date = parse_date(values.get("date"))
        if parsed_date is None:
            issues.append(issue("invalid_date", "日期缺失或不是 YYYY-MM-DD 格式"))
        else:
            if parsed_date > date.today():
                issues.append(issue("future_date", "检查日期不能晚于今天"))
            if patient is not None and patient.birth_date and parsed_date < patient.birth_date:
                issues.append(issue("before_birth", "检查日期早于出生日期"))

        definition = definitions.get(code) if code else None
        numeric = parse_float(raw_value)
        if definition is not None:
            value_type = definition.value_type
        elif numeric is not None:
            value_type = ValueType.NUMERIC
        else:
            value_type = ValueType.QUALITATIVE if raw_value else ValueType.NUMERIC
        if value_type is ValueType.NUMERIC and numeric is None:
            issues.append(issue("invalid_value", "数值型指标的数值无法解析"))
        if definition is not None and numeric is not None:
            below = definition.valid_min is not None and numeric < definition.valid_min
            above = definition.valid_max is not None and numeric > definition.valid_max
            if below or above:
                issues.append(issue("out_of_dictionary_range", "数值超出字典允许范围，请核对单位"))
        if definition is None:
            if code:
                issues.append(issue("unmapped_metric", "目录中没有该指标编码，已保留原文待映射"))
            else:
                issues.append(issue("missing_metric", "缺少指标编码，入库后仍可补充映射"))
        if unit is None:
            issues.append(issue("missing_unit", "缺少单位，无法判断能否换算"))
        elif definition is not None and definition.standard_unit and unit != (
            definition.standard_unit
        ):
            conversions = definition.unit_conversions or {}
            if unit in conversions:
                issues.append(
                    issue("unit_needs_confirmation", f"单位 {unit} 与标准单位不同，需确认后换算")
                )
            else:
                issues.append(
                    issue("unsupported_unit", f"单位 {unit} 无换算依据，请确认是纠正标签还是换算")
                )
        reference_min = parse_float(values.get("reference_min"))
        reference_max = parse_float(values.get("reference_max"))
        if reference_min is not None and reference_max is not None and (
            reference_min > reference_max
        ):
            issues.append(issue("reference_range_invalid", "参考区间下限大于上限"))
        duplicate = self._existing_metric(task.patient_id, parsed_date, code, original_name)
        if duplicate is not None:
            issues.append(issue("duplicate_existing", "该档案同日已有相同指标记录"))

        return {
            "date": parsed_date.isoformat() if parsed_date else None,
            "metric_code": code,
            "original_name": original_name or (definition.canonical_name if definition else ""),
            "original_value": raw_value,
            "value": numeric,
            "value_type": value_type.value,
            "qualitative_value": (
                raw_value if value_type is not ValueType.NUMERIC and raw_value else None
            ),
            "unit": unit,
            "standard_unit": definition.standard_unit if definition else None,
            "reference_min": reference_min,
            "reference_max": reference_max,
            "source_ref": source_ref,
            "include": True,
            "issues": issues,
            "duplicate_of_record_id": None if duplicate is None else duplicate.id,
        }

    def _existing_metric(
        self, patient_id: str, check_date: date | None, code: str | None, name: str
    ) -> LabMetric | None:
        if check_date is None or (not code and not name):
            return None
        statement = (
            select(LabMetric)
            .join(HealthCheck, LabMetric.health_check_id == HealthCheck.id)
            .where(HealthCheck.patient_id == patient_id, HealthCheck.check_date == check_date)
        )
        if code:
            statement = statement.where(LabMetric.metric_code == code)
        else:
            statement = statement.where(LabMetric.original_name == name)
        return self.db.scalar(statement.limit(1))

    # ---- 校对 -------------------------------------------------------------
    def rows(self, task: ImportTask) -> list[dict[str, Any]]:
        rows = list((task.draft or {}).get("rows", []))
        for position, row in enumerate(rows, start=1):
            row.setdefault("row_id", f"r{position}")
        return rows

    def update_rows(self, task: ImportTask, updates: list[dict[str, Any]]) -> ImportTask:
        if task.status is not ImportTaskStatus.PREVIEW_READY:
            raise ImportTaskError("只有待校对的任务可以修改预览内容", status_code=409)
        current = {row["row_id"]: row for row in self.rows(task)}
        for update in updates:
            row_id = update.get("row_id")
            if row_id not in current:
                raise ImportTaskError(f"未知的行标识：{row_id}", status_code=422)
            merged = {**current[row_id], **update}
            rebuilt = self._rebuild_row(task, merged)
            rebuilt["row_id"] = row_id
            rebuilt["include"] = bool(merged.get("include", True))
            current[row_id] = rebuilt
        ordered = [current[row["row_id"]] for row in self.rows(task)]
        task.draft = {"rows": ordered, "parser": task.parser}
        self.db.commit()
        self.db.refresh(task)
        return task

    def _rebuild_row(self, task: ImportTask, row: dict[str, Any]) -> dict[str, Any]:
        return self._build_row(
            task,
            {
                "date": row.get("date") or "",
                "metric_code": row.get("metric_code") or "",
                "original_name": row.get("original_name") or "",
                "value": row.get("original_value") or "",
                "unit": row.get("unit") or "",
                "reference_min": row.get("reference_min"),
                "reference_max": row.get("reference_max"),
            },
            source_ref=row.get("source_ref") or "",
        )

    # ---- 确认入库 ---------------------------------------------------------
    def confirm(
        self,
        task: ImportTask,
        *,
        allow_duplicate: bool = False,
        merge_same_day: bool = False,
        actor_account_id: str | None = None,
    ) -> dict[str, Any]:
        if task.status is ImportTaskStatus.CONFIRMED:
            return task.result_summary or {}
        if task.status is not ImportTaskStatus.PREVIEW_READY:
            raise ImportTaskError("任务尚未完成解析，不能确认入库", status_code=409)
        rows = [row for row in self.rows(task) if row.get("include", True)]
        if not rows:
            raise ImportTaskError("没有勾选任何可入库的记录", status_code=422)
        blocking = {
            row["row_id"]: [item for item in row["issues"] if item["code"] in BLOCKING_ISSUES]
            for row in rows
            if any(item["code"] in BLOCKING_ISSUES for item in row["issues"])
        }
        if blocking:
            raise ImportTaskError(
                "存在必须修正的字段错误，已阻止入库", status_code=422, details=blocking
            )
        duplicates = [row for row in rows if row.get("duplicate_of_record_id")]
        if duplicates and not merge_same_day:
            raise ImportTaskError(
                "同一档案同日已有相同指标，请选择合并或移除重复行",
                status_code=409,
                details=[row["row_id"] for row in duplicates],
            )
        if task.duplicate_of_task_id and not allow_duplicate:
            raise ImportTaskError(
                "该文件与此前已确认的任务内容相同，如确实要重复入库请显式确认",
                status_code=409,
                details={"duplicate_of_task_id": task.duplicate_of_task_id},
            )

        definitions = {
            item.metric_code: item for item in self.db.scalars(select(MetricDictionary)).all()
        }
        # 未映射指标不能凭空调用编码：先落一条占位字典项，保留原文并进入待映射队列。
        pending_codes = {
            row["metric_code"]
            for row in rows
            if row["metric_code"] and row["metric_code"] not in definitions
        }
        if pending_codes or any(not row["metric_code"] for row in rows):
            definitions["UNMAPPED"] = self._ensure_pending_definition()
        revisions = RecordRevisionService(self.db)
        created_checks: list[str] = []
        created_metrics = 0
        skipped: list[str] = []
        try:
            by_date: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                by_date.setdefault(row["date"], []).append(row)
            for check_date, date_rows in sorted(by_date.items()):
                check = self.db.scalar(
                    select(HealthCheck).where(
                        HealthCheck.patient_id == task.patient_id,
                        HealthCheck.check_date == date.fromisoformat(check_date),
                    )
                )
                if check is None:
                    check = HealthCheck(
                        patient_id=task.patient_id,
                        check_date=date.fromisoformat(check_date),
                        institution=f"导入任务 {task.filename}"[:200],
                        source_kind="import",
                        source_ref=f"import_task:{task.id}",
                    )
                    self.db.add(check)
                    self.db.flush()
                    revisions.record(
                        check,
                        action="create",
                        source_kind="import",
                        source_ref=f"import_task:{task.id}",
                        actor_account_id=actor_account_id,
                    )
                created_checks.append(check.id)
                existing = {
                    metric.metric_code
                    for metric in self.db.scalars(
                        select(LabMetric).where(LabMetric.health_check_id == check.id)
                    )
                }
                for row in date_rows:
                    definition = definitions.get(row["metric_code"] or "")
                    code = definition.metric_code if definition else "UNMAPPED"
                    # 占位编码下按原始名称区分，避免把不同未映射指标当成重复。
                    key = code if code != "UNMAPPED" else f"UNMAPPED:{row['original_name']}"
                    if key in existing:
                        skipped.append(row["row_id"])
                        continue
                    definition = definitions.get(code)
                    metric = LabMetric(
                        health_check_id=check.id,
                        metric_code=code,
                        original_name=(row["original_name"] or "未命名指标")[:200],
                        canonical_name=(
                            definition.canonical_name
                            if definition
                            else (row["original_name"] or "未映射指标")
                        )[:200],
                        original_value=(row["original_value"] or "-")[:100],
                        value=row["value"],
                        original_unit=row["unit"],
                        standard_unit=(definition.standard_unit if definition else row["unit"]),
                        reference_min=row["reference_min"],
                        reference_max=row["reference_max"],
                        status=MetricStatus.UNKNOWN,
                        normalization_status=(
                            NormalizationStatus.NORMALIZED
                            if definition
                            else NormalizationStatus.UNMAPPED_METRIC
                        ),
                        normalization_version="import-task-v1",
                        value_type=ValueType(row["value_type"]),
                        qualitative_value=row["qualitative_value"],
                        source_kind="import",
                        source_ref=f"import_task:{task.id}#{row['row_id']}",
                    )
                    self.db.add(metric)
                    self.db.flush()
                    existing.add(key)
                    revisions.record(
                        metric,
                        action="create",
                        source_kind="import",
                        source_ref=f"import_task:{task.id}#{row['row_id']}",
                        actor_account_id=actor_account_id,
                    )
                    created_metrics += 1
            task.status = ImportTaskStatus.CONFIRMED
            task.confirmed_at = _utcnow()
            task.confirmed_by_account_id = actor_account_id
            task.result_summary = {
                "health_check_ids": created_checks,
                "created_metric_count": created_metrics,
                "skipped_row_ids": skipped,
                "merged_same_day": bool(skipped),
            }
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._cleanup_temporary(task)
        self.db.refresh(task)
        return task.result_summary

    def _ensure_pending_definition(self) -> MetricDictionary:
        """待映射占位字典项：保留原文，人工映射后再改编码（T08 管理接口）。"""

        definition = self.db.scalar(
            select(MetricDictionary).where(MetricDictionary.metric_code == "UNMAPPED")
        )
        if definition is None:
            definition = MetricDictionary(
                metric_code="UNMAPPED",
                canonical_name="未映射指标（待人工映射）",
                aliases=[],
                standard_unit=None,
                category="待映射",
                value_type=ValueType.TEXT,
                unit_conversions={},
                source="系统占位：导入时未命中目录，须人工确认后映射",
                version="pending-v1",
            )
            self.db.add(definition)
            self.db.flush()
        return definition

    def cancel(self, task: ImportTask) -> ImportTask:
        if task.status is ImportTaskStatus.CONFIRMED:
            raise ImportTaskError("已入库的任务不能取消，请通过记录修订回退", status_code=409)
        task.status = ImportTaskStatus.CANCELLED
        self.db.commit()
        self._cleanup_temporary(task)
        self.db.refresh(task)
        return task

    def _cleanup_temporary(self, task: ImportTask) -> None:
        if task.temporary_path:
            try:
                Path(task.temporary_path).unlink(missing_ok=True)
            except OSError:
                pass
        task.temporary_path = None
        self.db.commit()

    # ---- 展示 -------------------------------------------------------------
    def serialize(self, task: ImportTask) -> dict[str, Any]:
        rows = self.rows(task)
        return {
            "task_id": task.id,
            "patient_id": task.patient_id,
            "status": task.status.value,
            "filename": task.filename,
            "content_type": task.content_type,
            "size_bytes": task.size_bytes,
            "parser": task.parser,
            "attempts": task.attempts,
            "warnings": task.warnings or [],
            "error_message": task.error_message,
            "duplicate_of_task_id": task.duplicate_of_task_id,
            "rows": rows,
            # 只有勾选入库的行才影响确认结果；排除行的问题仍逐行返回。
            "blocking_row_ids": [
                row["row_id"]
                for row in rows
                if row.get("include", True)
                and any(item["code"] in BLOCKING_ISSUES for item in row["issues"])
            ],
            "issue_count": sum(len(row["issues"]) for row in rows),
            "confirmed_at": task.confirmed_at,
            "result_summary": task.result_summary,
        }
