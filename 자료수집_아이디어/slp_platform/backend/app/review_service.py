"""
치료사 검토(UI 명세 ① 문항 검토). AI 결과와 치료사 수정값을 분리 저장하고 수정 이력을 남긴다.
"""
from typing import List, Optional
from .enums import *
from .models import *
from .repository import Repo, SaveError, ConflictError
from .permissions import require


class ReviewError(Exception):
    pass


def _snapshot(r: TherapistReview, t: Trial) -> dict:
    return {
        "usage": r.usage.value, "first": r.first_judgement.value if r.first_judgement else None,
        "cues": [c.value for c in r.cues_given], "post": r.post_cue_judgement.value if r.post_cue_judgement else None,
        "tags": [x.value for x in r.observation_tags], "note": r.observation_note,
        "transcripts": [a.therapist_transcript for a in t.attempts],
        "timing": {"onset": t.timing.first_speech_onset_s, "post_cue_onset": t.timing.post_cue_onset_s},
    }


def review_trial(repo: Repo, user: User, trial_id: str, *, expected_row_version: int,
                 usage: TrialUsage, exclusion_reason: Optional[str] = None,
                 first: Optional[FirstResponseJudgement] = None, cues: Optional[List[CueType]] = None,
                 post: Optional[PostCueJudgement] = None, tags: Optional[List[ObservationTag]] = None,
                 note: str = "", therapist_transcripts: Optional[List[Optional[str]]] = None,
                 onset_correction: Optional[float] = None, post_cue_onset_correction: Optional[float] = None,
                 modification_reason: Optional[ModificationReason] = None, hold_reason: Optional[str] = None,
                 clinician_speech_ratings: Optional[dict] = None) -> Trial:
    require(user, "trial.review")
    t = repo.trials[trial_id]
    s = repo.sessions[t.session_id]
    r = t.review
    prev = _snapshot(r, t)

    # 제외 시 사유 필수
    if usage == TrialUsage.EXCLUDED and not exclusion_reason:
        raise ReviewError("결과에서 제외하려면 제외 사유를 입력해야 합니다.")
    # 보류 시 이유 필수
    if (first == FirstResponseJudgement.HOLD or post == PostCueJudgement.HOLD or usage == TrialUsage.HOLD) and not hold_reason:
        raise ReviewError("판정 보류에는 이유가 필요합니다.")
    # 도움 전 수행만 판정: 최초 반응이 독립 성공이면 도움 후 판정은 '해당 없음'
    if first == FirstResponseJudgement.INDEPENDENT_SUCCESS and post not in (None, PostCueJudgement.NOT_APPLICABLE):
        raise ReviewError("최초 반응이 독립 성공이면 도움 후 반응은 '해당 없음'이어야 합니다.")
    # 단서를 기록하지 않았는데 도움 후 판정을 하면 오류
    if post not in (None, PostCueJudgement.NOT_APPLICABLE) and not cues:
        raise ReviewError("도움 후 반응을 판정하려면 실제 제공한 단서를 먼저 기록하세요.")

    # 전사: AI 전사는 읽기 전용, 치료사 전사는 별도 저장
    if therapist_transcripts:
        for a, txt in zip(t.attempts, therapist_transcripts):
            if txt is not None:
                a.therapist_transcript = txt
    # 시간 수정: 원래 값은 auto_values 에 보존, 수정값 저장 → 결과 재계산
    if onset_correction is not None:
        t.timing.first_speech_onset_s = onset_correction
        t.timing.corrected_by = user.id
    if post_cue_onset_correction is not None:
        t.timing.post_cue_onset_s = post_cue_onset_correction
        t.timing.corrected_by = user.id

    r.usage = usage
    r.exclusion_reason = exclusion_reason
    r.first_judgement = first
    r.cues_given = cues or []
    r.post_cue_judgement = post if post else (PostCueJudgement.NOT_APPLICABLE if first == FirstResponseJudgement.INDEPENDENT_SUCCESS else None)
    r.observation_tags = tags or []
    r.observation_note = note
    r.hold_reason = hold_reason
    r.modification_reason = modification_reason
    if clinician_speech_ratings:
        r.clinician_speech_ratings = {**clinician_speech_ratings, "rater": user.id, "rated_at": now()}
    r.reviewer_id = user.id
    r.reviewed_at = now()

    # 상태 결정
    if usage == TrialUsage.EXCLUDED:
        r.review_status = ReviewStatus.EXCLUDED
    elif usage == TrialUsage.HOLD or first == FirstResponseJudgement.HOLD or post == PostCueJudgement.HOLD:
        r.review_status = ReviewStatus.HOLD
    else:
        ai_first = t.attempts[0].ai_classification or ""
        changed_from_ai = (first and first.value.split(" ")[0] not in ai_first)
        r.review_status = ReviewStatus.MODIFIED if (changed_from_ai or modification_reason) else ReviewStatus.REVIEWED
        if t.analysis and t.analysis.status in (AnalysisStatus.AUTO_DONE_PENDING, AnalysisStatus.THERAPIST_REVIEW_REQUIRED):
            t.analysis.status = AnalysisStatus.AUTO_DONE_REVIEWED

    r.history.append(ReviewVersion(len(r.history) + 1, user.id, now(), prev, _snapshot(r, t), modification_reason))

    # 결과 확정 후 문항 수정 → 새 수정본 생성, 결과·계획 재검토 표시
    if s.state in (SessionState.RESULT_FINALIZED, SessionState.PLAN_APPROVED):
        s.result_version += 1
        s.transitions.append(StateTransition(s.state.value, SessionState.BASIS_CHANGED.value, user.id, now(), f"문항 {t.id} 수정 → 결과·계획 재검토 필요"))
        s.state = SessionState.BASIS_CHANGED
        for p in repo.plans.values():
            if p.based_on_session_id == s.id and p.state == PlanState.APPROVED:
                p.state = PlanState.REAPPROVAL_REQUIRED
                p.history.append({"at": now(), "by": user.id, "event": "기초 결과 변경됨 → 재승인 요구"})
    elif s.state != SessionState.REVIEWING:
        s.transitions.append(StateTransition(s.state.value, SessionState.REVIEWING.value, user.id, now()))
        s.state = SessionState.REVIEWING

    repo.save_trial(t, expected_row_version)   # SaveError / ConflictError 는 호출자가 처리
    repo.log_access(user.id, s.patient_id, f"trial.review:{t.id}")
    return t


