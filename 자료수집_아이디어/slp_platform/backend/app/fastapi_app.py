"""
현대적인 고성능 비동기 FastAPI 애플리케이션 엔트리포인트.
- Vercel Serverless, AWS Lambda, Supabase Functions 또는 Docker(Cloud Run) 배포를 지원합니다.
- CORS 미들웨어, 헬스체크, 의존성 주입(DI), 역할별 권한 검증 탑재.
- Phase 1 (예비 언어재활사 모의임상 API) 및 Phase 2 (성인 라이프스킬 교구 API) 확장 라우트 포함.
"""
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .enums import *
from .repository import Repo, SaveError, ConflictError
from .models import User
from . import review_service, session_service, planner, reports, metrics_engine
from .llm_adapters import VirtualPatientSimulator, AdultLifeSkillGenerator, GeminiClinicalWriterAdapter
from .speech_adapters_production import WhisperAPIAdapter

app = FastAPI(
    title="Unione Rehab API (유니원 라랩 임상·실습 플랫폼)",
    description="예비 언어재활사 가상환자 모의임상 및 성인 발달장애 주간활동 자립 소통 지원 REST API",
    version="1.0.0"
)

# CORS 설정 (개발 환경 및 Vercel 프론트엔드 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 인메모리 싱글톤 저장소 (데모 및 테스트용, 프로덕션에서는 Supabase/PostgreSQL 연동)
_global_repo: Optional[Repo] = None
_global_users: Dict[str, User] = {}
_patient_simulator = VirtualPatientSimulator()
_lifeskill_generator = AdultLifeSkillGenerator()
_clinical_writer = GeminiClinicalWriterAdapter()
_speech_adapter = WhisperAPIAdapter()

def set_app_context(repo: Repo, users: Dict[str, User]):
    global _global_repo, _global_users
    _global_repo = repo
    _global_users = users

def get_repo() -> Repo:
    if _global_repo is None:
        raise HTTPException(status_code=503, detail="Repository not initialized")
    return _global_repo

def get_current_user(x_user_id: Optional[str] = Header(None)) -> User:
    if not x_user_id or x_user_id not in _global_users:
        raise HTTPException(status_code=401, detail="인증되지 않은 사용자입니다 (X-User-Id 헤더 필요)")
    return _global_users[x_user_id]


# --- Pydantic 요청 스키마 정의 ---
class ReviewRequest(BaseModel):
    row_version: int
    usage: str
    exclusion_reason: Optional[str] = None
    first: Optional[str] = None
    cues: List[str] = Field(default_factory=list)
    post: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    note: str = ""
    transcripts: Optional[Dict[str, str]] = None
    onset: Optional[Dict[str, float]] = None
    reason: Optional[str] = None
    hold_reason: Optional[str] = None

class FinalizeRequest(BaseModel):
    interpretation: str = ""
    acknowledge_holds: bool = False

class ProposalDecisionRequest(BaseModel):
    decision: str
    edit: Optional[Dict[str, Any]] = None

class HomeAssignRequest(BaseModel):
    proposal_id: str
    guidance: List[str] = Field(default_factory=list)
    stop_rule: str = ""

class VirtualInteractionRequest(BaseModel):
    persona_key: str = "broca_aphasia"
    therapist_utterance: str

class LifeSkillTaskRequest(BaseModel):
    domain: str = "kiosk_ordering"
    difficulty: int = 1


# --- API 엔드포인트 정의 ---

@app.get("/health", tags=["시스템"])
def health_check():
    return {
        "status": "healthy",
        "service": "Unione Rehab Backend",
        "version": "1.0.0",
        "scope": "Phase 1 Pre-SLP + Phase 2 Adult Day-Care"
    }

# 1. 회기 및 문항 검토 (기존 api.py 호환)
@app.get("/api/sessions/{session_id}/review-summary", tags=["임상 검토"])
def get_review_summary(session_id: str, repo: Repo = Depends(get_repo)):
    return review_service.review_summary(repo, session_id)

@app.get("/api/sessions/{session_id}/trials", tags=["임상 검토"])
def get_trials(session_id: str, filter: str = Query("전체"), repo: Repo = Depends(get_repo)):
    ts = review_service.filter_trials(repo, session_id, filter)
    return [review_service.trial_card(t, repo.stimuli[t.stimulus_id].label) for t in ts]

@app.get("/api/trials/{trial_id}", tags=["임상 검토"])
def get_trial(trial_id: str, repo: Repo = Depends(get_repo)):
    if trial_id not in repo.trials:
        raise HTTPException(status_code=404, detail="문항을 찾을 수 없습니다")
    return repo.trials[trial_id].to_dict()

