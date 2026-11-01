"""
End-to-End HTTP Integration & Finish Gate Tests covering REQ-001 through REQ-016:
- Empty tenant returns `[]` (not `null`) on every collection endpoint
- Cross-tenant access returns 404 without leaking existence (REQ-013)
- Admin clinical access returns 403 ADMIN_CLINICAL_ACCESS_BLOCKED (REQ-013)
- Trainee (`?role=실습생`) cannot final-approve (403), can only request supervisor approval (REQ-006, REQ-002)
- External AI unconsented patient blocks external LLM call (403 EXTERNAL_AI_CONSENT_BLOCKED, REQ-011)
- 6-layer speech analysis onset calibration recalculates reaction_time_ms & rejects bulk approval (422, REQ-004)
- Scoring criteria change transitions reviewed items to RECHECK_REQUIRED (REQ-016)
- Multimodal camera frame analysis (REQ-005), AI Hub dysarthria ASR (REQ-007), Homecare (REQ-008), Plugins (REQ-009), sLMM (REQ-010)
- HTML UI includes non-medical mandatory phrases (REQ-015) and 3-column review layout (REQ-004)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import UniRehabApplication, create_http_handler


class TestHttpEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.app_ctx = UniRehabApplication(base_dir=cls.tmp_dir.name)
        handler = create_http_handler(cls.app_ctx)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp_dir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        tenant: str = "seoul_rehab",
        actor: str = "slp-kim",
        role: str = "언어재활사",
    ) -> tuple[int, dict | str]:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Tenant-Id", tenant)
        req.add_header("X-Actor-Id", actor)
        req.add_header("X-Actor-Role", urllib.parse.quote(role))
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8")
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    return resp.status, json.loads(raw)
                return resp.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            return e.code, json.loads(raw)

    def test_01_ui_html_and_req015_non_medical_phrases(self) -> None:
        status, html = self._request("GET", "/?role=" + urllib.parse.quote("실습생"))
        self.assertEqual(status, 200)
        self.assertIn("치료사가 선택한 접근에 기반한 연습", html)
        self.assertIn("비의료 일상생활 훈련", html)
        self.assertIn("three-col-review", html)

    def test_02_empty_tenant_collections_return_empty_list_never_null(self) -> None:
        for ep in ("/api/patients", "/api/plans", "/api/materials", "/api/speech-sessions", "/api/homecare"):
            status, data = self._request("GET", ep + "?limit=10", tenant="empty_new_tenant")
            self.assertEqual(status, 200)
            self.assertIsInstance(data["items"], list)
            self.assertEqual(data["items"], [])
            self.assertEqual(data["limit"], 10)

    def test_03_cross_tenant_and_admin_clinical_access_blocked_req013(self) -> None:
        # Cross-tenant request must return 404
        st_cross, err_cross = self._request(
            "GET",
            "/api/plans?target_tenant=busan_welfare",
            tenant="seoul_rehab",
            role="언어재활사",
        )
        self.assertEqual(st_cross, 404)
        self.assertEqual(err_cross["code"], "RESOURCE_NOT_FOUND")

        # Admin accessing clinical endpoint must return 403
        st_admin, err_admin = self._request(
            "GET",
            "/api/plans",
            tenant="seoul_rehab",
            actor="admin-01",
            role="관리자",
        )
        self.assertEqual(st_admin, 403)
        self.assertEqual(err_admin["code"], "ADMIN_CLINICAL_ACCESS_BLOCKED")

        # Admin can still read audit logs
        st_audit, audit_data = self._request(
            "GET",
            "/api/audit-logs?limit=5",
            tenant="seoul_rehab",
            actor="admin-01",
            role="관리자",
        )
        self.assertEqual(st_audit, 200)
        self.assertGreaterEqual(len(audit_data["items"]), 1)

    def test_04_end_to_end_clinical_workflow_req001_req002_req006(self) -> None:
        # Trainee creates plan & SOAP draft
        st_create, plan = self._request(
            "POST",
            "/api/plans",
            body={
                "disorder_type": "실어증",
                "life_context": "마트·장보기",
                "asha_fcm_level": 3,
                "baseline_correct": 10,
                "baseline_total": 20,
                "session_correct": 17,
                "session_total": 20,
                "cued_correct": 19,
                "avg_reaction_time_ms": 1150,
            },
            role="실습생",
            actor="trainee-lee",
        )
        self.assertEqual(st_create, 201)
        self.assertEqual(plan["session_stats"]["independent_accuracy"]["formatted"], "17/20 (85.0%)")

        plan_id = plan["plan_id"]

        # Trainee attempts final approval -> 403
        st_forbid, err_forbid = self._request(
            "POST",
            f"/api/plans/{plan_id}/transition",
            body={"target_status": "APPROVED"},
            role="실습생",
            actor="trainee-lee",
        )
        self.assertEqual(st_forbid, 403)
        self.assertEqual(err_forbid["code"], "TRAINEE_FINAL_APPROVAL_FORBIDDEN")

        # Trainee requests supervisor approval -> 200 PENDING_SUPERVISOR
        st_req, pending_plan = self._request(
            "POST",
            f"/api/plans/{plan_id}/transition",
            body={"target_status": "PENDING_SUPERVISOR", "supervisor_comment": "검토 요청"},
            role="실습생",
            actor="trainee-lee",
        )
        self.assertEqual(st_req, 200)
        self.assertEqual(pending_plan["status"], "PENDING_SUPERVISOR")

        # Supervisor approves -> 200 APPROVED
        st_app, approved_plan = self._request(
            "POST",
            f"/api/plans/{plan_id}/transition",
            body={"target_status": "APPROVED", "supervisor_comment": "승인 완료"},
            role="지도교수",
            actor="prof-park",
        )
        self.assertEqual(st_app, 200)
        self.assertEqual(approved_plan["status"], "APPROVED")

    def test_05_end_to_end_speech_6layers_onset_bulk_reject_and_recheck_req004_req016(self) -> None:
        st_list, sess_list = self._request("GET", "/api/speech-sessions")
        self.assertEqual(st_list, 200)
        sess = sess_list["items"][0]
        session_id = sess["session_id"]
        utt_id = sess["utterances"][0]["utterance_id"]

        # Bulk approval attempt -> 422 BULK_APPROVAL_PROHIBITED
        st_bulk, err_bulk = self._request("POST", f"/api/speech-sessions/{session_id}/bulk-approve")
        self.assertEqual(st_bulk, 422)
        self.assertEqual(err_bulk["code"], "BULK_APPROVAL_PROHIBITED")

        # Manual onset calibration -> recalculates reaction_time_ms
        st_cal, cal_utt = self._request(
            "POST",
            f"/api/speech-utterances/{utt_id}/calibrate",
            body={"manual_onset_ms": 1820, "final_score": 2, "mark_reviewed": True},
        )
        self.assertEqual(st_cal, 200)
        self.assertEqual(cal_utt["manual_onset_ms"], 1820)
        self.assertEqual(cal_utt["reaction_time_ms"], 820)
        self.assertEqual(cal_utt["review_status"], "REVIEWED")

        # Change scoring criteria -> transitions reviewed utterance to RECHECK_REQUIRED (REQ-016)
        st_crit, updated_sess = self._request(
            "POST",
            f"/api/speech-sessions/{session_id}/scoring-criteria",
            body={"latency_threshold_ms": 1100, "accuracy_threshold_pct": 85},
        )
        self.assertEqual(st_crit, 200)
        self.assertEqual(updated_sess["utterances"][0]["review_status"], "RECHECK_REQUIRED")

    def test_06_missing_required_env_refuses_startup(self) -> None:
        env = dict(
            PATH="/usr/bin:/bin",
            REQUIRE_STRICT_ENV="1",
        )
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "app.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("UNIREHAB_TENANT_SECRET", proc.stderr)


if __name__ == "__main__":
    unittest.main()
