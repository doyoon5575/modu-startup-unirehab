"""인메모리 저장소(파일 JSON 영속화). 실제 배포 시 schema/schema.sql 로 교체."""
import json, os
from typing import Dict, Any
from .models import *


class SaveError(Exception):
    """저장 실패 시 '저장됨' 표시 금지 → 재시도·이동 경고."""


class ConflictError(Exception):
    """다른 사용자가 수정: 최신 변경 확인 후 충돌 해결."""


class Repo:
    def __init__(self, path: str = None, fail_next_save: bool = False):
        self.path = path
        self.fail_next_save = fail_next_save
        self.orgs: Dict[str, Organization] = {}
        self.users: Dict[str, User] = {}
        self.consents: Dict[str, Consent] = {}
        self.access_logs: list = []
        self.patients: Dict[str, Patient] = {}
        self.assessments: Dict[str, Assessment] = {}
        self.goals: Dict[str, Goal] = {}
        self.stimuli: Dict[str, Stimulus] = {}
        self.criteria: Dict[str, ScoringCriterion] = {}
        self.evidence: Dict[str, EvidenceItem] = {}
        self.sessions: Dict[str, Session] = {}
        self.activities: Dict[str, Activity] = {}
        self.trials: Dict[str, Trial] = {}
        self.plans: Dict[str, NextSessionPlan] = {}
        self.home_assignments: Dict[str, HomeAssignment] = {}
        self.home_reports: Dict[str, HomePracticeReport] = {}
        self.validation_items: Dict[str, ValidationItem] = {}

    # ---- 저장 (실패 처리 포함)
    def save_trial(self, trial: Trial, expected_row_version: int):
        if self.fail_next_save:
            self.fail_next_save = False
            raise SaveError("저장 실패: 네트워크 오류. 저장되지 않았습니다. 재시도하거나, 이동 시 변경 내용이 사라집니다.")
        stored = self.trials.get(trial.id)
        if stored and stored.row_version != expected_row_version:
            raise ConflictError(f"다른 사용자가 문항 {trial.id}를 수정했습니다(현재 v{stored.row_version}, 내 기준 v{expected_row_version}). 최신 변경을 확인한 뒤 다시 저장하세요.")
        trial.row_version = expected_row_version + 1
        self.trials[trial.id] = trial
        return trial.row_version

    def log_access(self, user_id: str, patient_id: str, action: str):
        self.access_logs.append(AccessLog(new_id("LOG"), user_id, patient_id, action, now()))

    def trials_of_session(self, session_id: str):
        return sorted([t for t in self.trials.values() if t.session_id == session_id], key=lambda t: t.order)

    def dump(self) -> Dict[str, Any]:
        out = {}
        for name in ["orgs","users","consents","patients","assessments","goals","stimuli","criteria","evidence",
                     "sessions","activities","trials","plans","home_assignments","home_reports","validation_items"]:
            out[name] = {k: v.to_dict() for k, v in getattr(self, name).items()}
        out["access_logs"] = [a.to_dict() for a in self.access_logs]
        return out

    def persist(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.dump(), f, ensure_ascii=False, indent=1)
