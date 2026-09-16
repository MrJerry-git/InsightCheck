import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.importing.contracts import validate_bundle
from app.importing.synthea import prepare_synthea


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit or import a local synthetic Synthea CSV ZIP"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument(
        "--import-data", action="store_true", help="Persist after successful validation"
    )
    args = parser.parse_args()
    request, audit = prepare_synthea(args.archive)
    report, _ = validate_bundle(request)
    audit["audited_at"] = datetime.now(UTC).isoformat()
    audit["validation"] = report.model_dump()
    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    if args.import_data and report.valid:
        from app.core.database import SessionLocal
        from app.services.import_service import ImportService

        with SessionLocal() as session:
            audit["import_result"] = ImportService(session).run(request)
    rendered = json.dumps(audit, ensure_ascii=False, indent=2)
    if args.audit_output:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report.valid:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
