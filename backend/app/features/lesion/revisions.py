"""影像病灶人工修订回算（H06）。

人工判定优先于算法匹配；每次回算追加修订记录（revision_no 递增），
不覆盖历史。跨部位关联一律拒绝（不将不同部位强行关联）；
NEED_REVIEW 不写入轨迹（沿用 LESION_MATCHING.md 约束）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.features.lesion.schemas import (
    LesionFeatureSchema,
    LesionMatchDecision,
    LesionMatchStatus,
    LesionTrackCandidate,
    StructuredLesion,
)
from app.features.lesion.terminology import LesionTerminology

REVISION_VERSION = "lesion-manual-revision-v1"


class RevisionAction(StrEnum):
    LINK = "link"
    UNLINK = "unlink"
    MARK_PENDING = "mark_pending"


class ManualRevision(LesionFeatureSchema):
    """一条人工判定：关联/解除/待定，必须填写原因。"""

    lesion_id: str = Field(min_length=1, max_length=100)
    action: RevisionAction
    track_id: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    actor: str = Field(min_length=1, max_length=100)


class RevisionRecord(LesionFeatureSchema):
    """修订留痕：只追加、不覆盖。"""

    revision_no: int
    lesion_id: str
    action: RevisionAction
    track_id: str | None = None
    reason: str
    actor: str
    applied: bool
    reject_reason: str | None = None
    resulting_status: LesionMatchStatus | None = None


class ManualRevisionRequest(LesionFeatureSchema):
    """回算输入：算法匹配结果 + 本轮人工判定 + 既有修订历史。"""

    algorithm_matches: list[LesionMatchDecision] = Field(default_factory=list)
    current_lesions: list[StructuredLesion] = Field(default_factory=list)
    previous_tracks: list[LesionTrackCandidate] = Field(default_factory=list)
    manual_revisions: list[ManualRevision] = Field(default_factory=list)
    history: list[RevisionRecord] = Field(default_factory=list)


class ManualRevisionResult(LesionFeatureSchema):
    decisions: list[LesionMatchDecision]
    records: list[RevisionRecord]
    revision_version: str = REVISION_VERSION


class ManualRevisionApplier:
    """把人工判定回算进匹配结果；生成新的修订记录列表。"""

    def __init__(self, terminology: LesionTerminology | None = None) -> None:
        self._terminology = terminology or LesionTerminology()

    def apply(self, request: ManualRevisionRequest) -> ManualRevisionResult:
        decisions: dict[str, LesionMatchDecision] = {
            d.current_lesion_id: d.model_copy(deep=True)
            for d in request.algorithm_matches
        }
        records: list[RevisionRecord] = list(request.history)
        next_no = max((r.revision_no for r in records), default=0) + 1

        for revision in request.manual_revisions:
            applied, reject_reason, resulting_status = self._apply_one(
                request, decisions, revision
            )
            records.append(
                RevisionRecord(
                    revision_no=next_no,
                    lesion_id=revision.lesion_id,
                    action=revision.action,
                    track_id=revision.track_id,
                    reason=revision.reason,
                    actor=revision.actor,
                    applied=applied,
                    reject_reason=reject_reason,
                    resulting_status=resulting_status,
                )
            )
            next_no += 1

        ordered = [
            decisions[d.current_lesion_id]
            for d in request.algorithm_matches
            if d.current_lesion_id in decisions
        ]
        ordered.extend(
            decision
            for lesion_id, decision in decisions.items()
            if lesion_id not in {d.current_lesion_id for d in request.algorithm_matches}
        )
        return ManualRevisionResult(decisions=ordered, records=records)

    # ---- 单条修订 ----

    def _apply_one(
        self,
        request: ManualRevisionRequest,
        decisions: dict[str, LesionMatchDecision],
        revision: ManualRevision,
    ) -> tuple[bool, str | None, LesionMatchStatus | None]:
        lesion = next(
            (item for item in request.current_lesions if item.lesion_id == revision.lesion_id),
            None,
        )
        if lesion is None:
            return False, f"未知病灶 {revision.lesion_id}", None
        decision = decisions.get(revision.lesion_id)
        if decision is None:
            decision = decisions[revision.lesion_id] = LesionMatchDecision(
                current_lesion_id=revision.lesion_id,
                confidence=0.0,
                status=LesionMatchStatus.NEW_LESION,
                reasons=["无算法匹配结果，按新病灶登记"],
            )

        if revision.action == RevisionAction.LINK:
            return self._link(request, lesion, decision, revision)
        if revision.action == RevisionAction.UNLINK:
            return self._unlink(decision, revision)
        return self._mark_pending(decision, revision)

    def _link(
        self,
        request: ManualRevisionRequest,
        lesion: StructuredLesion,
        decision: LesionMatchDecision,
        revision: ManualRevision,
    ) -> tuple[bool, str | None, LesionMatchStatus]:
        if not revision.track_id:
            return False, "关联操作必须提供 track_id", None
        track = next(
            (t for t in request.previous_tracks if t.track_id == revision.track_id), None
        )
        if track is None:
            return False, f"未知病灶轨迹 {revision.track_id}", None

        cross_site = self._cross_site_reason(lesion, track)
        if cross_site:
            return False, cross_site, None

        decision.matched_track_id = revision.track_id
        decision.candidate_track_id = revision.track_id
        decision.status = LesionMatchStatus.MATCHED
        decision.confidence = 1.0
        decision.reasons = [
            f"人工确认关联（优先于算法）：{revision.reason}",
            f"操作人：{revision.actor}",
        ]
        return True, None, LesionMatchStatus.MATCHED

    def _unlink(
        self, decision: LesionMatchDecision, revision: ManualRevision
    ) -> tuple[bool, str | None, LesionMatchStatus]:
        no_existing_link = (
            decision.status == LesionMatchStatus.NEW_LESION
            and decision.matched_track_id is None
        )
        if no_existing_link:
            return False, "病灶当前未关联任何轨迹，无需解除", None
        mismatched_track = (
            revision.track_id
            and decision.matched_track_id
            and revision.track_id != decision.matched_track_id
        )
        if mismatched_track:
            return False, (
                f"解除目标 {revision.track_id} 与当前关联 {decision.matched_track_id} 不一致"
            ), None
        decision.matched_track_id = None
        decision.status = LesionMatchStatus.NEW_LESION
        decision.confidence = 0.0
        decision.reasons = [
            f"人工解除关联（优先于算法）：{revision.reason}",
            f"操作人：{revision.actor}",
        ]
        return True, None, LesionMatchStatus.NEW_LESION

    def _mark_pending(
        self, decision: LesionMatchDecision, revision: ManualRevision
    ) -> tuple[bool, str | None, LesionMatchStatus]:
        decision.matched_track_id = None
        decision.status = LesionMatchStatus.NEED_REVIEW
        decision.reasons = [
            f"人工标记待复核（不写入轨迹）：{revision.reason}",
            f"操作人：{revision.actor}",
        ]
        return True, None, LesionMatchStatus.NEED_REVIEW

    # ---- 跨部位守卫 ----

    def _cross_site_reason(
        self, lesion: StructuredLesion, track: LesionTrackCandidate
    ) -> str | None:
        latest = max(track.observations, key=lambda item: item.exam_date)
        lesion_organ = self._organ_of(lesion)
        track_organ = self._organ_of(latest)
        if lesion_organ is None or track_organ is None:
            return (
                "任一侧缺少可归一的部位信息，禁止人工跨部位关联；"
                "请先补全部位再执行关联"
            )
        if lesion_organ != track_organ:
            return (
                f"拒绝跨部位关联：病灶属于 {lesion_organ}，"
                f"轨迹最近观察属于 {track_organ}"
            )
        return None

    def _organ_of(self, item: StructuredLesion) -> str | None:
        organ = self._terminology.normalize_organ(item.organ, item.location)
        if organ:
            return organ
        body_part = self._terminology.normalize_body_part(item.body_part)
        return body_part
