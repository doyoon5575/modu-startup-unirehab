"""
데이터 계산 엔진(기획서 8-1). 검토된 수행 데이터만 사용하고, 모든 지표에 분자·분모·포함 문항 ID를 붙인다.
서로 분리할 성과지표: 독립 수행률 / 도움 후 성공 / 단서 사용 / 반응 시간 / 새로운 자극 수행 / 유지 / 생활 목표 수행
"""
from collections import Counter, defaultdict
from statistics import mean, median
from typing import Dict, Any, List
from .enums import *
from .models import Trial
from .repository import Repo


def _ratio(n, d):
    return {"분자": n, "분모": d, "비율": (round(n / d * 100, 1) if d else None)}


def compute_session_metrics(repo: Repo, session_id: str) -> Dict[str, Any]:
    trials = repo.trials_of_session(session_id)
    performed = len(trials)
    included = [t for t in trials if t.review.usage == TrialUsage.INCLUDED and t.review.review_status in (ReviewStatus.REVIEWED, ReviewStatus.MODIFIED)]
    excluded = [t for t in trials if t.review.review_status == ReviewStatus.EXCLUDED]
    held = [t for t in trials if t.review.review_status == ReviewStatus.HOLD]
    unreviewed = [t for t in trials if t.review.review_status in (ReviewStatus.UNREVIEWED, ReviewStatus.IN_REVIEW, ReviewStatus.NEEDS_CHECK, ReviewStatus.RECHECK)]

    out = {
        "계산 범위": {
            "실시 문항": performed, "결과 포함 문항": len(included), "제외 문항": len(excluded),
            "보류 문항": len(held), "미검토 문항": len(unreviewed),
            "제외 사유": [{"문항": t.id, "사유": t.review.exclusion_reason} for t in excluded],
            "보류 사유": [{"문항": t.id, "사유": t.review.hold_reason} for t in held],
        },
        "목표별": {},
        "해석 제한": [],
    }
    if unreviewed:
        out["해석 제한"].append(f"미검토 문항 {len(unreviewed)}개: 결과는 임시값입니다.")
    if held:
        out["해석 제한"].append(f"보류 문항 {len(held)}개는 계산에서 제외되었습니다. 보류 처리와 해석 제한을 확인한 뒤 확정하세요.")

    by_goal: Dict[str, List[Trial]] = defaultdict(list)
    for t in included:
        by_goal[t.goal_id].append(t)

    for goal_id, ts in by_goal.items():
        g = repo.goals[goal_id]
        # 독립 수행률: 추가 도움 없이 기준 충족. (말운동: 따라 말하기·함께 말하기는 독립 산출로 계산하지 않음)
        indep_eligible = [t for t in ts if t.production_condition == ProductionCondition.INDEPENDENT]
        indep_ok = [t for t in indep_eligible if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS]
        # 도움 후 성공: 독립 수행하지 못한 문항이 분모
        not_indep = [t for t in ts if t.review.first_judgement in (FirstResponseJudgement.OTHER_RESPONSE, FirstResponseJudgement.NO_RESPONSE)]
        post_ok = [t for t in not_indep if t.review.post_cue_judgement == PostCueJudgement.SUCCESS]
        # 단서 사용
        cue_counter = Counter()
        cue_success = Counter()
        for t in not_indep:
            for c in t.review.cues_given:
                cue_counter[c.value] += 1
                if t.review.post_cue_judgement == PostCueJudgement.SUCCESS:
                    cue_success[c.value] += 1
        # 반응 시간(측정 정의 + 포함 문항)
        lat = [(t.id, t.timing.response_latency()) for t in ts if t.timing.response_latency() is not None]
        post_lat = [(t.id, t.timing.post_cue_latency()) for t in ts if t.timing.post_cue_latency() is not None]
        # 새 자극 vs 연습 자극
        practice = [t for t in ts if t.stimulus_purpose == StimulusPurpose.PRACTICE and t.production_condition == ProductionCondition.INDEPENDENT]
        probe = [t for t in ts if t.stimulus_purpose == StimulusPurpose.PROBE and t.production_condition == ProductionCondition.INDEPENDENT]
        maint = [t for t in ts if t.stimulus_purpose == StimulusPurpose.MAINTENANCE]
        # 치료실 vs 가정
        clinic = [t for t in indep_eligible if t.setting == Setting.CLINIC]
        home = [t for t in indep_eligible if t.setting == Setting.HOME]
        # 순서 효과(앞 절반 vs 뒤 절반)
        ordered = sorted(indep_eligible, key=lambda t: t.order)
        half = len(ordered) // 2
        front = ordered[:half]; back = ordered[half:]
        # 관찰 태그
        tag_counter = Counter(x.value for t in ts for x in t.review.observation_tags)
        # 대표 반응(원음·전사 이동용)
        reps = []
        for t in ts[:3]:
            a = t.attempts[0]
            reps.append({"문항": t.id, "전사": a.therapist_transcript or a.ai_transcript, "원음": a.audio_ref.split("|")[0] if a.audio_ref else None,
                         "판정": t.review.first_judgement.value if t.review.first_judgement else None})

        out["목표별"][goal_id] = {
            "목표": g.sentence(),
            "독립 수행": {**_ratio(len(indep_ok), len(indep_eligible)), "포함 문항": [t.id for t in indep_eligible]},
            "도움 후 성공": {**_ratio(len(post_ok), len(not_indep)), "분모 설명": "독립 수행하지 못한 문항", "포함 문항": [t.id for t in not_indep]},
            "단서 사용": {k: {"제공": v, "제공 후 성공": cue_success[k]} for k, v in cue_counter.items()},
            "반응 시간": {
                "측정 정의": ts[0].timing.definition, "포함 문항": [i for i, _ in lat],
                "중앙값(초)": round(median([v for _, v in lat]), 2) if lat else None,
                "평균(초)": round(mean([v for _, v in lat]), 2) if lat else None,
                "단서 후 반응 시간 중앙값(초)": round(median([v for _, v in post_lat]), 2) if post_lat else None,
            },
            "연습 자극 독립 수행": _ratio(sum(1 for t in practice if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(practice)),
            "새 자극 독립 수행": _ratio(sum(1 for t in probe if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(probe)),
            "유지 확인": _ratio(sum(1 for t in maint if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(maint)),
            "치료실 독립 수행": _ratio(sum(1 for t in clinic if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(clinic)),
            "가정 독립 수행": _ratio(sum(1 for t in home if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(home)),
            "앞 절반 독립 수행": _ratio(sum(1 for t in front if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(front)),
            "뒤 절반 독립 수행": _ratio(sum(1 for t in back if t.review.first_judgement == FirstResponseJudgement.INDEPENDENT_SUCCESS), len(back)),
            "산출 조건 분포": dict(Counter(t.production_condition.value for t in ts)),
            "관찰 태그": dict(tag_counter),
            "대표 반응": reps,
            "분석 불가·제외": [{"문항": t.id, "상태": t.analysis.status.value if t.analysis else "분석 대기"} for t in trials if t.goal_id == goal_id and t.analysis and t.analysis.status in (AnalysisStatus.POOR_RECORDING, AnalysisStatus.OUT_OF_SCOPE)],
        }
    return out


def compare_with_previous(repo: Repo, session_id: str, prev_session_id: str) -> Dict[str, Any]:
    """이전 회기 비교: 조건(과제·채점 기준·자극 버전·도움 조건·모델 버전·장소)이 다르면 경고."""
    cur = repo.sessions[session_id]; prev = repo.sessions[prev_session_id]
    ct = repo.trials_of_session(session_id); pt = repo.trials_of_session(prev_session_id)
    warnings = []
    def s(ts, f): return set(f(t) for t in ts)
    if cur.setting != prev.setting: warnings.append("이전 회기와 실시 장소(치료실/가정)가 다름")
    if s(ct, lambda t: t.scoring_criterion_version) != s(pt, lambda t: t.scoring_criterion_version): warnings.append("채점 기준 버전이 다름")
    if s(ct, lambda t: (t.stimulus_id, t.stimulus_version)) != s(pt, lambda t: (t.stimulus_id, t.stimulus_version)): warnings.append("자극 구성 또는 자극 버전이 다름")
    if s(ct, lambda t: tuple(t.review.cues_given)) != s(pt, lambda t: tuple(t.review.cues_given)): warnings.append("이전 회기와 도움 조건 다름")
    if s(ct, lambda t: t.analysis.model_version if t.analysis else None) != s(pt, lambda t: t.analysis.model_version if t.analysis else None): warnings.append("분석 모델 버전이 다름(점수 변화가 모델 변경 때문일 수 있음)")
    if not any(t.stimulus_purpose == StimulusPurpose.PROBE for t in ct): warnings.append("새 자극 자료 없음")
    m_cur = compute_session_metrics(repo, session_id); m_prev = compute_session_metrics(repo, prev_session_id)
    diff = {}
    for gid, cm in m_cur["목표별"].items():
        pm = m_prev["목표별"].get(gid)
        if pm:
            diff[gid] = {"독립 수행 변화(%p)": round((cm["독립 수행"]["비율"] or 0) - (pm["독립 수행"]["비율"] or 0), 1),
                         "이전": pm["독립 수행"], "현재": cm["독립 수행"]}
    return {"비교 가능 범위": "경고가 없는 지표만 직접 비교 가능" if not warnings else "조건 차이 있음 → 수치 비교에 주의", "경고": warnings, "목표별 변화": diff}
