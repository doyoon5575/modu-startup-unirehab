"""
다음 회기 계획 = '규칙 + 근거 + AI 문서화'.
검토된 수행 데이터 → 목표별 변화 계산 → 임상 규칙 적용 → 근거 자료 연결 → 계획서 초안 → 치료사 승인.
LLM 역할은 '확인된 데이터를 문장으로 정리'로 제한한다. 여기서는 LLM 호출을 DocumentWriter 인터페이스로 분리하고,
기본 구현은 템플릿 기반(결정적)으로 두어 수치·근거를 임의로 생성하지 않도록 한다.
"""
from typing import Optional, Protocol, Dict, Any, List
from .enums import *
from .models import *
from .repository import Repo
from .permissions import require
from .rule_engine import generate_candidates, RuleConfig
from .evidence_repo import find_by_approach
from .metrics_engine import compute_session_metrics, compare_with_previous


class DocumentWriter(Protocol):
    def write(self, facts: Dict[str, Any]) -> str: ...


class TemplateWriter:
    """확인된 사실만 문장화. 입력에 없는 수치·근거를 만들지 않는다."""
    def write(self, facts: Dict[str, Any]) -> str:
        lines = [f"[다음 회기 계획 초안] 대상자 {facts['patient_code']} · 기준 회기 {facts['session_date']} (결과 v{facts['result_version']})", ""]
        lines.append("■ 유지할 목표")
        for g in facts["goals_to_keep"]:
            lines.append(f"  - {g['goal']} — 이유: {g['reason']}")
        lines.append("■ 바꿀 조건")
        for c in facts["conditions_to_change"] or [{"target": "없음", "change": "변경 제안 없음"}]:
            lines.append(f"  - {c['target']}: {c['change']}")
        lines.append("■ 제안별 근거")
        for p in facts["proposals"]:
            lines.append(f"  [{p['title']}] 근거: {p['rationale']} / 불확실성: {p['uncertainty']} / 확인 필요: {p['needs_confirmation']} / 참고자료: {p['evidence']}")
        lines.append("■ 확인 과제: " + ("; ".join(facts["probe_tasks"]) or "없음"))
        lines.append("■ 가정 연습 후보(승인 후 별도 배정): " + ("; ".join(facts["home_candidates"]) or "없음"))
        lines.append("■ 중단·조정 조건: " + facts["stop_adjust"])
        lines.append("■ 승인 상태: " + facts["state"])
        return "\n".join(lines)


def build_plan(repo: Repo, user: User, session_id: str, prev_session_id: Optional[str] = None,
               cfg: RuleConfig = RuleConfig(), writer: DocumentWriter = TemplateWriter()) -> NextSessionPlan:
    require(user, "session.plan")
    s = repo.sessions[session_id]
    if s.state not in (SessionState.RESULT_FINALIZED,):
        raise ValueError(f"회기 결과가 확정되어야 계획을 생성할 수 있습니다(현재: {s.state.value}).")
    patient = repo.patients[s.patient_id]
    plan_id = new_id("PLAN")
    cands = generate_candidates(repo, session_id, prev_session_id, cfg)

    proposals: List[Proposal] = []
    for c in cands:
        ev = find_by_approach(repo, c.evidence_approach_keys) if c.evidence_approach_keys else []
        proposals.append(Proposal(new_id("PR"), plan_id, c.title, c.goal_id, c.rationale_data, c.related_trial_ids,
                                  c.activity_draft, c.uncertainty, c.needs_confirmation, [e.id for e in ev], c.rule_key, c.precheck))

    goals_to_keep = []
    for gid in s.goal_ids:
        g = repo.goals[gid]
        reason = "이번 회기 결과가 확정되어 다음 회기 비교 기준으로 사용" if g.goal_type != GoalType.MAINTENANCE else "기능 유지 목표: 점수 향상이 아니라 현재 수행 유지가 기준"
        goals_to_keep.append({"goal_id": gid, "goal": g.sentence(), "reason": reason})

    conditions = []
    for p in proposals:
        target = {"CUE_DEPENDENT": "도움", "NO_PROBE": "자극", "GENERALIZATION": "자극", "FATIGUE": "분량", "HOME_DROP": "도움 방식",
                  "COLLECTION_FIRST": "수집 조건", "MORE_OBSERVATION": "분량", "INDEP_INCREASED": "자극"}.get(p.rule_key, "기타")
        conditions.append({"target": target, "change": p.activity_draft, "proposal_id": p.id})

    probe_tasks = [p.activity_draft for p in proposals if p.rule_key in ("NO_PROBE", "GENERALIZATION", "INDEP_INCREASED")]
    home_candidates = [p.activity_draft for p in proposals if p.rule_key in ("CUE_DEPENDENT", "HOME_DROP")]

    state = PlanState.DRAFT if user.role != Role.TRAINEE else PlanState.DRAFT
    facts = {
        "patient_code": patient.code, "session_date": s.date, "result_version": s.result_version,
        "goals_to_keep": goals_to_keep, "conditions_to_change": conditions,
        "proposals": [{"title": p.title, "rationale": p.rationale_data, "uncertainty": p.uncertainty,
                       "needs_confirmation": p.needs_confirmation, "evidence": p.evidence_label()} for p in proposals],
        "probe_tasks": probe_tasks, "home_candidates": home_candidates,
        "stop_adjust": s.rest_stop_condition or "치료사 설정 필요", "state": state.value,
    }
    plan = NextSessionPlan(plan_id, s.patient_id, session_id, s.result_version, state, goals_to_keep, conditions,
                           "; ".join(p.rationale_data for p in proposals) or "변경을 뒷받침하는 수행 데이터 없음",
                           probe_tasks, home_candidates, s.rest_stop_condition or "치료사 설정 필요", proposals,
                           writer.write(facts), author_id=user.id,
                           history=[{"at": now(), "by": user.id, "event": "AI 초안 생성", "role": user.role.value}])
    repo.plans[plan.id] = plan
    return plan


