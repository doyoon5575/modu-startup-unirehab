"""
AI Adult Life-Context Material & 3-Step Hint Cue Generator.

Covers:
- REQ-003: 성인 환자의 일상생활 환경(병원·약국, 마트·장보기, 대중교통·이동, 은행·관공서 등)을 반영한
  한국어 어휘·문장 과제와 3단계 힌트 단서(1단계 의미 단서, 2단계 문장 완성 단서, 3단계 시각적 보기) 맞춤형 생성
- REQ-010: 한국어 경량 모델(sLMM) 로컬/온디바이스 구동 옵션('local_slmm') 및 외부 LLM('external_llm') 선택 연동
- REQ-011: 외부 AI 전송 미동의 시 외부 LLM 호출 자동 차단(403 EXTERNAL_AI_CONSENT_BLOCKED)
- REQ-015: 비의료 일상생활 훈련 및 치료사가 선택한 접근에 기반한 연습 문구 표기 강제
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.db import NON_MEDICAL_NOTICES, DatabaseManager, now_iso, sanitize_tenant_id

ADULT_CONTEXT_BANK: Dict[str, List[Dict[str, Any]]] = {
    "병원·약국 방문": [
        {
            "target_word": "처방전",
            "category": "명사",
            "sentence_task": "진료가 끝난 뒤 수납 창구에서 ____을 받아 약국에 제출해요.",
            "full_sentence": "진료가 끝난 뒤 수납 창구에서 처방전을 받아 약국에 제출해요.",
            "hints": {
                "step1_semantic": "의사가 환자에게 어떤 약을 조제해 주어야 하는지 적어 주는 공식 문서예요.",
                "step2_sentence_completion": "약국에 가서 약사에게 '여기 병원에서 받은 ㅊㅂㅈ이요'라고 말해요.",
                "step3_visual_choices": ["처방전", "영수증", "진단서"],
            },
        },
        {
            "target_word": "식후 삼십 분",
            "category": "구/시간표현",
            "sentence_task": "위장 자극을 줄이기 위해 이 약은 아침·저녁 ____에 미지근한 물과 함께 복용해요.",
            "full_sentence": "위장 자극을 줄이기 위해 이 약은 아침·저녁 식후 삼십 분에 미지근한 물과 함께 복용해요.",
            "hints": {
                "step1_semantic": "식사를 마치고 시계 긴바늘이 반 바퀴 지난 뒤 약을 먹는 시간이에요.",
                "step2_sentence_completion": "약봉투 복약 안내란에 '하루 세 번, ㅅㅎ 30분 복용'이라고 적혀 있어요.",
                "step3_visual_choices": ["식후 삼십 분", "취침 직전", "공복 상태"],
            },
        },
        {
            "target_word": "물리치료실",
            "category": "명사",
            "sentence_task": "어깨 통증 완화를 위해 2층 재활의학과 옆 ____로 이동하여 온열 치료를 받아요.",
            "full_sentence": "어깨 통증 완화를 위해 2층 재활의학과 옆 물리치료실로 이동하여 온열 치료를 받아요.",
            "hints": {
                "step1_semantic": "병원에서 열·전기 자극이나 운동 기구로 굳은 근육과 관절의 회복을 돕는 치료 공간이에요.",
                "step2_sentence_completion": "진료실 간호사가 '수납 후 2층 ㅁㄹㅊㄹㅅ로 가셔서 접수하세요'라고 안내해요.",
                "step3_visual_choices": ["물리치료실", "채혈검사실", "방사선촬영실"],
            },
        },
        {
            "target_word": "신분증",
            "category": "명사",
            "sentence_task": "병원 외래 접수 창구에서 본인 확인을 위해 주민등록증이나 운전면허증 같은 ____을 제시해요.",
            "full_sentence": "병원 외래 접수 창구에서 본인 확인을 위해 주민등록증이나 운전면허증 같은 신분증을 제시해요.",
            "hints": {
                "step1_semantic": "건강보험 자격과 내 이름·사진·생년월일을 증명하는 카드예요.",
                "step2_sentence_completion": "접수 직원이 '환자분 본인 확인을 위해 ㅅㅂㅈ 보여주시겠어요?'라고 요청해요.",
                "step3_visual_choices": ["신분증", "교통카드", "도서대출증"],
            },
        },
    ],
    "마트·장보기": [
        {
            "target_word": "유통기한",
            "category": "명사",
            "sentence_task": "우유와 두부를 장바구니에 담기 전에 포장지 윗면의 ____ 날짜를 먼저 확인해요.",
            "full_sentence": "우유와 두부를 장바구니에 담기 전에 포장지 윗면의 유통기한 날짜를 먼저 확인해요.",
            "hints": {
                "step1_semantic": "식품을 안전하게 판매하거나 섭취할 수 있도록 정해 놓은 마감 날짜예요.",
                "step2_sentence_completion": "신선 코너에서 우유 팩에 찍힌 'ㅇㅌㄱㅎ 11월 15일까지' 표시를 읽어요.",
                "step3_visual_choices": ["유통기한", "제조번호", "영양성분"],
            },
        },
        {
            "target_word": "종량제 봉투",
            "category": "명사",
            "sentence_task": "계산대에서 장본 물건을 담기 위해 20리터짜리 재사용 ____ 한 장을 함께 구매해요.",
            "full_sentence": "계산대에서 장본 물건을 담기 위해 20리터짜리 재사용 종량제 봉투 한 장을 함께 구매해요.",
            "hints": {
                "step1_semantic": "장바구니 대신 물건을 담아 집에 가져간 뒤 생활 쓰레기를 버릴 때도 쓰는 지정 봉투예요.",
                "step2_sentence_completion": "계산원에게 '비닐 대신 20리터 재사용 ㅈㄹㅈ ㅂㅌ 한 장 주세요'라고 말해요.",
                "step3_visual_choices": ["종량제 봉투", "보냉 가방", "선물 포장지"],
            },
        },
        {
            "target_word": "무인 계산대",
            "category": "명사",
            "sentence_task": "바코드 스캐너에 상품을 직접 찍고 카드로 결제하기 위해 ____ 화면을 터치해요.",
            "full_sentence": "바코드 스캐너에 상품을 직접 찍고 카드로 결제하기 위해 무인 계산대 화면을 터치해요.",
            "hints": {
                "step1_semantic": "직원 없이 고객이 직접 바코드를 읽히고 카드를 꽂아 계산하는 기기예요.",
                "step2_sentence_completion": "줄이 짧아서 소량 구매 고객 전용 ㅁㅇ ㄱㅅㄷ로 걸어가요.",
                "step3_visual_choices": ["무인 계산대", "물품 보관함", "고객 상담실"],
            },
        },
        {
            "target_word": "영수증",
            "category": "명사",
            "sentence_task": "결제한 금액과 할인 내역이 맞는지 확인하고 주차 정산을 받으려고 종이 ____을 챙겨요.",
            "full_sentence": "결제한 금액과 할인 내역이 맞는지 확인하고 주차 정산을 받으려고 종이 영수증을 챙겨요.",
            "hints": {
                "step1_semantic": "물건을 사고 돈을 지불했다는 내역과 금액이 인쇄되어 나오는 종이예요.",
                "step2_sentence_completion": "주차 요금 할인을 받으려면 바코드가 찍힌 ㅇㅅㅈ이 필요해요.",
                "step3_visual_choices": ["영수증", "상품권", "교환권"],
            },
        },
    ],
    "대중교통·이동": [
        {
            "target_word": "환승 단말기",
            "category": "명사",
            "sentence_task": "시내버스에서 내리기 전에 뒷문 옆 ____에 교통카드를 꼭 태그해요.",
            "full_sentence": "시내버스에서 내리기 전에 뒷문 옆 환승 단말기에 교통카드를 꼭 태그해요.",
            "hints": {
                "step1_semantic": "버스나 지하철을 갈아탈 때 추가 요금이 붙지 않도록 카드를 갖다 대는 기계예요.",
                "step2_sentence_completion": "'하차입니다'라는 음성이 나오도록 ㅎㅅ ㄷㅁㄱ에 카드를 대요.",
                "step3_visual_choices": ["환승 단말기", "하차 벨", "노선 안내도"],
            },
        },
        {
            "target_word": "약자석",
            "category": "명사",
            "sentence_task": "지하철 객차 양 끝의 교통 ____에 앉아 안전 손잡이를 잡고 이동해요.",
            "full_sentence": "지하철 객차 양 끝의 교통 약자석에 앉아 안전 손잡이를 잡고 이동해요.",
            "hints": {
                "step1_semantic": "고령자, 임산부, 장애인이나 거동이 불편한 승객을 위해 배려해 둔 좌석이에요.",
                "step2_sentence_completion": "전철 안에서 보행이 불편할 때는 노약자·교통 ㅇㅈㅅ에 앉아요.",
                "step3_visual_choices": ["약자석", "수하물칸", "운전실"],
            },
        },
        {
            "target_word": "엘리베이터",
            "category": "명사",
            "sentence_task": "계단 오르내리기가 힘들어 지하철 출구 안내 표지판에서 ____ 위치를 먼저 찾아요.",
            "full_sentence": "계단 오르내리기가 힘들어 지하철 출구 안내 표지판에서 엘리베이터 위치를 먼저 찾아요.",
            "hints": {
                "step1_semantic": "지하 승강장에서 지상 출구까지 버튼을 눌러 수직으로 이동하는 승강기예요.",
                "step2_sentence_completion": "무릎에 무리가 가지 않게 에스컬레이터 대신 ㅇㄹㅂㅇㅌ를 타요.",
                "step3_visual_choices": ["엘리베이터", "개찰구", "비상계단"],
            },
        },
        {
            "target_word": "하차 벨",
            "category": "명사",
            "sentence_task": "이번 정류장에서 내리기 위해 안내 방송이 나오자마자 기둥에 붙은 빨간 ____을 눌러요.",
            "full_sentence": "이번 정류장에서 내리기 위해 안내 방송이 나오자마자 기둥에 붙은 빨간 하차 벨을 눌러요.",
            "hints": {
                "step1_semantic": "버스 기사님께 다음 정류장에 내릴 승객이 있음을 불빛과 소리로 알리는 버튼이에요.",
                "step2_sentence_completion": "내릴 정류장 이름이 방송되면 미리 ㅎㅊ ㅂ을 눌러요.",
                "step3_visual_choices": ["하차 벨", "비상 망치", "창문 손잡이"],
            },
        },
    ],
    "은행·관공서": [
        {
            "target_word": "번호표",
            "category": "명사",
            "sentence_task": "주민센터에 도착하면 먼저 순번 대기 기기에서 민원 창구 ____를 뽑고 기다려요.",
            "full_sentence": "주민센터에 도착하면 먼저 순번 대기 기기에서 민원 창구 번호표를 뽑고 기다려요.",
            "hints": {
                "step1_semantic": "창구에서 내 차례가 몇 번째인지 숫자로 적혀 나오는 작은 종이예요.",
                "step2_sentence_completion": "대기 인원이 많으니 입구 발권기에서 ㅂㅎㅍ부터 뽑으세요.",
                "step3_visual_choices": ["번호표", "위임장", "통장"],
            },
        },
        {
            "target_word": "비밀번호",
            "category": "명사",
            "sentence_task": "현금자동입출금기(ATM)에서 출금할 때 화면을 가리고 네 자리 ____를 입력해요.",
            "full_sentence": "현금자동입출금기(ATM)에서 출금할 때 화면을 가리고 네 자리 비밀번호를 입력해요.",
            "hints": {
                "step1_semantic": "통장이나 카드 주인만 알고 있는 보안 숫자 조합이에요.",
                "step2_sentence_completion": "창구 앞 숫자 키패드에 네 자리 ㅂㅁㅂㅎ를 누르고 확인 버튼을 눌러요.",
                "step3_visual_choices": ["비밀번호", "우편번호", "계좌번호"],
            },
        },
    ],
}


class MaterialGenerationService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def generate_contextual_materials(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        patient_uuid: str,
        life_context: str = "병원·약국 방문",
        difficulty: str = "중급(3어절 문장+어휘)",
        disorder_type: str = "실어증",
        engine_mode: str = "external_llm",
        item_count: int = 4,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-003 & REQ-011:
        - 먼저 verify_external_ai_consent로 4종 동의 상태를 검증한다.
        - 외부 AI 미동의 상태에서 engine_mode=='external_llm' 요청 시 즉시 403 차단한다.
        - 성인 생활맥락(병원·약국 방문, 마트·장보기, 대중교통·이동, 은행·관공서)에 맞춘
          한국어 어휘·문장 과제와 3단계 힌트 단서(1. 의미 단서, 2. 문장 완성 단서, 3. 시각적 보기)를 생성한다.
        """
        t = sanitize_tenant_id(tenant_id)
        ok_consent, err_consent = self.db.verify_external_ai_consent(
            tenant_id=t,
            patient_uuid=patient_uuid,
            actor_id=actor_id,
            actor_role=actor_role,
            requested_engine=engine_mode,
        )
        if not ok_consent:
            return None, err_consent

        bank = ADULT_CONTEXT_BANK.get(life_context) or ADULT_CONTEXT_BANK["병원·약국 방문"]
        capped_count = max(1, min(int(item_count or 4), len(bank)))
        selected = bank[:capped_count]

        items: List[Dict[str, Any]] = []
        for idx, entry in enumerate(selected, start=1):
            items.append(
                {
                    "item_no": idx,
                    "life_context": life_context,
                    "difficulty": difficulty,
                    "disorder_type": disorder_type,
                    "target_word": entry["target_word"],
                    "category": entry["category"],
                    "sentence_task": entry["sentence_task"],
                    "full_sentence": entry["full_sentence"],
                    "hints": {
                        "step1_semantic": entry["hints"]["step1_semantic"],
                        "step2_sentence_completion": entry["hints"]["step2_sentence_completion"],
                        "step3_visual_choices": list(entry["hints"]["step3_visual_choices"]),
                    },
                    "practice_notice": NON_MEDICAL_NOTICES["therapist_selected_practice"],
                }
            )

        material_id = f"mat-{uuid.uuid4().hex[:10]}"
        ts = now_iso()
        engine_label = (
            "Ko-Rehab-sLMM-3B-OnDevice (망분리 로컬 구동)"
            if engine_mode == "local_slmm"
            else "External-Clinical-LLM-KO (외부 AI 전송 동의 확인됨)"
        )

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                INSERT INTO generated_materials (
                    material_id, tenant_id, patient_uuid, life_context,
                    difficulty, disorder_type, engine_used, items_json,
                    non_medical_label, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    material_id,
                    t,
                    patient_uuid,
                    life_context,
                    difficulty,
                    disorder_type,
                    engine_label,
                    json.dumps(items, ensure_ascii=False),
                    NON_MEDICAL_NOTICES["full_banner"],
                    actor_id,
                    ts,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="generated_material",
            entity_id=material_id,
            from_state="NONE",
            to_state=f"GENERATED({len(items)}문항/{engine_mode})",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"성인 생활맥락({life_context}) 맞춤형 교구 및 3단계 힌트 생성",
        )

        return self.get_material(t, material_id), None

    def get_material(self, tenant_id: str, material_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM generated_materials WHERE material_id = ? AND tenant_id = ?",
                (material_id, t),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["items"] = json.loads(d.pop("items_json", "[]"))
        return d

    def list_materials(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        capped = max(1, min(int(limit or 50), 200))
        with self.db.connect_clinical(t) as conn:
            rows = conn.execute(
                "SELECT * FROM generated_materials WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (t, capped),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["items"] = json.loads(d.pop("items_json", "[]"))
            out.append(d)
        return out
