"""
Speech & Utterance 6-Layer Analysis Service, Manual Onset Calibration,
3-Column Review Support, Bulk Approval Prohibition, and Scoring Criteria Invalidation.

Covers:
- REQ-004: 음성·발화 분석 6층 분리 아키텍처
  * Layer 1: 오디오 품질확인(Audio Quality — SNR, 클리핑, 배경소음 검증)
  * Layer 2: 자동전사(ASR — AI 허브 구음장애 특화 ASR 전사 및 음절 신뢰도)
  * Layer 3: 시간측정(Timing — 자극 종료 시점, 자동/수동 발화 시작점 Onset, 반응시간 Latency 실시간 재계산)
  * Layer 4: 음향관찰(Acoustic Observation — F0, 강도 dB, Jitter/Shimmer, 쉼 구간)
  * Layer 5: 언어반응분류(Linguistic Classification — 정반응, 의미착어, 음소착어, 신조어, 무반응)
  * Layer 6: 치료사검토(Therapist Review — 개별 문항 확인·보정, AI 일괄 승인(Bulk Approve) 원천 배제)
- REQ-005: 카메라 기반 안면·구강 움직임 동시 인식 멀티모달 분석(입술 개구도 lip_aperture_mm, 안면 좌우 비대칭 facial_asymmetry_idx, 조음 탐색 동작 groping_detected,
   시각적 발화 시작점 visual_onset_ms와 음향 시작점 audio_onset_ms 비교 측정)
- REQ-007: AI 허브 구음장애 음성인식 데이터셋 기반 파인튜닝 한국어 ASR 엔진 연동 인터페이스
- REQ-016: 채점 기준 변경 시 기존에 이미 검토 완료(REVIEWED)된 문항이라도 '재확인 필요(RECHECK_REQUIRED)' 상태로 자동 전환
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.clinical_service import compute_role_permissions
from core.db import NON_MEDICAL_NOTICES, DatabaseManager, now_iso, sanitize_tenant_id

AIHUB_DYSARTHRIA_ASR_PROFILES: Dict[str, Dict[str, Any]] = {
    "aihub-dysarthria-conformer-ko-v2.1": {
        "engine_id": "aihub-dysarthria-conformer-ko-v2.1",
        "title": "AI 허브 구음장애 음성인식 데이터셋(한국어) 파인튜닝 Conformer-CTC/Attention v2.1",
        "dataset_source": "AI 허브 장애인의 구음장애 음성인식 데이터(뇌졸중·파킨슨·뇌성마비 발화 코퍼스)",
        "cer_benchmark_pct": 8.4,
        "supports_phoneme_error_tagging": True,
        "supports_slurred_vowel_compensation": True,
    },
    "aihub-apraxia-whisper-ko-v1.4": {
        "engine_id": "aihub-apraxia-whisper-ko-v1.4",
        "title": "AI 허브 구음장애·말실행증 한국어 파인튜닝 Whisper-Medium-KO v1.4",
        "dataset_source": "AI 허브 구음장애 음성인식 데이터셋 + 성인 신경언어장애 임상 발화",
        "cer_benchmark_pct": 9.1,
        "supports_phoneme_error_tagging": True,
        "supports_slurred_vowel_compensation": True,
    },
}


class SpeechAnalysisService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def create_session_with_sample_utterances(
        self,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        patient_uuid: str,
        latency_threshold_ms: int = 1500,
        accuracy_threshold_pct: int = 80,
        slmm_mode: str = "local_slmm",
        asr_engine: str = "aihub-dysarthria-conformer-ko-v2.1",
    ) -> Dict[str, Any]:
        """
        Creates a speech analysis session with 3 realistic utterances containing all 6 separated layers
        and multimodal camera measurements.
        """
        t = sanitize_tenant_id(tenant_id)
        session_id = f"sess-{uuid.uuid4().hex[:10]}"
        ts = now_iso()
        criteria_ver = f"v1.0-L{int(latency_threshold_ms)}-A{int(accuracy_threshold_pct)}"

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                INSERT INTO speech_sessions (
                    session_id, tenant_id, patient_uuid, scoring_criteria_version,
                    latency_threshold_ms, accuracy_threshold_pct, slmm_mode,
                    asr_engine, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    t,
                    patient_uuid,
                    criteria_ver,
                    int(latency_threshold_ms),
                    int(accuracy_threshold_pct),
                    slmm_mode,
                    asr_engine,
                    actor_id,
                    ts,
                    ts,
                ),
            )
            conn.commit()

        sample_specs = [
            {
                "item_index": 1,
                "prompt_text": "약국 창구에서 약사에게 무엇을 내밀어야 하나요?",
                "target_word": "처방전",
                "transcribed_text": "처방전",
                "phoneme_sequence": "ㅊㅓ-ㅂㅏㅇ-ㅈㅓㄴ",
                "stimulus_end_ms": 1000,
                "auto_onset_ms": 2120,
                "visual_onset_ms": 1840,
                "lip_aperture_mm": 19.4,
                "facial_asymmetry_idx": 0.08,
                "groping_detected": False,
                "error_type": "정반응(Correct)",
                "snr_db": 26.8,
            },
            {
                "item_index": 2,
                "prompt_text": "이 약은 식사 후 몇 분 뒤에 복용하나요?",
                "target_word": "식후 삼십 분",
                "transcribed_text": "식후... 어... 삼십 분",
                "phoneme_sequence": "ㅅㅣㄱ-ㅎㅜ [쉼 420ms] ㅅㅏㅁ-ㅅㅣㅂ-ㅂㅜㄴ",
                "stimulus_end_ms": 1000,
                "auto_onset_ms": 2680,
                "visual_onset_ms": 2110,
                "lip_aperture_mm": 14.2,
                "facial_asymmetry_idx": 0.19,
                "groping_detected": True,
                "error_type": "지연 정반응·조음 탐색 동반(Delayed Correct with Groping)",
                "snr_db": 23.5,
            },
            {
                "item_index": 3,
                "prompt_text": "버스에서 내릴 때 카드를 어디에 태그하나요?",
                "target_word": "환승 단말기",
                "transcribed_text": "환승... 판독기",
                "phoneme_sequence": "ㅎㅘㄴ-ㅅㅡㅇ ㅍㅏㄴ-ㄷㅗㄱ-ㄱㅣ",
                "stimulus_end_ms": 1000,
                "auto_onset_ms": 2410,
                "visual_onset_ms": 1980,
                "lip_aperture_mm": 16.8,
                "facial_asymmetry_idx": 0.14,
                "groping_detected": True,
                "error_type": "의미착어(Semantic Paraphasia)",
                "snr_db": 25.1,
            },
        ]

        for spec in sample_specs:
            self._insert_utterance(
                tenant_id=t,
                session_id=session_id,
                patient_uuid=patient_uuid,
                asr_engine=asr_engine,
                latency_threshold_ms=int(latency_threshold_ms),
                spec=spec,
            )

        self.db.log_state_change(
            tenant_id=t,
            entity_type="speech_session",
            entity_id=session_id,
            from_state="NONE",
            to_state=f"CREATED({criteria_ver})",
            actor_id=actor_id,
            actor_role=actor_role,
            reason="음성·발화 6층 분리 분석 세션 생성",
        )
        return self.get_session_detail(t, session_id)

    def _insert_utterance(
        self,
        tenant_id: str,
        session_id: str,
        patient_uuid: str,
        asr_engine: str,
        latency_threshold_ms: int,
        spec: Dict[str, Any],
    ) -> str:
        utt_id = f"utt-{uuid.uuid4().hex[:10]}"
        ts = now_iso()
        stim_end = int(spec["stimulus_end_ms"])
        auto_onset = int(spec["auto_onset_ms"])
        manual_onset = auto_onset
        reaction_ms = max(0, manual_onset - stim_end)
        within_threshold = reaction_ms <= latency_threshold_ms

        asr_profile = AIHUB_DYSARTHRIA_ASR_PROFILES.get(
            asr_engine, AIHUB_DYSARTHRIA_ASR_PROFILES["aihub-dysarthria-conformer-ko-v2.1"]
        )

        # 6 Separated Architecture Layers (REQ-004)
        layer1_audio_quality = {
            "layer_no": 1,
            "layer_name": "오디오 품질확인(Audio Quality Check)",
            "snr_db": spec["snr_db"],
            "clipping_ratio_pct": 0.0,
            "background_noise_dbfs": -44.2,
            "sample_rate_hz": 16000,
            "quality_grade": "PASS (임상 분석 적합)",
        }
        layer2_asr = {
            "layer_no": 2,
            "layer_name": "자동전사(Dysarthria-Specialized ASR)",
            "asr_engine_id": asr_profile["engine_id"],
            "asr_engine_title": asr_profile["title"],
            "dataset_source": asr_profile["dataset_source"],
            "target_word": spec["target_word"],
            "transcribed_text": spec["transcribed_text"],
            "phoneme_sequence": spec["phoneme_sequence"],
            "confidence": 0.91 if spec["target_word"] == spec["transcribed_text"] else 0.78,
        }
        layer3_timing = {
            "layer_no": 3,
            "layer_name": "시간측정(Onset & Latency Timing)",
            "stimulus_end_ms": stim_end,
            "auto_onset_ms": auto_onset,
            "manual_onset_ms": manual_onset,
            "reaction_time_ms": reaction_ms,
            "latency_threshold_ms": latency_threshold_ms,
            "within_latency_threshold": within_threshold,
            "calibrated_by_human": False,
        }
        layer4_acoustic = {
            "layer_no": 4,
            "layer_name": "음향관찰(Acoustic Observation)",
            "f0_mean_hz": 134.5,
            "intensity_mean_db": 64.2,
            "jitter_local_pct": 1.18,
            "shimmer_local_pct": 4.25,
            "pause_count": 1 if "..." in spec["transcribed_text"] else 0,
        }
        is_exact_match = spec["target_word"] == spec["transcribed_text"]
        layer5_linguistic = {
            "layer_no": 5,
            "layer_name": "언어반응분류(Linguistic Response Classification)",
            "classification": spec["error_type"],
            "semantic_similarity": 0.98 if is_exact_match else 0.74,
            "phonemic_match_ratio": "3/3 (100.0%)" if is_exact_match else "2/4 (50.0%)",
            "auto_suggested_score": 2 if (is_exact_match and within_threshold) else 1,
            "max_score": 2,
        }
        layer6_therapist_review = {
            "layer_no": 6,
            "layer_name": "치료사검토(Therapist Final Review)",
            "review_status": "PENDING_REVIEW",
            "final_score": None,
            "therapist_note": "",
            "bulk_approve_allowed": False,
            "non_medical_notice": NON_MEDICAL_NOTICES["therapist_selected_practice"],
        }

        visual_onset = int(spec["visual_onset_ms"])
        multimodal = {
            "camera_model": "MediaPipe-FaceMesh-468-KO-Clinical",
            "lip_aperture_mm": spec["lip_aperture_mm"],
            "facial_asymmetry_idx": spec["facial_asymmetry_idx"],
            "asymmetry_status": "경미한 우측 입꼬리 비대칭 관찰" if spec["facial_asymmetry_idx"] >= 0.15 else "정상 대칭 범위",
            "groping_detected": bool(spec["groping_detected"]),
            "groping_description": (
                "발성 개시 전 입술·혀 조음 위치 탐색 동작(Groping) 감지됨"
                if spec["groping_detected"]
                else "조음 탐색 동작 없이 즉시 조음 개시"
            ),
            "visual_onset_ms": visual_onset,
            "audio_onset_ms": manual_onset,
            "visual_to_audio_lag_ms": manual_onset - visual_onset,
        }

        with self.db.connect_clinical(tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO speech_utterances (
                    utterance_id, session_id, tenant_id, patient_uuid,
                    item_index, prompt_text, target_word, stimulus_end_ms,
                    auto_onset_ms, manual_onset_ms, reaction_time_ms,
                    layer1_audio_quality_json, layer2_asr_json, layer3_timing_json,
                    layer4_acoustic_json, layer5_linguistic_json, layer6_therapist_review_json,
                    multimodal_json, review_status, reviewed_by, reviewed_role, reviewed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utt_id,
                    session_id,
                    tenant_id,
                    patient_uuid,
                    int(spec["item_index"]),
                    spec["prompt_text"],
                    spec["target_word"],
                    stim_end,
                    auto_onset,
                    manual_onset,
                    reaction_ms,
                    json.dumps(layer1_audio_quality, ensure_ascii=False),
                    json.dumps(layer2_asr, ensure_ascii=False),
                    json.dumps(layer3_timing, ensure_ascii=False),
                    json.dumps(layer4_acoustic, ensure_ascii=False),
                    json.dumps(layer5_linguistic, ensure_ascii=False),
                    json.dumps(layer6_therapist_review, ensure_ascii=False),
                    json.dumps(multimodal, ensure_ascii=False),
                    "PENDING_REVIEW",
                    "",
                    "",
                    "",
                    ts,
                ),
            )
            conn.commit()
        return utt_id

    def calibrate_utterance_onset(
        self,
        tenant_id: str,
        utterance_id: str,
        new_manual_onset_ms: int,
        actor_id: str,
        actor_role: str,
        final_score: Optional[int] = None,
        therapist_note: str = "",
        mark_reviewed: bool = True,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-004 & REQ-006:
        - 발화 시작점(Onset) 수동 보정 시 반응시간(reaction_time_ms = manual_onset_ms - stimulus_end_ms)과
          멀티모달 시각-음향 격차(visual_to_audio_lag_ms)를 실시간 재계산한다.
        - 실습생(실습생/trainee)이 최종 검토 승인(mark_reviewed=True with final approval)을 요청할 경우
          상태를 'TRAINEE_CHECKED_PENDING_SUPERVISOR'로 저장하고 최종 승인(REVIEWED)은 지도교수/언어재활사만 가능하도록 분리한다.
        """
        t = sanitize_tenant_id(tenant_id)
        utt = self.get_utterance(t, utterance_id)
        if not utt:
            return None, (404, "UTTERANCE_NOT_FOUND", "해당 발화 분석 문항을 찾을 수 없어요.")

        session = self.get_session_row(t, utt["session_id"])
        latency_threshold = int(session["latency_threshold_ms"]) if session else 1500

        stim_end = int(utt["stimulus_end_ms"])
        manual_onset = max(stim_end, int(new_manual_onset_ms))
        reaction_time_ms = manual_onset - stim_end
        within_threshold = reaction_time_ms <= latency_threshold

        layer3 = utt["layer3_timing"]
        prev_onset = layer3["manual_onset_ms"]
        layer3["manual_onset_ms"] = manual_onset
        layer3["reaction_time_ms"] = reaction_time_ms
        layer3["latency_threshold_ms"] = latency_threshold
        layer3["within_latency_threshold"] = within_threshold
        layer3["calibrated_by_human"] = True

        multimodal = utt["multimodal"]
        visual_onset = int(multimodal.get("visual_onset_ms", stim_end))
        multimodal["audio_onset_ms"] = manual_onset
        multimodal["visual_to_audio_lag_ms"] = manual_onset - visual_onset

        perms = compute_role_permissions(actor_role)
        prev_status = utt["review_status"]
        if mark_reviewed:
            new_status = "TRAINEE_DRAFT_REVIEWED" if perms["is_trainee"] else "REVIEWED"
        else:
            new_status = prev_status

        layer6 = utt["layer6_therapist_review"]
        layer6["review_status"] = new_status
        layer6["final_score"] = int(final_score) if final_score is not None else layer6.get("final_score", 2)
        layer6["therapist_note"] = therapist_note.strip() or f"Onset 수동 보정 완료({prev_onset} ms -> {manual_onset} ms)"
        layer6["bulk_approve_allowed"] = False

        ts = now_iso()
        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE speech_utterances
                SET manual_onset_ms = ?, reaction_time_ms = ?,
                    layer3_timing_json = ?, layer6_therapist_review_json = ?,
                    multimodal_json = ?, review_status = ?,
                    reviewed_by = ?, reviewed_role = ?, reviewed_at = ?, updated_at = ?
                WHERE utterance_id = ? AND tenant_id = ?
                """,
                (
                    manual_onset,
                    reaction_time_ms,
                    json.dumps(layer3, ensure_ascii=False),
                    json.dumps(layer6, ensure_ascii=False),
                    json.dumps(multimodal, ensure_ascii=False),
                    new_status,
                    actor_id,
                    actor_role,
                    ts,
                    ts,
                    utterance_id,
                    t,
                ),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="speech_utterance",
            entity_id=utterance_id,
            from_state=f"{prev_status}(onset={prev_onset}ms)",
            to_state=f"{new_status}(onset={manual_onset}ms,rt={reaction_time_ms}ms)",
            actor_id=actor_id,
            actor_role=actor_role,
            reason=f"발화 시작점(Onset) 수동 보정 및 반응시간 재계산({reaction_time_ms} ms)",
        )
        return self.get_utterance(t, utterance_id), None

    def reject_bulk_approval_attempt(
        self,
        tenant_id: str,
        session_id: str,
        actor_id: str,
        actor_role: str,
    ) -> Tuple[int, str, str]:
        """
        REQ-004: AI 일괄 승인(Bulk Approve) 기능 배제 강제.
        API로 일괄 승인을 시도하더라도 422 BULK_APPROVAL_PROHIBITED 오류를 반환하고 감사 로그에 남긴다.
        """
        t = sanitize_tenant_id(tenant_id)
        self.db.log_access(
            tenant_id=t,
            actor_id=actor_id,
            actor_role=actor_role,
            action="ATTEMPT_BULK_APPROVE_UTTERANCES",
            resource_type="speech_session",
            resource_id=session_id,
            outcome="REJECTED_CLINICAL_SAFETY_RULE",
            detail="임상 안전 지침에 따라 AI 분석 결과 일괄 승인(Bulk Approve)은 금지되어 있으며 개별 문항 단위로만 검토해야 해요.",
        )
        return (
            422,
            "BULK_APPROVAL_PROHIBITED",
            "임상 안전 기준(REQ-004)에 따라 AI 분석 결과 일괄 승인은 금지되어 있어요. 3단 검토 화면에서 문항별로 발화 시작점(Onset)과 전사 결과를 확인한 뒤 개별 승인해 주세요.",
        )

    def update_scoring_criteria_and_invalidate_reviewed(
        self,
        tenant_id: str,
        session_id: str,
        new_latency_threshold_ms: int,
        new_accuracy_threshold_pct: int,
        actor_id: str,
        actor_role: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-016: 치료사가 채점 기준(반응시간 임계값, 정반응 기준 등)을 변경할 경우
        기존에 이미 검토 완료(REVIEWED / TRAINEE_DRAFT_REVIEWED)된 문항이라도
        즉시 '재확인 필요(RECHECK_REQUIRED)' 상태로 자동 전환한다.
        """
        t = sanitize_tenant_id(tenant_id)
        session = self.get_session_row(t, session_id)
        if not session:
            return None, (404, "SESSION_NOT_FOUND", "음성 분석 세션을 찾을 수 없어요.")

        old_version = session["scoring_criteria_version"]
        new_version = f"v2.0-L{int(new_latency_threshold_ms)}-A{int(new_accuracy_threshold_pct)}"
        ts = now_iso()

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE speech_sessions
                SET scoring_criteria_version = ?,
                    latency_threshold_ms = ?,
                    accuracy_threshold_pct = ?,
                    updated_at = ?
                WHERE session_id = ? AND tenant_id = ?
                """,
                (
                    new_version,
                    int(new_latency_threshold_ms),
                    int(new_accuracy_threshold_pct),
                    ts,
                    session_id,
                    t,
                ),
            )
            rows = conn.execute(
                "SELECT * FROM speech_utterances WHERE session_id = ? AND tenant_id = ? ORDER BY item_index ASC",
                (session_id, t),
            ).fetchall()

            transitioned_count = 0
            for r in rows:
                utt_id = r["utterance_id"]
                prev_status = r["review_status"]
                layer3 = json.loads(r["layer3_timing_json"])
                layer6 = json.loads(r["layer6_therapist_review_json"])

                rt_ms = int(r["reaction_time_ms"])
                layer3["latency_threshold_ms"] = int(new_latency_threshold_ms)
                layer3["within_latency_threshold"] = rt_ms <= int(new_latency_threshold_ms)

                if prev_status in ("REVIEWED", "TRAINEE_DRAFT_REVIEWED"):
                    new_status = "RECHECK_REQUIRED"
                    transitioned_count += 1
                else:
                    new_status = "RECHECK_REQUIRED"
                    transitioned_count += 1

                layer6["review_status"] = new_status
                layer6["recheck_reason"] = (
                    f"채점 기준 변경({old_version} -> {new_version})으로 인해 재확인 필요 상태로 자동 전환됨"
                )

                conn.execute(
                    """
                    UPDATE speech_utterances
                    SET layer3_timing_json = ?,
                        layer6_therapist_review_json = ?,
                        review_status = ?,
                        updated_at = ?
                    WHERE utterance_id = ? AND tenant_id = ?
                    """,
                    (
                        json.dumps(layer3, ensure_ascii=False),
                        json.dumps(layer6, ensure_ascii=False),
                        new_status,
                        ts,
                        utt_id,
                        t,
                    ),
                )

                self.db.log_state_change(
                    tenant_id=t,
                    entity_type="speech_utterance",
                    entity_id=utt_id,
                    from_state=prev_status,
                    to_state=new_status,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    reason=f"채점 기준 변경({old_version} -> {new_version})에 따른 검토 문항 재확인 자동 전환",
                )
            conn.commit()

        detail = self.get_session_detail(t, session_id)
        if detail is not None:
            detail["recheck_transitioned_count"] = transitioned_count
        return detail, None

    def analyze_multimodal_camera_frame(
        self,
        tenant_id: str,
        utterance_id: str,
        actor_id: str,
        actor_role: str,
        lip_aperture_mm: float,
        facial_asymmetry_idx: float,
        groping_detected: bool,
        visual_onset_ms: int,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, str]]]:
        """
        REQ-005: 카메라 기반 안면·구강 움직임 동시 인식 멀티모달 분석 업데이트 및
        시각적 발화 시작점(Visual Onset)과 음향 시작점(Audio Onset) 비교 측정.
        """
        t = sanitize_tenant_id(tenant_id)
        utt = self.get_utterance(t, utterance_id)
        if not utt:
            return None, (404, "UTTERANCE_NOT_FOUND", "해당 발화 문항을 찾을 수 없어요.")

        audio_onset_ms = int(utt["manual_onset_ms"])
        v_onset_ms = int(visual_onset_ms)
        lag_ms = audio_onset_ms - v_onset_ms
        asym = round(float(facial_asymmetry_idx), 3)
        lip_mm = round(float(lip_aperture_mm), 1)

        multimodal = {
            "camera_model": "MediaPipe-FaceMesh-468-KO-Clinical",
            "lip_aperture_mm": lip_mm,
            "facial_asymmetry_idx": asym,
            "asymmetry_status": (
                "중등도 이상 안면 좌우 비대칭 감지(구강 운동 협응 확인 권장)"
                if asym >= 0.15
                else "정상 대칭 범위"
            ),
            "groping_detected": bool(groping_detected),
            "groping_description": (
                f"시각 시작점({v_onset_ms} ms)부터 음향 시작점({audio_onset_ms} ms) 사이 {lag_ms} ms 동안 조음 탐색 동작(Groping) 감지됨"
                if groping_detected
                else "조음 탐색 동작 없음"
            ),
            "visual_onset_ms": v_onset_ms,
            "audio_onset_ms": audio_onset_ms,
            "visual_to_audio_lag_ms": lag_ms,
        }

        with self.db.connect_clinical(t) as conn:
            conn.execute(
                """
                UPDATE speech_utterances
                SET multimodal_json = ?, updated_at = ?
                WHERE utterance_id = ? AND tenant_id = ?
                """,
                (json.dumps(multimodal, ensure_ascii=False), now_iso(), utterance_id, t),
            )
            conn.commit()

        self.db.log_state_change(
            tenant_id=t,
            entity_type="speech_utterance_multimodal",
            entity_id=utterance_id,
            from_state="PREV_MULTIMODAL",
            to_state=f"VISUAL:{v_onset_ms}ms|AUDIO:{audio_onset_ms}ms|LAG:{lag_ms}ms|GROPING:{bool(groping_detected)}",
            actor_id=actor_id,
            actor_role=actor_role,
            reason="카메라 기반 멀티모달(입술 개구도·안면 비대칭·조음 탐색·시각/음향 Onset) 측정 갱신",
        )
        return self.get_utterance(t, utterance_id), None

    def get_session_row(self, tenant_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM speech_sessions WHERE session_id = ? AND tenant_id = ?",
                (session_id, t),
            ).fetchone()
        return dict(row) if row else None

    def get_utterance(self, tenant_id: str, utterance_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        with self.db.connect_clinical(t) as conn:
            row = conn.execute(
                "SELECT * FROM speech_utterances WHERE utterance_id = ? AND tenant_id = ?",
                (utterance_id, t),
            ).fetchone()
        if not row:
            return None
        return self._deserialize_utterance(dict(row))

    def get_session_detail(self, tenant_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        sess = self.get_session_row(t, session_id)
        if not sess:
            return None
        with self.db.connect_clinical(t) as conn:
            rows = conn.execute(
                "SELECT * FROM speech_utterances WHERE session_id = ? AND tenant_id = ? ORDER BY item_index ASC",
                (session_id, t),
            ).fetchall()
        utterances = [self._deserialize_utterance(dict(r)) for r in rows]
        total = len(utterances)
        reviewed_cnt = sum(1 for u in utterances if u["review_status"] == "REVIEWED")
        recheck_cnt = sum(1 for u in utterances if u["review_status"] == "RECHECK_REQUIRED")
        sess["utterances"] = utterances
        sess["summary"] = {
            "total_utterances": total,
            "reviewed_count": reviewed_cnt,
            "recheck_required_count": recheck_cnt,
            "review_completion_ratio": f"{reviewed_cnt}/{total} ({round((reviewed_cnt / max(1, total)) * 100.0, 1)}%)",
            "bulk_approve_button_rendered": False,
        }
        sess["asr_engine_profile"] = AIHUB_DYSARTHRIA_ASR_PROFILES.get(
            sess["asr_engine"], AIHUB_DYSARTHRIA_ASR_PROFILES["aihub-dysarthria-conformer-ko-v2.1"]
        )
        return sess

    def list_sessions(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        t = sanitize_tenant_id(tenant_id)
        capped = max(1, min(int(limit or 50), 200))
        with self.db.connect_clinical(t) as conn:
            rows = conn.execute(
                "SELECT session_id FROM speech_sessions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (t, capped),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = self.get_session_detail(t, r["session_id"])
            if d:
                out.append(d)
        return out

    def _deserialize_utterance(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["layer1_audio_quality"] = json.loads(row.pop("layer1_audio_quality_json", "{}"))
        row["layer2_asr"] = json.loads(row.pop("layer2_asr_json", "{}"))
        row["layer3_timing"] = json.loads(row.pop("layer3_timing_json", "{}"))
        row["layer4_acoustic"] = json.loads(row.pop("layer4_acoustic_json", "{}"))
        row["layer5_linguistic"] = json.loads(row.pop("layer5_linguistic_json", "{}"))
        row["layer6_therapist_review"] = json.loads(row.pop("layer6_therapist_review_json", "{}"))
        row["multimodal"] = json.loads(row.pop("multimodal_json", "{}"))
        return row
