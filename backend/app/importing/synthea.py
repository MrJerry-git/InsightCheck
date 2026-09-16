"""Read the official Synthea CSV ZIP without extracting or retaining identity fields."""

import csv
import hashlib
import io
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from app.importing.contracts import (
    METRICS,
    EncounterRow,
    ImportRequest,
    ObservationRow,
    PatientRow,
)

SOURCE_URL = (
    "https://synthetichealth.github.io/synthea-sample-data/"
    "downloads/latest/synthea_sample_data_csv_latest.zip"
)


def csv_text(schema: type, rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(schema.model_fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def prepare_synthea(path: Path) -> tuple[ImportRequest, dict]:
    if path.stat().st_size > 50_000_000:
        raise ValueError("v1 supports small archives up to 50 MB")
    with path.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    with ZipFile(path) as archive:
        members = archive.infolist()
        if sum(item.file_size for item in members) > 300_000_000:
            raise ValueError("archive expansion exceeds 300 MB")
        if len({item.filename for item in members}) != len(members):
            raise ValueError("duplicate archive member")
        tables: dict[str, list[dict]] = {}
        fields: dict[str, list[str]] = {}
        for name in ("patients", "encounters", "observations"):
            with archive.open(f"{name}.csv") as member:
                reader = csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig"), strict=True)
                fields[name] = reader.fieldnames or []
                tables[name] = list(reader)
    required = {
        "patients": {"Id", "BIRTHDATE", "GENDER"},
        "encounters": {"Id", "PATIENT", "START", "ENCOUNTERCLASS"},
        "observations": {
            "DATE",
            "PATIENT",
            "ENCOUNTER",
            "CODE",
            "DESCRIPTION",
            "VALUE",
            "UNITS",
            "TYPE",
        },
    }
    for name, headers in required.items():
        if not headers <= set(fields[name]):
            raise ValueError(f"{name}: missing required Synthea columns")
        if any(None in row or any(v is None for v in row.values()) for row in tables[name]):
            raise ValueError(f"{name}: malformed row width")
    encounters = [
        {
            "source_id": row["Id"],
            "patient_source_id": row["PATIENT"],
            "event_time": row["START"],
            "encounter_type": "wellness",
        }
        for row in tables["encounters"]
        if row["ENCOUNTERCLASS"] == "wellness"
    ]
    selected_encounters = {row["source_id"] for row in encounters}
    selected_patients = {row["patient_source_id"] for row in encounters}
    gender = {"F": "female", "M": "male"}
    patients = [
        {
            "source_id": row["Id"],
            "birth_date": row["BIRTHDATE"],
            "gender": gender.get(row["GENDER"], "unknown"),
        }
        for row in tables["patients"]
        if row["Id"] in selected_patients
    ]
    observations = []
    excluded: Counter = Counter()
    for line, row in enumerate(tables["observations"], start=2):
        if row["ENCOUNTER"] not in selected_encounters:
            excluded["not_selected_wellness"] += 1
        elif row["TYPE"] != "numeric":
            excluded["non_numeric"] += 1
        elif row["CODE"] not in METRICS:
            excluded["unmapped_code"] += 1
        else:
            observations.append(
                {
                    "source_id": f"observations:{line}",
                    "patient_source_id": row["PATIENT"],
                    "encounter_source_id": row["ENCOUNTER"],
                    "event_time": row["DATE"],
                    "code": row["CODE"],
                    "original_name": row["DESCRIPTION"],
                    "original_value": row["VALUE"],
                    "original_unit": row["UNITS"],
                }
            )
    request = ImportRequest(
        source_version=archive_hash,
        patients_csv=csv_text(PatientRow, patients),
        encounters_csv=csv_text(EncounterRow, encounters),
        observations_csv=csv_text(ObservationRow, observations),
    )
    audit = {
        "source_url": SOURCE_URL,
        "archive_sha256": archive_hash,
        "archive_bytes": path.stat().st_size,
        "source_kind": "synthetic",
        "adapter_version": request.adapter_version,
        "raw_counts": {key: len(value) for key, value in tables.items()},
        "raw_columns": fields,
        "encounter_classes": dict(Counter(row["ENCOUNTERCLASS"] for row in tables["encounters"])),
        "selected_counts": {
            "patients": len(patients),
            "encounters": len(encounters),
            "observations": len(observations),
        },
        "excluded_observations": dict(excluded),
        "selected_codes": dict(Counter(row["code"] for row in observations)),
        "availability": "No available_at in source; event timestamps retained without inference",
        "scope": "Wellness plus five numeric vital codes only; no disease or recommendation labels",
    }
    return request, audit
