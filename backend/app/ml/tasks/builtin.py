"""首批内置模型任务登记。

对齐 docs/RISK_TASK_NLST.md（真实风险任务尚未冻结）与 README（DeepFM
合成演示运行、真实制品未接入）；合作方队列任务对应九华数据接入准备
（H11）。全部任务当前显式不可用，不产生疾病概率。
"""

from __future__ import annotations

from app.ml.risk.contracts import RiskUnavailableReason
from app.ml.tasks.registry import ModelTaskRegistration, TaskKind, TaskStatus

BUILTIN_TASK_REGISTRATIONS: tuple[ModelTaskRegistration, ...] = (
    ModelTaskRegistration(
        task_id="lung-cancer-future-event-nlst",
        task_kind=TaskKind.RISK_MODEL,
        disease_goal="肺癌（未来事件预测）",
        population="NLST 入组标准人群；确切人群定义以任务卡冻结版为准",
        input_features=(
            "age",
            "smoking_history",
            "ct_screening_findings",
            "（特征清单以任务卡冻结版为准，待核验）",
        ),
        time_horizon="6-year（NLST 试验窗口，待冻结确认）",
        output_spec="未来肺癌事件概率（0-1）；未接入前不产生任何概率",
        data_source="public_observational",
        source_version="risk-task-nlst-v0（未冻结）",
        status=TaskStatus.AWAITING_DATA,
        unavailable_reason=RiskUnavailableReason.REVIEW_NOT_FROZEN,
        source_doc="docs/RISK_TASK_NLST.md",
    ),
    ModelTaskRegistration(
        task_id="exam-item-matching-deepfm",
        task_kind=TaskKind.RANKING_MODEL,
        disease_goal="非疾病目标：受检者×检查项目匹配分（不是疾病概率）",
        population="合成演示记录（is_demo=true，年龄 18-84）；真实人群未评估",
        input_features=(
            "patient_features（app/features/feature_pipeline）",
            "exam_item_codes",
        ),
        time_horizon="不适用（匹配任务）",
        output_spec="Patient×ExamItem 匹配分数；必须经规则引擎约束，不是最终方案",
        data_source="synthetic",
        source_version="workflow-synthetic-v1（演示）/ 真实制品未接入",
        status=TaskStatus.IN_DEVELOPMENT,
        unavailable_reason=RiskUnavailableReason.ARTIFACT_MISSING,
        source_doc="RECOMMENDATION_MODEL.md",
    ),
    ModelTaskRegistration(
        task_id="partner-cohort-risk-models",
        task_kind=TaskKind.RISK_MODEL,
        disease_goal="合作方队列疾病风险（病种清单待数据到达后与任务卡共同确定）",
        population="合作方体检人群；人群描述待数据质量审计后登记",
        input_features=("(待数据到达后按特征接口登记，)",),
        time_horizon="待任务卡确定",
        output_spec="疾病风险概率（0-1）；未接入前不产生任何概率",
        data_source="partner_observational",
        source_version="未冻结（数据未取得）",
        status=TaskStatus.AWAITING_DATA,
        unavailable_reason=RiskUnavailableReason.REVIEW_NOT_FROZEN,
        source_doc="docs/DATASET_PLAN.md",
    ),
)
