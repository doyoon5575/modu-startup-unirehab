"""
필수 데이터 객체: 대상자 → 평가 → 목표 → 회기 → 활동 → 문항별 시도 → 분석 → 검토 → 계획
별도 관리: 과제·자료 버전, 분석 모델 버전, 목표·계획 변경 이력, AI 결과와 치료사 수정값, 동의 범위와 접근 이력, 기관별 서식
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from .enums import *


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Base:
    def to_dict(self) -> Dict[str, Any]:
        def conv(o):
            if isinstance(o, Enum):
                return o.value
            if isinstance(o, list):
                return [conv(x) for x in o]
            if isinstance(o, dict):
                return {k: conv(v) for k, v in o.items()}
            if hasattr(o, "__dataclass_fields__"):
                return {k: conv(v) for k, v in asdict(o).items()}
            return o
        return conv(self)


# ---------------------------------------------------------------- 사용자·기관·동의
@dataclass
class Organization(Base):
    id: str
    name: str
    report_template: Dict[str, Any] = field(default_factory=dict)   # 기관별 서식
    data_partition: str = ""                                          # 기관 간 데이터 분리 키


@dataclass
class User(Base):
    id: str
    name: str
    role: Role
    org_id: str
    supervisor_id: Optional[str] = None     # 실습생 → 지도자
    clinical_access: bool = True            # 관리자는 임상정보 접근 별도 권한


@dataclass
class Consent(Base):
    id: str
    patient_id: str
    consent_type: ConsentType
    granted: bool
    granted_at: str
    scope_note: str = ""                    # 보호자 열람 허용 범위 등


@dataclass
class AccessLog(Base):
    id: str
    user_id: str
    patient_id: str
    action: str
    at: str


# ---------------------------------------------------------------- 대상자·프로필
@dataclass
class InfoField(Base):
    """모든 프로필 항목은 값 + 출처 + 확인 상태를 함께 가진다."""
    value: Optional[str] = None
    source: Optional[InfoSource] = None
    status: InfoStatus = InfoStatus.NOT_ENTERED
    confirmed_by: Optional[str] = None
    document_ref: Optional[str] = None

    def display(self) -> str:
        # "청력 정상"이 아니라 "청력 관련 정보 미입력"으로 표시
        if self.status == InfoStatus.NOT_ENTERED or self.value in (None, ""):
            return "정보 미입력"
        return f"{self.value} ({self.status.value}·{self.source.value if self.source else '출처 미기재'})"


@dataclass
class FunctionalProfile(Base):
    """같은 진단명 안에서도 기능을 나누어 입력한다 (문서 2-2, 자료수집 '입력 화면에 필요한 항목')."""
    # 언어 이해
    word_comprehension: InfoField = field(default_factory=InfoField)
    sentence_comprehension: InfoField = field(default_factory=InfoField)
    discourse_comprehension: InfoField = field(default_factory=InfoField)
    # 표현
    naming: InfoField = field(default_factory=InfoField)
    sentence_production: InfoField = field(default_factory=InfoField)
    conversation: InfoField = field(default_factory=InfoField)
    writing: InfoField = field(default_factory=InfoField)
    gesture: InfoField = field(default_factory=InfoField)
    reading_aloud: InfoField = field(default_factory=InfoField)
    reading_comprehension: InfoField = field(default_factory=InfoField)
    aac_use: InfoField = field(default_factory=InfoField)
    # 말 산출(치료사 관찰)
    articulation: InfoField = field(default_factory=InfoField)
    speech_rate: InfoField = field(default_factory=InfoField)
    voice: InfoField = field(default_factory=InfoField)
    prosody: InfoField = field(default_factory=InfoField)
    respiration: InfoField = field(default_factory=InfoField)
    resonance: InfoField = field(default_factory=InfoField)
    intelligibility_clinician_rating: InfoField = field(default_factory=InfoField)
    # 인지-의사소통
    attention: InfoField = field(default_factory=InfoField)
    memory: InfoField = field(default_factory=InfoField)
    organization: InfoField = field(default_factory=InfoField)
    # 7개 질문(2-2)
    can_select_picture_when_speech_hard: InfoField = field(default_factory=InfoField)
    word_vs_long_sentence: InfoField = field(default_factory=InfoField)
    sound_vs_word_retrieval: InfoField = field(default_factory=InfoField)
    reading_writing_as_support: InfoField = field(default_factory=InfoField)
    needs_time_to_answer: InfoField = field(default_factory=InfoField)
    helpful_cues: List[CueType] = field(default_factory=list)
    most_needed_situations: List[str] = field(default_factory=list)
    # 수행에 영향을 주는 조건·접근성
    hearing: InfoField = field(default_factory=InfoField)
    vision: InfoField = field(default_factory=InfoField)
    motor_access: InfoField = field(default_factory=InfoField)
    fatigue: InfoField = field(default_factory=InfoField)
    device_support_needed: InfoField = field(default_factory=InfoField)
    touch_difficulty: InfoField = field(default_factory=InfoField)
    recording_difficulty: InfoField = field(default_factory=InfoField)
    # 접근성 설정
    font_scale: float = 1.0
    large_buttons: bool = False
    alternative_input: Optional[str] = None


@dataclass
class ClinicalBackground(Base):
    diagnoses: List[Dict[str, Any]] = field(default_factory=list)  # {name, source, status, confirmed_by, document}
    onset_date: InfoField = field(default_factory=InfoField)
    course: InfoField = field(default_factory=InfoField)
    assessment_date: InfoField = field(default_factory=InfoField)
    assume_cognitive_impairment: bool = False  # 실어증이라는 이유만으로 인지장애를 전제하지 않음(항상 False 기본)


@dataclass
class LifeGoal(Base):
    id: str
    who: str
    where: str
    what: str
    priority: int = 1
    reported_by: InfoSource = InfoSource.SELF_OR_CAREGIVER_REPORT


@dataclass
class HomeEnvironment(Base):
    devices: InfoField = field(default_factory=InfoField)
    helper: InfoField = field(default_factory=InfoField)
    practice_time: InfoField = field(default_factory=InfoField)
    practice_situations: InfoField = field(default_factory=InfoField)


@dataclass
class StandardizedTestScore(Base):
    """표준화검사: 점수 입력·정리만 지원. 검사 문항 탑재는 권리 확인 후 별도(ContentRights)."""
    test_name: str
    administered_on: str
    scores: Dict[str, Any]
    administered_by: str
    note: str = ""


@dataclass
class Patient(Base):
    id: str
    org_id: str
    code: str                        # 식별 코드(개인정보 최소 표시)
    name_masked: str = ""
    age: InfoField = field(default_factory=InfoField)
    primary_language: InfoField = field(default_factory=InfoField)
    education_occupation: InfoField = field(default_factory=InfoField)
    domains: List[ClinicalDomain] = field(default_factory=list)   # 중복 선택
    clinical: ClinicalBackground = field(default_factory=ClinicalBackground)
    profile: FunctionalProfile = field(default_factory=FunctionalProfile)
    life_goals: List[LifeGoal] = field(default_factory=list)
    home: HomeEnvironment = field(default_factory=HomeEnvironment)
    standardized_tests: List[StandardizedTestScore] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    speech_samples: List[str] = field(default_factory=list)
    assigned_therapist_id: Optional[str] = None
    assigned_trainee_id: Optional[str] = None
    aac_board: List[Dict[str, str]] = field(default_factory=list)   # 개인별 표현판: 사람·장소·요구·거절·질문
    created_at: str = field(default_factory=now)


# ---------------------------------------------------------------- 평가·목표
@dataclass
class Assessment(Base):
    id: str
    patient_id: str
    date: str
    assessor_id: str
    domain_observations: Dict[str, str] = field(default_factory=dict)
    structured_task_results: List[Dict[str, Any]] = field(default_factory=list)
    baseline: Dict[str, Any] = field(default_factory=dict)    # 기능 프로필·기초선


@dataclass
class GoalVersion(Base):
    version: int
    text: str
    changed_by: str
    changed_at: str
    reason: str


@dataclass
class Goal(Base):
    """목표 작성 틀: 대상자는 [상황·자료]에서 [도움 조건]으로 [달성 기준]에 따라 [목표 행동]한다. 목표 하나 = 핵심 행동 하나."""
    id: str
    patient_id: str
    goal_type: GoalType
    long_term: bool
    parent_goal_id: Optional[str]
    context_material: str          # 상황·자료
    support_condition: str         # 도움 조건
    criterion: str                 # 달성 기준(치료사가 기초선과 개인 목표로 정함; 80%가 보편 기준이라는 뜻 아님)
    target_behavior: str           # 목표 행동
    indicator: str                 # 측정 지표
    response_mode: ResponseMode
    linked_life_goal_ids: List[str] = field(default_factory=list)
    linked_domain: Optional[ClinicalDomain] = None
    status: str = "활성"
    history: List[GoalVersion] = field(default_factory=list)
    created_by: str = ""
    approved_by: Optional[str] = None

    def sentence(self) -> str:
        return f"대상자는 {self.context_material}에서 {self.support_condition}으로 {self.criterion}에 따라 {self.target_behavior}."


# ---------------------------------------------------------------- 콘텐츠·근거
@dataclass
class ContentRights(Base):
    license: str = "미확인"
    redistribution_allowed: Optional[bool] = None
    modification_allowed: Optional[bool] = None
    verified_by: Optional[str] = None


@dataclass
class Stimulus(Base):
    """콘텐츠마다 붙이는 정보(자료수집 '생활 과제를 치료로 설계')."""
    id: str
    version: int
    label: str
    media_ref: str
    linked_goal_function: str
    response_mode: ResponseMode
    familiarity: str                   # 친숙도
    personal_relevance: str            # 개인적 관련성
    length_complexity: str             # 음절·단어·구·문장, 언어적 복잡도
    allowed_cues: List[CueType]
    cue_order: List[CueType]
    accepted_expressions: List[str]    # 허용하는 표현
    needs_review_expressions: List[str]  # 치료사 확인이 필요한 표현
    purpose: StimulusPurpose
    rights: ContentRights = field(default_factory=ContentRights)
    situation: Optional[str] = None    # 예: 마트 장보기


@dataclass
class ScoringCriterion(Base):
    id: str
    version: int
    description: str
    accepted_expressions_policy: str
    cue_conditions: str
    changed_by: str
    changed_at: str


@dataclass
class EvidenceItem(Base):
    """근거 자료 저장 형식(기획서 11장) + 자료 추가 묶음(자료수집 마지막 절)."""
    id: str
    title: str
    target_population: str          # 적용 대상: 장애 영역·중증도·발병 단계
    target_function: str            # 목표 기능
    intervention: str               # 중재 내용: 절차·자극·단서·실시 조건
    evidence_level: str             # 지침·체계적 문헌고찰·개별 연구 등
    outcome_measures: str           # 연구에서 실제 측정한 내용
    limitations: str                # 한국어 적용 여부, 표본·환경의 한계
    korean_applicability: str       # 확인됨 / 미확인 / 부분
    usage_rights: str               # 문항·이미지·검사자료 사용 범위
    linked_feature: str             # 연결할 서비스 기능
    reviewer: str = ""
    reviewed_at: str = ""
    update_status: str = "검토 필요"
    url: str = ""
    approach_key: str = ""          # SFA, PCA, VNeST, SCRIPT, READING_SUPPORT, PARTNER_TRAINING ...
    verified_effect_in_app: bool = False   # 앱 기능의 치료 효과 검증 여부(항상 별도)


# ---------------------------------------------------------------- 회기·활동·시도
@dataclass
class Activity(Base):
    id: str
    session_id: str
    goal_id: str
    name: str
    approach_key: str                       # 치료사가 선택한 접근(표시 문구: '치료사가 선택한 접근에 기반한 연습')
    stimulus_ids: List[str]
    response_mode: ResponseMode
    cue_sequence: List[CueType]             # 단서 제공 순서
    target_response_form: str
    error_no_response_handling: str         # 오반응·무반응 대응
    measurement_method: str
    production_condition: ProductionCondition = ProductionCondition.INDEPENDENT
    length_level: str = "단어"
    rate_rhythm_support: Optional[str] = None
    feedback_setting: Dict[str, Any] = field(default_factory=lambda: {"timing": "즉시", "frequency": "매 문항", "type": "정답 안내"})
    rest_stop_condition: str = ""
    order_in_session: int = 1
    planned: bool = True
    actually_performed: bool = False


@dataclass
class TimingMarks(Base):
    """세 시간을 분리: 자극→첫 반응 / 단서→재반응 / 발화 시작→목표 반응 완성. 측정 기준(무엇부터 무엇까지)을 항상 명시."""
    stimulus_end_s: Optional[float] = None
    first_speech_onset_s: Optional[float] = None
    cue_given_s: Optional[float] = None
    post_cue_onset_s: Optional[float] = None
    target_completed_s: Optional[float] = None
    definition: str = "자극 음성 종료 → 첫 발화 시작"
    exclusion_rule: str = "기침·헛기침·타인의 말·목표 반응 전 비언어 소리는 발화 시작으로 보지 않음"
    auto_values: Dict[str, Optional[float]] = field(default_factory=dict)   # 원래 자동 측정값 보존
    corrected_by: Optional[str] = None

    def response_latency(self) -> Optional[float]:
        if self.stimulus_end_s is None or self.first_speech_onset_s is None:
            return None
        return round(self.first_speech_onset_s - self.stimulus_end_s, 2)

    def post_cue_latency(self) -> Optional[float]:
        if self.cue_given_s is None or self.post_cue_onset_s is None:
            return None
        return round(self.post_cue_onset_s - self.cue_given_s, 2)

    def completion_duration(self) -> Optional[float]:
        onset = self.post_cue_onset_s or self.first_speech_onset_s
        if onset is None or self.target_completed_s is None:
            return None
        return round(self.target_completed_s - onset, 2)


@dataclass
class AttemptRecord(Base):
    """시도 단위(최초 / 단서 후 / 재시도). 첫 반응과 도움 후 반응을 덮어쓰지 않고 모두 남긴다."""
    attempt_type: str                       # 최초 반응 / 단서 후 반응 / 재시도
    audio_ref: Optional[str]
    audio_start_s: Optional[float]
    audio_end_s: Optional[float]
    ai_transcript: Optional[str] = None     # 읽기 전용 보존
    therapist_transcript: Optional[str] = None
    cue_before: CueType = CueType.NONE
    cue_given_at: Optional[str] = None
    ai_target_match: Optional[bool] = None  # '목표어와 맞는지' (실제 전사와 분리)
    ai_classification: Optional[str] = None # '자동 분석 제안' 배지
    ai_confidence: Optional[float] = None


@dataclass
class AutoAnalysis(Base):
    model_version: str
    recording_quality: RecordingQuality
    recording_issues: List[RecordingIssue]
    status: AnalysisStatus
    limits: List[str]                     # 분석 제한 사유
    speech_rate: Optional[float] = None   # 정의한 단위에 따른 속도
    speech_rate_unit: str = "음절/초(쉼 제외)"
    speech_rate_segment: str = ""
    repetitions: List[Dict[str, Any]] = field(default_factory=list)   # 반복·쉼 사건과 위치(관찰값, 자동 분류 금지)
    pauses: List[Dict[str, Any]] = field(default_factory=list)
    analyzed_at: str = field(default_factory=now)


@dataclass
class ReviewVersion(Base):
    version: int
    reviewer_id: str
    at: str
    previous: Dict[str, Any]
    current: Dict[str, Any]
    reason: Optional[ModificationReason]
    note: str = ""


@dataclass
class TherapistReview(Base):
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    usage: TrialUsage = TrialUsage.INCLUDED
    exclusion_reason: Optional[str] = None
    first_judgement: Optional[FirstResponseJudgement] = None
    cues_given: List[CueType] = field(default_factory=list)
    post_cue_judgement: Optional[PostCueJudgement] = None
    observation_tags: List[ObservationTag] = field(default_factory=list)
    observation_note: str = ""
    hold_reason: Optional[str] = None
    modification_reason: Optional[ModificationReason] = None
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    history: List[ReviewVersion] = field(default_factory=list)
    clinician_speech_ratings: Dict[str, Any] = field(default_factory=dict)  # 말 특성 평가(평가자·조건 포함)


@dataclass
class Trial(Base):
    """문항별 시도 — 기본 저장 단위."""
    id: str
    session_id: str
    activity_id: str
    goal_id: str
    stimulus_id: str
    stimulus_version: int
    order: int
    presentation_mode: str
    presented_at: str
    response_mode: ResponseMode
    setting: Setting
    collection: CollectionOutcome
    attempts: List[AttemptRecord]
    timing: TimingMarks
    analysis: Optional[AutoAnalysis]
    review: TherapistReview = field(default_factory=TherapistReview)
    scoring_criterion_id: str = ""
    scoring_criterion_version: int = 1
    helper: Optional[str] = None                # 가정: 도움 제공자
    help_level: HelpLevel = HelpLevel.NONE
    distractions: str = ""
    production_condition: ProductionCondition = ProductionCondition.INDEPENDENT
    stimulus_purpose: StimulusPurpose = StimulusPurpose.PRACTICE
    note: str = ""
    row_version: int = 1                        # 동시 수정 충돌 감지


@dataclass
class StateTransition(Base):
    from_state: str
    to_state: str
    actor_id: str
    at: str
    note: str = ""


@dataclass
class Session(Base):
    id: str
    patient_id: str
    date: str
    setting: Setting
    therapist_id: str
    goal_ids: List[str]
    state: SessionState = SessionState.PLANNED
    transitions: List[StateTransition] = field(default_factory=list)
    therapist_interpretation: str = ""
    result_finalized_by: Optional[str] = None
    result_finalized_at: Optional[str] = None
    result_version: int = 0
    rest_stop_condition: str = ""
    author_id: Optional[str] = None
    reviewer_id: Optional[str] = None
    created_by_role: Optional[Role] = None


# ---------------------------------------------------------------- 계획·제안·가정연습
@dataclass
class Proposal(Base):
    id: str
    plan_id: str
    title: str
    linked_goal_id: str
    rationale_data: str                 # 관찰 데이터에 근거한 이유
    related_trial_ids: List[str]        # [관련 문항 보기]
    activity_draft: str                 # 치료사가 편집 가능
    uncertainty: str                    # 판단 제한
    needs_confirmation: str             # 치료사 확인 필요 항목
    evidence_ids: List[str]             # 비어 있으면 '근거 자료 연결 필요'
    rule_key: str
    precheck_condition: str             # 먼저 확인할 조건
    decision: ProposalDecision = ProposalDecision.PENDING
    therapist_edit: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None

    def evidence_label(self) -> str:
        return "근거 자료 연결됨" if self.evidence_ids else "근거 자료 연결 필요"


@dataclass
class NextSessionPlan(Base):
    id: str
    patient_id: str
    based_on_session_id: str
    based_on_result_version: int
    state: PlanState
    goals_to_keep: List[Dict[str, str]]       # 유지할 목표 + 이전 목표와 연결된 이유
    conditions_to_change: List[Dict[str, str]]  # 자극·도움·분량·반응 방식 중 변경 대상
    selection_rationale: str                   # 어떤 수행 데이터가 변경을 뒷받침하는지
    probe_tasks: List[str]                     # 새 자극·유지·다른 상황 확인
    home_practice_candidates: List[str]
    stop_adjust_conditions: str
    proposals: List[Proposal]
    document_draft: str                        # LLM/템플릿 문서화 결과(확인된 데이터만)
    author_id: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    supervisor_feedback: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class HomeAssignment(Base):
    """승인된 활동만 별도 선택해 배정. 계획 승인만으로 자동 배정되지 않는다."""
    id: str
    patient_id: str
    plan_id: str
    proposal_id: str
    activity_description: str
    caregiver_guidance: List[str]          # 승인된 안내: 기다리기, 선택지 제공, 표현 확인 등
    stop_rule: str                          # 어려우면 멈추는 방법
    assigned_by: str
    assigned_at: str
    offline_fallback: str = "녹음·네트워크가 작동하지 않으면 종이 표현판·체크표로 수행 후 다음 방문 시 입력"


@dataclass
class HomePracticeReport(Base):
    id: str
    assignment_id: str
    performed_at: str
    performed_alone: bool
    helper: Optional[str]
    help_level: HelpLevel
    environment_note: str
    trial_ids: List[str]
    life_goal_events: List[Dict[str, str]] = field(default_factory=list)  # 누구와 어떤 상황에서 메시지 전달


@dataclass
class ValidationItem(Base):
    """아직 확보해야 할 근거(자료수집 문서). '조사 완료'로 표시하지 않는다."""
    key: str
    required_material: str
    reason: str
    status: str = "미확보"
