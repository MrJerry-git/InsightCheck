"""影像报告字段解析候选（H06）。

从超声/放射报告文本识别：检查类型、部位、所见/结论段落、含病灶
描述的句子与尺寸。输出是**候选结构**，携带行号与原文，供人工校对
与病灶关联（C06）；不自动创建病灶，不做原始影像诊断。
自包含实现：不依赖报告文本抽取模块，输入是已分行的报告文本。
"""

from __future__ import annotations

import re

from pydantic import Field

from app.features.lesion.schemas import LesionFeatureSchema

IMAGING_PARSER_VERSION = "imaging-report-parser-v1"

# 段落键名：_section_header 与 _split_sections 必须共用同一组常量，
# 否则独占一行的段头会写入不存在的键并抛 KeyError（PR #23 P1）。
SECTION_BODY = "body"
SECTION_FINDINGS = "findings"
SECTION_CONCLUSIONS = "conclusions"
SECTION_KEYS = (SECTION_BODY, SECTION_FINDINGS, SECTION_CONCLUSIONS)

_FINDING_HEADERS = ("影像所见", "超声所见", "检查所见", "所见")
_CONCLUSION_HEADERS = ("影像结论", "超声提示", "诊断意见", "影像诊断", "结论")
_EXAM_TYPE_KEYWORDS = ("超声", "彩超", "DR", "CT", "MRI", "磁共振", "钼靶", "X线")
_BODY_PART_KEYWORDS = (
    "胸部",
    "腹部",
    "颈部",
    "甲状腺",
    "乳腺",
    "泌尿系",
    "肝胆胰脾",
    "双肾",
    "盆腔",
)
_LESION_KEYWORDS = re.compile(r"结节|肿块|占位|囊肿|结石|钙化|包块")
_NEGATION_RE = re.compile(r"未见|无明显|未及|未见确切|未见异常")
_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)"
    r"|大小约?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)"
)
_SENTENCE_SPLIT_RE = re.compile(r"[。；;！？\n]")
_INLINE_HEADER_RE = re.compile(
    r"^(影像所见|超声所见|检查所见|所见)[：:]\s*(.*)$"
    r"|^(影像结论|超声提示|诊断意见|影像诊断|结论)[：:]\s*(.*)$"
)


class LesionSentenceCandidate(LesionFeatureSchema):
    """含病灶描述的句子候选：带尺寸与原文定位。"""

    sentence: str
    page_line_no: int
    section: str  # findings | conclusions
    size_mm: float | None = None
    size_text: str | None = None


class ImagingReportCandidates(LesionFeatureSchema):
    """一份影像报告的解析候选。"""

    source_name: str
    exam_type: str | None = None
    body_part: str | None = None
    findings: list[str] = Field(default_factory=list)
    conclusions: list[str] = Field(default_factory=list)
    lesion_sentences: list[LesionSentenceCandidate] = Field(default_factory=list)
    parser_version: str = IMAGING_PARSER_VERSION
    notes: list[str] = Field(default_factory=list)


class ImagingReportParser:
    """H06 影像报告字段解析服务。"""

    VERSION = IMAGING_PARSER_VERSION

    def parse(self, source_name: str, lines: list[str]) -> ImagingReportCandidates:
        cleaned = [
            (line_no, line.strip())
            for line_no, line in enumerate(lines, start=1)
            if line.strip()
        ]
        header = self._header_line(text for _, text in cleaned)
        sections = self._split_sections(cleaned)
        lesion_sentences = self._lesion_sentences(sections)

        return ImagingReportCandidates(
            source_name=source_name,
            exam_type=header.get("exam_type"),
            body_part=header.get("body_part"),
            findings=[text for _, text in sections[SECTION_FINDINGS]],
            conclusions=[text for _, text in sections[SECTION_CONCLUSIONS]],
            lesion_sentences=lesion_sentences,
            notes=self._notes(header, sections),
        )

    # ---- 头部信息 ----

    def _header_line(self, lines) -> dict[str, str | None]:
        info: dict[str, str | None] = {"exam_type": None, "body_part": None}
        for text in lines:
            if info["exam_type"] is None:
                for keyword in _EXAM_TYPE_KEYWORDS:
                    if keyword in text:
                        info["exam_type"] = keyword
                        break
            if info["body_part"] is None:
                for keyword in _BODY_PART_KEYWORDS:
                    if keyword in text:
                        info["body_part"] = keyword
                        break
            if info["exam_type"] and info["body_part"]:
                break
        return info

    # ---- 段落切分 ----

    def _split_sections(
        self, cleaned: list[tuple[int, str]]
    ) -> dict[str, list[tuple[int, str]]]:
        sections: dict[str, list[tuple[int, str]]] = {
            key: [] for key in SECTION_KEYS
        }
        current = SECTION_BODY
        for line_no, text in cleaned:
            inline = _INLINE_HEADER_RE.match(text)
            if inline:
                if inline.group(1):  # 所见类段头
                    current = SECTION_FINDINGS
                    remainder = inline.group(2)
                else:  # 结论类段头
                    current = SECTION_CONCLUSIONS
                    remainder = inline.group(4)
                remainder = remainder.strip()
                if remainder:
                    sections[current].append((line_no, remainder))
                continue
            header = self._section_header(text)
            if header is not None:
                current = header
                continue
            sections[current].append((line_no, text))
        return sections

    def _section_header(self, text: str) -> str | None:
        cleaned = text.rstrip("：: ").strip()
        if not cleaned or len(cleaned) > 12:
            return None
        if cleaned in _FINDING_HEADERS:
            return SECTION_FINDINGS
        if cleaned in _CONCLUSION_HEADERS:
            return SECTION_CONCLUSIONS
        return None

    # ---- 病灶句子 ----

    def _lesion_sentences(
        self, sections: dict[str, list[tuple[int, str]]]
    ) -> list[LesionSentenceCandidate]:
        candidates: list[LesionSentenceCandidate] = []
        for section in (SECTION_FINDINGS, SECTION_CONCLUSIONS):
            for line_no, text in sections[section]:
                for sentence in _SENTENCE_SPLIT_RE.split(text):
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    # 否定句（"未见明显占位"等）不是病灶描述，跳过；
                    # 复杂否定语义仍由人工校对兜底
                    if _NEGATION_RE.search(sentence):
                        continue
                    if not _LESION_KEYWORDS.search(sentence):
                        continue
                    size_mm, size_text = self._extract_size(sentence)
                    candidates.append(
                        LesionSentenceCandidate(
                            sentence=sentence,
                            page_line_no=line_no,
                            section=section,
                            size_mm=size_mm,
                            size_text=size_text,
                        )
                    )
        return candidates

    def _extract_size(self, sentence: str) -> tuple[float | None, str | None]:
        match = _SIZE_RE.search(sentence)
        if not match:
            return None, None
        if match.group(1) is not None:
            width = float(match.group(1))
            height = float(match.group(2))
            return max(width, height), match.group(0).strip()
        return float(match.group(3)), match.group(0).strip()

    def _notes(
        self, header: dict[str, str | None], sections: dict[str, list[tuple[int, str]]]
    ) -> list[str]:
        notes: list[str] = []
        if header["exam_type"] is None:
            notes.append("未识别检查类型，请人工校对")
        if header["body_part"] is None:
            notes.append("未识别检查部位，请人工校对")
        if not sections[SECTION_FINDINGS] and not sections[SECTION_CONCLUSIONS]:
            notes.append("未识别所见/结论段落，全文按正文处理")
        return notes
