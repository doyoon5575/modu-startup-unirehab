"""
Tests for Milestone 1-1:
- REQ-011: 4종 동의 분리 수집 및 외부 AI 미동의 시 LLM 호출 자동 차단
- REQ-012: 식별정보(PII)와 음성·임상 데이터 물리 격리 및 UUID 가명화 매핑
- REQ-013: 기관별 테넌트 DB 격리 및 관리자 임상 데이터 직접 열람 차단
- REQ-014: 전수 접근 로그(AccessLog) 및 상태 변경 이력(StateChangeHistory) 감사 추적
- REQ-015: 비의료 일상생활 훈련 소프트웨어 문구 표기 상수 검증
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest

from core.db import NON_MEDICAL_NOTICES, DatabaseManager


class TestSecurityAndCompliance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(base_dir=self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_req011_four_consents_and_external_ai_block(self) -> None:
        # Register patient with external_ai_transfer = False
        profile = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="김철수",
            birth_year=1958,
            phone="010-1234-5678",
            guardian_contact="010-8765-4321",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": False,
                "pseudonym_research": True,
            },
        )
        p_uuid = profile["patient_uuid"]
        self.assertTrue(p_uuid.startswith("pt-"))

        # External LLM call must be blocked (403)
        ok, err = self.db.verify_external_ai_consent(
            tenant_id="seoul_rehab",
            patient_uuid=p_uuid,
            actor_id="slp-01",
            actor_role="언어재활사",
            requested_engine="external_llm",
        )
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertEqual(err[0], 403)
        self.assertEqual(err[1], "EXTERNAL_AI_CONSENT_BLOCKED")

        # On-device sLMM must be allowed even when external_ai_transfer is False
        ok_local, err_local = self.db.verify_external_ai_consent(
            tenant_id="seoul_rehab",
            patient_uuid=p_uuid,
            actor_id="slp-01",
            actor_role="언어재활사",
            requested_engine="local_slmm",
        )
        self.assertTrue(ok_local)
        self.assertIsNone(err_local)

        # Updating external_ai_transfer to True enables external LLM
        self.db.update_patient_consents(
            tenant_id="seoul_rehab",
            patient_uuid=p_uuid,
            actor_id="slp-01",
            actor_role="언어재활사",
            consents={"external_ai_transfer": True},
        )
        ok_after, _ = self.db.verify_external_ai_consent(
            tenant_id="seoul_rehab",
            patient_uuid=p_uuid,
            actor_id="slp-01",
            actor_role="언어재활사",
            requested_engine="external_llm",
        )
        self.assertTrue(ok_after)

    def test_req012_physical_isolation_and_uuid_pseudonymization(self) -> None:
        profile = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="박영희",
            birth_year=1962,
            phone="010-2222-3333",
            guardian_contact="010-4444-5555",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": True,
                "pseudonym_research": False,
            },
        )
        pii_path = self.db.pii_db_path("seoul_rehab")
        clinical_path = self.db.clinical_db_path("seoul_rehab")
        # Trigger clinical schema creation
        with self.db.connect_clinical("seoul_rehab"):
            pass

        self.assertNotEqual(pii_path, clinical_path)
        self.assertTrue(pii_path.exists())
        self.assertTrue(clinical_path.exists())

        # Verify clinical DB has no patient_identity table or full_name column
        with sqlite3.connect(str(clinical_path)) as c_conn:
            tables = [
                r[0]
                for r in c_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            self.assertNotIn("patient_identity", tables)
            for tbl in tables:
                cols = [c[1] for c in c_conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
                self.assertNotIn("full_name", cols)
                self.assertNotIn("phone", cols)

        self.assertEqual(profile["masked_name"], "박**")

    def test_req013_tenant_isolation_and_admin_clinical_block(self) -> None:
        # Cross-tenant access must be blocked with 404
        ok_cross, err_cross = self.db.enforce_clinical_access(
            session_tenant_id="seoul_rehab",
            target_tenant_id="busan_welfare",
            actor_id="slp-01",
            actor_role="언어재활사",
            action="READ_THERAPY_PLAN",
            resource_type="therapy_plan",
            resource_id="plan-1",
        )
        self.assertFalse(ok_cross)
        self.assertEqual(err_cross[0], 404)

        # Admin accessing clinical data within same tenant must be blocked with 403
        ok_admin, err_admin = self.db.enforce_clinical_access(
            session_tenant_id="seoul_rehab",
            target_tenant_id="seoul_rehab",
            actor_id="admin-01",
            actor_role="관리자",
            action="READ_SPEECH_ANALYSIS",
            resource_type="speech_session",
            resource_id="sess-1",
        )
        self.assertFalse(ok_admin)
        self.assertEqual(err_admin[0], 403)
        self.assertEqual(err_admin[1], "ADMIN_CLINICAL_ACCESS_BLOCKED")

    def test_req014_audit_logs_and_state_change_history(self) -> None:
        profile = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="이민수",
            birth_year=1950,
            phone="010-9999-0000",
            guardian_contact="",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": False,
                "pseudonym_research": False,
            },
        )
        self.db.update_patient_consents(
            tenant_id="seoul_rehab",
            patient_uuid=profile["patient_uuid"],
            actor_id="slp-01",
            actor_role="언어재활사",
            consents={"external_ai_transfer": True},
        )
        records = self.db.list_audit_records("seoul_rehab", limit=20)
        self.assertGreaterEqual(len(records["items"]), 1)
        self.assertGreaterEqual(len(records["state_changes"]), 2)

    def test_req015_non_medical_notices_exact_phrases(self) -> None:
        self.assertIn("치료사가 선택한 접근에 기반한 연습", NON_MEDICAL_NOTICES["full_banner"])
        self.assertIn("비의료 일상생활 훈련", NON_MEDICAL_NOTICES["full_banner"])


if __name__ == "__main__":
    unittest.main()
