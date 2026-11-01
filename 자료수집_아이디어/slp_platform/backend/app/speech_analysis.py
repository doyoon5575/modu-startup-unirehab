"""
음성 분석 층 분리(기획서 7-1):
  녹음 품질 → 음성→문자 → 시간 분석 → 음향·말 분석 → 언어 반응 분석 → (임상 검토는 review_service)
원칙:
  - 장애 발화를 완벽히 인식한다고 전제하지 않는다. 적용 범위 밖이면 자동 판단을 제공하지 않는다.
  - '목표어와 맞는지 확인' 과 '실제로 어떻게 말했는지' 를 분리한다.
  - 문맥에 맞게 오류를 몰래 교정하지 않는다(전사 초안은 들은 그대로).
  - 느린 반응·쉼·반복은 관찰값으로만 기록, 유창성장애·말운동장애로 자동 분류하지 않는다.
  - AI 전사가 맞았다는 이유로 '명료도 높음'이라고 판단하지 않는다.
실제 ASR/음향 엔진은 Adapter 로 교체한다(아래 MockAdapter 는 구조 검증용).
"""
from typing import Protocol, Dict, Any, List, Optional
from .enums import *
from .models import AutoAnalysis, AttemptRecord, TimingMarks, Trial

MODEL_VERSION = "mock-ko-asr-0.1"

# 현재 검증된 적용 범위(출시 전 검증 결과에 따라 갱신). 범위 밖은 OUT_OF_SCOPE.
VALIDATED_SCOPE = {
    "domains": {ClinicalDomain.APHASIA},
    "tasks": {"naming"},
    "response_modes": {ResponseMode.SPEECH, ResponseMode.PICTURE_SELECT},
    "settings": {Setting.CLINIC},
    "languages": {"ko"},
}


class SpeechAdapter(Protocol):
    def check_quality(self, audio_ref: str) -> Dict[str, Any]: ...
    def transcribe(self, audio_ref: str, start: float, end: float) -> Dict[str, Any]: ...
    def detect_onsets(self, audio_ref: str) -> Dict[str, Optional[float]]: ...
    def speech_features(self, audio_ref: str, start: float, end: float) -> Dict[str, Any]: ...


class MockAdapter:
    """구조 검증용. audio_ref 문자열에 심어둔 메타('|' 뒤 JSON)로 결과를 흉내낸다."""
    def _meta(self, audio_ref):
        import json
        if audio_ref and "|" in audio_ref:
            return json.loads(audio_ref.split("|", 1)[1])
        return {}

    def check_quality(self, audio_ref):
        m = self._meta(audio_ref)
        return {"quality": m.get("quality", "ok"), "issues": m.get("issues", []), "snr_db": m.get("snr", 25)}

    def transcribe(self, audio_ref, start, end):
        m = self._meta(audio_ref)
        return {"text": m.get("text", ""), "confidence": m.get("conf", 0.6)}

    def detect_onsets(self, audio_ref):
        m = self._meta(audio_ref)
        return {"stimulus_end": m.get("stim_end", 0.0), "onset": m.get("onset"), "completed": m.get("done")}

    def speech_features(self, audio_ref, start, end):
        m = self._meta(audio_ref)
        return {"rate": m.get("rate"), "repetitions": m.get("reps", []), "pauses": m.get("pauses", [])}


def _in_scope(trial: Trial, patient_domains, task_key: str, language: str) -> List[str]:
    reasons = []
    if not (set(patient_domains) & VALIDATED_SCOPE["domains"]) or (set(patient_domains) - VALIDATED_SCOPE["domains"] - {ClinicalDomain.AAC}):
        reasons.append("대상자 임상 영역이 현재 검증 범위(뇌졸중 후 실어증) 밖")
    if task_key not in VALIDATED_SCOPE["tasks"]:
        reasons.append(f"과제 '{task_key}'는 자동 채점 검증 범위 밖")
    if trial.response_mode not in VALIDATED_SCOPE["response_modes"]:
        reasons.append(f"반응 방식 '{trial.response_mode.value}'는 자동 분석 범위 밖")
    if trial.setting not in VALIDATED_SCOPE["settings"]:
        reasons.append("가정 녹음은 기기·환경별 성능 미검증 → 자동 판정 미제공")
    if language not in VALIDATED_SCOPE["languages"]:
        reasons.append("한국어 외 언어는 미지원")
    return reasons


