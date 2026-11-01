"""
열거형 정의. 문서(기획서·자료수집·UI명세)에서 요구한 상태값을 그대로 코드로 고정한다.
- "미입력"을 "정상"으로 해석하지 않기 위해 모든 정보에 InfoStatus 를 붙인다.
- "인식하지 못함"을 "대상자가 틀림"으로 처리하지 않기 위해 AnalysisStatus / TrialUsage 를 분리한다.
"""
from enum import Enum


class Role(str, Enum):
    THERAPIST = "언어재활사"
    ORG_ADMIN = "병원·치료실 관리자"
    TRAINEE = "실습생"
    SUPERVISOR = "지도자·슈퍼바이저"
    PATIENT = "대상자"
    CAREGIVER = "보호자·의사소통 상대자"


class ClinicalDomain(str, Enum):
    """장기적으로 다룰 임상 영역(중복 선택 가능). 하나의 범주로 묶어 자동 처리하지 않는다."""
    APHASIA = "실어증"
    DYSARTHRIA = "마비말장애"
    AOS = "후천성 말실행증"
    COGNITIVE_COMMUNICATION = "인지-의사소통장애"
    AAC = "보완대체의사소통 지원"
    # 확장 영역(초기 제품에서 지원을 약속하지 않음)
    DEVELOPMENTAL_ADULT = "발달성 장애 성인(확장)"
    FLUENCY = "유창성장애(확장)"
    VOICE = "음성장애(확장)"


PHASE1_SUPPORTED_DOMAINS = {ClinicalDomain.APHASIA}
EXTENSION_DOMAINS = {ClinicalDomain.DEVELOPMENTAL_ADULT, ClinicalDomain.FLUENCY, ClinicalDomain.VOICE}


class InfoSource(str, Enum):
    """정보 출처 구분: AI 추정이 진단 사실처럼 저장되는 것을 막는다."""
    MEDICAL_RECORD = "의무기록에서 확인"
    THERAPIST_OBSERVED = "치료사 직접 관찰"
    SELF_OR_CAREGIVER_REPORT = "대상자·보호자 보고"
    AI_SUGGESTED_UNCONFIRMED = "AI 제안(미확인)"


class InfoStatus(str, Enum):
    CONFIRMED = "확인됨"
    REPORTED = "보고받음"
    OBSERVED = "관찰됨"
    UNCONFIRMED = "미확인"
    NOT_ENTERED = "미입력"   # 절대 '정상'으로 해석하지 않는다


class ResponseMode(str, Enum):
    SPEECH = "말하기"
    PICTURE_SELECT = "그림 선택"
    READING = "읽기"
    WRITING = "쓰기"
    GESTURE = "몸짓"
    AAC = "AAC(사진·글자·선택판)"


class CueType(str, Enum):
    NONE = "없음"
    SEMANTIC = "의미 단서"
    PHONEMIC = "소리 단서"
    PICTURE = "그림"
    WRITTEN = "글자"
    MODEL = "모델 제시"
    REPEAT_STIMULUS = "재청취"
    CHOICE = "선택지 제공"


class ProductionCondition(str, Enum):
    """말운동 영역: 모든 성공을 독립 산출로 계산하지 않기 위한 산출 조건."""
    INDEPENDENT = "혼자 말하기"
    IMITATION_AUDIO = "모델 보고 따라 말하기(음성만)"
    IMITATION_AUDIO_VIDEO = "모델 보고 따라 말하기(음성+영상)"
    SIMULTANEOUS = "함께 말하기"


class FirstResponseJudgement(str, Enum):
    INDEPENDENT_SUCCESS = "독립 성공"
    OTHER_RESPONSE = "다른 반응"
    NO_RESPONSE = "무반응"
    HOLD = "판정 보류"


class PostCueJudgement(str, Enum):
    SUCCESS = "성공"
    OTHER_RESPONSE = "다른 반응"
    NO_RESPONSE = "무반응"
    HOLD = "판정 보류"
    NOT_APPLICABLE = "해당 없음"


class ObservationTag(str, Enum):
    """'다른 반응'을 단순 실패로 다루지 않기 위한 관찰 태그. 진단·오류유형 자동 확정에 사용하지 않는다."""
    FUNCTION_INSTEAD_OF_NAME = "이름 대신 용도 설명"
    RELATED_WORD = "관련 단어 표현"
    PARTIAL = "부분 반응"
    SELF_CORRECTION = "자기수정"
    OTHER = "기타 관찰"


