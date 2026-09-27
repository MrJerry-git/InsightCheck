from app.features.lesion.schemas import (
    LesionMatchDecision,
    LesionMatchingRequest,
    LesionMatchingResult,
    LesionMatchStatus,
    LesionTrackCandidate,
    TrackPresenceDecision,
    TrackPresenceStatus,
)
from app.features.lesion.scorer import LesionScorer, months_between
from app.features.lesion.terminology import LesionTerminology


class LesionMatcher:
    """将同一批次结构化病灶与既有轨迹进行可解释匹配。

    terminology 可注入多部位扩展配置（H06）；缺省为内置肺部词表。
    """

    def __init__(self, terminology: LesionTerminology | None = None) -> None:
        self._terminology = terminology

    def match(self, request: LesionMatchingRequest) -> LesionMatchingResult:
        scorer = LesionScorer(request.config, terminology=self._terminology)
        pair_scores = [
            scorer.score(current, track)
            for current in request.current_lesions
            for track in request.previous_tracks
        ]
        pair_scores.sort(key=lambda item: item.confidence, reverse=True)
        assigned_lesions: set[str] = set()
        assigned_tracks: set[str] = set()
        selected_pairs = {}
        for pair in pair_scores:
            if pair.confidence < request.config.review_threshold:
                continue
            if pair.current_lesion_id in assigned_lesions:
                continue
            if pair.candidate_track_id in assigned_tracks:
                continue
            selected_pairs[pair.current_lesion_id] = pair
            assigned_lesions.add(pair.current_lesion_id)
            assigned_tracks.add(pair.candidate_track_id)

        decisions: list[LesionMatchDecision] = []
        continuing_tracks: set[str] = set()
        reviewing_tracks: set[str] = set()

        for current in request.current_lesions:
            current_scores = [
                item for item in pair_scores if item.current_lesion_id == current.lesion_id
            ]
            if not current_scores:
                decisions.append(
                    LesionMatchDecision(
                        current_lesion_id=current.lesion_id,
                        confidence=0.0,
                        status=LesionMatchStatus.NEW_LESION,
                        reasons=["没有可比较的既有病灶轨迹"],
                    )
                )
                continue

            best = selected_pairs.get(current.lesion_id)
            if best is None:
                highest = max(current_scores, key=lambda item: item.confidence)
                reasons = list(highest.reasons)
                if highest.candidate_track_id in assigned_tracks:
                    reasons.append("最佳候选轨迹已分配给同批次另一病灶，避免一对多错配")
                else:
                    reasons.append("最高置信度低于人工复核阈值，作为新病灶处理")
                decisions.append(
                    LesionMatchDecision(
                        current_lesion_id=current.lesion_id,
                        candidate_track_id=highest.candidate_track_id,
                        confidence=highest.confidence,
                        status=LesionMatchStatus.NEW_LESION,
                        component_scores=highest.component_scores,
                        weighted_contributions=highest.weighted_contributions,
                        reasons=reasons,
                    )
                )
                continue

            status = self._classify(best.confidence, request)
            matched_track_id = (
                best.candidate_track_id if status == LesionMatchStatus.MATCHED else None
            )
            if matched_track_id:
                continuing_tracks.add(matched_track_id)
            elif status == LesionMatchStatus.NEED_REVIEW:
                reviewing_tracks.add(best.candidate_track_id)
            decisions.append(
                LesionMatchDecision(
                    current_lesion_id=current.lesion_id,
                    candidate_track_id=best.candidate_track_id,
                    matched_track_id=matched_track_id,
                    confidence=best.confidence,
                    status=status,
                    component_scores=best.component_scores,
                    weighted_contributions=best.weighted_contributions,
                    reasons=best.reasons,
                )
            )

        track_presence = [
            self._presence(
                track,
                request,
                continuing=track.track_id in continuing_tracks,
                under_review=track.track_id in reviewing_tracks,
            )
            for track in request.previous_tracks
        ]
        return LesionMatchingResult(
            matches=decisions,
            track_presence=track_presence,
            matching_version=request.config.version,
        )

    @staticmethod
    def _classify(confidence: float, request: LesionMatchingRequest) -> LesionMatchStatus:
        if confidence >= request.config.matched_threshold:
            return LesionMatchStatus.MATCHED
        if confidence >= request.config.review_threshold:
            return LesionMatchStatus.NEED_REVIEW
        return LesionMatchStatus.NEW_LESION

    @staticmethod
    def _presence(
        track: LesionTrackCandidate,
        request: LesionMatchingRequest,
        *,
        continuing: bool,
        under_review: bool,
    ) -> TrackPresenceDecision:
        if continuing:
            return TrackPresenceDecision(
                track_id=track.track_id,
                status=TrackPresenceStatus.CONTINUING,
                disappeared=False,
                reasons=["本次检查存在已自动匹配的病灶观察"],
            )
        if under_review:
            return TrackPresenceDecision(
                track_id=track.track_id,
                status=TrackPresenceStatus.UNRESOLVED,
                disappeared=False,
                reasons=["存在待人工复核的候选病灶，不能判定轨迹延续或消失"],
            )

        last = max(track.observations, key=lambda item: item.exam_date)
        terminology = LesionTerminology()
        normalized_complete_parts = {
            terminology.normalize_body_part(item) for item in request.complete_body_parts
        }
        same_scope_complete = bool(
            last.body_part
            and terminology.normalize_body_part(last.body_part) in normalized_complete_parts
        )
        interval = months_between(
            last,
            last.model_copy(update={"exam_date": request.current_exam_date}),
        )
        if same_scope_complete and interval <= request.config.max_disappearance_interval_months:
            return TrackPresenceDecision(
                track_id=track.track_id,
                status=TrackPresenceStatus.DISAPPEARED,
                disappeared=True,
                reasons=["同一检查范围已完整记录，但本次未匹配到该轨迹"],
            )
        return TrackPresenceDecision(
            track_id=track.track_id,
            status=TrackPresenceStatus.UNRESOLVED,
            disappeared=False,
            reasons=["检查范围或时间信息不足，不能判定病灶消失"],
        )
