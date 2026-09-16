import json

from app.core.database import SessionLocal
from app.services.lesion_demo_seed_service import LesionMatchingDemoSeedService
from app.services.seed_service import DemoSeedService


def main() -> None:
    with SessionLocal() as session:
        health_summary = DemoSeedService(session).run()
        lesion_summary = LesionMatchingDemoSeedService(session).run()
    print(
        json.dumps(
            {
                "health_demo": health_summary.to_dict(),
                "lesion_matching_demo": lesion_summary.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
