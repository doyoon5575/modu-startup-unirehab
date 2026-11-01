"""
Physical DB isolation, tenant DB isolation, 4-type consent enforcement,
UUID pseudonymization, audit logging, and SaMD non-medical notice constants.

Covers:
- REQ-011: 4종 동의 분리 수집(이용약관, 음성 수집, 외부 AI 전송, 가명 연구 활용) 및 외부 AI 미동의 시 LLM 호출 자동 차단
- REQ-012: 식별정보(PII)와 음성·임상 데이터 물리 격리(별도 SQLite DB 파일) 및 UUID 가명화 매핑
- REQ-013: 기관별 테넌트 DB 격리 및 관리자(admin)의 임상 데이터 직접 열람 차단
- REQ-014: 전수 접근 로그(AccessLog) 및 데이터 상태 변경 이력(StateChangeHistory) 감사 추적
- REQ-015: 식약처 비의료 건강관리서비스 가이드라인 문구('치료사가 선택한 접근에 기반한 연습', '비의료 일상생활 훈련') 표기 강제
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NON_MEDICAL_NOTICES = {
    "therapist_selected_practice": "치료사가 선택한 접근에 기반한 연습",
    "non_medical_daily_training": "비의료 일상생활 훈련",
    "full_banner": (
        "[비의료 일상생활 훈련 안내] 본 소프트웨어는 식약처 비의료 건강관리서비스 가이드라인을 준수하는 "
        "'비의료 일상생활 훈련' 지원 도구이며, 모든 과제는 '치료사가 선택한 접근에 기반한 연습'으로 제공돼요. "
        "의학적 진단이나 처방을 대체하지 않아요."
    ),
}

CONSENT_KEYS = (
    "terms_of_service",      # 1. 이용약관 동의(필수)
    "voice_collection",      # 2. 음성 수집 동의(필수)
    "external_ai_transfer",  # 3. 외부 AI 전송 동의(선택 — 미동의 시 외부 LLM 호출 자동 차단)
    "pseudonym_research",    # 4. 가명 연구 활용 동의(선택)
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_tenant_id(tenant_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", (tenant_id or "").strip())
    if not cleaned:
        raise ValueError("유효하지 않은 기관(tenant_id) 식별자예요.")
    return cleaned


class DatabaseManager:
    """
    Manages physically isolated SQLite databases per tenant:
    1) pii_<tenant>.db       — 환자 실명·생년월일·연락처·4종 동의 상태 및 UUID 매핑만 보관(식별정보 물리 격리)
    2) clinical_<tenant>.db  — patient_uuid만 사용하여 치료계획, SOAP, 음성·발화 분석, 교구, 홈케어 보관(실명 컬럼 없음)
    3) audit_<tenant>.db     — AccessLog(전수 접근 로그), StateChangeHistory(상태 변경 이력), 기관 계정/승인 관리
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        env_dir = os.environ.get("UNIREHAB_DATA_DIR")
        self.base_path = Path(base_dir or env_dir or Path(__file__).resolve().parent.parent / "data")
        self.pii_dir = self.base_path / "pii_vault"
        self.clinical_dir = self.base_path / "clinical_store"
        self.audit_dir = self.base_path / "audit_store"
        self.pii_dir.mkdir(parents=True, exist_ok=True)
        self.clinical_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def pii_db_path(self, tenant_id: str) -> Path:
        t = sanitize_tenant_id(tenant_id)
        return self.pii_dir / f"pii_{t}.db"

    def clinical_db_path(self, tenant_id: str) -> Path:
        t = sanitize_tenant_id(tenant_id)
        return self.clinical_dir / f"clinical_{t}.db"

    def audit_db_path(self, tenant_id: str) -> Path:
        t = sanitize_tenant_id(tenant_id)
        return self.audit_dir / f"audit_{t}.db"

    def connect_pii(self, tenant_id: str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.pii_db_path(tenant_id)))
        conn.row_factory = sqlite3.Row
        self._init_pii_schema(conn)
        return conn

    def connect_clinical(self, tenant_id: str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.clinical_db_path(tenant_id)))
        conn.row_factory = sqlite3.Row
        self._init_clinical_schema(conn)
        return conn

    def connect_audit(self, tenant_id: str) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.audit_db_path(tenant_id)))
        conn.row_factory = sqlite3.Row
        self._init_audit_schema(conn)
        return conn

    def _init_pii_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patient_identity (
                patient_uuid TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                full_name TEXT NOT NULL,
                birth_year INTEGER NOT NULL,
                phone TEXT DEFAULT '',
                guardian_contact TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS patient_consents (
                patient_uuid TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                terms_of_service INTEGER NOT NULL DEFAULT 0,
                voice_collection INTEGER NOT NULL DEFAULT 0,
                external_ai_transfer INTEGER NOT NULL DEFAULT 0,
                pseudonym_research INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def _init_clinical_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS therapy_plans (
                plan_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                patient_uuid TEXT NOT NULL,
                disorder_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                life_context TEXT NOT NULL,
                baseline_accuracy_num INTEGER NOT NULL,
                baseline_accuracy_den INTEGER NOT NULL,
                asha_fcm_domain TEXT NOT NULL,
                asha_fcm_level INTEGER NOT NULL,
                long_term_goals_json TEXT NOT NULL,
                short_term_goals_json TEXT NOT NULL,
                soap_draft_json TEXT NOT NULL,
                session_stats_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                created_by TEXT NOT NULL,
                created_role TEXT NOT NULL,
                supervisor_id TEXT DEFAULT '',
                supervisor_comment TEXT DEFAULT '',
                approved_at TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS generated_materials (
                material_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                patient_uuid TEXT NOT NULL,
                life_context TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                disorder_type TEXT NOT NULL,
                engine_used TEXT NOT NULL,
                items_json TEXT NOT NULL,
                non_medical_label TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS speech_sessions (
                session_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                patient_uuid TEXT NOT NULL,
                scoring_criteria_version TEXT NOT NULL,
                latency_threshold_ms INTEGER NOT NULL DEFAULT 1500,
                accuracy_threshold_pct INTEGER NOT NULL DEFAULT 80,
                slmm_mode TEXT NOT NULL DEFAULT 'cloud',
                asr_engine TEXT NOT NULL DEFAULT 'aihub-dysarthria-conformer-ko-v1',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS speech_utterances (
                utterance_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                patient_uuid TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                prompt_text TEXT NOT NULL,
                target_word TEXT NOT NULL,
                stimulus_end_ms INTEGER NOT NULL,
                auto_onset_ms INTEGER NOT NULL,
                manual_onset_ms INTEGER NOT NULL,
                reaction_time_ms INTEGER NOT NULL,
                layer1_audio_quality_json TEXT NOT NULL,
                layer2_asr_json TEXT NOT NULL,
                layer3_timing_json TEXT NOT NULL,
                layer4_acoustic_json TEXT NOT NULL,
                layer5_linguistic_json TEXT NOT NULL,
                layer6_therapist_review_json TEXT NOT NULL,
                multimodal_json TEXT NOT NULL DEFAULT '{}',
                review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                reviewed_by TEXT DEFAULT '',
                reviewed_role TEXT DEFAULT '',
                reviewed_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS homecare_assignments (
                assignment_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                patient_uuid TEXT NOT NULL,
                target_group TEXT NOT NULL,
                title TEXT NOT NULL,
                life_context TEXT NOT NULL,
                daily_goal_count INTEGER NOT NULL,
                tasks_json TEXT NOT NULL,
                approval_status TEXT NOT NULL DEFAULT 'APPROVED',
                approved_by TEXT NOT NULL,
                logs_json TEXT NOT NULL DEFAULT '[]',
                completed_trials INTEGER NOT NULL DEFAULT 0,
                total_target_trials INTEGER NOT NULL DEFAULT 10,
                average_accuracy_pct REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS extension_plugins (
                plugin_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                domain_code TEXT NOT NULL,
                title TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_settings (
                tenant_id TEXT PRIMARY KEY,
                slmm_mode TEXT NOT NULL DEFAULT 'local_slmm',
                slmm_model_name TEXT NOT NULL DEFAULT 'Ko-Rehab-sLMM-3B-OnDevice-GGUF',
                network_isolation_mode INTEGER NOT NULL DEFAULT 1,
                asr_model_name TEXT NOT NULL DEFAULT 'AIHub-Dysarthria-Conformer-KO-v2.1',
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    def _init_audit_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS access_logs (
                log_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                patient_uuid TEXT DEFAULT '',
                outcome TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS state_change_history (
                history_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS org_accounts (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                email TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                auth_mode TEXT NOT NULL DEFAULT 'ORG_SSO',
                account_status TEXT NOT NULL DEFAULT 'ACTIVE',
                approved_by TEXT DEFAULT 'SYSTEM_SSO',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Audit & State Change Logging (REQ-014)
    # ------------------------------------------------------------------
    def log_access(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "ALLOW",
        patient_uuid: str = "",
        detail: str = "",
    ) -> str:
        log_id = f"alog-{uuid.uuid4().hex[:12]}"
        with self.connect_audit(tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO access_logs (
                    log_id, tenant_id, actor_id, actor_role, action,
                    resource_type, resource_id, patient_uuid, outcome, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log_id,
                    sanitize_tenant_id(tenant_id),
                    actor_id,
                    actor_role,
                    action,
                    resource_type,
                    resource_id,
                    patient_uuid,
                    outcome,
                    detail,
                    now_iso(),
                ),
            )
            conn.commit()
        return log_id

    def log_state_change(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        from_state: str,
        to_state: str,
        actor_id: str,
        actor_role: str,
        reason: str,
    ) -> str:
        history_id = f"hist-{uuid.uuid4().hex[:12]}"
        with self.connect_audit(tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO state_change_history (
                    history_id, tenant_id, entity_type, entity_id,
                    from_state, to_state, actor_id, actor_role, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    sanitize_tenant_id(tenant_id),
                    entity_type,
                    entity_id,
                    from_state,
                    to_state,
                    actor_id,
                    actor_role,
                    reason,
                    now_iso(),
                ),
            )
            conn.commit()
        return history_id

    def list_audit_records(
        self, tenant_id: str, limit: int = 50, after: str = ""
    ) -> Dict[str, Any]:
        capped_limit = max(1, min(int(limit or 50), 200))
        with self.connect_audit(tenant_id) as conn:
            if after:
                access_rows = conn.execute(
                    """
                    SELECT * FROM access_logs
                    WHERE tenant_id = ? AND log_id < ?
                    ORDER BY created_at DESC, log_id DESC LIMIT ?
                    """,
                    (sanitize_tenant_id(tenant_id), after, capped_limit),
                ).fetchall()
            else:
                access_rows = conn.execute(
                    """
                    SELECT * FROM access_logs
                    WHERE tenant_id = ?
                    ORDER BY created_at DESC, log_id DESC LIMIT ?
                    """,
                    (sanitize_tenant_id(tenant_id), capped_limit),
                ).fetchall()

            state_rows = conn.execute(
                """
                SELECT * FROM state_change_history
                WHERE tenant_id = ?
                ORDER BY created_at DESC, history_id DESC LIMIT ?
                """,
                (sanitize_tenant_id(tenant_id), capped_limit),
            ).fetchall()

        access_items = [dict(r) for r in access_rows]
        state_items = [dict(r) for r in state_rows]
        next_cursor = access_items[-1]["log_id"] if len(access_items) == capped_limit else None
        return {
            "items": access_items,
            "state_changes": state_items,
            "next": next_cursor,
            "limit": capped_limit,
        }

    # ------------------------------------------------------------------
    # Tenant & Admin Guard (REQ-013)
    # ------------------------------------------------------------------
    def enforce_clinical_access(
        self,
        session_tenant_id: str,
        target_tenant_id: str,
        actor_id: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str = "*",
        patient_uuid: str = "",
    ) -> Tuple[bool, Optional[Tuple[int, str, str]]]:
        """
        Enforces:
        1) Cross-tenant isolation: session_tenant_id must match target_tenant_id (returns 404 on mismatch per backend-api skill)
        2) Admin clinical data block (REQ-013): 관리자(admin/관리자)는 임상 데이터(치료계획, SOAP, 음성·발화, 교구, 환자 실명) 직접 열람 불가
        3) Logs every access attempt (ALLOW / DENY) into AccessLog (REQ-014)
        """
        s_tenant = sanitize_tenant_id(session_tenant_id)
        t_tenant = sanitize_tenant_id(target_tenant_id)
        if s_tenant != t_tenant:
            self.log_access(
                tenant_id=s_tenant,
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_uuid=patient_uuid,
                outcome="DENY_CROSS_TENANT",
                detail=f"Cross-tenant access denied: {s_tenant} -> {t_tenant}",
            )
            return False, (404, "RESOURCE_NOT_FOUND", "요청한 기관 리소스를 찾을 수 없어요.")

        normalized_role = (actor_role or "").strip().lower()
        if normalized_role in ("admin", "관리자", "system_admin"):
            self.log_access(
                tenant_id=s_tenant,
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                patient_uuid=patient_uuid,
                outcome="DENY_ADMIN_CLINICAL_BLOCK",
                detail="관리자(admin) 계정은 환자 임상 데이터 및 음성 데이터를 직접 열람할 수 없어요.",
            )
            return False, (
                403,
                "ADMIN_CLINICAL_ACCESS_BLOCKED",
                "기관 관리자는 개인정보 보호 정책에 따라 임상·음성 데이터를 직접 열람할 수 없어요. 감사 로그만 조회할 수 있어요.",
            )

        self.log_access(
            tenant_id=s_tenant,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_uuid=patient_uuid,
            outcome="ALLOW",
            detail="임상 데이터 접근 허용",
        )
        return True, None

    # ------------------------------------------------------------------
    # Patient Identity & UUID Pseudonymization + 4 Consents (REQ-011, REQ-012)
    # ------------------------------------------------------------------
    def register_patient_with_consents(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        full_name: str,
        birth_year: int,
        phone: str,
        guardian_contact: str,
        consents: Dict[str, bool],
        patient_uuid: Optional[str] = None,
    ) -> Dict[str, Any]:
        t = sanitize_tenant_id(tenant_id)
        p_uuid = patient_uuid or f"pt-{uuid.uuid4()}"
        ts = now_iso()

        c_terms = 1 if consents.get("terms_of_service") else 0
        c_voice = 1 if consents.get("voice_collection") else 0
        c_ext_ai = 1 if consents.get("external_ai_transfer") else 0
        c_research = 1 if consents.get("pseudonym_research") else 0

        with self.connect_pii(t) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO patient_identity (
                    patient_uuid, tenant_id, full_name, birth_year, phone, guardian_contact, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (p_uuid, t, full_name.strip(), int(birth_year), phone.strip(), guardian_contact.strip(), ts),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO patient_consents (
                    patient_uuid, tenant_id, terms_of_service, voice_collection,
                    external_ai_transfer, pseudonym_research, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (p_uuid, t, c_terms, c_voice, c_ext_ai, c_research, actor_id, ts),
            )
            conn.commit()

        self.log_access(
            tenant_id=t,
            actor_id=actor_id,
            actor_role=actor_role,
            action="REGISTER_PATIENT_PII_AND_CONSENT",
            resource_type="patient_identity",
            resource_id=p_uuid,
            patient_uuid=p_uuid,
            outcome="ALLOW",
            detail=f"UUID 가명화 발급 및 4종 동의 저장(external_ai={bool(c_ext_ai)})",
        )
        self.log_state_change(
            tenant_id=t,
            entity_type="patient_consents",
            entity_id=p_uuid,
            from_state="INITIAL",
            to_state=f"TOS:{c_terms}|VOICE:{c_voice}|EXT_AI:{c_ext_ai}|RESEARCH:{c_research}",
            actor_id=actor_id,
            actor_role=actor_role,
            reason="개인정보 4종 분리 동의 등록",
        )

        return self.get_patient_pseudonym_profile(t, p_uuid)

    def update_patient_consents(
        self,
        tenant_id: str,
        patient_uuid: str,
        actor_id: str,
        actor_role: str,
        consents: Dict[str, bool],
    ) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        existing = self.get_patient_consents(t, patient_uuid)
        if not existing:
            return None

        prev_state = (
            f"TOS:{int(existing['terms_of_service'])}|"
            f"VOICE:{int(existing['voice_collection'])}|"
            f"EXT_AI:{int(existing['external_ai_transfer'])}|"
            f"RESEARCH:{int(existing['pseudonym_research'])}"
        )

        c_terms = 1 if consents.get("terms_of_service", existing["terms_of_service"]) else 0
        c_voice = 1 if consents.get("voice_collection", existing["voice_collection"]) else 0
        c_ext_ai = 1 if consents.get("external_ai_transfer", existing["external_ai_transfer"]) else 0
        c_research = 1 if consents.get("pseudonym_research", existing["pseudonym_research"]) else 0

        with self.connect_pii(t) as conn:
            conn.execute(
                """
                UPDATE patient_consents
                SET terms_of_service = ?, voice_collection = ?,
                    external_ai_transfer = ?, pseudonym_research = ?,
                    updated_by = ?, updated_at = ?
                WHERE patient_uuid = ? AND tenant_id = ?
                """,
                (c_terms, c_voice, c_ext_ai, c_research, actor_id, now_iso(), patient_uuid, t),
            )
            conn.commit()

        new_state = f"TOS:{c_terms}|VOICE:{c_voice}|EXT_AI:{c_ext_ai}|RESEARCH:{c_research}"
        self.log_state_change(
            tenant_id=t,
            entity_type="patient_consents",
            entity_id=patient_uuid,
            from_state=prev_state,
            to_state=new_state,
            actor_id=actor_id,
            actor_role=actor_role,
            reason="개인정보 4종 동의 변경",
        )
        return self.get_patient_consents(t, patient_uuid)

    def get_patient_consents(self, tenant_id: str, patient_uuid: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.connect_pii(t) as conn:
            row = conn.execute(
                "SELECT * FROM patient_consents WHERE patient_uuid = ? AND tenant_id = ?",
                (patient_uuid, t),
            ).fetchone()
        if not row:
            return None
        return {
            "patient_uuid": row["patient_uuid"],
            "tenant_id": row["tenant_id"],
            "terms_of_service": bool(row["terms_of_service"]),
            "voice_collection": bool(row["voice_collection"]),
            "external_ai_transfer": bool(row["external_ai_transfer"]),
            "pseudonym_research": bool(row["pseudonym_research"]),
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }

    def get_patient_pseudonym_profile(self, tenant_id: str, patient_uuid: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.connect_pii(t) as conn:
            id_row = conn.execute(
                "SELECT * FROM patient_identity WHERE patient_uuid = ? AND tenant_id = ?",
                (patient_uuid, t),
            ).fetchone()
        if not id_row:
            return None
        consents = self.get_patient_consents(t, patient_uuid) or {}
        name = id_row["full_name"]
        masked_name = name[0] + "*" * max(1, len(name) - 1) if name else "대상자"
        return {
            "patient_uuid": id_row["patient_uuid"],
            "tenant_id": id_row["tenant_id"],
            "masked_name": masked_name,
            "birth_year": id_row["birth_year"],
            "consents": consents,
            "physical_isolation": {
                "pii_db_file": self.pii_db_path(t).name,
                "clinical_db_file": self.clinical_db_path(t).name,
                "clinical_contains_pii": False,
            },
        }

    def list_patients(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        capped = max(1, min(int(limit or 50), 200))
        with self.connect_pii(t) as conn:
            rows = conn.execute(
                "SELECT patient_uuid FROM patient_identity WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (t, capped),
            ).fetchall()
        result: List[Dict[str, Any]] = []
        for r in rows:
            prof = self.get_patient_pseudonym_profile(t, r["patient_uuid"])
            if prof:
                result.append(prof)
        return result

    def verify_external_ai_consent(
        self,
        tenant_id: str,
        patient_uuid: str,
        actor_id: str,
        actor_role: str,
        requested_engine: str = "external_llm",
    ) -> Tuple[bool, Optional[Tuple[int, str, str]]]:
        """
        REQ-011: 외부 AI 미동의 시 LLM 호출 자동 차단.
        온디바이스/로컬 sLMM('local_slmm')은 외부 전송이 없으므로 이용약관+음성수집 동의 시 허용하되,
        외부 LLM('external_llm' / 'cloud') 호출은 external_ai_transfer == True가 아니면 즉시 403 차단한다.
        """
        consents = self.get_patient_consents(tenant_id, patient_uuid)
        if not consents:
            return False, (404, "PATIENT_CONSENT_NOT_FOUND", "대상자의 개인정보 동의 정보를 찾을 수 없어요.")

        if not consents["terms_of_service"] or not consents["voice_collection"]:
            self.log_access(
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_role=actor_role,
                action="CALL_AI_ENGINE",
                resource_type="consent_gate",
                resource_id=patient_uuid,
                patient_uuid=patient_uuid,
                outcome="DENY_MISSING_MANDATORY_CONSENT",
                detail="필수 동의(이용약관 또는 음성 수집) 미완료",
            )
            return False, (
                403,
                "MANDATORY_CONSENT_REQUIRED",
                "필수 동의(이용약관 및 음성 수집)가 완료되지 않아 분석 및 생성 기능을 실행할 수 없어요.",
            )

        if requested_engine in ("external_llm", "cloud", "cloud_llm") and not consents["external_ai_transfer"]:
            self.log_access(
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_role=actor_role,
                action="CALL_EXTERNAL_LLM",
                resource_type="consent_gate",
                resource_id=patient_uuid,
                patient_uuid=patient_uuid,
                outcome="BLOCKED_EXTERNAL_AI_UNCONSENTED",
                detail="외부 AI 전송 동의(external_ai_transfer=False) 미동의로 외부 LLM 호출 자동 차단",
            )
            return False, (
                403,
                "EXTERNAL_AI_CONSENT_BLOCKED",
                "대상자가 '외부 AI 전송 동의'에 동의하지 않아 외부 LLM 호출이 자동 차단되었어요. 온디바이스 한국어 경량 모델(sLMM) 모드를 사용하거나 동의를 업데이트해 주세요.",
            )

        return True, None

    # ------------------------------------------------------------------
    # Organization Accounts & Auth Onboarding (확정된 답변 기본값 반영)
    # ------------------------------------------------------------------
    def list_org_accounts(self, tenant_id: str) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.connect_audit(t) as conn:
            rows = conn.execute(
                "SELECT * FROM org_accounts WHERE tenant_id = ? ORDER BY created_at ASC",
                (t,),
            ).fetchall()
        return [dict(r) for r in rows]

    def register_or_approve_org_account(
        self,
        tenant_id: str,
        user_id: str,
        email: str,
        display_name: str,
        role: str,
        auth_mode: str = "ORG_SSO",
        account_status: str = "ACTIVE",
        approved_by: str = "SYSTEM_SSO",
    ) -> Dict[str, Any]:
        """
        Supports two onboarding flows (확정된 답변 note 반영):
        1. ORG_SSO (기관 SSO 계정 로그인 — 기본값): 병원/대학 실습기관 도메인 인증 시 즉시 ACTIVE
        2. SELF_SIGNUP_ADMIN_APPROVAL (일반 가입 후 기관 관리자 승인): PENDING_APPROVAL 생성 후 관리자 승인 시 ACTIVE 전환
        """
        t = sanitize_tenant_id(tenant_id)
        ts = now_iso()
        with self.connect_audit(t) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO org_accounts (
                    user_id, tenant_id, email, display_name, role, auth_mode, account_status, approved_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, t, email, display_name, role, auth_mode, account_status, approved_by, ts),
            )
            conn.commit()
        return {
            "user_id": user_id,
            "tenant_id": t,
            "email": email,
            "display_name": display_name,
            "role": role,
            "auth_mode": auth_mode,
            "account_status": account_status,
            "approved_by": approved_by,
        }
