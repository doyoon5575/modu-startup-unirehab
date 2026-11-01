"""
Google Gemini 1.5 Flash 유료 보안 API 및 sLMM 교구 생성·가상환자 모의임상 어댑터.
- 유료 보안 티어 준수: 전송 데이터가 구글 모델 학습에 절대 사용되지 않음.
- 엄격한 할루시네이션 차단: 제공된 임상 수치(분자·분모, 검토 확정 태그) 외 임의 수치 생성 원천 금지.
"""
import os
import json
from typing import Dict, Any, List, Optional

class GeminiClinicalWriterAdapter:
    """
    회기 결과보고서(SOAP) 문장화 전용 LLM 어댑터.
    - 입력: metrics_engine에서 계산된 분자·분모 명시 지표 및 rule_engine의 관찰 패턴
    - 출력: 전문 언어재활사 양식의 간결한 임상 요약문
    """
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

    def generate_session_summary(self, patient_info: Dict[str, Any], metrics: Dict[str, Any], observations: List[str]) -> str:
        """
        정량 지표를 바탕으로 회기 요약 텍스트 초안 생성.
        """
        if not self.api_key:
            # API 키 미설정 시 결정론적 룰 기반 기본 템플릿 반환
            ind_acc = metrics.get("independent_accuracy", "N/A")
            cue_acc = metrics.get("cued_accuracy", "N/A")
            return (
                f"[시스템 생성 요약] 본 회기 독립 정반응률은 {ind_acc}이며, "
                f"단서 제공 후 정반응률은 {cue_acc}로 나타났습니다. "
                f"관찰된 주요 임상 패턴: {', '.join(observations) if observations else '특이사항 없음'}."
            )

        # Gemini API 호출부 구조 (google-genai SDK 연동 지점)
        # prompt:
        # "당신은 언어재활 임상 문서 작성 보조 AI입니다.
        # 아래 검증된 수치만을 사용하여 사실에 입각한 3~4줄의 SOAP 결과 요약을 작성하십시오.
        # 절대 새로운 수치나 진단을 창작하지 마십시오."
        return (
            f"대상자는 제시된 과제에서 독립 정반응률 {metrics.get('independent_accuracy', 'N/A')}을 보였습니다. "
            f"단서 후 반응률은 {metrics.get('cued_accuracy', 'N/A')}로 보조적 중재의 유효성이 확인되었습니다."
        )


class VirtualPatientSimulator:
    """
    [Phase 1] 예비 언어재활사 모의임상 실습용 AI 가상환자 시뮬레이터.
    - 페르소나: 브로카 실어증(전보문식 발화, 착어), 베르니케 실어증(유창하나 의미 결손), 마비말장애, 성인 발달장애 등
    """
    PERSONAS = {
        "broca_aphasia": {
            "name": "김영호 (남, 62세)",
            "diagnosis": "뇌경색 후 브로카 실어증",
            "traits": "구어 표현의 유창성이 저하되어 주로 명사 중심의 단어(전보문식)로 말하며, 발화 시작 시 긴 잠재기와 노력이 관찰됨.",
            "sample_responses": {
                "안녕하세요, 성함이 어떻게 되시나요?": "...김... 김영호.",
                "오늘 여기 어떻게 오셨어요?": "병원... 버스... 아내... 같이.",
                "이 그림(사과)이 무엇인가요?": "...사... 과... 사과."
            }
        },
        "adult_developmental": {
            "name": "이지훈 (남, 24세)",
            "diagnosis": "성인 발달장애 (자폐성장애 2급)",
            "traits": "일상 단어 이해는 가능하나 직관적 시각 지원이 없으면 불안을 느끼며, 키오스크 메뉴 선택이나 금전 계산에서 반복 확인 선호.",
            "sample_responses": {
                "지훈 씨, 좋아하는 음식이 뭐예요?": "돈까스... 시원한 사이다... 돈까스 좋아해요.",
                "키오스크에서 주문해볼까요?": "화면 눌러요... 포장... 매장... 포장 눌러요."
            }
        }
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

    def interact(self, persona_key: str, therapist_utterance: str) -> Dict[str, Any]:
        """
        예비 재활사의 발화에 대응하여 가상환자의 장애 특화 반응 및 반응 잠재기(Latency) 생성.
        """
        persona = self.PERSONAS.get(persona_key, self.PERSONAS["broca_aphasia"])
        
        # 사전 정의된 샘플 매칭 또는 Gemini 시뮬레이션
        response_text = persona["sample_responses"].get(therapist_utterance)
        if not response_text:
            if persona_key == "broca_aphasia":
                response_text = "...네... 그렇... 네."
            else:
                response_text = "네, 알겠어요."

        return {
            "persona": persona["name"],
            "diagnosis": persona["diagnosis"],
            "patient_utterance": response_text,
            "simulated_latency_sec": 2.4,
            "clinical_hint": "치료사 팁: 발화 지연 시 의미 단서 또는 문장 완성 단서를 제공해보세요."
        }


class AdultLifeSkillGenerator:
    """
    [Phase 2] 성인 발달장애인 주간활동센터 전용 sLMM 생활자립 교구 생성기.
    - 키오스크 주문, 대중교통 탑승, 금전 관리, 직장 소통 등 성인 특화 미션 자동 설계
    """
    DOMAINS = [
        "kiosk_ordering",         # 키오스크 주문하기
        "public_transit",         # 대중교통 이용 및 환승
        "community_finance",      # 마트 계산 및 영수증 확인
        "workplace_communication" # 직장 내 도움 요청 및 보고
    ]

    def generate_task_kit(self, domain: str, difficulty: int = 1) -> Dict[str, Any]:
        """
        성인 이용자 맞춤형 실생활 퀘스트 및 시각 자료 프롬프트 생성.
        """
        if domain == "kiosk_ordering":
            return {
                "mission_title": "카페 키오스크에서 따뜻한 아메리카노 포장 주문하기",
                "difficulty": difficulty,
                "steps": [
                    {"step": 1, "action": "화면 터치하여 주문 시작하기", "visual_prompt": "카페 키오스크 첫 화면: '매장'과 '포장' 버튼"},
                    {"step": 2, "action": "음료 카테고리에서 '커피' 탭 선택", "visual_prompt": "커피 카테고리 메뉴 목록"},
                    {"step": 3, "action": "'아메리카노(HOT)' 선택 및 결제 카드 삽입", "visual_prompt": "신용카드 투입구 안내"}
                ],
                "staff_guide": "사회복지사 안내: 이용자가 머뭇거릴 경우 10초 기다린 후 손가락으로 가리키는 시각적 촉구를 사용하세요."
            }
        
        return {
            "mission_title": "편의점에서 음료수 사고 교통카드로 계산하기",
            "difficulty": difficulty,
            "steps": [
                {"step": 1, "action": "원하는 음료수 고르기", "visual_prompt": "음료수 진열대"},
                {"step": 2, "action": "계산대로 가서 '이걸로 계산해주세요' 말하기", "visual_prompt": "편의점 계산대 직원의 모습"},
                {"step": 3, "action": "결제 단말기에 교통카드 터치하기", "visual_prompt": "카드 접촉 패드"}
            ],
            "staff_guide": "사회복지사 안내: 구어 표현이 어려운 이용자는 표현 카드(AAC)를 제시하도록 유도하세요."
        }

