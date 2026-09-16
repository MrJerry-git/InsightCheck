"""Reproducible, aggregate-only audit of the public IDC NLST clinical subset."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

TABLES = ("nlst_prsn", "nlst_screen", "nlst_ctab", "nlst_ctabc", "nlst_canc")
BASE = "https://idc-open-metadata.s3.amazonaws.com/bigquery_export/idc_v24_clinical"
DICTIONARY = (
    "https://github.com/ImagingDataCommons/idc-index-data/releases/download/"
    "24.2.2/clinical_index.parquet"
)
EXPECTED_SHA256 = {
    "nlst_prsn": "3227b367486c44e693b85ad40d8eebbab10b86954a8444135b6b39974d003c7d",
    "nlst_screen": "7227401ba86444c22793cd0b9d4856b44aa809c64148fcfda23d6330815e51fd",
    "nlst_ctab": "0dd091842933e57891da51db0ab045fbfba3307dcf9a9e4ced66cf5369111f9d",
    "nlst_ctabc": "f2ebee5100fe20efbb0b4ac9be0730efc2545c36dfb6bbe29b9af07300a617d8",
    "nlst_canc": "7902dce4e7daacd9091c612bf534a9a66967098c5eb4219d071c61dd90f3ebfb",
    "clinical_index": "0d0a494711964054862de9a0ddd8c6e3c4bebfa5d10e4e9668e86c644d08aee7",
}
KEYS = {
    "nlst_prsn": ["pid"],
    "nlst_screen": ["pid", "study_yr"],
    "nlst_ctab": ["pid", "study_yr", "sct_ab_num"],
    "nlst_ctabc": ["pid", "study_yr", "sct_ab_num"],
    "nlst_canc": ["pid", "lc_order"],
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sources() -> dict[str, str]:
    return {
        **{name: f"{BASE}/{name}/000000000000.parquet" for name in TABLES},
        "clinical_index": DICTIONARY,
    }


def download(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in sources().items():
        target = directory / f"{name}.parquet"
        if target.exists():
            if sha256(target) != EXPECTED_SHA256[name]:
                raise ValueError(f"cached source hash differs: {name}; preserve and review")
            continue  # Preserve the original snapshot; audit records its actual hash.
        with urlopen(url, timeout=60) as response:
            content = response.read(20_000_001)
        if len(content) > 20_000_000:
            raise ValueError(f"unexpected file size: {name}")
        if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256[name]:
            raise ValueError(f"source changed: {name}; explicit version review required")
        temporary = target.with_suffix(".partial")
        temporary.write_bytes(content)
        pd.read_parquet(temporary)  # Do not install an HTML error response as source data.
        temporary.replace(target)


def missing(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.isna() | text.eq("").fillna(False) | text.str.match(r"^\.[A-Z]?$", na=False)


def audit(directory: Path) -> dict:
    frames = {name: pd.read_parquet(directory / f"{name}.parquet") for name in TABLES}
    dictionary = pd.read_parquet(directory / "clinical_index.parquet")
    dictionary = dictionary[dictionary.collection_id == "nlst"]
    people = set(frames["nlst_prsn"].pid.dropna())
    report = {
        "source_kind": "public_observational",
        "idc_version": "v24",
        "dictionary_version": "24.2.2",
        "audited_at": datetime.now(UTC).isoformat(),
        "files": {},
        "tables": {},
        "task_status": "BLOCKED_PENDING_FOLLOWUP_DEFINITION",
    }
    for name, url in sources().items():
        path = directory / f"{name}.parquet"
        report["files"][name] = {
            "url": url,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "matches_reference_snapshot": sha256(path) == EXPECTED_SHA256[name],
        }
    for name, frame in frames.items():
        for field in KEYS[name]:
            if field not in frame:
                raise ValueError(f"missing key {name}.{field}")
        summary = {
            "rows": len(frame),
            "patients": int(frame.pid.nunique()),
            "duplicate_key_rows": int(frame.duplicated(KEYS[name], keep=False).sum()),
            "missing_key_rows": int(
                pd.concat([missing(frame[c]) for c in KEYS[name]], axis=1).any(axis=1).sum()
            ),
            "orphan_patient_rows": int((~frame.pid.isin(people)).sum()),
            "columns": list(frame.columns),
            "missing_counts": {col: int(missing(frame[col]).sum()) for col in frame},
            "dataset_versions": sorted(
                frame.dataset_version.dropna().astype(str).unique().tolist()
            ),
        }
        if "study_yr" in frame:
            summary["study_year_rows"] = (
                frame.study_yr.astype(str).value_counts().sort_index().to_dict()
            )
        report["tables"][name] = summary
    screen = frames["nlst_screen"]
    report["ct_screen_rounds_per_patient"] = (
        screen.groupby("pid").study_yr.nunique().value_counts().sort_index().to_dict()
    )
    person = frames["nlst_prsn"]
    report["outcome_field_presence"] = {
        key: key in person
        for key in ("candx_days", "canc_free_days", "fup_days", "death_days", "rndgroup")
    }
    report["time_fields"] = {}
    for key in ("scr_days0", "scr_days1", "scr_days2", "candx_days", "canc_free_days"):
        if key in person:
            numeric = pd.to_numeric(person[key], errors="coerce")
            report["time_fields"][key] = {
                "numeric_rows": int(numeric.notna().sum()),
                "min": float(numeric.min()) if numeric.notna().any() else None,
                "max": float(numeric.max()) if numeric.notna().any() else None,
                "unrecognized_non_numeric_rows": int(
                    (numeric.isna() & ~missing(person[key])).sum()
                ),
            }
    abnormality_keys = frames["nlst_ctab"][KEYS["nlst_ctab"]]
    linked = frames["nlst_ctabc"].merge(
        abnormality_keys.drop_duplicates(), on=KEYS["nlst_ctab"], how="left", indicator=True
    )
    report["comparison_rows_without_same_round_abnormality"] = int(
        (linked["_merge"] == "left_only").sum()
    )
    fields = ("candx_days", "canc_free_days", "scr_days0", "sct_ab_num")
    report["critical_dictionary_labels"] = [
        {"table": row.short_table_name, "column": row.column, "label": row.column_label}
        for row in dictionary.itertuples()
        if row.column in fields
    ]
    report["limitations"] = [
        "canc_free_days is not an approved substitute for fup_days; outcome task remains unfrozen",
        "sct_ab_num restarts for each participant and study year; no cross-year lesion identity",
        "public subset does not establish report availability timestamps or external validity",
        "population coverage differs; not all participants are CT patients",
    ]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.download:
        download(args.directory)
    result = audit(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "tables": {k: v["rows"] for k, v in result["tables"].items()},
                "task_status": result["task_status"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