class ModificationReason(str, Enum):
    TRANSCRIPT_ERROR = "전사 오류"
    CRITERION_ERROR = "기준 적용 오류"
    OTHER = "기타"


class RecordingQuality(str, Enum):
    ANALYZABLE = "분석 가능"
    RERECORD = "재녹음"
    NEEDS_REVIEW = "검토 필요"


class RecordingIssue(str, Enum):
    CLIPPED = "잘림"
    OVERLAP = "겹치는 말"
    NOISE = "잡음"
    LOW_VOLUME = "음량 부족"
    MISSING = "녹음 누락"


class AnalysisStatus(str, Enum):
    """분석 상태(최소 4가지 + 추가 구분)."""
    AUTO_DONE_REVIEWED = "자동 분석 후 검토 완료"
    AUTO_DONE_PENDING = "자동 분석 후 검토 대기"
    THERAPIST_REVIEW_REQUIRED = "치료사 확인 필요"
    POOR_RECORDING = "녹음 품질 부족"
    OUT_OF_SCOPE = "현재 모델의 검증 범위 밖"
    NOT_ANALYZED = "분석 대기"  # AI 분석이 아직 없음 → 원음 기반 수동 검토 허용


class TrialUsage(str, Enum):
    """자료 사용 여부. 수집 실패를 대상자의 오반응으로 계산하지 않는다."""
    INCLUDED = "결과에 포함"
    EXCLUDED = "결과에서 제외"
    HOLD = "보류"


class CollectionOutcome(str, Enum):
    COLLECTED = "수집됨"
    PATIENT_NO_RESPONSE = "대상자 무반응"   # 과제 반응으로 기록
    COLLECTION_FAILURE = "수집 실패"       # 오반응으로 계산하지 않음


class ReviewStatus(str, Enum):
    UNREVIEWED = "미검토"
    IN_REVIEW = "검토 중"
    REVIEWED = "검토 완료"
    NEEDS_CHECK = "확인 필요"
    MODIFIED = "수정됨"
    HOLD = "판정 보류"
    EXCLUDED = "제외"
    RECHECK = "재확인 필요"   # 채점 기준 변경 또는 확정 후 수정 시


class SessionState(str, Enum):
    """확정 상태: 검토 중 → 회기 결과 확정 → 계획 승인 (각 단계에 작성자·승인자·시간 기록)"""
    PLANNED = "계획됨"
    IN_PROGRESS = "실시 중"
    REVIEWING = "검토 중"
    RESULT_FINALIZED = "회기 결과 확정"
    PLAN_APPROVED = "계획 승인"
    BASIS_CHANGED = "기초 결과 변경됨"  # 확정 후 문항 수정 → 재승인 요구


class PlanState(str, Enum):
    DRAFT = "초안"
    EDITING = "수정 중"
    PENDING_SUPERVISOR = "지도자 승인 대기"
    APPROVED = "확정"
    REAPPROVAL_REQUIRED = "재승인 필요"


class ProposalDecision(str, Enum):
    PENDING = "AI 초안"
    ACCEPTED = "수락"
    MODIFIED = "수정"
    REJECTED = "채택하지 않음"


class GoalType(str, Enum):
    IMPROVEMENT = "기능 향상"
    MAINTENANCE = "기능 유지"           # 진행성 질환·중증
    COMPENSATION = "보상 수단 사용"      # AAC 등
    PARTICIPATION = "활동·참여"


class Setting(str, Enum):
    CLINIC = "치료실"
    HOME = "가정"


class HelpLevel(str, Enum):
    """가정 연습 도움 기록: 안내만 / 선택지 / 답 대신 제공"""
    NONE = "도움 없음"
    GUIDANCE_ONLY = "안내만 함"
    CHOICES_GIVEN = "선택지 제공"
    ANSWER_GIVEN = "답을 대신 제공"


class StimulusPurpose(str, Enum):
    PRACTICE = "연습용"
    PROBE = "새 자극 확인용"
    MAINTENANCE = "유지 확인용"


class ConsentType(str, Enum):
    SERVICE = "서비스 이용 동의"
    RESEARCH_TRAINING = "연구·모델 학습 이용 동의"   # 서비스 이용 동의와 분리
    CAREGIVER_VIEW = "보호자 열람 동의"
    EXTERNAL_AI_TRANSFER = "외부 AI 서비스 전송 동의"
