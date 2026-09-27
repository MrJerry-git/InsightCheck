"""H06 多部位术语、影像报告解析与人工修订回算。"""

from dataclasses import dataclass
from datetime import date

import pytest

from app.features.lesion.imaging_report import (
    SECTION_BODY,
    SECTION_CONCLUSIONS,
    SECTION_FINDINGS,
    SECTION_KEYS,
    ImagingReportParser,
)
from app.features.lesion.matcher import LesionMatcher
from app.features.lesion.revisions import (
    ManualRevision,
    ManualRevisionApplier,
    ManualRevisionRequest,
    RevisionAction,
)
from app.features.lesion.schemas import (
    LesionMatchingRequest,
    LesionMatchStatus,
    LesionTrackCandidate,
    StructuredLesion,
)
from app.features.lesion.terminology import LesionSiteConfig, LesionTerminology

# ---- 多部位术语 ----


def test_default_terminology_stays_lung_only() -> None:
    terminology = LesionTerminology()
    assert terminology.normalize_location("甲状腺右叶").matched is False
    assert terminology.multisite_enabled is False
    assert terminology.organs() == ["LUNG"]
    assert terminology.normalize_location("右肺上叶").canonical_location == "RIGHT_UPPER_LOBE"


def test_multisite_config_adds_sites_without_touching_lung() -> None:
    terminology = LesionTerminology(LesionSiteConfig.load_builtin())
    assert terminology.multisite_enabled is True
    assert "THYROID" in terminology.organs() and "LIVER" in terminology.organs()
    assert terminology.normalize_location("甲状腺右叶").canonical_location == "THYROID_RIGHT_LOBE"
    assert terminology.display_location("THYROID_RIGHT_LOBE") == "甲状腺右叶"
    assert terminology.normalize_lesion_type("甲状腺结节") == "THYROID_NODULE"
    # 肺词表不受影响
    assert terminology.normalize_location("右肺上叶").canonical_location == "RIGHT_UPPER_LOBE"


def test_site_config_alias_conflict_is_rejected() -> None:
    config = LesionSiteConfig(location_aliases={"右肺上叶": "THYROID_RIGHT_LOBE"})
    with pytest.raises(ValueError) as excinfo:
        LesionTerminology(config)
    assert "冲突" in str(excinfo.value)


# ---- 多部位匹配与跨部位隔离 ----


def lesion(
    lesion_id: str,
    location: str,
    lesion_type: str,
    organ: str,
    body_part: str,
    size: float,
    day: str,
) -> StructuredLesion:
    return StructuredLesion(
        lesion_id=lesion_id,
        exam_date=date.fromisoformat(day),
        lesion_type=lesion_type,
        organ=organ,
        body_part=body_part,
        location=location,
        size_mm=size,
    )


