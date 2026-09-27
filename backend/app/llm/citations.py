"""共享引用校验链路（H08 / T10 统一）。

背景：H08（本分支）与 T10（`feat/report-qa` 的 `app/services/qa.py`）各自
实现了一套问答。两套的引用**表示**不同：

- H08：模型回答正文里写 `[EV:<ref_id>]`，服务端用正则提回并核对。
- T10：要求模型返回 JSON，引用放在 `citations: [{"ref": ...}]` 字段里。

但两者要校验的是**同一件事**：回答引用的编号必须来自服务端提供的证据集合，
且引用与所引内容不能错位。各写一套会漂移（PR #26 审查要求「走同一引用校验
链路」）。本模块提供两个入口：

- `extract_inline_citations(text)`：从行内文本提回 `[EV:<id>]` 编号。
- `validate_citations(...)`：对「编号 + 可选正文」执行统一校验，返回通过项、
  无效项（编号不存在）与错配项（编号存在但内容属于别的证据）。

两个服务都把各自的引用表示折算成 `(ref_id, content, record_ref)` 后调用
同一函数，判定口径因此一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_RE = re.compile(r"\[EV:([A-Za-z0-9_\-\.]+)\]")
_SENTENCE_SPLIT_RE = re.compile(r"[。；;\n]")
_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?\s*[A-Za-zμ%/]+")


@dataclass(frozen=True)
class CitationBinding:
    """一条可用引用：编号 / 对应正文 / 来源记录，三者绑定。"""

    ref_id: str
    text: str = ""
    record_ref: str = ""


@dataclass
class CitationVerdict:
    """统一校验结果：通过 / 编号不存在 / 引用错配。"""

    accepted: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)

    @property
    def rejected(self) -> list[str]:
        return list(dict.fromkeys(self.unknown + self.mismatched))

    @property
    def is_clean(self) -> bool:
        return not self.unknown and not self.mismatched


def extract_inline_citations(text: str) -> list[str]:
    """按出现顺序提回行内 `[EV:<id>]` 编号（去重）。"""
    return list(dict.fromkeys(CITATION_RE.findall(text)))


def _fingerprint_hit(sentence: str, evidence_text: str) -> bool:
    """句子是否含该证据的特征片段（数字+单位），保守判定，不做语义推断。"""
    if not evidence_text:
        return False
    for token in _TOKEN_RE.findall(evidence_text):
        token = token.strip()
        if token and token in sentence:
            return True
    return False


def find_mismatched_citations(
    content: str, bindings: list[CitationBinding]
) -> list[str]:
    """找出「编号存在但引用的文字属于另一条证据」的编号。

    只在同一句内比对，且要求句子命中了别的证据的特征片段、却没命中自己
    的——纯语义层面的张冠李戴不在此列，交由人工核对兜底。
    """
    by_id = {b.ref_id: b for b in bindings}
    mismatched: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(content):
        for ref in extract_inline_citations(sentence):
            own = by_id.get(ref)
            if own is None:
                continue  # 编号不存在，由 unknown 分支处理
            if _fingerprint_hit(sentence, own.text):
                continue
            for other_id, other in by_id.items():
                if other_id == ref:
                    continue
                if _fingerprint_hit(sentence, other.text):
                    mismatched.append(ref)
                    break
    return list(dict.fromkeys(mismatched))


def validate_citations(
    cited: list[str],
    bindings: list[CitationBinding],
    content: str = "",
) -> CitationVerdict:
    """统一引用校验：编号存在性 + 引用与内容是否错位。

    `cited` 是提回或解析出的编号列表；`content` 给正文用于错配判定
    （T10 的 JSON 形态没有行内编号时留空，只做存在性校验）。
    """
    known = {b.ref_id for b in bindings}
    verdict = CitationVerdict()
    for ref in cited:
        if ref not in known:
            verdict.unknown.append(ref)
        elif ref not in verdict.accepted:
            verdict.accepted.append(ref)
    if content:
        for ref in find_mismatched_citations(content, bindings):
            if ref in verdict.accepted:
                verdict.accepted.remove(ref)
            verdict.mismatched.append(ref)
    verdict.unknown = list(dict.fromkeys(verdict.unknown))
    verdict.mismatched = list(dict.fromkeys(verdict.mismatched))
    return verdict
