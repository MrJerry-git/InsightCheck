"""H08 真实模型问答运行记录脚本。

用项目自身的 OpenAICompatibleLLMProvider + QAService 走一次真实模型调用，
把「模型确实被接入且在跑」的证据落到 docs/llm-qa-run-record.json：
请求的上下文绑定、模型回答原文、引用守卫判定结果、耗时与模型标识。

凭据只从环境变量读取，不落盘、不进 Git。未配置凭据时脚本以
`skipped` 结束并写明原因，不伪造记录。

用法：
    python scripts/llm_qa_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.versioning import PipelineVersions  # noqa: E402
from app.llm.openai_compat import (  # noqa: E402
    LLMProviderError,
    OpenAICompatConfig,
    OpenAICompatibleLLMProvider,
)
from app.llm.qa import EvidenceItem, QAAnswer, QAContext, QAService  # noqa: E402
from app.llm.templated import TemplatedLLMProvider  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "llm-qa-run-record.json"

# 编号故意不与输入顺序一致，用来验证绑定关系没有按编号排序错位
EVIDENCE = (
    EvidenceItem(ref_id="EV-9", text="空腹血糖 7.2 mmol/L（偏高）", record_ref="rec-labs-2026-06-01"),
    EvidenceItem(ref_id="EV-2", text="尿酸 480 μmol/L（偏高）", record_ref="rec-labs-2026-06-01"),
    EvidenceItem(ref_id="EV-5", text="体质指数 27.4 kg/m2（超重）", record_ref="rec-body-2026-06-01"),
)

QUESTION = (
    "请只依据上面给出的证据条目，说明我这次体检有哪些需要复查的异常，"
    "每条结论后面用 [EV:编号] 标出你依据的证据编号。"
)


def _config_from_env() -> OpenAICompatConfig:
    """从环境变量读出 OpenAI 兼容接入点配置。"""
    base_url = (
        os.environ.get("IC_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL", "")
    ).strip()
    api_key = (
        os.environ.get("IC_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    ).strip()
    model = (
        os.environ.get("IC_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("ANTHROPIC_MODEL", "")
    ).strip()
    return OpenAICompatConfig(base_url=base_url, api_key=api_key, model=model)


def _answer_record(answer: QAAnswer) -> dict:
    return {
        "question": answer.question,
        "content": answer.content,
        "mode": answer.mode,
        "llm_model": answer.llm_model,
        "trace_id": answer.trace_id,
        "citations": list(answer.citations),
        "citation_records": [list(pair) for pair in answer.citation_records],
        "invalid_citations_removed": list(answer.invalid_citations_removed),
    }


def main() -> int:
    config = _config_from_env()
    provider = OpenAICompatibleLLMProvider(config)
    context = QAContext(
        patient_ref="P-SMOKE-001",
        findings=EVIDENCE,
        plan_snapshot_ref="snapshot-2026-06",
        plan_summary="标准档方案 v1（含血脂四项、甲状腺超声）",
        versions=PipelineVersions(),
    )

    record: dict = {
        "task": "H08 结构化解释与真实语言模型问答服务",
        "owner": "王宏锦（WHJ-2007）",
        "service_version": QAService.VERSION,
        "evidence_input": [
            {"ref_id": i.ref_id, "text": i.text, "record_ref": i.record_ref}
            for i in EVIDENCE
        ],
        "question": QUESTION,
        "endpoint_configured": provider.is_available(),
        "base_url_scheme": config.base_url.split("://", 1)[0] if config.base_url else None,
        "model": config.model,
    }

    # 模板模式基线：始终可跑，用于对照
    template_service = QAService(TemplatedLLMProvider())
    template_answer = asyncio.run(template_service.answer(QUESTION, context))
    record["template_mode"] = _answer_record(template_answer)

    if not provider.is_available():
        record["model_mode"] = {
            "status": "skipped",
            "reason": "未配置模型接入点（base_url/api_key/model 任一为空）；不伪造调用记录",
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"skipped: {OUT_PATH}")
        return 0

    service = QAService(provider)
    started = time.perf_counter()
    try:
        answer = asyncio.run(service.answer(QUESTION, context))
    except LLMProviderError as exc:
        elapsed = time.perf_counter() - started
        record["model_mode"] = {
            "status": "error",
            "reason": str(exc),
            "elapsed_seconds": round(elapsed, 3),
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"error: {exc}")
        return 1
    elapsed = time.perf_counter() - started

    record["model_mode"] = {
        "status": "ok",
        "elapsed_seconds": round(elapsed, 3),
        **_answer_record(answer),
    }
    record["guard_check"] = {
        "cited": list(answer.citations),
        "invalid_removed": list(answer.invalid_citations_removed),
        "binding_ok": all(
            ref in {i.ref_id for i in EVIDENCE} for ref in answer.citations
        ),
        "record_refs_resolved": [
            {"ref_id": ref, "record_ref": rec} for ref, rec in answer.citation_records
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"ok: {OUT_PATH}")
    print(f"mode={answer.mode} model={answer.llm_model} elapsed={elapsed:.2f}s")
    print(f"citations={answer.citations} invalid={answer.invalid_citations_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