@app.post("/api/trials/{trial_id}/review", tags=["임상 검토"])
def post_review(trial_id: str, req: ReviewRequest, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    try:
        t = review_service.review_trial(
            repo, user, trial_id, expected_row_version=req.row_version,
            usage=TrialUsage(req.usage), exclusion_reason=req.exclusion_reason,
            first=FirstResponseJudgement(req.first) if req.first else None,
            cues=[CueType(c) for c in req.cues],
            post=PostCueJudgement(req.post) if req.post else None,
            tags=[ObservationTag(x) for x in req.tags], note=req.note,
            therapist_transcripts=req.transcripts, onset_correction=req.onset,
            modification_reason=ModificationReason(req.reason) if req.reason else None,
            hold_reason=req.hold_reason
        )
        return {"saved": True, "row_version": t.row_version, "status": t.review.review_status.value}
    except ConflictError as e:
        raise HTTPException(status_code=409, detail={"conflict": True, "error": str(e)})
    except SaveError as e:
        raise HTTPException(status_code=503, detail={"retry": True, "error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 2. 회기 결과 및 지표 산출
@app.get("/api/sessions/{session_id}/metrics", tags=["임상 지표"])
def get_metrics(session_id: str, repo: Repo = Depends(get_repo)):
    return metrics_engine.compute_session_metrics(repo, session_id)

@app.post("/api/sessions/{session_id}/finalize", tags=["임상 지표"])
def finalize_session(session_id: str, req: FinalizeRequest, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    try:
        s = session_service.finalize_result(repo, user, session_id, req.interpretation, req.acknowledge_holds)
        return {"state": s.state.value, "result_version": s.result_version}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 3. 차기 계획 및 가정 배정
@app.post("/api/sessions/{session_id}/plan", tags=["치료 계획"])
def build_next_plan(session_id: str, prev_session_id: Optional[str] = None, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    p = planner.build_plan(repo, user, session_id, prev_session_id)
    return p.to_dict()

@app.post("/api/plans/{plan_id}/proposals/{prop_id}", tags=["치료 계획"])
def decide_proposal(plan_id: str, prop_id: str, req: ProposalDecisionRequest, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    p = planner.decide_proposal(repo, user, plan_id, prop_id, ProposalDecision(req.decision), req.edit)
    return p.to_dict()

@app.post("/api/plans/{plan_id}/approve", tags=["치료 계획"])
def approve_plan(plan_id: str, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    p = planner.approve_plan(repo, user, plan_id)
    return {"state": p.state.value}

@app.post("/api/plans/{plan_id}/home-assign", tags=["치료 계획"])
def assign_home_practice(plan_id: str, req: HomeAssignRequest, user: User = Depends(get_current_user), repo: Repo = Depends(get_repo)):
    ha = planner.assign_home_practice(repo, user, plan_id, req.proposal_id, req.guidance, req.stop_rule)
    return ha.to_dict()

# 4. 보고서 및 환자 대시보드
@app.get("/api/sessions/{session_id}/report", tags=["보고서"])
def get_session_report(session_id: str, prev: Optional[str] = None, repo: Repo = Depends(get_repo)):
    return {"text": reports.session_report(repo, session_id, prev)}

@app.get("/api/patients/{patient_id}/today", tags=["대상자 화면"])
def get_patient_today(patient_id: str, repo: Repo = Depends(get_repo)):
    return reports.patient_today_view(repo, patient_id)


# --- [신규 확장 엔드포인트: Phase 1 & Phase 2] ---

@app.post("/api/simulator/interact", tags=["Phase 1: 예비 언어재활사 모의임상"])
def simulate_virtual_patient(req: VirtualInteractionRequest):
    """
    [Phase 1] 가상 환자 롤플레잉 모의 실습 엔드포인트.
    수련생의 질문에 대해 실어증/발달장애 페르소나의 반응 및 발화 잠재기를 반환합니다.
    """
    return _patient_simulator.interact(req.persona_key, req.therapist_utterance)

@app.post("/api/lifeskill/generate", tags=["Phase 2: 성인 발달장애 주간활동"])
def generate_lifeskill_mission(req: LifeSkillTaskRequest):
    """
    [Phase 2] 성인 발달장애인 주간활동센터 실생활 자립 퀘스트 생성 엔드포인트.
    키오스크 주문, 대중교통 등 비전문가(사회복지사)를 위한 지도 가이드와 함께 반환합니다.
    """
    return _lifeskill_generator.generate_task_kit(req.domain, req.difficulty)
