"""
UniRehab HTTP Server & REST API Application.

Binds to 0.0.0.0:${PORT:-8000}.
Implements all REST endpoints for REQ-001 through REQ-016 using Python 3.12 standard library
(zero external dependencies required for air-gapped / sandbox execution).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.clinical_service import ClinicalPlanService, compute_role_permissions
from core.db import NON_MEDICAL_NOTICES, DatabaseManager, sanitize_tenant_id
from core.extensions_and_homecare import HomecareAndExtensionsService
from core.material_service import MaterialGenerationService
from core.speech_analysis_service import SpeechAnalysisService

STATIC_DIR = Path(__file__).resolve().parent / "static"


def seed_initial_tenant_data(
    db: DatabaseManager,
    clinical_svc: ClinicalPlanService,
    material_svc: MaterialGenerationService,
    speech_svc: SpeechAnalysisService,
    ext_svc: HomecareAndExtensionsService,
    tenant_id: str = "seoul_rehab",
) -> None:
    """
    Idempotently seeds initial sample data only when the tenant DB has no patients yet
    (preserves carried-over data across redeploys).
    """
    t = sanitize_tenant_id(tenant_id)
    existing_patients = db.list_patients(t, limit=5)
    if existing_patients:
        return

    # 1. Seed organization accounts (확정된 답변 note: 기관 SSO 기본값 + 일반가입 후 관리자 승인 병행 지원)
    db.register_or_approve_org_account(
        tenant_id=t,
        user_id="prof-park",
        email="prof.park@snu-rehab.ac.kr",
        display_name="박지훈 지도교수(슈퍼바이저)",
        role="지도교수",
        auth_mode="ORG_SSO",
        account_status="ACTIVE",
        approved_by="ORG_SSO_IDP",
    )
    db.register_or_approve_org_account(
        tenant_id=t,
        user_id="slp-kim",
        email="slp.kim@snu-rehab.ac.kr",
        display_name="김서연 언어재활사(1급)",
        role="언어재활사",
        auth_mode="ORG_SSO",
        account_status="ACTIVE",
        approved_by="ORG_SSO_IDP",
    )
    db.register_or_approve_org_account(
        tenant_id=t,
        user_id="trainee-lee",
        email="trainee.lee@snu-rehab.ac.kr",
        display_name="이도윤 임상실습생",
        role="실습생",
        auth_mode="ORG_SSO",
        account_status="ACTIVE",
        approved_by="ORG_SSO_IDP",
    )
    db.register_or_approve_org_account(
        tenant_id=t,
        user_id="trainee-external",
        email="ext.student@korea-univ.kr",
        display_name="최민지 외부실습생(관리자 승인 완료)",
        role="실습생",
        auth_mode="SELF_SIGNUP_ADMIN_APPROVAL",
        account_status="ACTIVE",
        approved_by="admin-choi",
    )

    # 2. Seed two patients (one with external AI consent=True, one with external AI consent=False)
    p1 = db.register_patient_with_consents(
        tenant_id=t,
        actor_id="slp-kim",
        actor_role="언어재활사",
        full_name="김영호",
        birth_year=1956,
        phone="010-3456-7890",
        guardian_contact="010-9876-5432",
        consents={
            "terms_of_service": True,
            "voice_collection": True,
            "external_ai_transfer": True,
            "pseudonym_research": True,
        },
    )
    db.register_patient_with_consents(
        tenant_id=t,
        actor_id="slp-kim",
        actor_role="언어재활사",
        full_name="박순자",
        birth_year=1951,
        phone="010-2345-6789",
        guardian_contact="010-8765-1234",
        consents={
            "terms_of_service": True,
            "voice_collection": True,
            "external_ai_transfer": False,
            "pseudonym_research": False,
        },
    )

    p1_uuid = p1["patient_uuid"]

    # 3. Seed an initial therapy plan & SOAP draft created by trainee and requested for supervisor review
    plan = clinical_svc.generate_plan_and_soap_draft(
        tenant_id=t,
        actor_id="trainee-lee",
        actor_role="실습생",
        patient_uuid=p1_uuid,
        disorder_type="실어증",
        severity="중등도(Moderate)",
        life_context="병원·약국 방문",
        asha_fcm_level=3,
        baseline_correct=11,
        baseline_total=20,
        session_correct=16,
        session_total=20,
        cued_correct=18,
        avg_reaction_time_ms=1240,
    )
    clinical_svc.transition_plan_status(
        tenant_id=t,
        plan_id=plan["plan_id"],
        actor_id="trainee-lee",
        actor_role="실습생",
        target_status="PENDING_SUPERVISOR",
        supervisor_comment="지도교수님, 병원·약국 맥락 1회기 SOAP 결과보고서 초안 검토 및 승인 요청드려요.",
    )

    # 4. Seed contextual materials
    material_svc.generate_contextual_materials(
        tenant_id=t,
        actor_id="slp-kim",
        actor_role="언어재활사",
        patient_uuid=p1_uuid,
        life_context="병원·약국 방문",
        engine_mode="local_slmm",
        item_count=4,
    )

    # 5. Seed 6-layer speech analysis session
    speech_svc.create_session_with_sample_utterances(
        tenant_id=t,
        actor_id="slp-kim",
        actor_role="언어재활사",
        patient_uuid=p1_uuid,
        latency_threshold_ms=1500,
        accuracy_threshold_pct=80,
    )

    # 6. Seed homecare assignment & plugins & sLMM runtime settings
    hc, _ = ext_svc.create_homecare_assignment(
        tenant_id=t,
        actor_id="slp-kim",
        actor_role="언어재활사",
        patient_uuid=p1_uuid,
        target_group="퇴원 성인 환자",
        daily_goal_count=10,
    )
    if hc:
        ext_svc.record_homecare_training_log(
            tenant_id=t,
            assignment_id=hc["assignment_id"],
            actor_id="patient-self",
            actor_role="환자·보호자",
            correct_count=8,
            trial_count=10,
            avg_reaction_time_ms=1290,
            guardian_memo="퇴원 1일차 가정 내 처방전·복약 어휘 10문항 중 8문항 정반응 수행",
        )
    ext_svc.ensure_default_plugins(t)
    ext_svc.get_runtime_settings(t)


class UniRehabApplication:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.db = DatabaseManager(base_dir=base_dir)
        self.clinical_svc = ClinicalPlanService(self.db)
        self.material_svc = MaterialGenerationService(self.db)
        self.speech_svc = SpeechAnalysisService(self.db)
        self.ext_svc = HomecareAndExtensionsService(self.db)
        seed_initial_tenant_data(
            self.db,
            self.clinical_svc,
            self.material_svc,
            self.speech_svc,
            self.ext_svc,
            tenant_id="seoul_rehab",
        )
        seed_initial_tenant_data(
            self.db,
            self.clinical_svc,
            self.material_svc,
            self.speech_svc,
            self.ext_svc,
            tenant_id="busan_welfare",
        )


def create_http_handler(app_ctx: UniRehabApplication):
    class UniRehabRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Structured one-line logging handled in _dispatch
            pass

        def _extract_session(self, query_params: Dict[str, list]) -> Tuple[str, str, str]:
            raw_tenant = self.headers.get("X-Tenant-Id") or (query_params.get("tenant", ["seoul_rehab"])[0])
            raw_actor = self.headers.get("X-Actor-Id") or (query_params.get("actor", ["slp-kim"])[0])
            raw_role_hdr = self.headers.get("X-Actor-Role", "")
            raw_role = (
                urllib.parse.unquote(raw_role_hdr)
                if raw_role_hdr
                else (query_params.get("role", ["언어재활사"])[0])
            )
            return sanitize_tenant_id(raw_tenant), raw_actor.strip() or "slp-kim", raw_role.strip() or "언어재활사"

        def _send_json(self, status_code: int, payload: Dict[str, Any], req_id: str, start_ts: float) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-Id", req_id)
            self.end_headers()
            self.wfile.write(body)
            dur_ms = round((time.time() - start_ts) * 1000.0, 2)
            sys.stdout.write(
                json.dumps(
                    {
                        "request_id": req_id,
                        "method": self.command,
                        "path": self.path,
                        "status": status_code,
                        "duration_ms": dur_ms,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()

        def _send_error_json(
            self, status_code: int, code: str, message: str, req_id: str, start_ts: float
        ) -> None:
            self._send_json(
                status_code,
                {"error": {"code": code, "message": message}, "code": code, "message": message},
                req_id,
                start_ts,
            )

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            if not raw.strip():
                return {}
            return json.loads(raw)

        def do_GET(self) -> None:
            self._handle_request("GET")

        def do_POST(self) -> None:
            self._handle_request("POST")

        def do_PUT(self) -> None:
            self._handle_request("PUT")

        def do_PATCH(self) -> None:
            self._handle_request("PATCH")

        def _handle_request(self, method: str) -> None:
            start_ts = time.time()
            req_id = f"req-{uuid.uuid4().hex[:10]}"
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            try:
                # Serve Frontend HTML
                if method == "GET" and path in ("/", "/index.html"):
                    html_path = STATIC_DIR / "index.html"
                    content = html_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("X-Request-Id", req_id)
                    self.end_headers()
                    self.wfile.write(content)
                    return

                tenant_id, actor_id, actor_role = self._extract_session(query)
                target_tenant = sanitize_tenant_id(query.get("target_tenant", [tenant_id])[0])

                # Health check endpoint (verifies SQLite stores are writable/readable)
                if method == "GET" and path == "/api/health":
                    with app_ctx.db.connect_pii(tenant_id) as c1, app_ctx.db.connect_clinical(tenant_id) as c2:
                        c1.execute("SELECT 1").fetchone()
                        c2.execute("SELECT 1").fetchone()
                    self._send_json(
                        200,
                        {
                            "status": "ok",
                            "non_medical_notices": NON_MEDICAL_NOTICES,
                            "physical_isolation_verified": True,
                        },
                        req_id,
                        start_ts,
                    )
                    return

                # Role permissions inspection (REQ-006)
                if method == "GET" and path == "/api/permissions":
                    perms = compute_role_permissions(actor_role)
                    self._send_json(
                        200,
                        {"permissions": perms, "non_medical_notices": NON_MEDICAL_NOTICES},
                        req_id,
                        start_ts,
                    )
                    return

                # Audit logs (allowed for admin as well as clinicians within their tenant — REQ-013, REQ-014)
                if method == "GET" and path == "/api/audit-logs":
                    if tenant_id != target_tenant:
                        self._send_error_json(404, "RESOURCE_NOT_FOUND", "요청한 기관 리소스를 찾을 수 없어요.", req_id, start_ts)
                        return
                    limit = int(query.get("limit", ["50"])[0])
                    after = query.get("after", [""])[0]
                    records = app_ctx.db.list_audit_records(tenant_id, limit=limit, after=after)
                    self._send_json(200, records, req_id, start_ts)
                    return

                # Org accounts (확정된 답변 기본값: 기관 SSO + 일반 가입 후 관리자 승인)
                if path == "/api/org-accounts":
                    if method == "GET":
                        items = app_ctx.db.list_org_accounts(tenant_id)
                        self._send_json(
                            200,
                            {
                                "items": items,
                                "next": None,
                                "default_onboarding_policy": "ORG_SSO_WITH_ADMIN_APPROVAL_FALLBACK",
                            },
                            req_id,
                            start_ts,
                        )
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        acc = app_ctx.db.register_or_approve_org_account(
                            tenant_id=tenant_id,
                            user_id=body.get("user_id") or f"usr-{uuid.uuid4().hex[:8]}",
                            email=body.get("email", "new.trainee@hospital.kr"),
                            display_name=body.get("display_name", "신규 실습생"),
                            role=body.get("role", "실습생"),
                            auth_mode=body.get("auth_mode", "ORG_SSO"),
                            account_status=body.get("account_status", "ACTIVE"),
                            approved_by=actor_id,
                        )
                        self._send_json(201, acc, req_id, start_ts)
                        return

                # Enforce clinical access guard for all clinical/patient endpoints (REQ-013, REQ-014)
                ok_access, err_access = app_ctx.db.enforce_clinical_access(
                    session_tenant_id=tenant_id,
                    target_tenant_id=target_tenant,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    action=f"{method}_{path}",
                    resource_type=path.strip("/").replace("/", "_"),
                )
                if not ok_access and err_access:
                    self._send_error_json(err_access[0], err_access[1], err_access[2], req_id, start_ts)
                    return

                limit_param = max(1, min(int(query.get("limit", ["50"])[0]), 200))

                # Patients & 4 Consents (REQ-011, REQ-012)
                if path == "/api/patients":
                    if method == "GET":
                        items = app_ctx.db.list_patients(tenant_id, limit=limit_param)
                        self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        prof = app_ctx.db.register_patient_with_consents(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            full_name=body.get("full_name", "신규대상자"),
                            birth_year=int(body.get("birth_year", 1960)),
                            phone=body.get("phone", ""),
                            guardian_contact=body.get("guardian_contact", ""),
                            consents=body.get(
                                "consents",
                                {
                                    "terms_of_service": True,
                                    "voice_collection": True,
                                    "external_ai_transfer": False,
                                    "pseudonym_research": False,
                                },
                            ),
                        )
                        self._send_json(201, prof, req_id, start_ts)
                        return

                if path.startswith("/api/patients/") and path.endswith("/consents") and method in ("PATCH", "PUT", "POST"):
                    parts = path.strip("/").split("/")
                    patient_uuid = parts[2]
                    body = self._read_json_body()
                    updated = app_ctx.db.update_patient_consents(
                        tenant_id=tenant_id,
                        patient_uuid=patient_uuid,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        consents=body,
                    )
                    if not updated:
                        self._send_error_json(404, "PATIENT_NOT_FOUND", "대상자를 찾을 수 없어요.", req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                # Therapy Plans & SOAP Drafts (REQ-001, REQ-002, REQ-006)
                if path == "/api/plans":
                    if method == "GET":
                        status_filter = query.get("status", [""])[0]
                        items = app_ctx.clinical_svc.list_plans(tenant_id, limit=limit_param, status_filter=status_filter)
                        self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        patients = app_ctx.db.list_patients(tenant_id, limit=1)
                        p_uuid = body.get("patient_uuid") or (patients[0]["patient_uuid"] if patients else "pt-default")
                        plan = app_ctx.clinical_svc.generate_plan_and_soap_draft(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            patient_uuid=p_uuid,
                            disorder_type=body.get("disorder_type", "실어증"),
                            severity=body.get("severity", "중등도(Moderate)"),
                            life_context=body.get("life_context", "병원·약국 방문"),
                            asha_fcm_level=int(body.get("asha_fcm_level", 3)),
                            baseline_correct=int(body.get("baseline_correct", 11)),
                            baseline_total=int(body.get("baseline_total", 20)),
                            session_correct=int(body.get("session_correct", 16)),
                            session_total=int(body.get("session_total", 20)),
                            cued_correct=int(body.get("cued_correct", 18)),
                            avg_reaction_time_ms=int(body.get("avg_reaction_time_ms", 1240)),
                            subjective_note=body.get("subjective_note", ""),
                        )
                        self._send_json(201, plan, req_id, start_ts)
                        return

                if path.startswith("/api/plans/") and path.endswith("/transition") and method == "POST":
                    plan_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated, err = app_ctx.clinical_svc.transition_plan_status(
                        tenant_id=tenant_id,
                        plan_id=plan_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        target_status=body.get("target_status", "PENDING_SUPERVISOR"),
                        supervisor_comment=body.get("supervisor_comment", ""),
                    )
                    if err:
                        self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                # AI Adult Life-Context Materials & 3-Step Hints (REQ-003, REQ-011)
                if path == "/api/materials":
                    if method == "GET":
                        items = app_ctx.material_svc.list_materials(tenant_id, limit=limit_param)
                        self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        patients = app_ctx.db.list_patients(tenant_id, limit=1)
                        p_uuid = body.get("patient_uuid") or (patients[0]["patient_uuid"] if patients else "")
                        mat, err = app_ctx.material_svc.generate_contextual_materials(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            patient_uuid=p_uuid,
                            life_context=body.get("life_context", "병원·약국 방문"),
                            difficulty=body.get("difficulty", "중급(3어절 문장+어휘)"),
                            disorder_type=body.get("disorder_type", "실어증"),
                            engine_mode=body.get("engine_mode", "local_slmm"),
                            item_count=int(body.get("item_count", 4)),
                        )
                        if err:
                            self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                            return
                        self._send_json(201, mat, req_id, start_ts)
                        return

                # 6-Layer Speech Analysis Sessions & Utterances (REQ-004, REQ-005, REQ-007, REQ-016)
                if path == "/api/speech-sessions":
                    if method == "GET":
                        items = app_ctx.speech_svc.list_sessions(tenant_id, limit=limit_param)
                        self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        patients = app_ctx.db.list_patients(tenant_id, limit=1)
                        p_uuid = body.get("patient_uuid") or (patients[0]["patient_uuid"] if patients else "")
                        sess = app_ctx.speech_svc.create_session_with_sample_utterances(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            patient_uuid=p_uuid,
                            latency_threshold_ms=int(body.get("latency_threshold_ms", 1500)),
                            accuracy_threshold_pct=int(body.get("accuracy_threshold_pct", 80)),
                            slmm_mode=body.get("slmm_mode", "local_slmm"),
                            asr_engine=body.get("asr_engine", "aihub-dysarthria-conformer-ko-v2.1"),
                        )
                        self._send_json(201, sess, req_id, start_ts)
                        return

                if path.startswith("/api/speech-sessions/") and path.endswith("/bulk-approve") and method == "POST":
                    session_id = path.strip("/").split("/")[2]
                    code, err_key, msg = app_ctx.speech_svc.reject_bulk_approval_attempt(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                    )
                    self._send_error_json(code, err_key, msg, req_id, start_ts)
                    return

                if path.startswith("/api/speech-sessions/") and path.endswith("/scoring-criteria") and method == "POST":
                    session_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated, err = app_ctx.speech_svc.update_scoring_criteria_and_invalidate_reviewed(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        new_latency_threshold_ms=int(body.get("latency_threshold_ms", 1200)),
                        new_accuracy_threshold_pct=int(body.get("accuracy_threshold_pct", 85)),
                        actor_id=actor_id,
                        actor_role=actor_role,
                    )
                    if err:
                        self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                if path.startswith("/api/speech-utterances/") and path.endswith("/calibrate") and method == "POST":
                    utterance_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated, err = app_ctx.speech_svc.calibrate_utterance_onset(
                        tenant_id=tenant_id,
                        utterance_id=utterance_id,
                        new_manual_onset_ms=int(body.get("manual_onset_ms", 1800)),
                        actor_id=actor_id,
                        actor_role=actor_role,
                        final_score=body.get("final_score"),
                        therapist_note=body.get("therapist_note", ""),
                        mark_reviewed=bool(body.get("mark_reviewed", True)),
                    )
                    if err:
                        self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                if path.startswith("/api/speech-utterances/") and path.endswith("/multimodal") and method == "POST":
                    utterance_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated, err = app_ctx.speech_svc.analyze_multimodal_camera_frame(
                        tenant_id=tenant_id,
                        utterance_id=utterance_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        lip_aperture_mm=float(body.get("lip_aperture_mm", 18.0)),
                        facial_asymmetry_idx=float(body.get("facial_asymmetry_idx", 0.09)),
                        groping_detected=bool(body.get("groping_detected", False)),
                        visual_onset_ms=int(body.get("visual_onset_ms", 1750)),
                    )
                    if err:
                        self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                # Homecare Assignments & Quantitative Logs (REQ-008)
                if path == "/api/homecare":
                    if method == "GET":
                        items = app_ctx.ext_svc.list_homecare_assignments(tenant_id, limit=limit_param)
                        self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                        return
                    if method == "POST":
                        body = self._read_json_body()
                        patients = app_ctx.db.list_patients(tenant_id, limit=1)
                        p_uuid = body.get("patient_uuid") or (patients[0]["patient_uuid"] if patients else "")
                        hc, err = app_ctx.ext_svc.create_homecare_assignment(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            patient_uuid=p_uuid,
                            target_group=body.get("target_group", "퇴원 성인 환자"),
                            title=body.get("title", "퇴원 후 일상 어휘 연속 홈케어 과제"),
                            life_context=body.get("life_context", "병원·약국 방문"),
                            daily_goal_count=int(body.get("daily_goal_count", 10)),
                        )
                        if err:
                            self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                            return
                        self._send_json(201, hc, req_id, start_ts)
                        return

                if path.startswith("/api/homecare/") and path.endswith("/logs") and method == "POST":
                    assignment_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated, err = app_ctx.ext_svc.record_homecare_training_log(
                        tenant_id=tenant_id,
                        assignment_id=assignment_id,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        correct_count=int(body.get("correct_count", 8)),
                        trial_count=int(body.get("trial_count", 10)),
                        avg_reaction_time_ms=int(body.get("avg_reaction_time_ms", 1250)),
                        guardian_memo=body.get("guardian_memo", ""),
                    )
                    if err:
                        self._send_error_json(err[0], err[1], err[2], req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                # Extension Plugins (REQ-009)
                if path == "/api/plugins" and method == "GET":
                    items = app_ctx.ext_svc.ensure_default_plugins(tenant_id)
                    self._send_json(200, {"items": items, "next": None, "limit": limit_param}, req_id, start_ts)
                    return

                if path.startswith("/api/plugins/") and method in ("PATCH", "PUT", "POST"):
                    plugin_id = path.strip("/").split("/")[2]
                    body = self._read_json_body()
                    updated = app_ctx.ext_svc.toggle_extension_plugin(
                        tenant_id=tenant_id,
                        plugin_id=plugin_id,
                        enabled=bool(body.get("enabled", True)),
                        actor_id=actor_id,
                        actor_role=actor_role,
                    )
                    if not updated:
                        self._send_error_json(404, "PLUGIN_NOT_FOUND", "확장 플러그인을 찾을 수 없어요.", req_id, start_ts)
                        return
                    self._send_json(200, updated, req_id, start_ts)
                    return

                # Korean sLMM On-Device/Local Runtime Settings (REQ-010)
                if path == "/api/runtime-settings":
                    if method == "GET":
                        settings = app_ctx.ext_svc.get_runtime_settings(tenant_id)
                        self._send_json(200, settings, req_id, start_ts)
                        return
                    if method in ("PUT", "POST", "PATCH"):
                        body = self._read_json_body()
                        updated = app_ctx.ext_svc.update_runtime_settings(
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            actor_role=actor_role,
                            slmm_mode=body.get("slmm_mode", "local_slmm"),
                            slmm_model_name=body.get("slmm_model_name", "Ko-Rehab-sLMM-3B-OnDevice-GGUF"),
                            network_isolation_mode=bool(body.get("network_isolation_mode", True)),
                            asr_model_name=body.get("asr_model_name", "aihub-dysarthria-conformer-ko-v2.1"),
                        )
                        self._send_json(200, updated, req_id, start_ts)
                        return

                self._send_error_json(404, "ENDPOINT_NOT_FOUND", "요청한 API 경로를 찾을 수 없어요.", req_id, start_ts)

            except ValueError as ve:
                self._send_error_json(400, "BAD_REQUEST", str(ve), req_id, start_ts)
            except Exception:
                self._send_error_json(
                    500,
                    "INTERNAL_SERVER_ERROR",
                    "서버 내부 처리 중 오류가 발생했어요.",
                    req_id,
                    start_ts,
                )

    return UniRehabRequestHandler


def validate_startup_env() -> int:
    """
    Validates startup environment variables (per backend-api skill Finish Gate).
    If REQUIRE_STRICT_ENV=1 and UNIREHAB_TENANT_SECRET is missing, refuses to start with a clear message.
    """
    if os.environ.get("REQUIRE_STRICT_ENV") == "1" and not os.environ.get("UNIREHAB_TENANT_SECRET"):
        sys.stderr.write(
            "FATAL: 필수 환경변수 UNIREHAB_TENANT_SECRET가 설정되지 않아 서버 시작을 중단합니다.\n"
        )
        sys.stderr.flush()
        sys.exit(1)
    port_raw = os.environ.get("PORT", "8000")
    try:
        port = int(port_raw)
        if not (1 <= port <= 65535):
            raise ValueError()
        return port
    except ValueError:
        sys.stderr.write(f"FATAL: 유효하지 않은 PORT 환경변수 값입니다: {port_raw}\n")
        sys.stderr.flush()
        sys.exit(1)


def run_server() -> None:
    port = validate_startup_env()
    app_ctx = UniRehabApplication()
    handler_cls = create_http_handler(app_ctx)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_cls)
    sys.stdout.write(f"UniRehab server listening on http://0.0.0.0:{port}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
