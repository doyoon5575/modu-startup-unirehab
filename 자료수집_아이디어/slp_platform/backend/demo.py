"""
전체 흐름 시연(가상 데이터):
대상자 정보 입력 → 치료사 평가 → 목표 설정 → 회기 계획 → 치료·연습 수행 → 반응 분석 → 치료사 검토 → 회기 결과 확정
→ 다음 회기 계획(규칙+근거+문서화) → 치료사 승인 → 가정 연습 배정 → 가정 수행 보고
※ 모든 수치·반응은 구조 설명용 가상 예시입니다.
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.enums import *
from app.models import *
from app.repository import Repo, SaveError, ConflictError
from app.speech_analysis import analyze_trial, MockAdapter
from app import review_service as rv, session_service as ss, planner as pl, reports, evidence_repo, metrics_engine
from app.permissions import PermissionError_


def build_world(fail_first_save=False):
    repo = Repo(path=None, fail_next_save=fail_first_save)
    evidence_repo.seed_evidence(repo)
    org = Organization("ORG-1", "가상 재활병원", {"header": "언어재활 회기 결과보고서(가상 재활병원 서식)"}, "ORG-1")
    repo.orgs[org.id] = org
    users = {
        "slp": User("slp", "김치료", Role.THERAPIST, org.id),
        "sup": User("sup", "박지도", Role.SUPERVISOR, org.id),
        "trn": User("trn", "이실습", Role.TRAINEE, org.id, supervisor_id="sup"),
        "adm": User("adm", "관리자", Role.ORG_ADMIN, org.id, clinical_access=False),
        "pt":  User("pt", "대상자", Role.PATIENT, org.id),
        "cg":  User("cg", "보호자", Role.CAREGIVER, org.id),
    }
    repo.users.update(users)

    # ---- 대상자: 진단명 + 기능 프로필 + 출처·확인 상태
    p = Patient("P-001", org.id, "P-001", name_masked="홍**")
    p.age = InfoField("62", InfoSource.MEDICAL_RECORD, InfoStatus.CONFIRMED, "slp", "의무기록 2026-09")
    p.primary_language = InfoField("한국어", InfoSource.SELF_OR_CAREGIVER_REPORT, InfoStatus.REPORTED)
    p.domains = [ClinicalDomain.APHASIA]
    p.clinical.diagnoses = [{"name": "좌측 MCA 뇌경색 후 실어증", "source": InfoSource.MEDICAL_RECORD.value, "status": InfoStatus.CONFIRMED.value, "confirmed_by": "slp", "document": "진단서"}]
    p.clinical.onset_date = InfoField("2026-06-10", InfoSource.MEDICAL_RECORD, InfoStatus.CONFIRMED, "slp")
    p.profile.naming = InfoField("단어 수준 이름대기 어려움, 의미 단서에 반응", InfoSource.THERAPIST_OBSERVED, InfoStatus.OBSERVED, "slp")
    p.profile.sentence_comprehension = InfoField("짧은 문장 이해 가능, 긴 문장 어려움", InfoSource.THERAPIST_OBSERVED, InfoStatus.OBSERVED, "slp")
    p.profile.can_select_picture_when_speech_hard = InfoField("가능", InfoSource.THERAPIST_OBSERVED, InfoStatus.OBSERVED, "slp")
    p.profile.needs_time_to_answer = InfoField("예(3~5초)", InfoSource.THERAPIST_OBSERVED, InfoStatus.OBSERVED, "slp")
    p.profile.helpful_cues = [CueType.SEMANTIC, CueType.PHONEMIC]
    # 청력은 의도적으로 미입력 → '정보 미입력' 으로 표시되어야 함
    p.life_goals = [LifeGoal("LG-1", "마트 직원", "동네 마트", "필요한 물건 이름 말하고 요청하기", 1)]
    p.home.devices = InfoField("태블릿", InfoSource.SELF_OR_CAREGIVER_REPORT, InfoStatus.REPORTED)
    p.home.helper = InfoField("배우자", InfoSource.SELF_OR_CAREGIVER_REPORT, InfoStatus.REPORTED)
    p.standardized_tests = [StandardizedTestScore("K-WAB(점수만 입력)", "2026-09-01", {"AQ": "입력값(가상)"}, "slp")]
    p.aac_board = [{"유형": "요구", "내용": "물 주세요"}, {"유형": "거절", "내용": "아니요"}]
    p.assigned_therapist_id = "slp"; p.assigned_trainee_id = "trn"
    repo.patients[p.id] = p
    for ct in (ConsentType.SERVICE, ConsentType.CAREGIVER_VIEW):
        c = Consent(new_id("C"), p.id, ct, True, now()); repo.consents[c.id] = c
    c = Consent(new_id("C"), p.id, ConsentType.RESEARCH_TRAINING, False, now()); repo.consents[c.id] = c

    # ---- 평가·목표
    a = Assessment(new_id("A"), p.id, "2026-09-01", "slp", {"이름대기": "생활용품 20개 중 독립 6개(기초선, 가상)"}, baseline={"naming_indep_pct": 30})
    repo.assessments[a.id] = a
    lt = Goal("G-LT", p.id, GoalType.IMPROVEMENT, True, None, "일상 생활 상황", "추가 단서 없는 조건", "치료사 설정 기준", "필요한 물건의 이름을 말해 요청한다", "독립 이름대기 비율", ResponseMode.SPEECH, ["LG-1"], ClinicalDomain.APHASIA, created_by="slp", approved_by="slp")
    g = Goal("G-1", p.id, GoalType.IMPROVEMENT, False, "G-LT", "생활용품 사진 10개", "추가 단서 없는 조건", "8개 이상(기초선 3개 기준으로 치료사가 설정)", "이름을 말한다", "독립 이름대기 수(분자/분모)", ResponseMode.SPEECH, ["LG-1"], ClinicalDomain.APHASIA, created_by="slp", approved_by="slp")
    repo.goals[lt.id] = lt; repo.goals[g.id] = g

    # ---- 자극·채점 기준
    names = ["사과", "우유", "비누", "수건", "칫솔", "컵", "숟가락", "휴지", "빗", "열쇠"]
    stims = []
    for i, n in enumerate(names):
        s = Stimulus(f"ST-{i+1:02d}", 1, n, f"img/{n}.png", "이름대기", ResponseMode.SPEECH, "높음", "마트 구매 품목", "단어(2음절)",
                     [CueType.SEMANTIC, CueType.PHONEMIC], [CueType.SEMANTIC, CueType.PHONEMIC], [n], [n + "이요", n + "요"],
                     StimulusPurpose.PRACTICE if i < 8 else StimulusPurpose.PROBE, ContentRights("자체 제작", True, True, "slp"), "마트 장보기")
        repo.stimuli[s.id] = s; stims.append(s)
    crit = ScoringCriterion("CR-1", 1, "목표어 또는 허용 표현을 추가 단서 없이 산출하면 독립 성공", "'~이요/~요' 허용, 용도 설명은 다른 반응", "의미 → 소리 단서 순", "slp", now())
    repo.criteria[crit.id] = crit
    return repo, users, p, g, stims, crit


def run_session(repo, users, p, g, stims, crit, date, responses, setting=Setting.CLINIC):
    slp = users["slp"]
    s = ss.plan_session(repo, slp, p.id, date, setting, [g.id], "대상자가 피로를 호소하거나 3문항 연속 무반응이면 휴식 5분, 2회 휴식 후에도 지속되면 종료")
    act = ss.add_activity(repo, slp, s.id, g.id, "생활용품 사진 이름대기", "SFA", [x.id for x in stims], ResponseMode.SPEECH,
                          [CueType.SEMANTIC, CueType.PHONEMIC], "단어 산출(허용 표현 포함)", "5초 무반응 또는 오반응 시 의미 단서 → 소리 단서 순 제공",
                          "최초 반응·단서 후 반응 분리 기록, 반응 시간은 자극 음성 종료→첫 발화 시작", 1)
    ss.start_session(repo, slp, s.id)
    adapter = MockAdapter()
    trials = []
    for i, (st, r) in enumerate(zip(stims, responses)):
        meta = dict(text=r["t"], conf=r.get("c", 0.9), stim_end=1.0, onset=r.get("on", 1.0 + 2.5), quality=r.get("q", "ok"), issues=r.get("iss", []))
        attempts = [AttemptRecord("최초 반응", f"audio/{date}/{st.id}_1.wav|{json.dumps(meta, ensure_ascii=False)}", 0, 6)]
        if r.get("cue"):
            meta2 = dict(text=r["t2"], conf=r.get("c2", 0.9), stim_end=8.0, onset=9.2)
            attempts.append(AttemptRecord("단서 후 반응", f"audio/{date}/{st.id}_2.wav|{json.dumps(meta2, ensure_ascii=False)}", 7, 12, cue_before=r["cue"]))
        t = ss.record_trial(repo, s.id, act, st, i + 1, setting, r.get("col", CollectionOutcome.COLLECTED), attempts, criterion=crit)
        analyze_trial(t, adapter, p.domains, "naming", st.accepted_expressions)
        trials.append(t)
    return s, trials


def main():
    repo, users, p, g, stims, crit = build_world(fail_first_save=True)
    slp, trn, sup, adm = users["slp"], users["trn"], users["sup"], users["adm"]
    print("=" * 80); print("A. 대상자 요약(미입력은 '정보 미입력'으로 표시)"); print(reports.patient_summary(repo, p.id, Role.THERAPIST))
    print("   보호자 화면:", reports.patient_summary(repo, p.id, Role.CAREGIVER).splitlines()[-1].strip())

    # 권한: 관리자는 임상정보 접근 불가
    try:
        from app.permissions import require; require(adm, "patient.view_clinical")
    except PermissionError_ as e:
        print("   권한 안내 →", e)

    # ---- 회기 1 (이전 회기, 비교 기준)
    r1 = [dict(t="사과"), dict(t="우유"), dict(t="씻는 거", cue=CueType.SEMANTIC, t2="비누"), dict(t="", cue=CueType.SEMANTIC, t2="수건"),
          dict(t="이 닦는", cue=CueType.SEMANTIC, t2="칫솔"), dict(t="물 먹는 거", cue=CueType.SEMANTIC, t2="컵"),
          dict(t="", cue=CueType.PHONEMIC, t2="숟가락"), dict(t="휴지"), dict(t="", cue=CueType.SEMANTIC, t2=""), dict(t="", cue=CueType.SEMANTIC, t2="열쇠")]
    s1, t1 = run_session(repo, users, p, g, stims, crit, "2026-10-10", r1)
    for t in t1:
        a0 = t.attempts[0]; a1 = t.attempts[1] if len(t.attempts) > 1 else None
        first = FirstResponseJudgement.INDEPENDENT_SUCCESS if a0.ai_target_match else (FirstResponseJudgement.NO_RESPONSE if not a0.ai_transcript else FirstResponseJudgement.OTHER_RESPONSE)
        post = None
        if a1: post = PostCueJudgement.SUCCESS if a1.ai_target_match else (PostCueJudgement.NO_RESPONSE if not a1.ai_transcript else PostCueJudgement.OTHER_RESPONSE)
        try:
            rv.review_trial(repo, slp, t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=first,
                            cues=[a1.cue_before] if a1 else [], post=post)
        except SaveError as e:
            print("\nB. 저장 실패 처리 →", e); rv.review_trial(repo, slp, t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=first, cues=[a1.cue_before] if a1 else [], post=post)
    ss.finalize_result(repo, slp, s1.id, "회기 1: 독립 3/10, 의미 단서 후 추가 성공 관찰(가상).")

    # ---- 회기 2 (검토 화면 시연: 확인 필요·보류·제외·수정·충돌)
    r2 = [dict(t="사과"), dict(t="우유"), dict(t="비누"), dict(t="수건"), dict(t="치솔", c=0.55, cue=CueType.PHONEMIC, t2="칫솔"),
          dict(t="물 먹는 거", cue=CueType.SEMANTIC, t2="컵"), dict(t="", q="bad", iss=["잡음", "잘림"]), dict(t="휴지"),
          dict(t="머리 하는 거", cue=CueType.SEMANTIC, t2="빗"), dict(t="", col=CollectionOutcome.COLLECTION_FAILURE)]
    s2, t2 = run_session(repo, users, p, g, stims, crit, "2026-10-17", r2)

    print("\n" + "=" * 80); print("C. ① 문항 검토 — 상단 진행 수:", rv.review_summary(repo, s2.id))
    print("   A. 문항 목록 [확인 필요 필터]:")
    for card in [rv.trial_card(t, repo.stimuli[t.stimulus_id].label) for t in rv.filter_trials(repo, s2.id, "확인 필요")]:
        print("     ", card)
    t05 = t2[4]
    print("   B. 반응·근거(문항 05): AI 전사=", repr(t05.attempts[0].ai_transcript), "/ 신뢰도", t05.attempts[0].ai_confidence, "/ 분류", t05.attempts[0].ai_classification,
          "/ 분석 제한", t05.analysis.limits, "/ 반응시간", t05.timing.response_latency(), "초 (", t05.timing.definition, ")")

    # 치료사 판단: 05는 원음 확인 후 '칫솔'로 전사 수정 + 독립 성공(수정 이유: 전사 오류), 시간 수정
    rv.review_trial(repo, slp, t05.id, expected_row_version=t05.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS,
                    therapist_transcripts=["칫솔", None], modification_reason=ModificationReason.TRANSCRIPT_ERROR, onset_correction=3.1, note="원음상 '칫솔'로 들림")
    print("   C. 문항 05 판단 저장 → 상태:", t05.review.review_status.value, "/ 자동 측정 onset", t05.timing.auto_values["first_speech_onset_s"], "→ 수정", t05.timing.first_speech_onset_s,
          "/ 이력", len(t05.review.history), "건")
    # 07 음질 불량 → 제외(사유 필수)
    try:
        rv.review_trial(repo, slp, t2[6].id, expected_row_version=t2[6].row_version, usage=TrialUsage.EXCLUDED)
    except rv.ReviewError as e:
        print("   검증 →", e)
    rv.review_trial(repo, slp, t2[6].id, expected_row_version=t2[6].row_version, usage=TrialUsage.EXCLUDED, exclusion_reason="녹음 품질 부족(잡음·잘림)")
    # 09 판정 보류(이유 필수)
    rv.review_trial(repo, slp, t2[8].id, expected_row_version=t2[8].row_version, usage=TrialUsage.HOLD, first=FirstResponseJudgement.HOLD, hold_reason="'머리 하는 거'가 용도 설명인지 부분 반응인지 재청취 필요",
                    tags=[ObservationTag.FUNCTION_INSTEAD_OF_NAME])
    # 10 수집 실패는 analyze 단계에서 이미 제외됨
    print("   문항 10(수집 실패):", t2[9].review.review_status.value, "/", t2[9].review.exclusion_reason)
    # 동시 수정 충돌
    try:
        rv.review_trial(repo, trn, t05.id, expected_row_version=1, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.OTHER_RESPONSE)
    except ConflictError as e:
        print("   충돌 처리 →", e)
    # 나머지 문항 검토
    for t in [t2[0], t2[1], t2[2], t2[3], t2[7]]:
        rv.review_trial(repo, slp, t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    rv.review_trial(repo, slp, t2[5].id, expected_row_version=t2[5].row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.OTHER_RESPONSE,
                    cues=[CueType.SEMANTIC], post=PostCueJudgement.SUCCESS, tags=[ObservationTag.FUNCTION_INSTEAD_OF_NAME])
    print("   검토 후 진행 수:", rv.review_summary(repo, s2.id))

    # 채점 기준 변경 → 재확인 표시
    crit2 = ScoringCriterion("CR-1", 2, "허용 표현에 '~이요' 추가", "…", "…", "slp", now())
    flagged = rv.change_scoring_criterion(repo, slp, s2.id, crit2)
    print("   채점 기준 v2 변경 → 재확인 필요 문항:", len(flagged))
    for tid in flagged:   # 재확인(동일 판정 유지)
        t = repo.trials[tid]; r = t.review
        rv.review_trial(repo, slp, tid, expected_row_version=t.row_version, usage=r.usage, first=r.first_judgement, cues=r.cues_given, post=r.post_cue_judgement, tags=r.observation_tags, note=r.observation_note)

    # ---- ② 회기 결과
    print("\n" + "=" * 80); print("D. ② 회기 결과(분모 포함)")
    m = metrics_engine.compute_session_metrics(repo, s2.id)
    print("   계산 범위:", {k: v for k, v in m["계산 범위"].items() if not isinstance(v, list)})
    gm = m["목표별"]["G-1"]
    print("   독립 수행:", gm["독립 수행"]); print("   도움 후 성공:", gm["도움 후 성공"]); print("   단서 사용:", gm["단서 사용"]); print("   반응 시간:", gm["반응 시간"])
    print("   연습 자극:", gm["연습 자극 독립 수행"], "/ 새 자극:", gm["새 자극 독립 수행"])
    cmp = metrics_engine.compare_with_previous(repo, s2.id, s1.id); print("   이전 회기 비교:", cmp["비교 가능 범위"], cmp["경고"], cmp["목표별 변화"]["G-1"]["독립 수행 변화(%p)"])
    try:
        ss.finalize_result(repo, slp, s2.id, "…")
    except ValueError as e:
        print("   확정 차단 →", e)
    ss.finalize_result(repo, slp, s2.id, "회기 2: 연습 자극에서 독립 반응 증가, 새 자극(빗·열쇠)은 보류·수집실패로 자료 없음. 단서 효과는 반복 제시 영향으로 확정 불가.", acknowledge_holds=True)
    print("   회기 상태:", repo.sessions[s2.id].state.value, "/ 결과 v", repo.sessions[s2.id].result_version)

    # ---- ③ 다음 계획 (실습생 초안 → 지도자 승인 흐름)
    print("\n" + "=" * 80); print("E. ③ 다음 계획 — 제안 카드")
    plan = pl.build_plan(repo, trn, s2.id, prev_session_id=s1.id)
    for pr in plan.proposals:
        print(f"   [{pr.rule_key}] {pr.title} | 상태 {pr.decision.value} | 근거: {pr.rationale_data} | 판단 제한: {pr.uncertainty} | {pr.evidence_label()} | 관련 문항 {len(pr.related_trial_ids)}개")
    for pr in plan.proposals:
        pl.decide_proposal(repo, trn, plan.id, pr.id, ProposalDecision.ACCEPTED if pr.rule_key != "FATIGUE" else ProposalDecision.REJECTED)
    try:
        pl.approve_plan(repo, trn, plan.id)
    except PermissionError_ as e:
        print("   실습생 승인 시도 →", e)
    pl.request_supervisor_approval(repo, trn, plan.id)
    pl.supervisor_feedback(repo, sup, plan.id, "새 자극 확인 제안 적절. 승인.", approve=True)
    print("   계획 상태:", plan.state.value, "/ 승인자", plan.approved_by, "/ 회기 상태", repo.sessions[s2.id].state.value)
    print("\n" + plan.document_draft)

    # ---- 가정 연습 배정(승인만으로 자동 배정되지 않음)
    print("\n" + "=" * 80); print("F. 가정 연습")
    print("   승인 직후 배정 수:", len(repo.home_assignments))
    target = next(pr for pr in plan.proposals if pr.rule_key in ("CUE_DEPENDENT", "NO_PROBE", "INDEP_INCREASED", "GENERALIZATION"))
    try:
        pl.assign_home_practice(repo, slp, plan.id, target.id, ["답을 대신 말해주기"], "힘들면 멈추기")
    except ValueError as e:
        print("   보호자 안내 검증 →", e)
    ha = pl.assign_home_practice(repo, slp, plan.id, target.id, ["5초 기다리기", "두 개 중 고르게 하기", "표현한 내용 확인해 주기"], "3개 연속 어려우면 오늘은 여기까지")
    print("   대상자 오늘 화면:", json.dumps(reports.patient_today_view(repo, p.id), ensure_ascii=False))
    hr = HomePracticeReport(new_id("HR"), ha.id, "2026-10-20", False, "배우자", HelpLevel.CHOICES_GIVEN, "거실, TV 켜짐", [], [{"who": "마트 직원", "msg": "우유 주세요", "delivered": "예"}])
    repo.home_reports[hr.id] = hr
    print(reports.home_practice_report(repo, hr.id))

    # ---- 확정 후 문항 수정 → 기초 결과 변경 → 재승인 요구
    print("\n" + "=" * 80); print("G. 확정 후 수정 처리")
    rv.review_trial(repo, slp, t2[0].id, expected_row_version=repo.trials[t2[0].id].row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.OTHER_RESPONSE, modification_reason=ModificationReason.CRITERION_ERROR)
    print("   회기 상태:", repo.sessions[s2.id].state.value, "/ 결과 v", repo.sessions[s2.id].result_version, "/ 계획 상태:", plan.state.value)
    try:
        pl.approve_plan(repo, slp, plan.id)
    except ValueError as e:
        print("   재승인 차단 →", e)

    # ---- 보고서
    print("\n" + "=" * 80); print("H. 회기 결과보고서(기관 서식)")
    print(reports.session_report(repo, s2.id, s1.id, repo.orgs["ORG-1"].report_template))
    print("\n" + "=" * 80); print("I. 회기 전 계획서"); print(ss.pre_session_plan_document(repo, s2.id))
    print("\n" + "=" * 80); print("J. 아직 확보해야 할 근거(조사 완료로 표시하지 않음)")
    for v in repo.validation_items.values():
        print(f"   [{v.status}] {v.key}: {v.required_material} — {v.reason}")
    repo.path = os.path.join(os.path.dirname(__file__), "demo_state.json"); repo.persist()
    print("\n상태 저장:", repo.path)


if __name__ == "__main__":
    main()
