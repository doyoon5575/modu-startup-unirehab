"""
근거 자료 저장소(기획서 11장 + 자료수집 '중재 자료를 기능으로 연결').
'임상자료에 소개되어 있다' 와 '앱 기능의 치료 효과가 검증되었다' 를 분리한다(verified_effect_in_app).
"""
from .models import EvidenceItem, ValidationItem, new_id
from .repository import Repo

SEED = [
    ("SFA", "의미자질분석(Semantic Feature Analysis)", "실어증(이름대기 결함)", "이름대기",
     "목표어의 용도·장소·특징 등 의미 자질을 산출하도록 유도", "ASHA 실어증 임상자료(지침 수준)", "훈련 자극 이름대기 정확도",
     "한국어 자극과 채점 기준, 이해 부담 미검토", "미확인", "자체 제작 자극만 사용", "용도·장소·특징을 다루는 활동",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("PCA", "음운요소분석(Phonological Components Analysis)", "실어증", "이름대기",
     "목표어의 첫소리·음절 수·운 등 소리 정보를 활용", "ASHA 실어증 임상자료", "이름대기 정확도",
     "영어의 운·철자 과제를 한국어에 그대로 적용하지 않는 검토 필요", "미확인", "자체 제작 자극만 사용", "소리·음절 정보를 제공하는 활동",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("VNEST", "동사네트워크강화(VNeST)", "실어증", "문장 속 어휘 인출",
     "동사와 관련된 행위자·대상 역할을 구성", "ASHA 실어증 임상자료", "동사·문장 산출",
     "조사·어미·생략 등 한국어 반응의 허용 범위 미정", "미확인", "자체 제작", "'누가–무엇을–어떻게' 관계 구성 활동",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("SCRIPT", "스크립트 훈련", "실어증", "기능적 대화",
     "개인에게 중요한 상황의 말하기를 반복 연습", "ASHA 실어증 임상자료", "스크립트 산출 정확도·속도",
     "연습한 문장과 새로운 상황 수행을 분리 측정해야 함", "미확인", "자체 제작", "주문·예약·자기소개 등 개인별 대화 연습",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("READING_SUPPORT", "읽기 지원", "실어증", "읽기 이해",
     "이해를 돕는 사진·형식·언어적 지원 활용", "ASHA 실어증 임상자료", "읽기 이해",
     "읽기 이해와 소리 내어 읽기의 평가 분리 필요", "미확인", "자체 제작", "안내문·메시지·일정 읽기 활동",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("PARTNER_TRAINING", "의사소통 상대자 훈련", "실어증·보호자", "상대자의 지원 방식",
     "기다리기, 선택지 제공, 표현 확인 등 지원 방식 훈련", "ASHA 실어증 임상자료", "대화 참여·상대자 행동 변화",
     "정답을 대신 말하는 도움과 의사표현을 지원하는 도움의 구분 필요", "미확인", "자체 제작", "보호자용 도움 안내와 연습",
     "https://www.asha.org/practice-portal/clinical-topics/aphasia/"),
    ("AOS_MOTOR", "말실행증: 조음운동 접근·감각 단서·속도/리듬 조절(SPT 등)", "후천성 말실행증", "말운동 계획",
     "모델 보고 따라 말하기, 함께 말하기, 길이·복잡도 조절, 피드백 조건 설정", "ASHA 말실행증 임상자료 + 개별 비교연구(소표본)", "조음 정확도",
     "표본이 작아 확대 해석 주의; 한국어 미검증", "미확인", "자체 제작", "말운동 연습(2단계 이후)",
     "https://www.asha.org/practice-portal/clinical-topics/acquired-apraxia-of-speech/"),
    ("DYSARTHRIA", "마비말장애: 하위체계별 개별화", "마비말장애", "말 산출",
     "원인과 영향을 받는 말 하위체계(호흡·발성·공명·조음·운율)에 맞춘 개별화", "ASHA 마비말장애 임상자료", "말명료도(청자 기반)",
     "특정 질환 발성훈련을 모든 말장애에 공통 적용 금지", "미확인", "자체 제작", "말 특성 분석과 치료사가 선택한 연습(2단계 이후)",
     "https://www.asha.org/practice-portal/clinical-topics/dysarthria-in-adults/"),
    ("AAC", "AAC: 개인의 언어·운동·감각·환경·상대자 고려", "AAC 필요 성인", "보완·대체 표현",
     "사진·글자·선택판을 정식 의사소통 방식으로 제공", "ASHA AAC 임상자료", "메시지 전달 여부",
     "말이 일부 가능해도 보완 수단이 필요할 수 있음", "미확인", "자체 제작", "개인별 표현판, 반응 방식 전환",
     "https://www.asha.org/practice-portal/professional-issues/augmentative-and-alternative-communication/"),
    ("COG_COMM", "인지-의사소통: 기능적 상황 정보 중시", "외상성 뇌손상 등", "정보 조직화·전략 사용",
     "검사 결과와 일상 수행이 다를 수 있으므로 기능적 상황 기록", "ASHA TBI 임상자료", "정보 유지·순서·전략",
     "실어증이라는 이유만으로 인지장애를 전제하지 않음", "미확인", "자체 제작", "정보 조직화·보상전략 연습(확장)",
     "https://www.asha.org/practice-portal/clinical-topics/traumatic-brain-injury-in-adults/"),
]

VALIDATION_SEED = [
    ("한국어 중재 근거", "접근별 국내 연구, 대상자 특성, 연구 설계, 결과·제한", "해외 접근의 단순 번역 방지"),
    ("한국어 장애 발화 성능", "장애·중증도·기기·환경별 전사 및 채점 결과", "자동 분석 공개 범위 결정"),
    ("반응 시간 타당성", "전문가 표시 시점과 자동 측정의 차이", "측정값 신뢰성 확인"),
    ("임상가 간 일치", "같은 반응에 대한 평가자 간 차이", "정답 기준과 검토 기준 정교화"),
    ("기능적 의사소통 효과", "새 자극·생활 상황·유지 결과", "연습 성적과 생활 변화를 구분"),
    ("사용자 조사", "치료사·대상자·보호자·실습생의 실제 업무 관찰", "기능의 필요성과 부담 확인"),
    ("검사·콘텐츠 권리", "검사별 디지털 사용·재배포·변형 허용 범위", "무단 탑재 방지"),
    ("국내 규제 검토", "확정된 사용 목적과 출력물 기준의 검토(식약처 AI·LLM·전문가용 DMD 가이드라인)", "제품 기능과 표현 범위 결정"),
    ("개인정보 처리", "녹음·건강정보의 저장, 외부 전송, 학습 이용 조건", "데이터 흐름과 동의 설계"),
    ("사업성", "실제 검토 시간, 운영비, 지속 사용·지불 의사", "가격과 고객군 결정"),
    ("치료사 수정 부담", "검토 시간을 포함한 기록·계획 시간 변화", "업무 효과 검증"),
    ("중증도·기기·환경별 성능 차이", "조건별 분석 오류율", "출시 전 분석 성능 확인"),
]


def seed_evidence(repo: Repo):
    for key, title, pop, fn, interv, lvl, outc, lim, ko, rights, feat, url in SEED:
        e = EvidenceItem(new_id("EV"), title, pop, fn, interv, lvl, outc, lim, ko, rights, feat,
                         reviewer="", reviewed_at="", update_status="검토 필요", url=url, approach_key=key, verified_effect_in_app=False)
        repo.evidence[e.id] = e
    for key, mat, why in VALIDATION_SEED:
        repo.validation_items[key] = ValidationItem(key, mat, why, "미확보")


def find_by_approach(repo: Repo, keys):
    return [e for e in repo.evidence.values() if e.approach_key in keys]


def feature_label(e: EvidenceItem) -> str:
    """초기 화면 표현: '검증된 치료 효과'가 아니라 '치료사가 선택한 접근에 기반한 연습'."""
    return ("검증된 치료 효과" if e.verified_effect_in_app else "치료사가 선택한 접근에 기반한 연습") + f" — {e.title}"