def test_same_site_lesion_matches_track() -> None:
    terminology = LesionTerminology(LesionSiteConfig.load_builtin())
    matcher = LesionMatcher(terminology)
    track = LesionTrackCandidate(
        track_id="thy-track",
        observations=[
            lesion("t1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.0, "2025-06-01")
        ],
    )
    current = lesion("c1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.2, "2026-06-01")
    result = matcher.match(
        LesionMatchingRequest(
            current_exam_date=current.exam_date,
            previous_tracks=[track],
            current_lesions=[current],
        )
    )
    decision = result.matches[0]
    assert decision.status == LesionMatchStatus.MATCHED
    assert decision.matched_track_id == "thy-track"


def test_cross_site_pairs_never_auto_match() -> None:
    terminology = LesionTerminology(LesionSiteConfig.load_builtin())
    matcher = LesionMatcher(terminology)
    thyroid_track = LesionTrackCandidate(
        track_id="thy-track",
        observations=[
            lesion("t1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.0, "2025-06-01")
        ],
    )
    lung_track = LesionTrackCandidate(
        track_id="lung-track",
        observations=[
            lesion("t2", "右肺上叶", "肺结节", "肺", "胸部", 4.0, "2025-06-01")
        ],
    )
    thyroid_current = lesion("c1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.2, "2026-06-01")
    result = matcher.match(
        LesionMatchingRequest(
            current_exam_date=thyroid_current.exam_date,
            previous_tracks=[thyroid_track, lung_track],
            current_lesions=[thyroid_current],
        )
    )
    decision = result.matches[0]
    # 同部位轨迹在场地，算法匹配到同部位轨迹，绝不匹配异部位轨迹
    assert decision.matched_track_id == "thy-track"

    # 只有异部位轨迹在场时，算法不得自动确认匹配
    lung_only = matcher.match(
        LesionMatchingRequest(
            current_exam_date=thyroid_current.exam_date,
            previous_tracks=[lung_track],
            current_lesions=[thyroid_current],
        )
    )
    assert lung_only.matches[0].status != LesionMatchStatus.MATCHED
    assert lung_only.matches[0].matched_track_id is None


# ---- 影像报告解析 ----


THYROID_REPORT = [
    "超声检查报告单",
    "检查部位：甲状腺",
    "超声所见：",
    "甲状腺右叶可见低回声结节，大小约 4.2 x 3.1 mm，边界清。",
    "甲状腺左侧叶未见明显占位。",
    "超声提示：",
    "甲状腺右叶结节，建议随访。",
]

CHEST_REPORT = [
    "胸部正位DR",
    "影像所见：胸廓对称，纵隔居中，肺内未见结节及肿块。",
    "影像结论：心肺未见明显异常。",
]


def test_imaging_report_parse_with_lesion_sentences() -> None:
    parser = ImagingReportParser()
    result = parser.parse("thyroid_us.txt", THYROID_REPORT)
    assert result.exam_type == "超声"
    assert result.body_part == "甲状腺"
    assert any("甲状腺右叶可见低回声结节" in line for line in result.findings)
    assert any("建议随访" in line for line in result.conclusions)
    assert len(result.lesion_sentences) == 2
    first = result.lesion_sentences[0]
    assert first.size_mm == 4.2 and first.section == "findings"
    assert first.page_line_no == 4
    assert "4.2 x 3.1 mm" in (first.size_text or "")


def test_imaging_report_without_lesions_yields_empty_candidates() -> None:
    parser = ImagingReportParser()
    result = parser.parse("chest_dr.txt", CHEST_REPORT)
    assert result.lesion_sentences == []
    assert result.exam_type == "DR"
    assert result.body_part == "胸部"
    assert result.notes == []


def test_imaging_report_missing_header_produces_notes() -> None:
    parser = ImagingReportParser()
    result = parser.parse("bare.txt", ["报告正文，无段落结构。"])
    assert result.exam_type is None and result.body_part is None
    assert any("检查类型" in note for note in result.notes)


def test_size_single_diameter_extracted() -> None:
    parser = ImagingReportParser()
    result = parser.parse("demo.txt", ["所见：肝内见稍高回声结节，大小约 11 mm，边界清。"])
    assert result.lesion_sentences[0].size_mm == 11.0


# ---- 段落切分：段头键名必须统一（PR #23 P1） ----


def test_section_header_constants_are_shared_by_split_and_header() -> None:
    """_split_sections 只建 SECTION_KEYS 里的键，_section_header 只返回这些键。"""
    parser = ImagingReportParser()
    sections = parser._split_sections(
        [(1, "超声所见"), (2, "结节大小约5 mm"), (3, "结论"), (4, "建议复查")]
    )
    assert set(sections) == set(SECTION_KEYS)
    assert sections[SECTION_BODY] == []  # 无正文行
    assert parser._section_header("超声所见") == SECTION_FINDINGS
    assert parser._section_header("结论") == SECTION_CONCLUSIONS
    assert parser._section_header("超声所见：") == SECTION_FINDINGS
    assert parser._section_header("结论：") == SECTION_CONCLUSIONS


def test_header_on_own_line_without_colon() -> None:
    """审查复现用例：段头独占一行且不带冒号，不得抛 KeyError。"""
    parser = ImagingReportParser()
    result = parser.parse(
        "review-repro.txt",
        ["超声所见", "甲状腺结节大小约5 mm", "结论", "建议复查"],
    )
    assert result.findings == ["甲状腺结节大小约5 mm"]
    assert result.conclusions == ["建议复查"]
    assert len(result.lesion_sentences) == 1
    assert result.lesion_sentences[0].section == SECTION_FINDINGS
    assert result.lesion_sentences[0].size_mm == 5.0


def test_header_on_own_line_with_trailing_colon() -> None:
    parser = ImagingReportParser()
    result = parser.parse(
        "colon-header.txt",
        ["超声所见：", "甲状腺结节大小约 6 mm。", "超声提示：", "建议随访。"],
    )
    assert result.findings == ["甲状腺结节大小约 6 mm。"]
    assert result.conclusions == ["建议随访。"]
    assert result.lesion_sentences[0].size_mm == 6.0
    assert result.lesion_sentences[0].page_line_no == 2


def test_inline_header_with_body_on_same_line() -> None:
    parser = ImagingReportParser()
    result = parser.parse(
        "inline.txt",
        ["超声所见：甲状腺结节大小约 7 mm。", "超声提示：结节，建议复查。"],
    )
    assert result.findings == ["甲状腺结节大小约 7 mm。"]
    assert result.conclusions == ["结节，建议复查。"]
    sections = {c.section for c in result.lesion_sentences}
    assert sections == {SECTION_FINDINGS, SECTION_CONCLUSIONS}


def test_multi_section_report_mixes_both_header_styles() -> None:
    """多段报告：带冒号/不带冒号/同行正文混合出现。"""
    lines = [
        "超声检查报告单",
        "检查部位：甲状腺",
        "超声所见",  # 不带冒号
        "甲状腺右叶可见低回声结节，大小约 4.2 x 3.1 mm，边界清。",
        "超声提示：",  # 带冒号
        "甲状腺右叶结节，建议随访。",
        "补充：峡部未见明显占位。",
    ]
    result = ImagingReportParser().parse("mixed.txt", lines)
    assert result.exam_type == "超声" and result.body_part == "甲状腺"
    assert result.findings == ["甲状腺右叶可见低回声结节，大小约 4.2 x 3.1 mm，边界清。"]
    assert result.conclusions == ["甲状腺右叶结节，建议随访。", "补充：峡部未见明显占位。"]
    # 所见句子带尺寸，结论句不带尺寸（不能凭空继承尺寸）
    assert [c.size_mm for c in result.lesion_sentences] == [4.2, None]


# ---- H04 抽取结果接入 ----

try:  # H04（PR #20）合入后自动改用真实数据结构
    from app.report_extraction.schemas import ExtractedLine as _H04ExtractedLine
except ImportError:  # 本分支尚未合入 H04，用同契约替身
    _H04ExtractedLine = None


@dataclass(frozen=True)
class _ExtractedLineStub:
    """与 H04 `ExtractedLine`（page_no/line_no/text）契约一致的最小替身。"""

    page_no: int
    line_no: int
    text: str


def _h04_extracted_lines(lines: list[str]):
    """构造 H04 抽取结果：按页拆行，段头常独占一行且不带冒号。"""
    line_cls = _H04ExtractedLine or _ExtractedLineStub
    return [
        line_cls(page_no=1, line_no=no, text=text)
        for no, text in enumerate(lines, start=1)
    ]


def test_h04_line_split_result_feeds_parser() -> None:
    """H04 的真实分行结果（ExtractedLine 列表）能直接接入，不抛 KeyError。"""
    lines = _h04_extracted_lines(
        [
            "超声检查报告单",
            "检查部位：甲状腺",
            "超声所见",
            "甲状腺右叶可见低回声结节，大小约 4.2 x 3.1 mm，边界清。",
            "超声提示",
            "甲状腺右叶结节，建议随访。",
        ]
    )
    result = ImagingReportParser().parse("h04-doc.pdf", [line.text for line in lines])
    assert result.findings == ["甲状腺右叶可见低回声结节，大小约 4.2 x 3.1 mm，边界清。"]
    assert result.conclusions == ["甲状腺右叶结节，建议随访。"]
    assert result.lesion_sentences[0].size_mm == 4.2
    assert result.lesion_sentences[0].page_line_no == 4


def test_h04_document_lines_keep_page_and_line_locators() -> None:
    """接入时保留 H04 的页码/行号定位，供人工校对回溯原文。"""
    lines = _h04_extracted_lines(["超声所见", "甲状腺结节大小约5 mm"])
    parsed = ImagingReportParser().parse("h04-doc.pdf", [line.text for line in lines])
    assert parsed.lesion_sentences[0].page_line_no == lines[1].line_no


# ---- 人工修订回算 ----


def build_request() -> ManualRevisionRequest:
    thyroid_track = LesionTrackCandidate(
        track_id="thy-track",
        observations=[
            lesion("t1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.0, "2025-06-01")
        ],
    )
    lung_track = LesionTrackCandidate(
        track_id="lung-track",
        observations=[
            lesion("t2", "右肺上叶", "肺结节", "肺", "胸部", 5.0, "2025-06-01")
        ],
    )
    current = lesion("c1", "甲状腺右叶", "甲状腺结节", "甲状腺", "颈部", 4.2, "2026-06-01")
    return ManualRevisionRequest(
        algorithm_matches=[],
        current_lesions=[current],
        previous_tracks=[thyroid_track, lung_track],
        manual_revisions=[],
    )


def test_manual_link_overrides_algorithm_and_records_history() -> None:
    request = build_request()
    request.manual_revisions = [
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.LINK,
            track_id="thy-track",
            reason="同一患者同部位，报告编号一致",
            actor="医生A",
        )
    ]
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    record = result.records[0]
    assert record.applied is True and record.revision_no == 1
    assert record.resulting_status == LesionMatchStatus.MATCHED
    decision = result.decisions[0]
    assert decision.status == LesionMatchStatus.MATCHED
    assert decision.matched_track_id == "thy-track"
    assert "人工确认关联" in decision.reasons[0]


def test_manual_cross_site_link_is_rejected_with_reason() -> None:
    request = build_request()
    request.manual_revisions = [
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.LINK,
            track_id="lung-track",
            reason="误操作尝试跨部位关联",
            actor="医生A",
        )
    ]
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    record = result.records[0]
    assert record.applied is False
    assert record.reject_reason and "拒绝跨部位关联" in record.reject_reason
    assert record.resulting_status is None
    assert result.decisions[0].status == LesionMatchStatus.NEW_LESION


def test_unlink_and_mark_pending_flow() -> None:
    request = build_request()
    request.manual_revisions = [
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.LINK,
            track_id="thy-track",
            reason="初次关联",
            actor="医生A",
        ),
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.UNLINK,
            reason="复查发现报告归属错误",
            actor="医生B",
        ),
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.MARK_PENDING,
            reason="等待上一年度影像复核",
            actor="医生B",
        ),
    ]
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    assert all(r.applied for r in result.records)
    assert [r.revision_no for r in result.records] == [1, 2, 3]
    final = result.decisions[0]
    assert final.status == LesionMatchStatus.NEED_REVIEW
    assert final.matched_track_id is None


