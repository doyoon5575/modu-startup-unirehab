"""
Tests for Milestone 2:
- REQ-008: 승인형 가정 훈련(홈케어) 배정 및 정량 이력 관리
- REQ-009: 영역별 확장 모듈(마비말장애, 말실행증, AAC, 시니어 인지) 플러그인 지원
- REQ-010: 한국어 경량 모델(sLMM) 온디바이스/로컬 구동 인터페이스 옵션
"""

from __future__ import annotations

import tempfile
import unittest

from core.db import DatabaseManager
from core.extensions_and_homecare import HomecareAndExtensionsService


class TestExtensionsHomecareSlmm(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(base_dir=self.tmp_dir.name)
        self.service = HomecareAndExtensionsService(self.db)
        self.patient = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="윤서연",
            birth_year=1957,
            phone="010-1234-0000",
            guardian_contact="",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": False,
                "pseudonym_research": True,
            },
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_req008_approved_homecare_assignment_and_quantitative_logs(self) -> None:
        assignment, err = self.service.create_homecare_assignment(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=self.patient["patient_uuid"],
            target_group="복지관 대기자",
            daily_goal_count=10,
        )
        self.assertIsNone(err)
        self.assertEqual(assignment["approval_status"], "APPROVED")
        self.assertEqual(assignment["target_group"], "복지관 대기자")

        updated, err_log = self.service.record_homecare_training_log(
            tenant_id="seoul_rehab",
            assignment_id=assignment["assignment_id"],
            actor_id="patient-self",
            actor_role="환자·보호자",
            correct_count=8,
            trial_count=10,
            avg_reaction_time_ms=1240,
            guardian_memo="약국 처방전 문장 연습 8/10 수행",
        )
        self.assertIsNone(err_log)
        self.assertEqual(updated["completed_trials"], 10)
        self.assertEqual(updated["average_accuracy_pct"], 80.0)
        self.assertEqual(updated["logs"][0]["formatted_score"], "8/10 (80.0%)")

    def test_req009_domain_extension_plugins(self) -> None:
        plugins = self.service.ensure_default_plugins("seoul_rehab")
        codes = {p["domain_code"] for p in plugins}
        self.assertEqual(codes, {"DYSARTHRIA", "APRAXIA_OF_SPEECH", "AAC_BOARD", "SENIOR_COGNITION"})

        toggled = self.service.toggle_extension_plugin(
            tenant_id="seoul_rehab",
            plugin_id="plugin-aac",
            enabled=False,
            actor_id="slp-01",
            actor_role="언어재활사",
        )
        self.assertIsNotNone(toggled)
        self.assertFalse(toggled["enabled"])

    def test_req010_korean_slmm_ondevice_runtime_settings(self) -> None:
        settings = self.service.get_runtime_settings("seoul_rehab")
        self.assertEqual(settings["slmm_mode"], "local_slmm")
        self.assertTrue(settings["network_isolation_mode"])
        self.assertTrue(settings["active_model_spec"]["air_gapped_ready"])

        updated = self.service.update_runtime_settings(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            slmm_mode="local_slmm",
            slmm_model_name="Ko-Speech-sLMM-1.8B-ONNX-Edge",
            network_isolation_mode=True,
        )
        self.assertEqual(updated["slmm_model_name"], "Ko-Speech-sLMM-1.8B-ONNX-Edge")
        self.assertFalse(updated["active_model_spec"]["external_network_outbound"])


if __name__ == "__main__":
    unittest.main()
