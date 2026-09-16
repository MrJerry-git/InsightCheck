import csv
import io
import math
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models.enums import Gender

ADAPTER_VERSION = "synthea-wellness-v1"
# Codes/units copied from source observations; no clinical normal ranges are inferred.
METRICS = {
    "8302-2": ("Body Height", "cm"),
    "29463-7": ("Body Weight", "kg"),
    "39156-5": ("Body mass index", "kg/m2"),
    "8480-6": ("Systolic Blood Pressure", "mm[Hg]"),
    "8462-4": ("Diastolic Blood Pressure", "mm[Hg]"),
}
SourceId = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class StrictRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class PatientRow(StrictRow):
    source_id: SourceId
    birth_date: date
    gender: Gender


class EncounterRow(StrictRow):
    source_id: SourceId
    patient_source_id: SourceId
    event_time: datetime
    encounter_type: Literal["wellness"]

    @field_validator("event_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_time requires a timezone")
        return value.astimezone(UTC)


class ObservationRow(StrictRow):
    source_id: SourceId
    patient_source_id: SourceId
    encounter_source_id: SourceId
    event_time: datetime
    code: str = Field(min_length=1, max_length=64)
    original_name: str = Field(min_length=1, max_length=200)
    original_value: str = Field(min_length=1, max_length=100)
    original_unit: str = Field(min_length=1, max_length=50)

    @field_validator("event_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return EncounterRow.require_timezone(value)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_dataset: Literal["synthea"] = "synthea"
    source_kind: Literal["synthetic"] = "synthetic"
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    adapter_version: Literal["synthea-wellness-v1"] = ADAPTER_VERSION
    patients_csv: str = Field(max_length=2_000_000)
    encounters_csv: str = Field(max_length=4_000_000)
    observations_csv: str = Field(max_length=12_000_000)


class ImportIssue(BaseModel):
    table: str
    row: int
    field: str
    message: str


class ValidationReport(BaseModel):
    valid: bool
    counts: dict[str, int]
    issues: list[ImportIssue]
    source_kind: Literal["synthetic"] = "synthetic"
    available_at_policy: str = "unknown_in_source; event_time_is_not_proven_availability"


TABLES = {"patients": PatientRow, "encounters": EncounterRow, "observations": ObservationRow}
LIMITS = {"patients": 1000, "encounters": 20_000, "observations": 50_000}


def validate_bundle(request: ImportRequest) -> tuple[ValidationReport, dict[str, list]]:
    issues: list[ImportIssue] = []
    parsed: dict[str, list] = {}
    line_numbers: dict[str, list[int]] = {}

    def issue(table: str, row: int, field: str, message: str) -> None:
        issues.append(ImportIssue(table=table, row=row, field=field, message=message))

    for table, schema in TABLES.items():
        parsed[table], line_numbers[table] = [], []
        reader = csv.DictReader(io.StringIO(getattr(request, f"{table}_csv")), strict=True)
        try:
            headers = reader.fieldnames or []
            if set(headers) != set(schema.model_fields) or len(headers) != len(set(headers)):
                issue(table, 1, "header", "headers must exactly match the documented template")
                continue
            seen: set[str] = set()
            for index, raw in enumerate(reader):
                line = reader.line_num
                if index >= LIMITS[table]:
                    issue(table, line, "rows", f"limit is {LIMITS[table]} records")
                    break
                if None in raw or any(value is None for value in raw.values()):
                    issue(table, line, "columns", "row has the wrong number of columns")
                    continue
                try:
                    entry = schema.model_validate(raw)
                except ValidationError as exc:
                    for error in exc.errors(include_input=False, include_url=False):
                        issue(table, line, str(error["loc"][0]), error["msg"])
                    continue
                if entry.source_id in seen:
                    issue(table, line, "source_id", "duplicate source_id")
                    continue
                seen.add(entry.source_id)
                parsed[table].append(entry)
                line_numbers[table].append(line)
        except csv.Error:
            issue(table, reader.line_num, "csv", "malformed CSV")

    patients = {row.source_id: row for row in parsed["patients"]}
    encounters = {row.source_id: row for row in parsed["encounters"]}
    for row, line in zip(parsed["encounters"], line_numbers["encounters"], strict=True):
        patient = patients.get(row.patient_source_id)
        if patient is None:
            issue("encounters", line, "patient_source_id", "patient is absent from this bundle")
        elif row.event_time.date() < patient.birth_date:
            issue("encounters", line, "event_time", "encounter precedes birth")
    for row, line in zip(parsed["observations"], line_numbers["observations"], strict=True):
        encounter = encounters.get(row.encounter_source_id)
        if encounter is None or encounter.patient_source_id != row.patient_source_id:
            issue("observations", line, "encounter_source_id", "missing or cross-patient encounter")
        elif row.event_time < encounter.event_time:
            issue("observations", line, "event_time", "observation precedes encounter")
        if row.code not in METRICS:
            issue("observations", line, "code", "unmapped code; v1 has five explicit mappings")
        elif row.original_unit != METRICS[row.code][1]:
            issue("observations", line, "original_unit", "unit differs from the v1 mapping")
        try:
            if not math.isfinite(float(row.original_value)):
                raise ValueError
        except ValueError:
            issue("observations", line, "original_value", "value must be a finite number")
    if not parsed["patients"] or not parsed["encounters"]:
        issue("bundle", 0, "rows", "at least one patient and wellness encounter are required")
    report = ValidationReport(
        valid=not issues, counts={key: len(rows) for key, rows in parsed.items()}, issues=issues
    )
    return report, parsed
