"""문서의 설계 원칙이 코드에서 강제되는지 확인하는 테스트."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.enums import *
from app.models import *
from app.repository import Repo, SaveError, ConflictError
from app.speech_analysis import analyze_trial, MockAdapter
from app import review_service as rv, session_service as ss, planner as pl, metrics_engine as me, evidence_repo
from app.permissions import PermissionError_
import demo


def world():
    repo, users, p, g, stims, crit = demo.build_world()
    return repo, users, p, g, stims, crit


def test_not_entered_is_not_normal():
    f = InfoField()
    assert f.display() == "정보 미입력"


def test_collection_failure_not_counted_as_error():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t="", col=CollectionOutcome.COLLECTION_FAILURE)] + [dict(t=x.label) for x in stims[1:]])
    assert ts[0].review.usage == TrialUsage.EXCLUDED
    for t in ts[1:]:
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    m = me.compute_session_metrics(repo, s.id)
    assert m["목표별"]["G-1"]["독립 수행"]["분모"] == 9   # 수집 실패는 분모에 들어가지 않음


def test_out_of_scope_gives_no_classification():
    repo, users, p, g, stims, crit = world()
    p.domains = [ClinicalDomain.DYSARTHRIA]
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    assert ts[0].analysis.status == AnalysisStatus.OUT_OF_SCOPE
    assert ts[0].attempts[0].ai_classification is None


def test_home_recording_out_of_scope():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims], setting=Setting.HOME)
    assert ts[0].analysis.status == AnalysisStatus.OUT_OF_SCOPE


def test_ai_transcript_preserved_and_separate():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t="치솔", c=0.5)] + [dict(t=x.label) for x in stims[1:]])
    t = ts[0]
    rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS, therapist_transcripts=["칫솔"], modification_reason=ModificationReason.TRANSCRIPT_ERROR)
    assert t.attempts[0].ai_transcript == "치솔" and t.attempts[0].therapist_transcript == "칫솔"
    assert len(t.review.history) == 1 and t.review.history[0].reason == ModificationReason.TRANSCRIPT_ERROR


def test_exclusion_requires_reason():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    try:
        rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=1, usage=TrialUsage.EXCLUDED); assert False
    except rv.ReviewError: pass


def test_save_failure_and_conflict():
    repo, users, p, g, stims, crit = demo.build_world(fail_first_save=True)
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    try:
        rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=1, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS); assert False
    except SaveError: pass
    rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=1, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    try:
        rv.review_trial(repo, users["trn"], ts[0].id, expected_row_version=1, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.OTHER_RESPONSE); assert False
    except ConflictError: pass


def test_finalize_blocked_by_unreviewed_and_holds():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    try:
        ss.finalize_result(repo, users["slp"], s.id, "x"); assert False
    except ValueError: pass
    for t in ts[1:]:
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=ts[0].row_version, usage=TrialUsage.HOLD, first=FirstResponseJudgement.HOLD, hold_reason="재청취")
    try:
        ss.finalize_result(repo, users["slp"], s.id, "x"); assert False
    except ValueError: pass
    ss.finalize_result(repo, users["slp"], s.id, "x", acknowledge_holds=True)
    assert repo.sessions[s.id].state == SessionState.RESULT_FINALIZED


def test_trainee_cannot_approve_and_plan_requires_decisions():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    for t in ts:
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    ss.finalize_result(repo, users["slp"], s.id, "x")
    plan = pl.build_plan(repo, users["trn"], s.id)
    try:
        pl.approve_plan(repo, users["trn"], plan.id); assert False
    except PermissionError_: pass
    try:
        pl.approve_plan(repo, users["slp"], plan.id); assert False   # 미결정 제안
    except ValueError: pass


def test_home_assignment_not_automatic_and_guidance_filtered():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    for t in ts:
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    ss.finalize_result(repo, users["slp"], s.id, "x")
    plan = pl.build_plan(repo, users["slp"], s.id)
    for pr in plan.proposals:
        pl.decide_proposal(repo, users["slp"], plan.id, pr.id, ProposalDecision.ACCEPTED)
    pl.approve_plan(repo, users["slp"], plan.id)
    assert len(repo.home_assignments) == 0
    try:
        pl.assign_home_practice(repo, users["slp"], plan.id, plan.proposals[0].id, ["답을 대신 말해주기"], "멈춤"); assert False
    except ValueError: pass


def test_finalized_edit_requires_reapproval():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    for t in ts:
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    ss.finalize_result(repo, users["slp"], s.id, "x")
    plan = pl.build_plan(repo, users["slp"], s.id)
    for pr in plan.proposals:
        pl.decide_proposal(repo, users["slp"], plan.id, pr.id, ProposalDecision.ACCEPTED)
    pl.approve_plan(repo, users["slp"], plan.id)
    rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=ts[0].row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.OTHER_RESPONSE, modification_reason=ModificationReason.CRITERION_ERROR)
    assert repo.sessions[s.id].state == SessionState.BASIS_CHANGED and plan.state == PlanState.REAPPROVAL_REQUIRED


def test_imitation_not_counted_as_independent():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    for t in ts:
        t.production_condition = ProductionCondition.IMITATION_AUDIO
        rv.review_trial(repo, users["slp"], t.id, expected_row_version=t.row_version, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    m = me.compute_session_metrics(repo, s.id)
    assert m["목표별"]["G-1"]["독립 수행"]["분모"] == 0


def test_criterion_change_flags_recheck():
    repo, users, p, g, stims, crit = world()
    s, ts = demo.run_session(repo, users, p, g, stims, crit, "2026-01-01", [dict(t=x.label) for x in stims])
    rv.review_trial(repo, users["slp"], ts[0].id, expected_row_version=1, usage=TrialUsage.INCLUDED, first=FirstResponseJudgement.INDEPENDENT_SUCCESS)
    flagged = rv.change_scoring_criterion(repo, users["slp"], s.id, ScoringCriterion("CR-1", 2, "v2", "", "", "slp", now()))
    assert flagged == [ts[0].id] and ts[0].review.review_status == ReviewStatus.RECHECK


def test_evidence_label_never_claims_verified_by_default():
    repo = Repo(); evidence_repo.seed_evidence(repo)
    for e in repo.evidence.values():
        assert evidence_repo.feature_label(e).startswith("치료사가 선택한 접근에 기반한 연습")


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for f in fns:
        f(); print("PASS", f.__name__)
    print(f"{len(fns)} tests passed")
