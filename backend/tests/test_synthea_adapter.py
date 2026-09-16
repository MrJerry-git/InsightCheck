import csv
import hashlib
import io
from zipfile import ZipFile

import pytest

from app.importing.contracts import validate_bundle
from app.importing.synthea import prepare_synthea


def write_csv(archive, name, rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    archive.writestr(f"{name}.csv", stream.getvalue())


def test_adapter_filters_with_accounting_and_drops_direct_identifiers(tmp_path):
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        write_csv(
            archive,
            "patients",
            [
                {"Id": "p1", "BIRTHDATE": "1980-01-01", "GENDER": "F", "SSN": "DO-NOT-IMPORT"},
            ],
        )
        write_csv(
            archive,
            "encounters",
            [
                {
                    "Id": "e1",
                    "PATIENT": "p1",
                    "START": "2020-01-01T10:00:00Z",
                    "ENCOUNTERCLASS": "wellness",
                },
                {
                    "Id": "e2",
                    "PATIENT": "p1",
                    "START": "2020-01-02T10:00:00Z",
                    "ENCOUNTERCLASS": "inpatient",
                },
            ],
        )
        base = {
            "DATE": "2020-01-01T10:00:00Z",
            "PATIENT": "p1",
            "ENCOUNTER": "e1",
            "CODE": "29463-7",
            "DESCRIPTION": "Weight",
            "VALUE": "60",
            "UNITS": "kg",
            "TYPE": "numeric",
        }
        write_csv(
            archive,
            "observations",
            [
                base,
                {**base, "ENCOUNTER": "e2"},
                {**base, "TYPE": "text"},
                {**base, "CODE": "unmapped"},
            ],
        )
    request, audit = prepare_synthea(path)
    assert request.source_version == hashlib.sha256(path.read_bytes()).hexdigest()
    assert validate_bundle(request)[0].valid
    assert audit["selected_counts"] == {"patients": 1, "encounters": 1, "observations": 1}
    assert sum(audit["excluded_observations"].values()) == 3
    assert "DO-NOT-IMPORT" not in request.model_dump_json()
    assert "SSN" not in request.patients_csv
    assert prepare_synthea(path)[0] == request


def test_adapter_fails_on_missing_columns(tmp_path):
    path = tmp_path / "bad.zip"
    with ZipFile(path, "w") as archive:
        for name in ("patients", "encounters", "observations"):
            write_csv(archive, name, [{"unexpected": "value"}])
    with pytest.raises(ValueError, match="required Synthea columns"):
        prepare_synthea(path)
