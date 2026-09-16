from logging.config import fileConfig
from typing import Any

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

ENUM_CHECK_CONSTRAINTS = {
    "ck_ai_reports_ai_report_type",
    "ck_exam_histories_exam_result_status",
    "ck_exam_items_cost_level",
    "ck_lab_metrics_metric_status",
    "ck_lab_metrics_normalization_status",
    "ck_lesion_observations_match_status",
    "ck_medical_rules_rule_action",
    "ck_patients_gender",
    "ck_recommendation_items_recommendation_decision",
    "ck_recommendations_plan_tier",
    "ck_recommendations_recommendation_status",
}


def include_object(_: Any, name: str | None, type_: str, reflected: bool, __: Any) -> bool:
    """SQLite 无法可靠反射 SQLAlchemy Enum 生成的 CHECK 表达式。"""

    if type_ == "check_constraint" and reflected and name in ENUM_CHECK_CONSTRAINTS:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