def change_scoring_criterion(repo: Repo, user: User, session_id: str, new_criterion: ScoringCriterion):
    """채점 기준을 검토 도중 변경하면 이미 검토한 문항에 재확인 표시(조용히 기준만 바뀌는 구조 금지)."""
    require(user, "trial.review")
    repo.criteria[new_criterion.id] = new_criterion
    flagged = []
    for t in repo.trials_of_session(session_id):
        if t.review.review_status in (ReviewStatus.REVIEWED, ReviewStatus.MODIFIED):
            t.review.review_status = ReviewStatus.RECHECK
            flagged.append(t.id)
        t.scoring_criterion_id = new_criterion.id
        t.scoring_criterion_version = new_criterion.version
    return flagged


def review_summary(repo: Repo, session_id: str) -> dict:
    trials = repo.trials_of_session(session_id)
    c = lambda st: sum(1 for t in trials if t.review.review_status == st)
    return {
        "전체": len(trials),
        "검토 완료": c(ReviewStatus.REVIEWED) + c(ReviewStatus.MODIFIED),
        "미검토": c(ReviewStatus.UNREVIEWED) + c(ReviewStatus.IN_REVIEW),
        "확인 필요": c(ReviewStatus.NEEDS_CHECK),
        "수정됨": c(ReviewStatus.MODIFIED),
        "판정 보류": c(ReviewStatus.HOLD),
        "제외": c(ReviewStatus.EXCLUDED),
        "재확인 필요": c(ReviewStatus.RECHECK),
    }


def filter_trials(repo: Repo, session_id: str, flt: str = "전체"):
    trials = repo.trials_of_session(session_id)   # 기본: 원래 시행 순서
    m = {
        "전체": lambda t: True,
        "미검토": lambda t: t.review.review_status in (ReviewStatus.UNREVIEWED, ReviewStatus.IN_REVIEW),
        "확인 필요": lambda t: t.review.review_status in (ReviewStatus.NEEDS_CHECK, ReviewStatus.RECHECK),
        "수정됨": lambda t: t.review.review_status == ReviewStatus.MODIFIED,
        "판정 보류": lambda t: t.review.review_status == ReviewStatus.HOLD,
        "제외": lambda t: t.review.review_status == ReviewStatus.EXCLUDED,
    }
    return [t for t in trials if m[flt](t)]


def trial_card(t: Trial, stim_label: str) -> dict:
    """왼쪽 문항 카드: 상태명 + 아이콘 + AI 제안 + 확인 사유."""
    icon = {"미검토": "○", "검토 중": "◐", "검토 완료": "✓", "확인 필요": "!", "수정됨": "✎", "판정 보류": "?", "제외": "×", "재확인 필요": "↻"}[t.review.review_status.value]
    reason = None
    if t.analysis:
        if t.analysis.status == AnalysisStatus.POOR_RECORDING: reason = "음질 문제"
        elif t.analysis.status == AnalysisStatus.OUT_OF_SCOPE: reason = "적용 범위 밖"
        elif t.analysis.limits: reason = "전사 검토"
    return {
        "번호": f"{t.order:02d}", "자극": stim_label, "상태": f"{icon} {t.review.review_status.value}",
        "최초": t.attempts[0].ai_classification or "분석 대기",
        "도움 후": (t.attempts[1].ai_classification if len(t.attempts) > 1 else "—") or "—",
        "확인 사유": reason,
    }