def test_unlink_without_existing_link_is_rejected() -> None:
    request = build_request()
    request.manual_revisions = [
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.UNLINK,
            reason="没有可解除的关联",
            actor="医生A",
        )
    ]
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    assert result.records[0].applied is False
    assert "未关联" in (result.records[0].reject_reason or "")


def test_unknown_lesion_and_track_rejected() -> None:
    request = build_request()
    request.manual_revisions = [
        ManualRevision(
            lesion_id="ghost",
            action=RevisionAction.LINK,
            track_id="thy-track",
            reason="未知病灶",
            actor="医生A",
        ),
        ManualRevision(
            lesion_id="c1",
            action=RevisionAction.LINK,
            track_id="ghost-track",
            reason="未知轨迹",
            actor="医生A",
        ),
    ]
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    assert result.records[0].applied is False and "未知病灶" in result.records[0].reject_reason
    assert result.records[1].applied is False and "未知" in result.records[1].reject_reason


def test_history_is_preserved_and_numbering_continues() -> None:
    base = build_request()
    request = ManualRevisionRequest(
        algorithm_matches=base.algorithm_matches,
        current_lesions=base.current_lesions,
        previous_tracks=base.previous_tracks,
        manual_revisions=[
            ManualRevision(
                lesion_id="c1",
                action=RevisionAction.LINK,
                track_id="thy-track",
                reason="复核后确认",
                actor="医生B",
            )
        ],
        history=[
            {
                "revision_no": 1,
                "lesion_id": "c1",
                "action": "mark_pending",
                "reason": "首轮待复核",
                "actor": "医生A",
                "applied": True,
                "reject_reason": None,
                "resulting_status": "NEED_REVIEW",
            }
        ],
    )
    result = ManualRevisionApplier(
        LesionTerminology(LesionSiteConfig.load_builtin())
    ).apply(request)
    assert len(result.records) == 2
    assert result.records[0].revision_no == 1  # 历史保留
    assert result.records[1].revision_no == 2  # 编号递增