def analyze_trial(trial: Trial, adapter: SpeechAdapter, patient_domains, task_key: str,
                  accepted_expressions: List[str], language: str = "ko") -> Trial:
    """문항 하나에 대한 자동 분석. 결과는 '자동 분석 제안'으로만 저장되며 치료사 확정과 분리된다."""
    limits: List[str] = []

    # 0. 수집 실패 / 녹음 누락은 분석하지 않고 상태만 기록 (대상자 무반응과 구분)
    if trial.collection == CollectionOutcome.COLLECTION_FAILURE:
        trial.analysis = AutoAnalysis(MODEL_VERSION, RecordingQuality.RERECORD, [RecordingIssue.MISSING],
                                      AnalysisStatus.POOR_RECORDING, ["녹음 누락: 대상자 오반응으로 계산하지 않음"])
        trial.review.usage = TrialUsage.EXCLUDED
        trial.review.exclusion_reason = "수집 실패(녹음 누락)"
        trial.review.review_status = ReviewStatus.EXCLUDED
        return trial
    if trial.collection == CollectionOutcome.PATIENT_NO_RESPONSE:
        trial.analysis = AutoAnalysis(MODEL_VERSION, RecordingQuality.ANALYZABLE, [],
                                      AnalysisStatus.THERAPIST_REVIEW_REQUIRED, ["대상자 무반응: 과제 반응으로 기록, 치료사 확인 필요"])
        trial.review.review_status = ReviewStatus.NEEDS_CHECK
        return trial

    first = trial.attempts[0]
    # 1. 녹음 품질
    q = adapter.check_quality(first.audio_ref)
    issues = [RecordingIssue(i) if i in RecordingIssue._value2member_map_ else RecordingIssue.NOISE for i in q["issues"]]
    if q["quality"] == "bad":
        trial.analysis = AutoAnalysis(MODEL_VERSION, RecordingQuality.RERECORD, issues,
                                      AnalysisStatus.POOR_RECORDING, ["녹음 품질 부족: 임상 점수 산출 보류(" + ", ".join(i.value for i in issues) + ")"])
        trial.review.review_status = ReviewStatus.NEEDS_CHECK
        return trial
    quality = RecordingQuality.NEEDS_REVIEW if q["quality"] == "marginal" else RecordingQuality.ANALYZABLE
    if quality == RecordingQuality.NEEDS_REVIEW:
        limits.append("음질 경계: " + ", ".join(i.value for i in issues))

    # 2. 적용 범위
    scope_reasons = _in_scope(trial, patient_domains, task_key, language)
    if scope_reasons:
        trial.analysis = AutoAnalysis(MODEL_VERSION, quality, issues, AnalysisStatus.OUT_OF_SCOPE, scope_reasons)
        trial.review.review_status = ReviewStatus.NEEDS_CHECK
        # 범위 밖: 전사 초안은 참고용으로만 제공, 반응 분류는 제공하지 않음
        for a in trial.attempts:
            if a.audio_ref:
                t = adapter.transcribe(a.audio_ref, a.audio_start_s or 0, a.audio_end_s or 0)
                a.ai_transcript = t["text"]; a.ai_confidence = t["confidence"]; a.ai_classification = None
        return trial

    # 3. 음성→문자 (들은 그대로) + 목표어 일치 판정 분리
    for a in trial.attempts:
        if a.audio_ref:
            t = adapter.transcribe(a.audio_ref, a.audio_start_s or 0, a.audio_end_s or 0)
            a.ai_transcript = t["text"]
            a.ai_confidence = t["confidence"]
            norm = (t["text"] or "").replace(" ", "")
            a.ai_target_match = any(norm == e.replace(" ", "") for e in accepted_expressions)
            if t["confidence"] < 0.75:
                a.ai_classification = "판정 보류 제안(전사 신뢰도 낮음)"
                limits.append(f"{a.attempt_type}: 전사 신뢰도 {t['confidence']:.2f} → 치료사 확인 필요")
            elif a.ai_target_match:
                a.ai_classification = "성공 제안" if a.attempt_type != "최초 반응" else "독립 성공 제안"
            elif not norm:
                a.ai_classification = "무반응 제안"
            else:
                a.ai_classification = "다른 반응 제안"

    # 4. 시간 분석 (측정 기준을 항상 함께 저장)
    on = adapter.detect_onsets(first.audio_ref)
    trial.timing.stimulus_end_s = on.get("stimulus_end")
    trial.timing.first_speech_onset_s = on.get("onset")
    trial.timing.target_completed_s = on.get("completed")
    trial.timing.auto_values = {"stimulus_end_s": on.get("stimulus_end"), "first_speech_onset_s": on.get("onset"), "target_completed_s": on.get("completed")}
    if len(trial.attempts) > 1 and trial.attempts[1].audio_ref:
        on2 = adapter.detect_onsets(trial.attempts[1].audio_ref)
        trial.timing.cue_given_s = on2.get("stimulus_end")
        trial.timing.post_cue_onset_s = on2.get("onset")
        trial.timing.auto_values.update({"cue_given_s": on2.get("stimulus_end"), "post_cue_onset_s": on2.get("onset")})
    if on.get("onset") is None:
        limits.append("발화 시작점 자동 검출 실패 → 반응 시간 미산출")

    # 5. 음향·말 분석 (관찰값만; 자동 분류 금지)
    feat = adapter.speech_features(first.audio_ref, first.audio_start_s or 0, first.audio_end_s or 0)
    analysis = AutoAnalysis(MODEL_VERSION, quality, issues, AnalysisStatus.AUTO_DONE_PENDING, limits,
                            speech_rate=feat.get("rate"), repetitions=feat.get("repetitions", []), pauses=feat.get("pauses", []))
    if feat.get("repetitions") or feat.get("pauses"):
        analysis.limits.append("반복·쉼은 관찰값입니다. 유창성·말운동 문제로 자동 해석하지 않습니다(언어 표현 어려움으로 인한 지연·수정일 수 있음).")
    trial.analysis = analysis

    # 검토 상태: AI가 확신해도 자동으로 '검토 완료'가 되지 않는다
    if limits:
        trial.review.review_status = ReviewStatus.NEEDS_CHECK
        analysis.status = AnalysisStatus.THERAPIST_REVIEW_REQUIRED
    else:
        trial.review.review_status = ReviewStatus.UNREVIEWED
    return trial
