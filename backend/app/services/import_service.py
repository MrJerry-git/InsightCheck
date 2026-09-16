import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.importing.contracts import METRICS, ImportRequest, validate_bundle
from app.models import (
    HealthCheck,
    ImportBatch,
    ImportedRecord,
    LabMetric,
    MetricDictionary,
    Patient,
)
from app.models.enums import MetricStatus, NormalizationStatus


class ImportConflictError(ValueError):
    pass


def digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def entity_id(request: ImportRequest, table: str, source_id: str) -> str:
    # Versions are intentionally isolated; never silently merge changing snapshots.
    key = f"insightcheck:{request.source_dataset}:{request.source_version}:{table}:{source_id}"
    return str(uuid5(NAMESPACE_URL, key))


class ImportService:
    def __init__(self, session: Session):
        self.session = session

    def run(self, request: ImportRequest) -> dict:
        report, tables = validate_bundle(request)
        if not report.valid:
            return {"status": "invalid", "validation": report.model_dump()}
        models = {"patients": Patient, "encounters": HealthCheck, "observations": LabMetric}
        payload_hash = digest(request.model_dump())
        batch = self.session.scalar(
            select(ImportBatch).where(ImportBatch.payload_sha256 == payload_hash)
        )
        existing: set[str] = set()
        for table, rows in tables.items():
            for row in rows:
                key = entity_id(request, table, row.source_id)
                record = self.session.get(ImportedRecord, key)
                target = self.session.get(models[table], key)
                if record:
                    if record.payload_sha256 != digest(row.model_dump(mode="json")) or not target:
                        raise ImportConflictError(
                            "source record changed or imported entity missing"
                        )
                    self._check_domain(request, table, row, target)
                    existing.add(key)
                elif target:
                    raise ImportConflictError("domain ID exists without matching provenance")
        created = dict.fromkeys(tables, 0)
        reused = dict.fromkeys(tables, 0)
        try:
            self._ensure_dictionaries({row.code for row in tables["observations"]})
            if batch is None:
                batch = ImportBatch(
                    payload_sha256=payload_hash,
                    source_dataset=request.source_dataset,
                    source_version=request.source_version,
                    source_kind=request.source_kind,
                    adapter_version=request.adapter_version,
                    counts=report.counts,
                )
                self.session.add(batch)
                self.session.flush()
            for table, rows in tables.items():
                for row in rows:
                    key = entity_id(request, table, row.source_id)
                    if key in existing:
                        reused[table] += 1
                        continue
                    self.session.add(models[table](id=key, **self._values(request, table, row)))
                    self.session.add(
                        ImportedRecord(
                            id=key,
                            batch_id=batch.id,
                            entity_type=table,
                            payload_sha256=digest(row.model_dump(mode="json")),
                            payload=row.model_dump(mode="json"),
                        )
                    )
                    created[table] += 1
                self.session.flush()
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ImportConflictError(
                "concurrent or conflicting import; revalidate and retry"
            ) from exc
        except Exception:
            self.session.rollback()
            raise
        return {
            "status": "imported",
            "batch_id": batch.id,
            "source_kind": "synthetic",
            "created": created,
            "reused": reused,
            "validation": report.model_dump(),
        }

    def _values(self, request: ImportRequest, table: str, row) -> dict:
        if table == "patients":
            return {
                "anonymous_code": f"SYN-{entity_id(request, table, row.source_id)}".upper(),
                "birth_date": row.birth_date,
                "gender": row.gender,
            }
        if table == "encounters":
            return {
                "patient_id": entity_id(request, "patients", row.patient_source_id),
                "check_date": row.event_time.date(),
                "institution": "SYNTHETIC wellness encounter",
                "is_demo": True,
            }
        name, unit = METRICS[row.code]
        code = f"SYN_LOINC_{row.code}"
        return {
            "health_check_id": entity_id(request, "encounters", row.encounter_source_id),
            "metric_code": code,
            "original_name": row.original_name,
            "canonical_name": name,
            "original_value": row.original_value,
            "value": float(row.original_value),
            "original_unit": row.original_unit,
            "standard_unit": unit,
            "status": MetricStatus.UNKNOWN,
            "normalization_status": NormalizationStatus.NORMALIZED,
            "normalization_version": "synthea-wellness-v1",
        }

    def _ensure_dictionaries(self, codes: set[str]) -> None:
        for source_code in sorted(codes):
            name, unit = METRICS[source_code]
            code = f"SYN_LOINC_{source_code}"
            dictionary = self.session.scalar(
                select(MetricDictionary).where(MetricDictionary.metric_code == code)
            )
            if dictionary is None:
                self.session.add(
                    MetricDictionary(
                        metric_code=code,
                        canonical_name=name,
                        aliases=[],
                        standard_unit=unit,
                        category="synthetic_vital",
                        source="Synthea source code/unit mapping",
                        version="synthea-wellness-v1",
                        unit_conversions={},
                    )
                )
            elif (
                dictionary.standard_unit != unit
                or dictionary.canonical_name != name
                or dictionary.version != "synthea-wellness-v1"
                or dictionary.unit_conversions
                or dictionary.valid_min is not None
                or dictionary.valid_max is not None
            ):
                raise ImportConflictError("existing metric dictionary differs from adapter mapping")
        self.session.flush()

    def _check_domain(self, request: ImportRequest, table: str, row, target) -> None:
        # Detect edits through generic CRUD; do not silently certify a stale replay.
        expected = self._values(request, table, row)
        if any(getattr(target, key) != value for key, value in expected.items()):
            raise ImportConflictError(
                "imported entity was modified; explicit reconciliation required"
            )
