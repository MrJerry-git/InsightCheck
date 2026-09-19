"""NLST 公开临床子集的受检者级适配入口：固定快照读取、显式字段映射与质量摘要。

边界：

- 只做可复现的结构性转换：按 `app.research.nlst` 的实测 SHA256 校验固定快照，未复核的
  快照一律拒绝；原始数据与转换结果都写在 Git 忽略目录，不进版本库。
- 输出每位受检者一行；`subject_id` 带队列前缀，不同队列不能按行拼成同一受检者。
- 不生成标签。NLST 未来事件任务的阴性定义、删失与报告可获得时间尚未核实
  （见 `docs/RISK_TASK_NLST.md`），`--emit-labels` 只会明确拒绝，而不是填一个未经审核的
  结局定义，更不能把缺少诊断记录当作阴性。
- 字段语义未复核的列只作描述性输出（`role=descriptive`），不能直接进入模型特征。

用法与字段对照见 `docs/NLST_COHORT.md`。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from app.research.nlst import (
    EXPECTED_SHA256,
    KEYS,
    TABLES,
    download,
    missing,
    sha256,
    sources,
)

ADAPTER_VERSION = "nlst-cohort-v1"
COHORT_ID = "nlst-idc-v24"
DATASET_VERSION = "2011.02.03/05.12.21"
INDEX_STUDY_YEAR = 1
ROUNDS = (0, 1, 2)
OUTPUT_FILES = {
    "features": "features.parquet",
    "mapping": "field_mapping.json",
    "quality": "quality.json",
}
TASK_STATUS = "BLOCKED_PENDING_FOLLOWUP_DEFINITION"

Role = Literal["key", "feature", "descriptive"]
Semantics = Literal["reviewed", "structure_only", "not_reviewed"]


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """一列输出的来源、聚合方式、单位与人工核验状态。"""

    column: str
    table: str
    source: str
    aggregation: str
    unit: str
    semantics: Semantics
    role: Role
    note: str


FIELD_MAPPING: tuple[FieldMapping, ...] = (
    FieldMapping(
        column="subject_id",
        table="nlst_prsn",
        source="pid",
        aggregation=f"'{COHORT_ID}:' + pid；队列前缀防止跨队列按行合并",
        unit="identifier",
        semantics="reviewed",
        role="key",
        note="本地转换表的主键；质量摘要不输出任何受检者标识",
    ),
    FieldMapping(
        column="age",
        table="nlst_prsn",
        source="age",
        aggregation="直接取值，特殊缺失码转未知",
        unit="未核验",
        semantics="structure_only",
        role="descriptive",
        note="字段存在且为数值；单位与取值口径尚未在仓库内复核，故不进入模型",
    ),
    FieldMapping(
        column="gender",
        table="nlst_prsn",
        source="gender",
        aggregation="去空白，特殊缺失码转未知",
        unit="category",
        semantics="structure_only",
        role="descriptive",
        note="类别编码字典尚未复核，不能直接当连续量或有序类别",
    ),
    FieldMapping(
        column="race",
        table="nlst_prsn",
        source="race",
        aggregation="去空白，特殊缺失码转未知",
        unit="category",
        semantics="structure_only",
        role="descriptive",
        note="类别编码字典尚未复核",
    ),
    FieldMapping(
        column="cigsmok",
        table="nlst_prsn",
        source="cigsmok",
        aggregation="去空白，特殊缺失码转未知",
        unit="category",
        semantics="structure_only",
        role="descriptive",
        note="吸烟状态编码字典尚未复核",
    ),
    FieldMapping(
        column="index_scr_days",
        table="nlst_prsn",
        source="scr_days1",
        aggregation="直接取值，保留原始正负偏移",
        unit="days_since_randomization",
        semantics="reviewed",
        role="feature",
        note="字典已核验为距随机化天数；不等于报告可获得时间，不能编造公历日期",
    ),
    FieldMapping(
        column="ct_screen_rounds",
        table="nlst_screen",
        source="study_yr",
        aggregation="按 pid 统计 study_yr 去重个数",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="只表示该受检者在 CT 筛查表出现的轮次数，不代表完成了全部轮次",
    ),
    FieldMapping(
        column="screen_observed_t0",
        table="nlst_screen",
        source="study_yr",
        aggregation="该轮是否有筛查记录",
        unit="boolean",
        semantics="structure_only",
        role="descriptive",
        note="轮次未出现时后续轮次计数必须为未知，不能当作未见异常",
    ),
    FieldMapping(
        column="screen_observed_t1",
        table="nlst_screen",
        source="study_yr",
        aggregation="该轮是否有筛查记录",
        unit="boolean",
        semantics="structure_only",
        role="descriptive",
        note="索引轮次的观察标记",
    ),
    FieldMapping(
        column="screen_observed_t2",
        table="nlst_screen",
        source="study_yr",
        aggregation="该轮是否有筛查记录",
        unit="boolean",
        semantics="structure_only",
        role="descriptive",
        note="T2 属于索引日之后的信息，只作覆盖审计，不得作为索引特征",
    ),
    FieldMapping(
        column="ab_records_t0",
        table="nlst_ctab",
        source="(rows)",
        aggregation="study_yr==0 的异常记录行数；轮次未出现时为 NULL",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="轮次已出现但没有记录行是否等于未见异常尚未复核，二者不可混同",
    ),
    FieldMapping(
        column="ab_records_t1",
        table="nlst_ctab",
        source="(rows)",
        aggregation="study_yr==1 的异常记录行数；轮次未出现时为 NULL",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="索引轮次的异常记录规模；0 与未知必须区分",
    ),
    FieldMapping(
        column="ab_records_t2",
        table="nlst_ctab",
        source="(rows)",
        aggregation="study_yr==2 的异常记录行数；轮次未出现时为 NULL",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="T2 属于索引日之后的信息，只作覆盖审计，不得作为索引特征",
    ),
    FieldMapping(
        column="ab_number_t1_max",
        table="nlst_ctab",
        source="sct_ab_num",
        aggregation="study_yr==1 的最大编号",
        unit="index",
        semantics="reviewed",
        role="descriptive",
        note="字典已核验：编号在每位受检者每个研究年从 1 重新开始，只用于同轮关联",
    ),
    FieldMapping(
        column="ab_long_dia_t1_max",
        table="nlst_ctab",
        source="sct_long_dia",
        aggregation="study_yr==1 的最大长径",
        unit="未核验",
        semantics="structure_only",
        role="descriptive",
        note="源字段单位与测量口径尚未复核，不能按毫米解读或做临床阈值判断",
    ),
    FieldMapping(
        column="ab_perp_dia_t1_max",
        table="nlst_ctab",
        source="sct_perp_dia",
        aggregation="study_yr==1 的最大垂直径",
        unit="未核验",
        semantics="structure_only",
        role="descriptive",
        note="源字段单位与测量口径尚未复核",
    ),
    FieldMapping(
        column="ctabc_records_t1",
        table="nlst_ctabc",
        source="(rows)",
        aggregation="study_yr==1 的比较阅片记录行数",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="只统计记录规模；比较阅片内容本身的可获得时间未复核",
    ),
    FieldMapping(
        column="ctabc_unmatched_t1",
        table="nlst_ctabc",
        source="(rows)",
        aggregation="无法通过 pid、study_yr、sct_ab_num 连到同轮异常的记录行数",
        unit="count",
        semantics="structure_only",
        role="descriptive",
        note="必须标记和复核，不能静默当作已匹配或新发病灶",
    ),
)

# 索引时点不可用或属于结局的字段：不进入输出表，也不得成为特征。
EXCLUDED_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "nlst_prsn",
        (
            "candx_days",
            "canc_free_days",
            "cancyr",
            "can_scr",
            "canc_rpt_link",
            "lesionsize",
            "de_type",
            "de_grade",
            "de_stag",
            "de_stag_7thed",
        ),
        "诊断、分期与结局衍生字段；索引时点不可用，也不能作为标签替代品",
    ),
    (
        "nlst_canc",
        ("*",),
        "整表是肺癌诊断、病理与分期结局，任何列都不得作为索引特征",
    ),
    (
        "nlst_ctabc",
        (
            "sct_ab_code",
            "sct_ab_preexist",
            "sct_ab_gwth",
            "sct_ab_invg",
            "sct_ab_attn",
            "visible_days",
        ),
        "比较阅片描述与事后可见信息；资料可获得时间未复核，暂不进入特征",
    ),
    (
        "nlst_prsn",
        ("scr_res0", "scr_res1", "scr_res2", "scr_iso0", "scr_iso1", "scr_iso2"),
        "患者表筛查结果字段：公开子集没有 rndgroup，无法据以推定 CT 组，暂不复用",
    ),
    (
        "nlst_screen",
        ("ctdxqual",),
        "检查质量编码字典未复核，暂不复用",
    ),
)

MODELING_APPROVED_COLUMNS: tuple[str, ...] = tuple(
    mapping.column for mapping in FIELD_MAPPING if mapping.role == "feature"
)

LIMITATIONS: tuple[str, ...] = (
    "缺 fup_days 与死亡时间：阴性、删失与竞争事件定义未定，缺少诊断记录不等于观察完整且未发生。",
    "sct_ab_num 每位受检者每个研究年从 1 重新编号，只能同轮关联，不是跨年病灶身份。",
    "公开子集没有报告可获得时间；scr_days 是相对随机化天数，不能编造公历日期或假设当天可用。",
    "患者表人群大于 CT 筛查人群，且公开子集缺 rndgroup，不能仅凭患者表推定筛查分组。",
    "轮次未出现时该轮计数为 NULL；轮次已出现但无异常记录行是否等于未见异常尚未复核。",
    "字段语义未复核的列只作描述性输出，直接用于建模会引入未经审核的临床含义。",
    "患者级表覆盖不等于影像可下载覆盖，本次未下载任何 CT 影像。",
)


def label_refusal() -> str:
    """拒绝生成标签的固定说明。"""
    return (
        "refused: this adapter does not produce a label column. The NLST outcome task is "
        f"{TASK_STATUS}: the negative definition, censoring and report availability are "
        "unresolved (docs/RISK_TASK_NLST.md). Writing a label here would invent a reviewed "
        "outcome definition and could turn unobserved participants into negatives."
    )


def emit_labels(*_: object) -> None:
    """占位入口：始终拒绝，避免用编造标签绕过任务检查。"""
    raise ValueError(label_refusal())


def excluded_conflicts() -> list[str]:
    """返回字段映射与禁用字段的冲突；应为空列表。"""
    excluded = {
        (table, column)
        for table, columns, _ in EXCLUDED_FIELDS
        for column in columns
    }
    return [
        f"{mapping.table}.{mapping.source} -> {mapping.column}"
        for mapping in FIELD_MAPPING
        if (mapping.table, "*") in excluded or (mapping.table, mapping.source) in excluded
    ]


def _numeric(series: pd.Series) -> pd.Series:
    """按 NLST 语义处理特殊缺失码后再转数值；不把 `.N` 等填成 0。"""
    return pd.to_numeric(series.where(~missing(series)), errors="coerce")


def _text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().where(~missing(series))


def load_snapshot(directory: Path, *, verify: bool = True) -> dict[str, pd.DataFrame]:
    """读取固定版本快照；正式入口始终校验哈希与内部数据版本。"""
    frames = {name: pd.read_parquet(directory / f"{name}.parquet") for name in TABLES}
    dictionary = pd.read_parquet(directory / "clinical_index.parquet")
    if verify:
        for name in (*TABLES, "clinical_index"):
            actual = sha256(directory / f"{name}.parquet")
            if actual != EXPECTED_SHA256[name]:
                raise ValueError(
                    f"snapshot hash differs for {name}; download the reviewed version instead"
                )
    versions = {
        str(value)
        for name, frame in frames.items()
        if "dataset_version" in frame
        for value in frame.dataset_version.dropna().unique()
    }
    if versions != {DATASET_VERSION}:
        raise ValueError(f"unexpected dataset versions: {sorted(versions)}; review before use")
    if dictionary.empty:
        raise ValueError("clinical dictionary is empty")
    return frames


def _round_presence(screen: pd.DataFrame) -> dict[int, pd.Series]:
    return {
        year: screen[screen.study_yr == year].groupby("pid").size().gt(0).rename(f"observed_{year}")
        for year in ROUNDS
    }


def _counts_by_round(abnormality: pd.DataFrame) -> pd.DataFrame:
    records = (
        abnormality.groupby(["pid", "study_yr"]).size().unstack(fill_value=0).reindex(
            columns=list(ROUNDS), fill_value=0
        )
    )
    return records


def build(directory: Path, *, verify: bool = True) -> tuple[pd.DataFrame, dict]:
    """返回受检者级特征表与质量摘要；不生成标签。"""
    conflicts = excluded_conflicts()
    if conflicts:
        raise ValueError(f"field mapping conflicts with excluded fields: {conflicts}")
    frames = load_snapshot(directory, verify=verify)
    people = frames["nlst_prsn"].assign(pid=lambda table: table.pid.astype(str))
    screen = frames["nlst_screen"].assign(pid=lambda table: table.pid.astype(str))
    abnormality = frames["nlst_ctab"].assign(pid=lambda table: table.pid.astype(str))
    comparison = frames["nlst_ctabc"].assign(pid=lambda table: table.pid.astype(str))
    if people.pid.duplicated().any():
        raise ValueError("participant table must have one row per participant")

    frame = pd.DataFrame(
        {
            "pid": people.pid.astype(str),
            "age": _numeric(people.age),
            "gender": _text(people.gender),
            "race": _text(people.race),
            "cigsmok": _text(people.cigsmok),
            "index_scr_days": _numeric(people.scr_days1),
        }
    )
    frame.insert(0, "subject_id", COHORT_ID + ":" + frame.pid)

    presence = _round_presence(screen)
    rounds = screen.groupby("pid").study_yr.nunique()
    frame["ct_screen_rounds"] = frame.pid.map(rounds).fillna(0).astype("int64")
    records = _counts_by_round(abnormality)
    for year in ROUNDS:
        observed = frame.pid.map(presence[year]).eq(True)
        frame[f"screen_observed_t{year}"] = observed
        counts = frame.pid.map(records[year]).fillna(0)
        frame[f"ab_records_t{year}"] = counts.where(observed)

    index_round = abnormality[abnormality.study_yr == INDEX_STUDY_YEAR].copy()
    index_round["ab_number"] = _numeric(index_round.sct_ab_num)
    index_round["long_dia"] = _numeric(index_round.sct_long_dia)
    index_round["perp_dia"] = _numeric(index_round.sct_perp_dia)
    per_patient = index_round.groupby("pid")[["ab_number", "long_dia", "perp_dia"]].max()
    per_patient.columns = ["ab_number_t1_max", "ab_long_dia_t1_max", "ab_perp_dia_t1_max"]
    for column in per_patient.columns:
        frame[column] = frame.pid.map(per_patient[column])

    index_comparison = comparison[comparison.study_yr == INDEX_STUDY_YEAR]
    keys = KEYS["nlst_ctabc"]
    linked = index_comparison.merge(
        index_round[keys].drop_duplicates(), on=keys, how="left", indicator=True
    )
    frame["ctabc_records_t1"] = frame.pid.map(index_comparison.groupby("pid").size())
    frame["ctabc_unmatched_t1"] = frame.pid.map(
        linked[linked["_merge"] == "left_only"].groupby("pid").size()
    )

    frame = frame.drop(columns=["pid"]).sort_values("subject_id").reset_index(drop=True)
    frame = frame[[mapping.column for mapping in FIELD_MAPPING]]
    return frame, _quality(frame, frames, verified=verify)


def _quality(frame: pd.DataFrame, frames: dict[str, pd.DataFrame], *, verified: bool) -> dict:
    columns = []
    for mapping in FIELD_MAPPING:
        series = frame[mapping.column]
        columns.append(
            {
                **asdict(mapping),
                "non_null": int(series.notna().sum()),
                "unknown": int(series.isna().sum()),
                "distinct_non_null": int(series.nunique(dropna=True)),
            }
        )
    return {
        "adapter_version": ADAPTER_VERSION,
        "cohort_id": COHORT_ID,
        "dataset_version": DATASET_VERSION,
        "index_study_year": INDEX_STUDY_YEAR,
        "built_at": datetime.now(UTC).isoformat(),
        "rows": int(len(frame)),
        "subjects": int(frame.subject_id.nunique()),
        "subject_id_policy": f"namespaced with '{COHORT_ID}:' so cohorts cannot be stacked by row",
        "files": {
            name: {
                "url": url,
                "reference_sha256": EXPECTED_SHA256[name],
                "matches_reference_snapshot": verified,
            }
            for name, url in sources().items()
        },
        "columns": columns,
        "coverage": {
            "screen_observed": {
                f"t{year}": int(frame[f"screen_observed_t{year}"].sum()) for year in ROUNDS
            },
            "index_scr_days_present": int(frame.index_scr_days.notna().sum()),
            "ct_screen_rounds": {
                str(key): int(value)
                for key, value in frame.ct_screen_rounds.value_counts().sort_index().items()
            },
            "ab_records_present": {
                f"t{year}": int(frame[f"ab_records_t{year}"].notna().sum()) for year in ROUNDS
            },
            "ctabc_records_t1_present": int(frame.ctabc_records_t1.notna().sum()),
            "ctabc_unmatched_t1_total": int(frame.ctabc_unmatched_t1.fillna(0).sum()),
        },
        "source_tables": {
            name: {"rows": int(len(table)), "patients": int(table.pid.nunique())}
            for name, table in frames.items()
            if "pid" in table
        },
        "modeling_approved_columns": list(MODELING_APPROVED_COLUMNS),
        "excluded_fields": [
            {"table": table, "columns": list(columns), "reason": reason}
            for table, columns, reason in EXCLUDED_FIELDS
        ],
        "label_column": None,
        "task_status": TASK_STATUS,
        "label_refusal": label_refusal(),
        "limitations": list(LIMITATIONS),
        "privacy": "aggregate counts only; no subject identifiers and no per-person rows",
        "clinical_use": False,
    }


def write(directory: Path, output: Path, *, verify: bool = True) -> dict:
    """写出特征表、字段映射与质量摘要；已存在的输出目录拒绝覆盖。"""
    frame, quality = build(directory, verify=verify)
    features = output / OUTPUT_FILES["features"]
    if features.exists():
        raise ValueError("output already exists; preserve the previous cohort and use a new path")
    output.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(features, index=False)
    quality["features_sha256"] = sha256(features)
    (output / OUTPUT_FILES["mapping"]).write_text(
        json.dumps(mapping_document(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / OUTPUT_FILES["quality"]).write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return quality


def mapping_document() -> dict:
    """可直接提交的字段映射文档（无个体信息）。"""
    return {
        "adapter_version": ADAPTER_VERSION,
        "cohort_id": COHORT_ID,
        "dataset_version": DATASET_VERSION,
        "index_study_year": INDEX_STUDY_YEAR,
        "columns": [asdict(mapping) for mapping in FIELD_MAPPING],
        "modeling_approved_columns": list(MODELING_APPROVED_COLUMNS),
        "excluded_fields": [
            {"table": table, "columns": list(columns), "reason": reason}
            for table, columns, reason in EXCLUDED_FIELDS
        ],
        "privacy": "no subject identifiers",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--emit-labels", action="store_true")
    args = parser.parse_args()
    if args.emit_labels:
        raise SystemExit(label_refusal())
    if args.download:
        download(args.directory)
    quality = write(args.directory, args.output)
    print(
        json.dumps(
            {
                "rows": quality["rows"],
                "subjects": quality["subjects"],
                "modeling_approved_columns": quality["modeling_approved_columns"],
                "task_status": quality["task_status"],
                "features_sha256": quality["features_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
