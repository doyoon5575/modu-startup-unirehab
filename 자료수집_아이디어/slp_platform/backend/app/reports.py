"""
9-2 회기 후 결과보고서 / 가정 연습 보고 / 대상자 요약.
원칙: 무엇을 측정했고 무엇까지 말할 수 있는지 구분한다. 치료사 관찰과 AI 분석을 구분한다. 작성·수정·승인 이력을 포함한다.
연습 과제 점수를 표준화검사 점수나 진단 결과처럼 표시하지 않는다.
"""
from typing import Optional
from .enums import *
from .repository import Repo
from .metrics_engine import compute_session_metrics, compare_with_previous

DISCLAIMER = "※ 본 수치는 앱 연습 과제의 수행 기록이며 표준화검사 점수나 진단 결과가 아닙니다."


def _fmt_ratio(r):
    return f"{r['분자']}/{r['분모']} ({r['비율']}%)" if r["분모"] else "자료 없음"


def session_report(repo: Repo, session_id: str, prev_session_id: Optional[str] = None, org_template: Optional[dict] = None) -> str:
    s = repo.sessions[session_id]; p = repo.patients[s.patient_id]
    m = compute_session_metrics(repo, session_id)
    acts = sorted([a for a in repo.activities.values() if a.session_id == session_id], key=lambda a: a.order_in_session)
    header = (org_template or {}).get("header", "회기 결과보고서")
    L = [f"[{header}] 대상자 {p.code} · {s.date} · {s.setting.value}", DISCLAIMER, ""]
    L.append("1. 계획한 활동과 실제 실시한 활동")
    for a in acts:
        L.append(f"  - {a.name}: 계획 {'O' if a.planned else 'X'} / 실시 {'O' if a.actually_performed else 'X'}")
    r = m["계산 범위"]
    L.append(f"2. 계산 범위: 실시 {r['실시 문항']} / 결과 포함 {r['결과 포함 문항']} / 제외 {r['제외 문항']} / 보류 {r['보류 문항']} / 미검토 {r['미검토 문항']}")
    for e in r["제외 사유"]: L.append(f"   제외 {e['문항']}: {e['사유']}")
    for e in r["보류 사유"]: L.append(f"   보류 {e['문항']}: {e['사유']}")
    L.append("3. 목표별 수행 결과(분모 포함)")
    for gid, gm in m["목표별"].items():
        L += [f"  ■ {gm['목표']}",
              f"     독립 수행: {_fmt_ratio(gm['독립 수행'])} [문항: {', '.join(gm['독립 수행']['포함 문항'])}]",
              f"     도움 후 성공: {_fmt_ratio(gm['도움 후 성공'])} (분모: {gm['도움 후 성공']['분모 설명']})",
              f"     단서 사용: {gm['단서 사용'] or '없음'}",
              f"     반응 시간: 중앙값 {gm['반응 시간']['중앙값(초)']}초 (측정: {gm['반응 시간']['측정 정의']}; 포함 문항 {len(gm['반응 시간']['포함 문항'])}개)",
              f"     연습 자극 {_fmt_ratio(gm['연습 자극 독립 수행'])} / 새 자극 {_fmt_ratio(gm['새 자극 독립 수행'])} / 유지 {_fmt_ratio(gm['유지 확인'])}",
              f"     치료실 {_fmt_ratio(gm['치료실 독립 수행'])} / 가정 {_fmt_ratio(gm['가정 독립 수행'])}",
              f"     산출 조건 분포: {gm['산출 조건 분포']}",
              f"     주요 관찰(치료사 태그): {gm['관찰 태그'] or '없음'}"]
        L.append("     대표 반응(원음·전사 연결):")
        for rep in gm["대표 반응"]:
            L.append(f"       · {rep['문항']} “{rep['전사']}” → {rep['판정']} [원음: {rep['원음']}]")
        if gm["분석 불가·제외"]:
            L.append(f"     분석 불가·제외 자료: {gm['분석 불가·제외']}")
    L.append("4. 치료사 관찰·해석(AI 분석과 구분)")
    L.append(f"   {s.therapist_interpretation or '(미작성)'}")
    L.append("5. AI 분석 요약(자동 분석 제안; 치료사 확정값과 별도)")
    for t in repo.trials_of_session(session_id):
        if t.analysis:
            L.append(f"   {t.id}: 모델 {t.analysis.model_version} / 상태 {t.analysis.status.value} / 제한 {t.analysis.limits or '없음'}")
    L.append("6. 이전 회기와 비교 가능한 범위")
    if prev_session_id:
        c = compare_with_previous(repo, session_id, prev_session_id)
        L.append(f"   {c['비교 가능 범위']}; 경고: {c['경고'] or '없음'}")
        for gid, d in c["목표별 변화"].items():
            L.append(f"   {gid}: 독립 수행 {d['이전']['비율']}% → {d['현재']['비율']}% ({d['독립 수행 변화(%p)']:+.1f}%p)")
    else:
        L.append("   비교할 이전 회기 없음")
    L.append("7. 해석 제한: " + ("; ".join(m["해석 제한"]) or "없음"))
    plan = next((pl for pl in repo.plans.values() if pl.based_on_session_id == session_id), None)
    L.append("8. 다음 회기 제안과 근거")
    if plan:
        for pr in plan.proposals:
            L.append(f"   - [{pr.decision.value}] {pr.title}: 근거 {pr.rationale_data} / 불확실성 {pr.uncertainty} / {pr.evidence_label()}")
    else:
        L.append("   (계획 미생성)")
    L.append("9. 작성·수정·승인 이력")
    for tr in s.transitions:
        L.append(f"   {tr.at} {tr.from_state} → {tr.to_state} by {tr.actor_id} {tr.note}")
    L.append(f"   최종 상태: {s.state.value}" + (" (치료사 검토 전 초안)" if s.state in (SessionState.REVIEWING, SessionState.IN_PROGRESS) else ""))
    return "\n".join(L)


