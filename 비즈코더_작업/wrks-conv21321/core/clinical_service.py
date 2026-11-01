"""
Clinical service module covering:
- REQ-001: 치료계획 수립 및 SOAP 결과보고서 자동 초안 생성 보조(ASHA NOMS/FCM 표준 임상 지침 기반 장단기 목표 후보 제안, 분자/분모가 명시된 통계 지표 및 SOAP 초안 자동 생성)
- REQ-002: 지도교수(슈퍼바이저) 온라인 검토·승인 워크플로우(DRAFT -> PENDING_SUPERVISOR -> APPROVED / REVISION_REQUESTED 상태 머신 및 감사 로그)
- REQ-006: 실습생 권한 분리 및 지도교수 승인 요청 제한(실습생 모드 진입 시 최종 승인 차단·지도교수 승인 요청만 허용)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.db import NON_MEDICAL_NOTICES, DatabaseManager, now_iso, sanitize_tenant_id

ASHA_FCM_DOMAINS: Dict[str, Dict[str, Any]] = {
    "실어증": {
        "fcm_domain": "Spoken Language Expression & Comprehension (ASHA NOMS Adult Speech-Language)",
        "default_level": 3,
        "long_term_templates": [
            "대상자는 일상생활 의사소통 환경({life_context})에서 ASHA FCM Level {target_level} 수준으로 기능적 어휘 인출 및 문장 산출을 독립적으로 수행해요(목표 정확도 80% 이상, 16/20 문항).",
            "대상자는 가족 및 지역사회 대화 파트너와의 일상 요구 표현 상황에서 단서 최소화 상태에서 핵심 의사소통 의도를 전달해요(회기당 4/5 상황 이상).",
        ],
        "short_term_templates": [
            "[단기목표 1] {life_context} 맥락 핵심 명사·동사 이름대기 과제에서 3단계 힌트(의미·문장완성·시각보기) 중 1단계 의미 단서 이하로 16/20(80.0%) 이상 정반응해요.",
            "[단기목표 2] {life_context} 상황 기능적 3어절 문장 완성 과제에서 평균 발화 시작 반응시간(Onset Latency) 1,500 ms 이내로 15/20(75.0%) 이상 수행해요.",
            "[단기목표 3] 회기 내 자가 수정(Self-correction) 전략을 활용하여 착어 발생 시 8/10(80.0%) 이상 목표 어휘로 재산출해요.",
        ],
    },
    "마비말장애": {
        "fcm_domain": "Motor Speech — Speech Intelligibility & Prosody (ASHA NOMS)",
        "default_level": 4,
        "long_term_templates": [
            "대상자는 {life_context} 환경에서 호흡-발성 협응과 조음 명료도 조절 전략을 사용하여 친숙하지 않은 청자에게도 문장 명료도 85%(17/20 문항) 이상을 유지해요(ASHA FCM Level {target_level}).",
        ],
        "short_term_templates": [
            "[단기목표 1] {life_context} 필수 구문 낭독 과제에서 과대비음 및 자음 왜곡을 줄여 음절 명료도 17/20(85.0%) 이상 달성해요.",
            "[단기목표 2] 문장 발화 시 적절한 쉼(Pause)과 강세 조절을 통해 적정 말속도(분당 140~170음절) 범위를 8/10(80.0%) 문항 이상 유지해요.",
        ],
    },
    "말실행증": {
        "fcm_domain": "Apraxia of Speech — Articulatory Kinematic Planning (ASHA NOMS)",
        "default_level": 3,
        "long_term_templates": [
            "대상자는 {life_context} 의사소통 상황에서 조음 탐색 동작(Groping)을 줄이고 시·청각 통합 단서를 활용해 다음절 어휘 및 단문을 정확도 80%(16/20 문항) 이상으로 산출해요(ASHA FCM Level {target_level}).",
        ],
        "short_term_templates": [
            "[단기목표 1] {life_context} 핵심 다음절 어휘 산출 시 시각적 조음 단서 후 15/20(75.0%) 이상 조음 탐색 없이 첫 음절을 개시해요.",
            "[단기목표 2] 8단계 자극 모방(Integral Stimulation) 절차에서 16/20(80.0%) 이상 음운 첨가·대체 없이 목표 문장을 발화해요.",
        ],
    },
    "인지-의사소통장애": {
        "fcm_domain": "Cognitive-Communication — Attention, Memory & Executive Function (ASHA NOMS)",
        "default_level": 4,
        "long_term_templates": [
            "대상자는 {life_context} 문제해결 및 일정·금전 관리 과제에서 주의집중과 작업기억 전략을 적용하여 80%(16/20 문항) 이상 독립적으로 수행해요(ASHA FCM Level {target_level}).",
        ],
        "short_term_templates": [
            "[단기목표 1] {life_context} 상황 다단계 지시 따르기 및 핵심 정보 회상 과제에서 16/20(80.0%) 이상 정반응해요.",
            "[단기목표 2] 생활 안전 및 복약·예약 확인 시나리오에서 간접 단서 1회 이하로 8/10(80.0%) 이상 적절한 의사결정을 표현해요.",
        ],
    },
}

VALID_PLAN_TRANSITIONS: Dict[str, List[str]] = {
    "DRAFT": ["PENDING_SUPERVISOR", "APPROVED"],
    "PENDING_SUPERVISOR": ["APPROVED", "REVISION_REQUESTED"],
    "REVISION_REQUESTED": ["DRAFT", "PENDING_SUPERVISOR"],
    "APPROVED": ["REVISION_REQUESTED"],  # Terminal recovery path documented per biz-internal-tool skill
}


def compute_role_permissions(role: str) -> Dict[str, Any]:
    """
    REQ-006: 실습생 권한 분리 및 지도교수 승인 요청 제한.
    실습생(?role=실습생 / trainee / intern)은 최종 승인 버튼이 비활성화(can_final_approve=False)되고
    지도교수 승인 요청(can_request_supervisor_approval=True)만 가능하다.
    """
    normalized = (role or "언어재활사").strip()
    is_trainee = normalized in ("실습생", "trainee", "intern", "student")
    is_supervisor = normalized in ("지도교수", "언어재활사", "supervisor", "therapist", "slp")
    is_admin = normalized in ("관리자", "admin", "system_admin")

    return {
        "role": normalized,
        "is_trainee": is_trainee,
        "is_supervisor": is_supervisor,
        "is_admin": is_admin,
        "can_create_draft": is_trainee or is_supervisor,
        "can_request_supervisor_approval": is_trainee or is_supervisor,
        "can_final_approve": is_supervisor and not is_trainee,
        "can_request_revision": is_supervisor and not is_trainee,
        "final_approve_button_disabled": is_trainee or is_admin,
        "ui_badge": (
            "실습생 전용 모드(최종 승인 비활성화 · 지도교수 승인 요청 전용)"
            if is_trainee
            else ("지도교수·언어재활사 검토/승인 모드" if is_supervisor else "기관 관리자 감사 전용 모드")
        ),
    }


class ClinicalPlanService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def generate_plan_and_soap_draft(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        patient_uuid: str,
        disorder_type: str = "실어증",
        severity: str = "중등도(Moderate)",
        life_context: str = "병원·약국 방문",
        asha_fcm_level: int = 3,
        baseline_correct: int = 11,
        baseline_total: int = 20,
        session_correct: int = 16,
        session_total: int = 20,
        cued_correct: int = 18,
        avg_reaction_time_ms: int = 1280,
        subjective_note: str = "",
    ) -> Dict[str, Any]:
        """
        REQ-001:
        1) ASHA NOMS/FCM 표준 임상 지침 기반 장·단기 목표 후보 자동 생성
        2) 분자·분모가 명시된 정량 통계 지표(예: 16/20 (80.0%)) 산출
        3) SOAP 결과보고서(S/O/A/P) 초안 자동 생성
        """
        t = sanitize_tenant_id(tenant_id)
        domain_spec = ASHA_FCM_DOMAINS.get(disorder_type, ASHA_FCM_DOMAINS["실어증"])
        fcm_lvl = max(1, min(int(asha_fcm_level or domain_spec["default_level"]), 7))
        target_lvl = min(7, fcm_lvl + 1)

        b_den = max(1, int(baseline_total or 20))
        b_num = max(0, min(int(baseline_correct or 0), b_den))
        b_pct = round((b_num / b_den) * 100.0, 1)

        s_den = max(1, int(session_total or 20))
        s_num = max(0, min(int(session_correct or 0), s_den))
        s_pct = round((s_num / s_den) * 100.0, 1)

        c_num = max(s_num, min(int(cued_correct or s_num), s_den))
        c_pct = round((c_num / s_den) * 100.0, 1)

        long_term_goals = [
            tpl.format(life_context=life_context, target_level=target_lvl)
            for tpl in domain_spec["long_term_templates"]
        ]
        short_term_goals = [
            tpl.format(life_context=life_context, target_level=target_lvl)
            for tpl in domain_spec["short_term_templates"]
        ]

        session_stats = {
            "baseline_accuracy": {
                "numerator": b_num,
                "denominator": b_den,
                "percentage": b_pct,
                "formatted": f"{b_num}/{b_den} ({b_pct}%)",
            },
            "independent_accuracy": {
                "numerator": s_num,
                "denominator": s_den,
                "percentage": s_pct,
                "formatted": f"{s_num}/{s_den} ({s_pct}%)",
            },
            "cued_accuracy": {
                "numerator": c_num,
                "denominator": s_den,
                "percentage": c_pct,
                "formatted": f"{c_num}/{s_den} ({c_pct}%)",
            },
            "avg_reaction_time_ms": int(avg_reaction_time_ms),
            "delta_percentage_pt": round(s_pct - b_pct, 1),
        }

        s_text = subjective_note.strip() or (
            f"대상자 및 보호자는 '{life_context}' 상황에서 필요한 단어가 바로 떠오르지 않아 답답함이 있었으나, "
            f"오늘 회기 연습 과제에는 적극적으로 참여하였다고 보고함."
        )
        o_text = (
            f"[정량 수행 지표 — 분자/분모 명시] '{life_context}' 맥락 어휘·문장 산출 과제 총 {s_den}문항 중 "
            f"독립 정반응 {s_num}/{s_den} ({s_pct}%), 3단계 단서 제공 포함 정반응 {c_num}/{s_den} ({c_pct}%)을 기록함 "
            f"(기초선 {b_num}/{b_den} ({b_pct}%) 대비 +{round(s_pct - b_pct, 1)}%p 향상). "
            f"평균 발화 시작 반응시간(Onset Latency)은 {int(avg_reaction_time_ms):,} ms로 측정됨."
        )
        a_text = (
            f"ASHA NOMS {domain_spec['fcm_domain']} 기준 현재 Level {fcm_lvl}에서 목표 Level {target_lvl}로 이행 중이며, "
            f"1단계 의미 단서 제공 시 인출 성공률이 {c_num}/{s_den} ({c_pct}%)로 상승하여 단서 반응성이 양호함. "
            f"({NON_MEDICAL_NOTICES['therapist_selected_practice']} · {NON_MEDICAL_NOTICES['non_medical_daily_training']})"
        )
        p_text = (
            f"차기 회기에는 '{life_context}' 심화 문장 과제({s_den}문항)를 유지하되 시각적 보기 단서를 점진적 소거(Fading)하고, "
            f"승인형 가정 훈련(홈케어)으로 일일 10문항 반복 연습을 연계할 계획임."
        )

        soap_draft = {
            "S": s_text,
            "O": o_text,
            "A": a_text,
            "P": p_text,
            "non_medical_disclaimer": NON_MEDICAL_NOTICES["full_banner"],
        }

        plan_id = f"plan-{uuid.uuid4().hex[:10]}"
        ts = now_iso()

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                INSERT INTO therapy_plans (
                    plan_id, tenant_id, patient_uuid, disorder_type, severity,
                    life_context, baseline_accuracy_num, baseline_accuracy_den,
                    asha_fcm_domain, asha_fcm_level, long_term_goals_json,
                    short_term_goals_json, soap_draft_json, session_stats_json,
                    status, created_by, created_role, supervisor_id, supervisor_comment,
                    approved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    t,
                    patient_uuid,
                    disorder_type,
                    severity,
                    life_context,
                    b_num,
                    b_den,
                    domain_spec["fcm_domain"],
                    fcm_lvl,
                    json.dumps(long_term_goals, ensure_ascii=False),
                    json.dumps(short_term_goals, ensure_ascii=False),
                    json.dumps(soap_draft, ensure_ascii=False),
                    json.dumps(session_stats, ensure_ascii=False),
                    "DRAFT",
                    actor_id,
                    actor_role,
                    "",
                    "",
                    "",
                    ts,
                    ts,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="therapy_plan",
            entity_id=plan_id,
            from_state="NONE",
            to_state="DRAFT",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"ASHA 표준 치료계획 및 SOAP 초안 생성({s_num}/{s_den})",
        )

        return self.get_plan(t, plan_id)

    def get_plan(self, tenant_id: str, plan_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM therapy_plans WHERE plan_id = ? AND tenant_id = ?",
                (plan_id, t),
            ).fetchone()
        if not row:
            return None
        return self._deserialize_plan(dict(row))

    def list_plans(
        self, tenant_id: str, limit: int = 50, status_filter: str = ""
    ) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        capped = max(1, min(int(limit or 50), 200))
        with self.db.connect_clinical(t) as conn:
            if status_filter:
                rows = conn.execute(
                    """
                    SELECT * FROM therapy_plans
                    WHERE tenant_id = ? AND status = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (t, status_filter, capped),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM therapy_plans
                    WHERE tenant_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (t, capped),
                ).fetchall()
        return [self._deserialize_plan(dict(r)) for r in rows]

    def transition_plan_status(
        self,
        tenant_id: str,
        plan_id: str,
        actor_id: str,
        actor_role: str,
        target_status: str,
        supervisor_comment: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-002 & REQ-006:
        - 실습생(실습생/trainee)은 PENDING_SUPERVISOR(지도교수 승인 요청)만 수행 가능하며,
          APPROVED(최종 승인)나 REVISION_REQUESTED(반려)를 호출하면 403 TRAINEE_FINAL_APPROVAL_FORBIDDEN 반환.
        - 지도교수/언어재활사는 PENDING_SUPERVISOR -> APPROVED 또는 REVISION_REQUESTED 전환 가능.
        - 모든 상태 전환은 StateChangeHistory에 감사 로그로 기록됨(REQ-014).
        """
        t = sanitize_tenant_id(tenant_id)
        plan = self.get_plan(t, plan_id)
        if not plan:
            return None, (404, "PLAN_NOT_FOUND", "치료계획서 및 SOAP 보고서를 찾을 수 없어요.")

        perms = compute_role_permissions(actor_role)
        current_status = plan["status"]

        if target_status == "APPROVED" and not perms["can_final_approve"]:
            self.db.log_access(
                tenant_id=t,
                actor_id=actor_id,
                actor_role=actor_role,
                action="ATTEMPT_FINAL_APPROVE_PLAN",
                resource_type="therapy_plan",
                resource_id=plan_id,
                patient_uuid=plan["patient_uuid"],
                outcome="DENY_TRAINEE_ROLE",
                detail="실습생 모드에서는 최종 승인이 제한되며 지도교수 승인 요청만 가능함",
            )
            return None, (
                403,
                "TRAINEE_FINAL_APPROVAL_FORBIDDEN",
                "실습생 모드에서는 최종 승인 권한이 없어요. '지도교수 승인 요청' 기능만 사용할 수 있어요.",
            )

        if target_status == "REVISION_REQUESTED" and not perms["can_request_revision"]:
            return None, (
                403,
                "SUPERVISOR_ROLE_REQUIRED",
                "보완 요청(반려)은 지도교수 또는 언어재활사만 수행할 수 있어요.",
            )

        allowed_next = VALID_PLAN_TRANSITIONS.get(current_status, [])
        if target_status not in allowed_next:
            return None, (
                409,
                "INVALID_STATE_TRANSITION",
                f"현재 상태({current_status})에서 '{target_status}' 상태로 직접 전환할 수 없어요.",
            )

        ts = now_iso()
        approved_at = ts if target_status == "APPROVED" else plan.get("approved_at", "")
        sup_id = actor_id if target_status in ("APPROVED", "REVISION_REQUESTED") else plan.get("supervisor_id", "")

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE therapy_plans
                SET status = ?, supervisor_id = ?, supervisor_comment = ?,
                    approved_at = ?, updated_at = ?
                WHERE plan_id = ? AND tenant_id = ?
                """,
                (target_status, sup_id, supervisor_comment.strip(), approved_at, ts, plan_id, t),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="therapy_plan",
            entity_id=plan_id,
            from_state=current_status,
            to_state=target_status,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=supervisor_comment.strip() or f"상태 전환: {current_status} -> {target_status}",
        )

        return self.get_plan(t, plan_id), None

    def _deserialize_plan(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["long_term_goals"] = json.loads(row.pop("long_term_goals_json", "[]"))
        row["short_term_goals"] = json.loads(row.pop("short_term_goals_json", "[]"))
        row["soap_draft"] = json.loads(row.pop("soap_draft_json", "{}"))
        row["session_stats"] = json.loads(row.pop("session_stats_json", "{}"))
        row["non_medical_notice"] = NON_MEDICAL_NOTICES["full_banner"]
        return row
