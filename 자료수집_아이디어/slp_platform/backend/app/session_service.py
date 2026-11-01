"""회기 설계·실행·결과 확정(모듈 ④⑤⑥)."""
from typing import List, Optional
from .enums import *
from .models import *
from .repository import Repo
from .permissions import require
from .metrics_engine import compute_session_metrics


def plan_session(repo: Repo, user: User, patient_id: str, date: str, setting: Setting, goal_ids: List[str],
                 rest_stop_condition: str) -> Session:
    require(user, "session.plan")
    s = Session(new_id("S"), patient_id, date, setting, user.id, goal_ids, rest_stop_condition=rest_stop_condition,
                author_id=user.id, created_by_role=user.role)
    s.transitions.append(StateTransition("-", SessionState.PLANNED.value, user.id, now()))
    repo.sessions[s.id] = s
    return s


def add_activity(repo: Repo, user: User, session_id: str, goal_id: str, name: str, approach_key: str, stimulus_ids: List[str],
                 response_mode: ResponseMode, cue_sequence: List[CueType], target_form: str, err_handling: str, measurement: str,
                 order: int, production_condition: ProductionCondition = ProductionCondition.INDEPENDENT, length_level: str = "단어") -> Activity:
    a = Activity(new_id("ACT"), session_id, goal_id, name, approach_key, stimulus_ids, response_mode, cue_sequence,
                 target_form, err_handling, measurement, production_condition, length_level, order_in_session=order)
    repo.activities[a.id] = a
    return a


def pre_session_plan_document(repo: Repo, session_id: str) -> str:
    """9-1 회기 전 계획서."""
    s = repo.sessions[session_id]; p = repo.patients[s.patient_id]
    acts = sorted([a for a in repo.activities.values() if a.session_id == session_id], key=lambda a: a.order_in_session)
    L = [f"[회기 전 계획서] 대상자 {p.code} · {s.date} · {s.setting.value}", "장기목표와 연결된 회기 목표:"]
    for gid in s.goal_ids:
        g = repo.goals[gid]
        parent = repo.goals[g.parent_goal_id].target_behavior if g.parent_goal_id else "—"
        L.append(f"  - {g.sentence()} (장기목표: {parent}; 지표: {g.indicator})")
    L.append("목표별 활동·자극:")
    for a in acts:
        L += [f"  [{a.order_in_session}] {a.name} / 접근: 치료사가 선택한 접근({a.approach_key}) / 자극 {len(a.stimulus_ids)}개 / 산출 조건: {a.production_condition.value} / 길이: {a.length_level}",
              f"      목표 반응 형태: {a.target_response_form}", f"      단서 제공 순서: {' → '.join(c.value for c in a.cue_sequence)}",
              f"      오반응·무반응 대응: {a.error_no_response_handling}", f"      측정 방법: {a.measurement_method}",
              f"      피드백 설정: {a.feedback_setting}"]
    L.append(f"휴식·종료 조건: {s.rest_stop_condition}")
    L.append("가정 연습 계획: 승인된 계획에서 별도 배정")
    L.append(f"작성자: {s.author_id} / 검토자: {s.reviewer_id or '—'} / 승인 상태: {s.state.value}")
    return "\n".join(L)


def start_session(repo: Repo, user: User, session_id: str):
    s = repo.sessions[session_id]
    s.transitions.append(StateTransition(s.state.value, SessionState.IN_PROGRESS.value, user.id, now()))
    s.state = SessionState.IN_PROGRESS
    for a in repo.activities.values():
        if a.session_id == session_id:
            a.actually_performed = True


def record_trial(repo: Repo, session_id: str, activity: Activity, stimulus: Stimulus, order: int, setting: Setting,
                 collection: CollectionOutcome, attempts: List[AttemptRecord], presentation_mode: str = "사진 제시",
                 helper: Optional[str] = None, help_level: HelpLevel = HelpLevel.NONE, distractions: str = "",
                 criterion: Optional[ScoringCriterion] = None) -> Trial:
    t = Trial(new_id("T"), session_id, activity.id, activity.goal_id, stimulus.id, stimulus.version, order, presentation_mode, now(),
              activity.response_mode, setting, collection, attempts, TimingMarks(), None,
              scoring_criterion_id=criterion.id if criterion else "", scoring_criterion_version=criterion.version if criterion else 1,
              helper=helper, help_level=help_level, distractions=distractions,
              production_condition=activity.production_condition, stimulus_purpose=stimulus.purpose)
    repo.trials[t.id] = t
    return t


def finalize_result(repo: Repo, user: User, session_id: str, interpretation: str, acknowledge_holds: bool = False) -> Session:
    """회기 결과 확정(다음 계획 승인과 분리). 미검토가 남아 있으면 확정 불가. 보류가 있으면 명시적 확인 필요."""
    require(user, "session.finalize_result")
    s = repo.sessions[session_id]
    m = compute_session_metrics(repo, session_id)
    if m["계산 범위"]["미검토 문항"] > 0:
        raise ValueError(f"미검토 문항 {m['계산 범위']['미검토 문항']}개가 남아 있어 결과를 확정할 수 없습니다.")
    if m["계산 범위"]["보류 문항"] > 0 and not acknowledge_holds:
        raise ValueError("보류 문항이 있습니다. 보류 처리와 해석 제한을 확인(acknowledge_holds=True)한 뒤 확정하세요.")
    s.therapist_interpretation = interpretation
    s.result_finalized_by = user.id; s.result_finalized_at = now(); s.result_version += 1
    s.transitions.append(StateTransition(s.state.value, SessionState.RESULT_FINALIZED.value, user.id, now(), f"결과 v{s.result_version}"))
    s.state = SessionState.RESULT_FINALIZED
    return s