def home_practice_report(repo: Repo, report_id: str) -> str:
    r = repo.home_reports[report_id]; a = repo.home_assignments[r.assignment_id]
    L = [f"[가정 연습 보고] 배정 {a.id} · {r.performed_at}",
         f"  활동: {a.activity_description}",
         f"  수행 방식: {'혼자 수행' if r.performed_alone else '도움 받음'} / 도움 제공자: {r.helper or '—'} / 도움 수준: {r.help_level.value}",
         f"  환경: {r.environment_note or '—'}",
         f"  문항 수: {len(r.trial_ids)} (가정 녹음은 자동 분석 검증 범위 밖 → 치료사 수동 검토 필요)"]
    for ev in r.life_goal_events:
        L.append(f"  생활 목표 수행: {ev}")
    return "\n".join(L)


def patient_summary(repo: Repo, patient_id: str, viewer_role: Role) -> str:
    p = repo.patients[patient_id]
    L = [f"[대상자 요약] {p.code}", f"  임상 영역: {', '.join(d.value for d in p.domains) or '미입력'}"]
    for d in p.clinical.diagnoses:
        L.append(f"  진단: {d['name']} ({d['status']}·{d['source']}; 확인: {d.get('confirmed_by','—')})")
    L.append(f"  발병 시점: {p.clinical.onset_date.display()}  /  경과: {p.clinical.course.display()}")
    L.append(f"  청력: {p.profile.hearing.display()}  /  시력: {p.profile.vision.display()}  /  피로: {p.profile.fatigue.display()}")
    L.append(f"  이름대기: {p.profile.naming.display()}  /  문장 이해: {p.profile.sentence_comprehension.display()}")
    L.append(f"  도움이 되는 단서: {[c.value for c in p.profile.helpful_cues] or '미입력'}")
    L.append(f"  생활 목표: {[(g.who, g.where, g.what) for g in p.life_goals] or '미입력'}")
    if viewer_role in (Role.PATIENT, Role.CAREGIVER):
        return "\n".join(L[:2]) + "\n  (상세 임상정보는 치료사 화면에서만 표시됩니다)"
    return "\n".join(L)


def patient_today_view(repo: Repo, patient_id: str) -> dict:
    """가정용 화면: 복잡한 그래프 대신 '오늘 연습할 것', '도움받는 방법', '어려우면 멈추는 방법'."""
    items = [a for a in repo.home_assignments.values() if a.patient_id == patient_id]
    return {
        "오늘 연습할 것": [a.activity_description for a in items],
        "도움받는 방법": sorted({g for a in items for g in a.caregiver_guidance}),
        "어려우면 멈추는 방법": sorted({a.stop_rule for a in items}),
        "녹음이 안 될 때": sorted({a.offline_fallback for a in items}),
    }
