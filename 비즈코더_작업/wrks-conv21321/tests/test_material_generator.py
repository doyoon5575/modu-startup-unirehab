"""
Tests for Milestone 1-3:
- REQ-003: AI 기반 성인 생활맥락 맞춤형 교구 및 3단계 힌트 단서(의미 단서, 문장 완성 단서, 시각적 보기) 생성
- REQ-011: 외부 AI 미동의 시 외부 LLM 호출 자동 차단 및 로컬 sLMM 폴백 허용
"""

from __future__ import annotations

import tempfile
import unittest

from core.db import DatabaseManager
from core.material_service import MaterialGenerationService


class TestMaterialGenerator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(base_dir=self.tmp_dir.name)
        self.service = MaterialGenerationService(self.db)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_req003_adult_life_context_and_three_step_hints(self) -> None:
        patient = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="강길동",
            birth_year=1954,
            phone="010-1234-9999",
            guardian_contact="",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": True,
                "pseudonym_research": True,
            },
        )
        for ctx in ("병원·약국 방문", "마트·장보기", "대중교통·이동"):
            mat, err = self.service.generate_contextual_materials(
                tenant_id="seoul_rehab",
                actor_id="slp-01",
                actor_role="언어재활사",
                patient_uuid=patient["patient_uuid"],
                life_context=ctx,
                engine_mode="external_llm",
                item_count=3,
            )
            self.assertIsNone(err)
            self.assertIsNotNone(mat)
            self.assertEqual(mat["life_context"], ctx)
            self.assertEqual(len(mat["items"]), 3)
            first = mat["items"][0]
            self.assertIn("target_word", first)
            self.assertIn("sentence_task", first)
            hints = first["hints"]
            self.assertTrue(bool(hints["step1_semantic"]))
            self.assertTrue(bool(hints["step2_sentence_completion"]))
            self.assertEqual(len(hints["step3_visual_choices"]), 3)
            self.assertIn(first["target_word"], hints["step3_visual_choices"])

    def test_req011_block_external_llm_when_unconsented(self) -> None:
        patient = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="조미영",
            birth_year=1960,
            phone="010-7777-8888",
            guardian_contact="",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": False,
                "pseudonym_research": False,
            },
        )
        # External LLM must be blocked
        mat, err = self.service.generate_contextual_materials(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=patient["patient_uuid"],
            life_context="병원·약국 방문",
            engine_mode="external_llm",
        )
        self.assertIsNone(mat)
        self.assertEqual(err[0], 403)
        self.assertEqual(err[1], "EXTERNAL_AI_CONSENT_BLOCKED")

        # On-device sLMM must succeed
        mat_local, err_local = self.service.generate_contextual_materials(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=patient["patient_uuid"],
            life_context="병원·약국 방문",
            engine_mode="local_slmm",
        )
        self.assertIsNone(err_local)
        self.assertIsNotNone(mat_local)
        self.assertIn("OnDevice", mat_local["engine_used"])


if __name__ == "__main__":
    unittest.main()
