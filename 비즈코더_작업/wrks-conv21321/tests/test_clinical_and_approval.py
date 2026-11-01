"""
Tests for Milestone 1-2:
- REQ-001: ASHA 표준 임상 지침 기반 장단기 목표 후보 제안 및 분자/분모 명시 통계 지표·SOAP 초안 자동 생성
- REQ-002: 지도교수(슈퍼바이저) 온라인 검토·승인 워크플로우
- REQ-006: 실습생 모드(?role=실습생) 진입 시 최종 승인 버튼 비활성화 및 지도교수 승인 요청만 허용
"""

from __future__ import annotations

import tempfile
import unittest

from core.clinical_service import ClinicalPlanService, compute_role_permissions
from core.db import DatabaseManager


class TestClinicalAndApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(base_dir=self.tmp_dir.name)
        self.service = ClinicalPlanService(self.db)
        self.patient = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="trainee-01",
            actor_role="실습생",
            full_name="정수민",
            birth_year=1955,
            phone="010-1111-2222",
            guardian_contact="010-3333-4444",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": True,
                "pseudonym_research": True,
            },
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_req001_asha_plan_and_soap_with_numerator_denominator(self) -> None:
        plan = self.service.generate_plan_and_soap_draft(
            tenant_id="seoul_rehab",
            actor_id="trainee-01",
            actor_role="실습생",
            patient_uuid=self.patient["patient_uuid"],
            disorder_type="실어증",
            severity="중등도(Moderate)",
            life_context="병원·약국 방문",
            asha_fcm_level=3,
            baseline_correct=10,
            baseline_total=20,
            session_correct=16,
            session_total=20,
            cued_correct=18,
            avg_reaction_time_ms=1190,
        )
        self.assertIn("ASHA NOMS", plan["asha_fcm_domain"])
        self.assertGreaterEqual(len(plan["long_term_goals"]), 1)
        self.assertGreaterEqual(len(plan["short_term_goals"]), 2)

        stats = plan["session_stats"]
        self.assertEqual(stats["independent_accuracy"]["numerator"], 16)
        self.assertEqual(stats["independent_accuracy"]["denominator"], 20)
        self.assertEqual(stats["independent_accuracy"]["formatted"], "16/20 (80.0%)")

        soap = plan["soap_draft"]
        self.assertIn("16/20 (80.0%)", soap["O"])
        self.assertIn("18/20 (90.0%)", soap["O"])
        self.assertIn("치료사가 선택한 접근에 기반한 연습", soap["A"])

    def test_req006_and_req002_trainee_restrictions_and_supervisor_approval(self) -> None:
        trainee_perms = compute_role_permissions("실습생")
        self.assertTrue(trainee_perms["is_trainee"])
        self.assertFalse(trainee_perms["can_final_approve"])
        self.assertTrue(trainee_perms["final_approve_button_disabled"])
        self.assertTrue(trainee_perms["can_request_supervisor_approval"])

        plan = self.service.generate_plan_and_soap_draft(
            tenant_id="seoul_rehab",
            actor_id="trainee-01",
            actor_role="실습생",
            patient_uuid=self.patient["patient_uuid"],
        )
        plan_id = plan["plan_id"]
        self.assertEqual(plan["status"], "DRAFT")

        # 1) Trainee attempts direct final approval -> must fail with 403
        updated, err = self.service.transition_plan_status(
            tenant_id="seoul_rehab",
            plan_id=plan_id,
            actor_id="trainee-01",
            actor_role="실습생",
            target_status="APPROVED",
        )
        self.assertIsNone(updated)
        self.assertEqual(err[0], 403)
        self.assertEqual(err[1], "TRAINEE_FINAL_APPROVAL_FORBIDDEN")

        # 2) Trainee requests supervisor approval -> succeeds (PENDING_SUPERVISOR)
        updated, err = self.service.transition_plan_status(
            tenant_id="seoul_rehab",
            plan_id=plan_id,
            actor_id="trainee-01",
            actor_role="실습생",
            target_status="PENDING_SUPERVISOR",
            supervisor_comment="지도교수님, 1회기 SOAP 초안 검토 요청드립니다.",
        )
        self.assertIsNone(err)
        self.assertEqual(updated["status"], "PENDING_SUPERVISOR")

        # 3) Trainee still cannot approve while PENDING_SUPERVISOR
        updated_fail, err_fail = self.service.transition_plan_status(
            tenant_id="seoul_rehab",
            plan_id=plan_id,
            actor_id="trainee-01",
            actor_role="실습생",
            target_status="APPROVED",
        )
        self.assertIsNone(updated_fail)
        self.assertEqual(err_fail[0], 403)

        # 4) Supervisor reviews and approves -> succeeds (APPROVED)
        approved_plan, err_sup = self.service.transition_plan_status(
            tenant_id="seoul_rehab",
            plan_id=plan_id,
            actor_id="prof-kim",
            actor_role="지도교수",
            target_status="APPROVED",
            supervisor_comment="ASHA FCM 목표 수준과 분자/분모 지표가 정확히 작성되어 승인합니다.",
        )
        self.assertIsNone(err_sup)
        self.assertEqual(approved_plan["status"], "APPROVED")
        self.assertEqual(approved_plan["supervisor_id"], "prof-kim")
        self.assertTrue(bool(approved_plan["approved_at"]))


if __name__ == "__main__":
    unittest.main()
