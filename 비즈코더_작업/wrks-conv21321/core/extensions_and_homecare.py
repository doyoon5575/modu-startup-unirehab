"""
Homecare Assignment & Quantitative Log Module, Domain Extension Plugins,
and Korean Lightweight Model (sLMM) On-Device/Local Runtime Option.

Covers:
- REQ-008: 승인형 가정 훈련(홈케어) 배정 및 관리 모듈(퇴원 성인 환자 및 복지관 대기자를 대상으로 지도교수/언어재활사가 승인한 과제를 배정하고,
   가정 수행 시 분자/분모 정량 이력 및 평균 반응시간을 누적 관리)
- REQ-009: 영역별 확장 모듈(마비말장애, 말실행증, AAC, 시니어 인지) 플러그인 지원(플러그인 레지스트리 조회, 활성화/비활성화 토글, 영역별 전용 프로토콜 실행)
- REQ-010: 한국어 경량 모델(sLMM) 온디바이스/로컬 구동 인터페이스 옵션(망분리 및 보안 환경 대응을 위해 로컬 sLMM GGUF/ONNX 구동 모드 전환 및 외부 네트워크 차단 검증)
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.clinical_service import compute_role_permissions
from core.db import NON_MEDICAL_NOTICES, DatabaseManager, now_iso, sanitize_tenant_id

DEFAULT_EXTENSION_PLUGINS: List[Dict[str, Any]] = [
    {
        "plugin_id": "plugin-dysarthria",
        "domain_code": "DYSARTHRIA",
        "title": "마비말장애 호흡·발성·조음 명료도 확장 모듈",
        "enabled": 1,
        "config": {
            "version": "1.2.0",
            "target_disorder": "마비말장애(Dysarthria)",
            "key_metrics": ["최대발성지속시간(MPT)", "음절 명료도(%)", "말속도(SPS)", "과대비음 지수"],
            "sample_protocol": "복식호흡 연장 발성(/아/ 10초) + 자음 대조 단어쌍 20문항 조음 명료도 훈련",
        },
    },
    {
        "plugin_id": "plugin-apraxia",
        "domain_code": "APRAXIA_OF_SPEECH",
        "title": "말실행증 8단계 자극 모방(Integral Stimulation) 확장 모듈",
        "enabled": 1,
        "config": {
            "version": "1.1.0",
            "target_disorder": "말실행증(Apraxia of Speech)",
            "key_metrics": ["시각-음향 Onset 격차(ms)", "조음 탐색(Groping) 빈도", "다음절 정확도"],
            "sample_protocol": "'보고 듣고 함께 말하기' 시·청각 동시 단서 기반 다음절 생활 어휘 조음 계획 훈련",
        },
    },
    {
        "plugin_id": "plugin-aac",
        "domain_code": "AAC_BOARD",
        "title": "성인 맞춤형 보완대체의사소통(AAC) 상황 표현판 모듈",
        "enabled": 1,
        "config": {
            "version": "1.3.0",
            "target_disorder": "중증 실어증·구음장애(AAC 필요군)",
            "key_metrics": ["상징 선택 반응시간(ms)", "핵심 어휘 조합 정확도", "의사소통 성공률"],
            "sample_protocol": "병원 통증 부위 표현·응급 호출·마트 결제 요청 12분할 한국어 상징+음성합성(TTS) 보드",
        },
    },
    {
        "plugin_id": "plugin-senior-cognition",
        "domain_code": "SENIOR_COGNITION",
        "title": "시니어 인지-의사소통(경도인지장애·치매 예방) 확장 모듈",
        "enabled": 1,
        "config": {
            "version": "1.0.4",
            "target_disorder": "노년기 인지-의사소통장애(MCI·초기 치매)",
            "key_metrics": ["작업기억 회상률", "시간·장소 지남력 점수", "복약·금전 계산 수행도"],
            "sample_protocol": "주간 병원 예약 일정 기억하기 + 약봉투 복용 시간 분류 및 마트 거스름돈 계산 훈련",
        },
    },
]

SLMM_MODELS_CATALOG: Dict[str, Dict[str, Any]] = {
    "Ko-Rehab-sLMM-3B-OnDevice-GGUF": {
        "model_id": "Ko-Rehab-sLMM-3B-OnDevice-GGUF",
        "runtime": "local_slmm",
        "quantization": "Q4_K_M (2.1 GB RAM)",
        "air_gapped_ready": True,
        "external_network_outbound": False,
        "description": "병원·복지관 망분리 PC 및 태블릿 내부에서 외부 인터넷 연결 없이 구동되는 한국어 언어재활 특화 경량 모델",
    },
    "Ko-Speech-sLMM-1.8B-ONNX-Edge": {
        "model_id": "Ko-Speech-sLMM-1.8B-ONNX-Edge",
        "runtime": "local_slmm",
        "quantization": "INT4 ONNX Runtime (1.3 GB RAM)",
        "air_gapped_ready": True,
        "external_network_outbound": False,
        "description": "실습실 저사양 노트북 및 온디바이스 환경용 초경량 한국어 힌트·SOAP 초안 생성 모델",
    },
    "External-Clinical-LLM-KO-Cloud": {
        "model_id": "External-Clinical-LLM-KO-Cloud",
        "runtime": "external_llm",
        "quantization": "FP16 Cloud API",
        "air_gapped_ready": False,
        "external_network_outbound": True,
        "description": "외부 AI 전송 동의(REQ-011)가 완료된 대상자에게만 허용되는 클라우드 고성능 한국어 LLM",
    },
}


class HomecareAndExtensionsService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # REQ-008: 승인형 가정 훈련(홈케어) 배정 및 정량 이력 관리
    # ------------------------------------------------------------------
    def create_homecare_assignment(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        patient_uuid: str,
        target_group: str = "퇴원 성인 환자",
        title: str = "퇴원 후 병원·약국 및 마트 일상 어휘 연속 홈케어 과제",
        life_context: str = "병원·약국 방문",
        daily_goal_count: int = 10,
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-008 & REQ-006:
        - 퇴원 성인 환자 및 복지관 대기자를 대상으로 가정 훈련 과제를 배정한다.
        - 실습생이 배정할 경우 'PENDING_SUPERVISOR'로 생성되며, 지도교수/언어재활사가 배정하거나 승인해야
          'APPROVED(가정 훈련 활성)' 상태가 된다.
        """
        t = sanitize_tenant_id(tenant_id)
        perms = compute_role_permissions(actor_role)
        approval_status = "PENDING_SUPERVISOR" if perms["is_trainee"] else "APPROVED"
        approved_by = "" if perms["is_trainee"] else actor_id

        default_tasks = tasks or [
            {"task_no": 1, "prompt": "처방전을 약국 창구에 제출하는 문장 말하기", "target_word": "처방전"},
            {"task_no": 2, "prompt": "식후 삼십 분 복약 안내 문장 따라 말하기", "target_word": "식후 삼십 분"},
            {"task_no": 3, "prompt": "마트 무인 계산대에서 영수증 요청 문장 말하기", "target_word": "영수증"},
        ]

        assignment_id = f"hc-{uuid.uuid4().hex[:10]}"
        ts = now_iso()
        goal = max(1, int(daily_goal_count or 10))

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                INSERT INTO homecare_assignments (
                    assignment_id, tenant_id, patient_uuid, target_group,
                    title, life_context, daily_goal_count, tasks_json,
                    approval_status, approved_by, logs_json,
                    completed_trials, total_target_trials, average_accuracy_pct,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment_id,
                    t,
                    patient_uuid,
                    target_group,
                    title,
                    life_context,
                    goal,
                    json.dumps(default_tasks, ensure_ascii=False),
                    approval_status,
                    approved_by,
                    "[]",
                    0,
                    goal,
                    0.0,
                    ts,
                    ts,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="homecare_assignment",
            entity_id=assignment_id,
            from_state="NONE",
            to_state=approval_status,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"승인형 가정 훈련(홈케어) 배정({target_group})",
        )
        return self.get_homecare_assignment(t, assignment_id), None

    def record_homecare_training_log(
        self,
        tenant_id: str,
        assignment_id: str,
        actor_id: str,
        actor_role: str,
        correct_count: int,
        trial_count: int,
        avg_reaction_time_ms: int = 1320,
        guardian_memo: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        t = sanitize_tenant_id(tenant_id)
        item = self.get_homecare_assignment(t, assignment_id)
        if not item:
            return None, (404, "HOMECARE_NOT_FOUND", "배정된 가정 훈련 과제를 찾을 수 없어요.")

        t_cnt = max(1, int(trial_count or 10))
        c_cnt = max(0, min(int(correct_count or 0), t_cnt))
        pct = round((c_cnt / t_cnt) * 100.0, 1)

        logs = list(item["logs"])
        log_entry = {
            "log_no": len(logs) + 1,
            "performed_at": now_iso(),
            "correct_numerator": c_cnt,
            "trial_denominator": t_cnt,
            "accuracy_pct": pct,
            "formatted_score": f"{c_cnt}/{t_cnt} ({pct}%)",
            "avg_reaction_time_ms": int(avg_reaction_time_ms),
            "guardian_memo": guardian_memo.strip() or "가정 내 일상 어휘 연습 완료",
        }
        logs.append(log_entry)

        total_completed = sum(int(x["trial_denominator"]) for x in logs)
        total_correct = sum(int(x["correct_numerator"]) for x in logs)
        cumulative_pct = round((total_correct / max(1, total_completed)) * 100.0, 1)

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE homecare_assignments
                SET logs_json = ?,
                    completed_trials = ?,
                    average_accuracy_pct = ?,
                    updated_at = ?
                WHERE assignment_id = ? AND tenant_id = ?
                """,
                (
                    json.dumps(logs, ensure_ascii=False),
                    total_completed,
                    cumulative_pct,
                    now_iso(),
                    assignment_id,
                    t,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="homecare_assignment",
            entity_id=assignment_id,
            from_state=f"TRIALS:{item['completed_trials']}",
            to_state=f"TRIALS:{total_completed}({total_correct}/{total_completed},{cumulative_pct}%)",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"가정 훈련 수행 이력 기록: {c_cnt}/{t_cnt} ({pct}%)",
        )
        return self.get_homecare_assignment(t, assignment_id), None

    def get_homecare_assignment(self, tenant_id: str, assignment_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM homecare_assignments WHERE assignment_id = ? AND tenant_id = ?",
                (assignment_id, t),
            ).fetchone()
        if not row:
            return None
        return self._deserialize_homecare(dict(row))

    def list_homecare_assignments(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        capped = max(1, min(int(limit or 50), 200))
        with self.db.connect_clinical(t) as conn:
            rows = conn.execute(
                "SELECT * FROM homecare_assignments WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (t, capped),
            ).fetchall()
        return [self._deserialize_homecare(dict(r)) for r in rows]

    def _deserialize_homecare(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["tasks"] = json.loads(row.pop("tasks_json", "[]"))
        row["logs"] = json.loads(row.pop("logs_json", "[]"))
        completed = int(row["completed_trials"])
        target = max(1, int(row["total_target_trials"]))
        row["progress_summary"] = f"{completed}/{target} ({round((completed / target) * 100.0, 1)}%)"
        row["non_medical_notice"] = NON_MEDICAL_NOTICES["full_banner"]
        return row

    # ------------------------------------------------------------------
    # REQ-009: 영역별 확장 모듈(마비말장애, 말실행증, AAC, 시니어 인지) 지원
    # ------------------------------------------------------------------
    def ensure_default_plugins(self, tenant_id: str) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS cnt FROM extension_plugins WHERE tenant_id = ?",
                (t,),
            ).fetchone()
            if not existing or int(existing["cnt"]) == 0:
                ts = now_iso()
                for p in DEFAULT_EXTENSION_PLUGINS:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO extension_plugins (
                            plugin_id, tenant_id, domain_code, title, enabled, config_json, updated_by, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["plugin_id"],
                            t,
                            p["domain_code"],
                            p["title"],
                            int(p["enabled"]),
                            json.dumps(p["config"], ensure_ascii=False),
                            "system-init",
                            ts,
                        ),
                    )
                conn.commit()
            rows = conn.execute(
                "SELECT * FROM extension_plugins WHERE tenant_id = ? ORDER BY plugin_id ASC",
                (t,),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d["enabled"])
            d["config"] = json.loads(d.pop("config_json", "{}"))
            out.append(d)
        return out

    def toggle_extension_plugin(
        self,
        tenant_id: str,
        plugin_id: str,
        enabled: bool,
        actor_id: str,
        actor_role: str,
    ) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        self.ensure_default_plugins(t)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM extension_plugins WHERE plugin_id = ? AND tenant_id = ?",
                (plugin_id, t),
            ).fetchone()
            if not row:
                return None
            prev = bool(row["enabled"])
            conn.execute(
                """
                UPDATE extension_plugins
                SET enabled = ?, updated_by = ?, updated_at = ?
                WHERE plugin_id = ? AND tenant_id = ?
                """,
                (1 if enabled else 0, actor_id, now_iso(), plugin_id, t),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="extension_plugin",
            entity_id=plugin_id,
            from_state="ENABLED" if prev else "DISABLED",
            to_state="ENABLED" if enabled else "DISABLED",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"영역별 확장 플러그인 상태 변경({plugin_id})",
        )
        plugins = self.ensure_default_plugins(t)
        for p in plugins:
            if p["plugin_id"] == plugin_id:
                return p
        return None

    # ------------------------------------------------------------------
    # REQ-010: 한국어 경량 모델(sLMM) 온디바이스/로컬 구동 인터페이스 옵션
    # ------------------------------------------------------------------
    def get_runtime_settings(self, tenant_id: str) -> Dict[str, Any]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM runtime_settings WHERE tenant_id = ?",
                (t,),
            ).fetchone()
            if not row:
                ts = now_iso()
                conn.execute(
                    """
                    INSERT INTO runtime_settings (
                        tenant_id, slmm_mode, slmm_model_name,
                        network_isolation_mode, asr_model_name, updated_by, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t,
                        "local_slmm",
                        "Ko-Rehab-sLMM-3B-OnDevice-GGUF",
                        1,
                        "aihub-dysarthria-conformer-ko-v2.1",
                        "system-init",
                        ts,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM runtime_settings WHERE tenant_id = ?",
                    (t,),
                ).fetchone()
        d = dict(row)
        d["network_isolation_mode"] = bool(d["network_isolation_mode"])
        d["available_models"] = list(SLMM_MODELS_CATALOG.values())
        d["active_model_spec"] = SLMM_MODELS_CATALOG.get(
            d["slmm_model_name"], SLMM_MODELS_CATALOG["Ko-Rehab-sLMM-3B-OnDevice-GGUF"]
        )
        return d

    def update_runtime_settings(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        slmm_mode: str,
        slmm_model_name: str,
        network_isolation_mode: bool = True,
        asr_model_name: str = "aihub-dysarthria-conformer-ko-v2.1",
    ) -> Dict[str, Any]:
        t = sanitize_tenant_id(tenant_id)
        prev = self.get_runtime_settings(t)
        mode = "local_slmm" if slmm_mode not in ("local_slmm", "external_llm") else slmm_mode
        model = (
            slmm_model_name
            if slmm_model_name in SLMM_MODELS_CATALOG
            else (
                "Ko-Rehab-sLMM-3B-OnDevice-GGUF"
                if mode == "local_slmm"
                else "External-Clinical-LLM-KO-Cloud"
            )
        )

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE runtime_settings
                SET slmm_mode = ?, slmm_model_name = ?,
                    network_isolation_mode = ?, asr_model_name = ?,
                    updated_by = ?, updated_at = ?
                WHERE tenant_id = ?
                """,
                (
                    mode,
                    model,
                    1 if network_isolation_mode else 0,
                    asr_model_name,
                    actor_id,
                    now_iso(),
                    t,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="runtime_settings",
            entity_id=t,
            from_state=f"{prev['slmm_mode']}:{prev['slmm_model_name']}",
            to_state=f"{mode}:{model}(net_iso={bool(network_isolation_mode)})",
            actor_id=actor_id,
            actor_role=actor_role,
            reason="한국어 경량 모델(sLMM) 온디바이스/로컬 구동 및 망분리 설정 변경",
        )
        return self.get_runtime_settings(t)
