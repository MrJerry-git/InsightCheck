"""T10：依据问答服务。

* 回答只使用当前已确认资料、分析结果与方案快照，并附可追溯引用。
* 语言模型可选：未配置时使用结构化本地回答；配置后调用 OpenAI 兼容接口，
  但回答里出现的引用必须来自服务端提供的证据集合，否则退回结构化回答。
* 问答不修改方案：本服务只写问答记录，不触碰方案、规则或价格。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Patient, Plan, QaRecord
from app.services.reporting.reports import ReportService

MAX_QUESTION_CHARS = 1000
PROVIDER_STRUCTURED = "structured-local-v1"


class QaError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def citation(kind: str, ref: str, label: str) -> dict[str, str]:
    return {"type": kind, "ref": ref, "label": label}


class QaService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 上下文 -----------------------------------------------------------
    def context(
        self, patient: Patient, plan: Plan | None
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        payload: dict[str, Any] = {
            "patient_code": patient.anonymous_code,
            "as_of_date": None,
            "tiers": [],
            "notes": [],
            "findings": [],
            "model_status": "未评估：尚无经验证的适用模型",
            "provider_version": None,
        }
        citations: list[dict[str, str]] = []
        if plan is None:
            return payload, citations

        document = ReportService(self.db).document(plan)
        payload.update(
            {
                "plan_id": plan.id,
                "plan_status": document["plan_status"],
                "revision_no": document["revision_no"],
                "as_of_date": document["as_of_date"],
                "tiers": [
                    {
                        "tier": tier["tier"],
                        "budget_status": tier["budget_status"],
                        "budget_note": tier["budget_note"],
                        "cost_summary": tier["cost_summary"],
                        "items": [
                            {
                                "code": item["code"],
                                "name": item["name"],
                                "rule_status": item["rule_status"],
                                "requires_review": item["requires_review"],
                                "price": item["price"],
                                "selection_reason": item["selection_reason"],
                            }
                            for item in tier["items"]
                        ],
                        "excluded": tier.get("excluded", []),
                        "conflicts": tier.get("conflicts", []),
                    }
                    for tier in document["tiers"]
                ],
                "notes": document["notes"],
                "findings": document["evidence"]["findings"],
                "provider_version": document["analysis"]["provider_version"],
            }
        )
        citations.append(
            citation("plan_revision", f"{plan.id}@{document['revision_no']}", "方案修订快照")
        )
        if document["analysis"]["run_id"]:
            citations.append(
                citation("analysis_run", str(document["analysis"]["run_id"]), "分析结果")
            )
        for price in document["evidence"]["prices"][:20]:
            if price.get("source"):
                citations.append(
                    citation(
                        "price",
                        price["source_url"] or price["source"],
                        f"{price['exam_item_code']} 价格来源",
                    )
                )
        for rule in document["evidence"]["rules"][:20]:
            citations.append(
                citation(
                    "rule",
                    f"{rule['rule_code']}@{rule['version']}",
                    f"规则依据：{rule['source']}",
                )
            )
        return payload, citations

    # ---- 回答 -------------------------------------------------------------
    def ask(
        self,
        *,
        patient: Patient,
        question: str,
        plan: Plan | None = None,
        request_id: str | None = None,
        actor_account_id: str | None = None,
    ) -> dict[str, Any]:
        text = question.strip()
        if not text:
            raise QaError("问题不能为空")
        if len(text) > MAX_QUESTION_CHARS:
            raise QaError(f"问题最多 {MAX_QUESTION_CHARS} 字")
        if request_id:
            existing = (
                self.db.query(QaRecord).filter(QaRecord.request_id == request_id).one_or_none()
            )
            if existing is not None:
                return self._serialize(existing)

        context, citations = self.context(patient, plan)
        allowed = {item["ref"] for item in citations}
        answer, used, provider, model_status = self._answer(text, context, citations, allowed)
        record = QaRecord(
            patient_id=patient.id,
            plan_id=None if plan is None else plan.id,
            plan_revision_no=context.get("revision_no"),
            question=text,
            answer=answer,
            citations=used,
            provider=provider,
            model_status=model_status,
            evidence_refs=[item["ref"] for item in used],
            request_id=request_id,
            created_by_account_id=actor_account_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._serialize(record)

    def _answer(
        self,
        question: str,
        context: dict[str, Any],
        citations: list[dict[str, str]],
        allowed: set[str],
    ) -> tuple[str, list[dict[str, str]], str, str]:
        settings = get_settings()
        if settings.llm_provider:
            try:
                answer, used = self._model_answer(question, context, citations, settings)
                if answer and used and {item["ref"] for item in used} <= allowed:
                    return (
                        answer,
                        used,
                        f"{settings.llm_provider}:{settings.llm_model}",
                        context["model_status"],
                    )
            except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError):
                pass  # 模型不可用或引用不合规时退回结构化回答，不编造内容。
        return (
            *self._structured_answer(question, context, citations),
            PROVIDER_STRUCTURED,
            context["model_status"],
        )

    def _structured_answer(
        self, question: str, context: dict[str, Any], citations: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, str]]]:
        by_type: dict[str, list[dict[str, str]]] = {}
        for item in citations:
            by_type.setdefault(item["type"], []).append(item)

        def pick(*kinds: str) -> list[dict[str, str]]:
            picked: list[dict[str, str]] = []
            for kind in kinds:
                picked.extend(by_type.get(kind, []))
            return picked[:8]

        tiers = context.get("tiers") or []
        if any(word in question for word in ("价格", "费用", "多少钱", "预算", "便宜")):
            if not tiers:
                return "当前没有方案，无法计算费用。请先生成方案。", []
            lines = []
            for tier in tiers:
                cost = tier["cost_summary"]
                total = cost.get("known_total_cents")
                total_text = (
                    "未知" if total is None else f"{total / 100:.2f} {cost.get('currency') or ''}"
                )
                lines.append(
                    f"{tier['tier']} 档：已知费用合计 {total_text}"
                    f"（{'完整' if cost.get('is_complete') else '不完整，有未知价格'}）；"
                    f"预算状态 {tier['budget_status']}。{tier['budget_note']}"
                )
            lines.append("未知价格不计入合计，也不冒充完整总价。")
            return "\n".join(lines), pick("price", "plan_revision")

        if any(word in question for word in ("风险", "概率", "模型", "预测")):
            return (
                f"{context['model_status']}。当前不提供疾病概率，也不把规则关联当作确诊；"
                "规则结论只作为待复核的工程草稿。",
                pick("plan_revision", "analysis_run"),
            )

        if any(word in question for word in ("依据", "来源", "为什么", "规则", "出处")):
            lines = ["方案结论依据："]
            for tier in tiers:
                for item in tier["items"][:6]:
                    lines.append(
                        f"· {item['name']}：规则状态 {item['rule_status']}；"
                        f"纳入理由 {item['selection_reason']}"
                    )
            if len(lines) == 1:
                lines.append("当前没有可解释的方案项目。")
            return "\n".join(lines), pick("rule", "plan_revision", "price")

        if any(word in question for word in ("多久", "时间", "随访", "什么时候")):
            scheduled = [
                item
                for tier in tiers
                for item in tier["items"]
                if "随访" in item["selection_reason"] or "复查" in item["selection_reason"]
            ]
            if not scheduled:
                return "规则没有给出确定时间；未定的项目不会由模型编造日期。", pick("plan_revision")
            lines = ["需要随访/复查的项目（时间以医生安排为准）："]
            lines.extend(f"· {item['name']}：{item['selection_reason']}" for item in scheduled[:8])
            return "\n".join(lines), pick("plan_revision", "rule")

        if any(word in question for word in ("项目", "做什么", "检查什么", "增加", "删除")):
            lines = []
            for tier in tiers:
                names = "、".join(item["name"] for item in tier["items"][:8]) or "无"
                lines.append(f"{tier['tier']} 档：{names}")
            if not lines:
                return "当前还没有保存的方案。", []
            lines.append("如需增删项目，请在方案编辑中填写修改原因，由后端复算。")
            return "\n".join(lines), pick("plan_revision")

        if any(word in question for word in ("数据", "记录", "来源", "依据资料")):
            findings = context.get("findings") or []
            lines = [f"已确认资料中的发现共 {len(findings)} 条："]
            lines.extend(
                f"· {item['name']}（{item.get('observed_value') or '未记录'}）"
                for item in findings[:8]
            )
            if not findings:
                lines.append("· 暂无异常发现；缺失信息见方案说明。")
            return "\n".join(lines), pick("analysis_run", "plan_revision")

        summary = [
            f"档案 {context['patient_code']}（分析日期 {context.get('as_of_date')}）",
            f"方案版本：第 {context.get('revision_no')} 版，状态 {context.get('plan_status')}",
        ]
        for tier in tiers:
            summary.append(
                f"{tier['tier']} 档 {len(tier['items'])} 项，预算状态 {tier['budget_status']}"
            )
        summary.append("可以询问费用、依据、随访时间或具体检查项目。")
        return "\n".join(summary), pick("plan_revision")

    def _model_answer(
        self,
        question: str,
        context: dict[str, Any],
        citations: list[dict[str, str]],
        settings: Any,
    ) -> tuple[str, list[dict[str, str]]]:
        """调用 OpenAI 兼容接口；要求模型返回 JSON，引用必须来自给定集合。"""

        base = (settings.llm_base_url or "").rstrip("/")
        if not base:
            raise ValueError("no base url")
        payload = {
            "model": settings.llm_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是体检方案说明助手。只能使用给出的结构化事实回答，"
                        "不得编造疾病概率、日期或新结论。返回 JSON："
                        '{"answer": "...", "citations": [{"ref": "..."}]}，'
                        "citations 只能引用 facts 里已有的 ref。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "facts": context,
                            "available_citations": citations,
                            "question": question,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        with httpx.Client(timeout=settings.llm_timeout, trust_env=False) as client:
            response = client.post(f"{base}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        answer = str(parsed.get("answer", "")).strip()
        refs = [str(item.get("ref")) for item in parsed.get("citations", []) if item.get("ref")]
        lookup = {item["ref"]: item for item in citations}
        used = [lookup[ref] for ref in refs if ref in lookup]
        return answer, used

    def _serialize(self, record: QaRecord) -> dict[str, Any]:
        return {
            "qa_id": record.id,
            "patient_id": record.patient_id,
            "plan_id": record.plan_id,
            "plan_revision_no": record.plan_revision_no,
            "question": record.question,
            "answer": record.answer,
            "citations": record.citations or [],
            "provider": record.provider,
            "model_status": record.model_status,
            "created_at": record.created_at,
            "can_modify_plan": False,
        }
