"""T09：报告文档组装、中文 PDF 渲染与 JSON 证据导出。

内容全部取自已保存的方案修订快照与对应的分析运行，不重新计算费用或规则；
未知价格、未接入模型与未审核规则都会原样出现在报告里。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisRun,
    LabMetric,
    MedicalRule,
    Patient,
    Plan,
    ReportEvidenceSnapshot,
)
from app.services.reporting.pdf import SimpleChinesePdf

REPORT_VERSION = "report-v1"
EVIDENCE_SNAPSHOT_VERSION = "report-evidence-v1"


class ReportError(Exception):
    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def price_text(price: dict[str, Any]) -> str:
    if price.get("amount_cents") is None:
        return "价格未知（未纳入总价）"
    amount = price["amount_cents"] / 100
    currency = price.get("currency") or "CNY"
    tag = "演示价" if price.get("is_demo_price") else "价格"
    source = price.get("source") or "来源未记录"
    return f"{tag} {amount:.2f} {currency}（来源：{source}）"


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def document(
        self, plan: Plan, *, revision_no: int | None = None
    ) -> dict[str, Any]:
        snapshot = self._snapshot(plan, revision_no)
        run = self.db.get(AnalysisRun, snapshot.get("analysis_run_id"))
        patient = self.db.get(Patient, plan.patient_id)
        if patient is None:
            raise ReportError("档案不存在", status_code=404)
        findings = {item["finding_code"]: item for item in (run.findings if run else [])}
        evidence = self._frozen_evidence(plan, revision_no, snapshot, findings)
        return {
            "report_version": REPORT_VERSION,
            "plan_id": plan.id,
            "patient_id": patient.id,
            "patient_code": patient.anonymous_code,
            "revision_no": self._revision_no(plan, revision_no),
            "plan_status": plan.status.value,
            "as_of_date": snapshot.get("as_of_date"),
            "generated_at": datetime.now(UTC).isoformat(),
            "price_catalog_version": snapshot.get("price_catalog_version"),
            "rule_set_versions": snapshot.get("rule_set_versions", []),
            "analysis": {
                "run_id": snapshot.get("analysis_run_id"),
                "input_fingerprint": snapshot.get("analysis_fingerprint"),
                "provider_version": run.provider_version if run else None,
                "finding_map_version": run.finding_map_version if run else None,
                "model_status": "未评估：尚无经验证的适用模型",
            },
            "tiers": snapshot.get("tiers_result", []),
            "notes": snapshot.get("notes", []),
            "disclosures": snapshot.get("disclosures", []),
            "manual_exclusions": snapshot.get("manual_exclusions", {}),
            "evidence": evidence,
        }

    def _snapshot(self, plan: Plan, revision_no: int | None) -> dict[str, Any]:
        if revision_no is None:
            return plan.current_snapshot or {}
        from app.models import PlanRevision

        revision = (
            self.db.query(PlanRevision)
            .filter(PlanRevision.plan_id == plan.id, PlanRevision.revision_no == revision_no)
            .one_or_none()
        )
        if revision is None:
            raise ReportError("方案修订不存在", status_code=404)
        return revision.snapshot

    def _revision_no(self, plan: Plan, revision_no: int | None) -> int:
        return plan.revision_no if revision_no is None else revision_no

    def _frozen_evidence(
        self,
        plan: Plan,
        revision_no: int | None,
        snapshot: dict[str, Any],
        findings: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """读取已冻结的证据快照；首次生成报告时冻结当时依据。

        报告一旦生成，之后修改/删除记录或更新规则都不再改变它的依据，
        历史问答同样读取这份快照，保证"报告与依据"版本一致。
        """

        number = self._revision_no(plan, revision_no)
        stored = self.db.scalar(
            select(ReportEvidenceSnapshot).where(
                ReportEvidenceSnapshot.plan_id == plan.id,
                ReportEvidenceSnapshot.revision_no == number,
            )
        )
        if stored is not None:
            return stored.evidence
        payload = {
            **self._evidence(snapshot, findings),
            "snapshot_version": EVIDENCE_SNAPSHOT_VERSION,
            "captured_at": datetime.now(UTC).isoformat(),
        }
        self.db.add(
            ReportEvidenceSnapshot(
                plan_id=plan.id,
                revision_no=number,
                evidence=payload,
                content_sha256=sha256(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
        )
        self.db.commit()
        return payload

    def _evidence(
        self, snapshot: dict[str, Any], findings: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        record_ids: set[str] = set()
        for tier in snapshot.get("tiers_result", []):
            for item in tier.get("items", []):
                record_ids.update(item.get("rule_evidence_refs", []))
        records = []
        if record_ids:
            rows = self.db.query(LabMetric).filter(LabMetric.id.in_(record_ids)).all()
            records = [
                {
                    "ref": row.id,
                    "type": "lab_metric",
                    "metric_code": row.metric_code,
                    "original_value": row.original_value,
                    "unit": row.standard_unit or row.original_unit,
                    "source_kind": row.source_kind,
                    "source_ref": row.source_ref,
                }
                for row in rows
            ]
        rule_codes = {
            decision["rule_code"]
            for tier in snapshot.get("tiers_result", [])
            for item in tier.get("items", [])
            for decision in item.get("applied_rules", [])
            if isinstance(decision, dict) and decision.get("rule_code")
        }
        rules = []
        if rule_codes:
            rows = self.db.query(MedicalRule).filter(MedicalRule.rule_code.in_(rule_codes)).all()
            rules = [
                {
                    "rule_code": row.rule_code,
                    "version": row.version,
                    "source": row.source,
                    "enabled": row.enabled,
                }
                for row in rows
            ]
        prices = [
            {
                "exam_item_code": item["code"],
                "amount_cents": item["price"]["amount_cents"],
                "currency": item["price"].get("currency"),
                "source": item["price"].get("source"),
                "source_url": item["price"].get("source_url"),
                "is_demo_price": item["price"].get("is_demo_price"),
                "catalog_version": item["price"].get("catalog_version"),
            }
            for tier in snapshot.get("tiers_result", [])
            for item in tier.get("items", [])
        ]
        return {
            "findings": list(findings.values()),
            "records": records,
            "rules": rules,
            "prices": prices,
            "price_catalog_version": snapshot.get("price_catalog_version"),
            "rule_set_versions": snapshot.get("rule_set_versions", []),
        }

    # ---- PDF --------------------------------------------------------------
    def render_pdf(self, document: dict[str, Any]) -> bytes:
        pdf = SimpleChinesePdf()
        pdf.add_title(f"循影定检 · 体检方案报告（{document['patient_code']}）")
        pdf.add_line(
            f"方案编号：{document['plan_id']}　版本：第 {document['revision_no']} 版　"
            f"状态：{document['plan_status']}"
        )
        pdf.add_line(f"分析日期：{document['as_of_date']}　生成时间：{document['generated_at']}")
        pdf.add_line(f"规则版本：{', '.join(document['rule_set_versions']) or '未配置'}")
        pdf.add_line(f"价格目录版本：{document['price_catalog_version'] or '未接入'}")
        pdf.add_line(f"模型状态：{document['analysis']['model_status']}")
        pdf.add_spacer()

        for tier in document["tiers"]:
            cost = tier.get("cost_summary", {})
            pdf.add_title(f"【{tier['tier']}】{tier.get('selection_note', '')}")
            total = cost.get("known_total_cents")
            total_text = "未知" if total is None else f"{total / 100:.2f}"
            pdf.add_line(
                f"已知费用合计：{total_text} {cost.get('currency') or ''}"
                f"（{'完整' if cost.get('is_complete') else '不完整'}）"
            )
            pdf.add_line(f"预算状态：{tier.get('budget_status')}　说明：{tier.get('budget_note')}")
            for conflict in tier.get("conflicts", []):
                pdf.add_line(f"冲突：{conflict.get('message')}")
            for item in tier.get("items", []):
                pdf.add_line(
                    f"· {item['name']}（{item['code']}）规则：{item['rule_status']}"
                    f"{'，需人工复核' if item.get('requires_review') else ''}"
                )
                pdf.add_line(f"　{price_text(item['price'])}")
                pdf.add_line(f"　纳入理由：{item.get('selection_reason', '')}")
            if not tier.get("items"):
                pdf.add_line("　该档位没有可纳入项目。")
            for excluded in tier.get("excluded", [])[:10]:
                pdf.add_line(f"　排除：{excluded['name']}（{excluded['reason']}）")
            pdf.add_spacer(8)

        pdf.add_title("缺失信息与限制")
        for note in document["notes"]:
            pdf.add_line(f"· {note}")
        pdf.add_title("免责声明")
        for line in document["disclosures"]:
            pdf.add_line(f"· {line}")
        return pdf.to_bytes()

    def digest(self, payload: bytes) -> str:
        return sha256(payload).hexdigest()
