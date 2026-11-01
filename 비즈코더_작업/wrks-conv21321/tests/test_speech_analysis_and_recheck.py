"""
Tests for Milestone 1-4 & Multimodal/ASR:
- REQ-004: 음성·발화 분석 6층 분리 아키텍처, 발화 시작점(Onset) 수동 보정 시 반응시간 실시간 재계산, AI 일괄 승인 배제
- REQ-005: 카메라 기반 입술 개구도, 안면 좌우 비대칭, 조음 탐색 동작 인식 및 시각/음향 Onset 비교 측정
- REQ-007: AI 허브 구음장애 음성인식 데이터셋 기반 파인튜닝 ASR 엔진 연동
- REQ-016: 채점 기준 변경 시 이미 검토 완료된 문항도 '재확인 필요(RECHECK_REQUIRED)' 상태로 자동 전환
"""

from __future__ import annotations

import tempfile
import unittest

from core.db import DatabaseManager
from core.speech_analysis_service import SpeechAnalysisService


class TestSpeechAnalysisAndRecheck(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(base_dir=self.tmp_dir.name)
        self.service = SpeechAnalysisService(self.db)
        self.patient = self.db.register_patient_with_consents(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            full_name="한지훈",
            birth_year=1952,
            phone="010-5555-6666",
            guardian_contact="",
            consents={
                "terms_of_service": True,
                "voice_collection": True,
                "external_ai_transfer": True,
                "pseudonym_research": True,
            },
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_req004_six_layers_manual_onset_recalculation_and_bulk_approve_rejection(self) -> None:
        sess = self.service.create_session_with_sample_utterances(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=self.patient["patient_uuid"],
            latency_threshold_ms=1500,
        )
        self.assertEqual(len(sess["utterances"]), 3)
        self.assertFalse(sess["summary"]["bulk_approve_button_rendered"])

        utt = sess["utterances"][0]
        # Verify all 6 layers exist
        self.assertEqual(utt["layer1_audio_quality"]["layer_no"], 1)
        self.assertEqual(utt["layer2_asr"]["layer_no"], 2)
        self.assertEqual(utt["layer3_timing"]["layer_no"], 3)
        self.assertEqual(utt["layer4_acoustic"]["layer_no"], 4)
        self.assertEqual(utt["layer5_linguistic"]["layer_no"], 5)
        self.assertEqual(utt["layer6_therapist_review"]["layer_no"], 6)

        # Manual onset calibration: stimulus_end_ms is 1000. Setting manual_onset_ms to 1950 -> reaction_time_ms = 950
        calibrated, err = self.service.calibrate_utterance_onset(
            tenant_id="seoul_rehab",
            utterance_id=utt["utterance_id"],
            new_manual_onset_ms=1950,
            actor_id="slp-01",
            actor_role="언어재활사",
            final_score=2,
            therapist_note="스펙트로그램 파형 기준 1,950 ms로 수동 보정함",
            mark_reviewed=True,
        )
        self.assertIsNone(err)
        self.assertEqual(calibrated["manual_onset_ms"], 1950)
        self.assertEqual(calibrated["reaction_time_ms"], 950)
        self.assertTrue(calibrated["layer3_timing"]["calibrated_by_human"])
        self.assertEqual(calibrated["review_status"], "REVIEWED")

        # Bulk approval attempt must be rejected (422)
        code, err_key, _ = self.service.reject_bulk_approval_attempt(
            tenant_id="seoul_rehab",
            session_id=sess["session_id"],
            actor_id="slp-01",
            actor_role="언어재활사",
        )
        self.assertEqual(code, 422)
        self.assertEqual(err_key, "BULK_APPROVAL_PROHIBITED")

    def test_req016_scoring_criteria_change_forces_recheck_required(self) -> None:
        sess = self.service.create_session_with_sample_utterances(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=self.patient["patient_uuid"],
            latency_threshold_ms=1500,
        )
        # Mark first two utterances as REVIEWED
        for u in sess["utterances"][:2]:
            self.service.calibrate_utterance_onset(
                tenant_id="seoul_rehab",
                utterance_id=u["utterance_id"],
                new_manual_onset_ms=u["auto_onset_ms"],
                actor_id="slp-01",
                actor_role="언어재활사",
                mark_reviewed=True,
            )

        before = self.service.get_session_detail("seoul_rehab", sess["session_id"])
        self.assertEqual(before["summary"]["reviewed_count"], 2)

        # Change scoring criteria -> all reviewed utterances must transition to RECHECK_REQUIRED
        updated, err = self.service.update_scoring_criteria_and_invalidate_reviewed(
            tenant_id="seoul_rehab",
            session_id=sess["session_id"],
            new_latency_threshold_ms=1200,
            new_accuracy_threshold_pct=85,
            actor_id="slp-01",
            actor_role="언어재활사",
        )
        self.assertIsNone(err)
        self.assertEqual(updated["summary"]["reviewed_count"], 0)
        self.assertEqual(updated["summary"]["recheck_required_count"], 3)
        for u in updated["utterances"]:
            self.assertEqual(u["review_status"], "RECHECK_REQUIRED")
            self.assertIn("재확인 필요", u["layer6_therapist_review"]["recheck_reason"])

    def test_req005_and_req007_multimodal_camera_and_aihub_dysarthria_asr(self) -> None:
        sess = self.service.create_session_with_sample_utterances(
            tenant_id="seoul_rehab",
            actor_id="slp-01",
            actor_role="언어재활사",
            patient_uuid=self.patient["patient_uuid"],
            asr_engine="aihub-dysarthria-conformer-ko-v2.1",
        )
        self.assertIn("AI 허브", sess["asr_engine_profile"]["dataset_source"])
        utt = sess["utterances"][1]
        updated_utt, err = self.service.analyze_multimodal_camera_frame(
            tenant_id="seoul_rehab",
            utterance_id=utt["utterance_id"],
            actor_id="slp-01",
            actor_role="언어재활사",
            lip_aperture_mm=15.6,
            facial_asymmetry_idx=0.21,
            groping_detected=True,
            visual_onset_ms=2000,
        )
        self.assertIsNone(err)
        mm = updated_utt["multimodal"]
        self.assertEqual(mm["lip_aperture_mm"], 15.6)
        self.assertEqual(mm["facial_asymmetry_idx"], 0.21)
        self.assertTrue(mm["groping_detected"])
        self.assertEqual(mm["visual_to_audio_lag_ms"], updated_utt["manual_onset_ms"] - 2000)


if __name__ == "__main__":
    unittest.main()
