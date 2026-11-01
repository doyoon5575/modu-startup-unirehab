"""
신규 추가된 어댑터(SpeechAdapter, LLM, Simulator, LifeSkill) 및 FastAPI 스키마 단위 테스트.
"""
import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.speech_adapters_production import WhisperAPIAdapter
from app.llm_adapters import VirtualPatientSimulator, AdultLifeSkillGenerator, GeminiClinicalWriterAdapter
from app.fastapi_app import app
from fastapi.testclient import TestClient

class TestAdaptersAndFastAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_whisper_adapter_interface(self):
        adapter = WhisperAPIAdapter()
        q = adapter.check_quality("test_audio.wav|{\"quality\": \"ok\", \"snr\": 28.0}")
        self.assertEqual(q["quality"], "ok")
        self.assertEqual(q["snr_db"], 28.0)

        t = adapter.transcribe("test.wav|{\"text\": \"사과\", \"conf\": 0.95}", 0.0, 1.5)
        self.assertEqual(t["text"], "사과")
        self.assertEqual(t["confidence"], 0.95)

        onsets = adapter.detect_onsets("test.wav|{\"onset\": 0.72}")
        self.assertEqual(onsets["onset"], 0.72)

    def test_virtual_patient_simulator(self):
        sim = VirtualPatientSimulator()
        res = sim.interact("broca_aphasia", "안녕하세요, 성함이 어떻게 되시나요?")
        self.assertEqual(res["persona"], "김영호 (남, 62세)")
        self.assertIn("김영호", res["patient_utterance"])
        self.assertGreater(res["simulated_latency_sec"], 0)

    def test_adult_life_skill_generator(self):
        gen = AdultLifeSkillGenerator()
        kit = gen.generate_task_kit("kiosk_ordering", difficulty=1)
        self.assertIn("키오스크", kit["mission_title"])
        self.assertEqual(len(kit["steps"]), 3)
        self.assertIn("사회복지사 안내", kit["staff_guide"])

    def test_clinical_writer_fallback(self):
        writer = GeminiClinicalWriterAdapter(api_key=None)
        metrics = {"independent_accuracy": "10/15 (66.7%)", "cued_accuracy": "4/5 (80.0%)"}
        summary = writer.generate_session_summary({}, metrics, ["초성단서 유효"])
        self.assertIn("66.7%", summary)
        self.assertIn("초성단서 유효", summary)

    def test_fastapi_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")

    def test_fastapi_simulator_and_lifeskill_endpoints(self):
        res1 = self.client.post("/api/simulator/interact", json={
            "persona_key": "broca_aphasia",
            "therapist_utterance": "오늘 여기 어떻게 오셨어요?"
        })
        self.assertEqual(res1.status_code, 200)
        self.assertIn("병원", res1.json()["patient_utterance"])

        res2 = self.client.post("/api/lifeskill/generate", json={
            "domain": "kiosk_ordering",
            "difficulty": 1
        })
        self.assertEqual(res2.status_code, 200)
        self.assertIn("키오스크", res2.json()["mission_title"])

if __name__ == "__main__":
    unittest.main()