def decide_proposal(repo: Repo, user: User, plan_id: str, proposal_id: str, decision: ProposalDecision, edit: Optional[str] = None):
    require(user, "session.plan")
    plan = repo.plans[plan_id]
    p = next(x for x in plan.proposals if x.id == proposal_id)
    p.decision = decision; p.therapist_edit = edit; p.decided_by = user.id; p.decided_at = now()
    if decision == ProposalDecision.MODIFIED and edit:
        p.activity_draft = edit
    plan.state = PlanState.EDITING
    plan.history.append({"at": now(), "by": user.id, "event": f"제안 '{p.title}' → {decision.value}"})
    return p


def save_draft(repo: Repo, user: User, plan_id: str):
    """계획 초안 저장: 아직 실시·배정할 수 없는 상태."""
    plan = repo.plans[plan_id]
    plan.state = PlanState.EDITING if plan.state != PlanState.DRAFT else PlanState.DRAFT
    plan.history.append({"at": now(), "by": user.id, "event": "계획 초안 저장"})
    return plan


def request_supervisor_approval(repo: Repo, user: User, plan_id: str):
    require(user, "plan.request_approval")
    plan = repo.plans[plan_id]
    plan.state = PlanState.PENDING_SUPERVISOR
    plan.history.append({"at": now(), "by": user.id, "event": "지도자 승인 요청"})
    return plan


def supervisor_feedback(repo: Repo, user: User, plan_id: str, feedback: str, approve: bool):
    require(user, "trainee.feedback")
    plan = repo.plans[plan_id]
    plan.supervisor_feedback.append({"at": now(), "by": user.id, "feedback": feedback})
    if approve:
        return approve_plan(repo, user, plan_id)
    plan.state = PlanState.EDITING
    plan.history.append({"at": now(), "by": user.id, "event": "지도자 피드백 → 수정 요청"})
    return plan


def approve_plan(repo: Repo, user: User, plan_id: str):
    """다음 회기 계획 승인(회기 결과 확정과 별도 동작). 가정 연습은 자동 배정되지 않는다."""
    require(user, "plan.approve")
    plan = repo.plans[plan_id]
    s = repo.sessions[plan.based_on_session_id]
    if s.result_version != plan.based_on_result_version or s.state == SessionState.BASIS_CHANGED:
        raise ValueError("기초 결과가 변경되었습니다. 회기 결과를 다시 확정하고 계획을 재생성·재승인하세요.")
    pending = [p for p in plan.proposals if p.decision == ProposalDecision.PENDING]
    if pending:
        raise ValueError(f"결정하지 않은 제안 {len(pending)}개가 있습니다: " + ", ".join(p.title for p in pending))
    plan.state = PlanState.APPROVED
    plan.approved_by = user.id; plan.approved_at = now()
    plan.history.append({"at": now(), "by": user.id, "event": "다음 회기 계획 승인"})
    s.transitions.append(StateTransition(s.state.value, SessionState.PLAN_APPROVED.value, user.id, now()))
    s.state = SessionState.PLAN_APPROVED
    return plan


def assign_home_practice(repo: Repo, user: User, plan_id: str, proposal_id: str, guidance: List[str], stop_rule: str) -> HomeAssignment:
    """승인된 활동만 별도로 선택해 배정."""
    require(user, "home.assign")
    plan = repo.plans[plan_id]
    if plan.state != PlanState.APPROVED:
        raise ValueError("승인된 계획의 활동만 가정 연습으로 배정할 수 있습니다.")
    p = next(x for x in plan.proposals if x.id == proposal_id)
    if p.decision not in (ProposalDecision.ACCEPTED, ProposalDecision.MODIFIED):
        raise ValueError("수락 또는 수정 후 수락된 제안만 배정할 수 있습니다.")
    for g in guidance:
        if "답" in g and "대신" in g:
            raise ValueError("정답을 대신 말하는 도움은 승인된 보호자 안내로 배정할 수 없습니다(의사표현을 지원하는 도움만 허용).")
    ha = HomeAssignment(new_id("HA"), plan.patient_id, plan_id, proposal_id, p.activity_draft, guidance, stop_rule, user.id, now())
    repo.home_assignments[ha.id] = ha
    return ha
