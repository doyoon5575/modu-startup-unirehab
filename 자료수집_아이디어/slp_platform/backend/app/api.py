"""
경량 REST API (표준 라이브러리 http.server). FastAPI 로 교체 가능하도록 핸들러를 함수형으로 둔다.
엔드포인트
  GET  /api/sessions/{id}/review-summary       상단 검토 진행 수
  GET  /api/sessions/{id}/trials?filter=미검토  A. 문항 목록
  GET  /api/trials/{id}                         B. 반응·근거
  POST /api/trials/{id}/review                  C. 치료사 판단 저장(row_version 필요)
  GET  /api/sessions/{id}/metrics               ② 회기 결과
  POST /api/sessions/{id}/finalize              회기 결과 확정
  POST /api/sessions/{id}/plan                  ③ 다음 계획 초안 생성
  POST /api/plans/{id}/proposals/{pid}          수락/수정/채택하지 않음
  POST /api/plans/{id}/approve                  다음 회기 계획 승인
  POST /api/plans/{id}/home-assign              가정 연습 배정
  GET  /api/sessions/{id}/report                회기 결과보고서
  GET  /api/patients/{id}/today                 대상자 오늘 화면
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from .enums import *
from .repository import Repo, SaveError, ConflictError
from . import review_service, session_service, planner, reports, metrics_engine


def make_handler(repo: Repo, users: dict):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _user(self):
            return users[self.headers.get("X-User-Id")]

        def do_GET(self):
            u = urlparse(self.path); parts = u.path.strip("/").split("/"); q = parse_qs(u.query)
            try:
                if parts[:2] == ["api", "sessions"] and parts[3] == "review-summary":
                    return self._send(200, review_service.review_summary(repo, parts[2]))
                if parts[:2] == ["api", "sessions"] and parts[3] == "trials":
                    ts = review_service.filter_trials(repo, parts[2], q.get("filter", ["전체"])[0])
                    return self._send(200, [review_service.trial_card(t, repo.stimuli[t.stimulus_id].label) for t in ts])
                if parts[:2] == ["api", "trials"]:
                    return self._send(200, repo.trials[parts[2]].to_dict())
                if parts[:2] == ["api", "sessions"] and parts[3] == "metrics":
                    return self._send(200, metrics_engine.compute_session_metrics(repo, parts[2]))
                if parts[:2] == ["api", "sessions"] and parts[3] == "report":
                    return self._send(200, {"text": reports.session_report(repo, parts[2], q.get("prev", [None])[0])})
                if parts[:2] == ["api", "patients"] and parts[3] == "today":
                    return self._send(200, reports.patient_today_view(repo, parts[2]))
                return self._send(404, {"error": "not found"})
            except Exception as e:
                return self._send(400, {"error": str(e)})

        def do_POST(self):
            u = urlparse(self.path); parts = u.path.strip("/").split("/")
            n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
            try:
                user = self._user()
                if parts[:2] == ["api", "trials"] and parts[3] == "review":
                    t = review_service.review_trial(repo, user, parts[2], expected_row_version=body["row_version"],
                        usage=TrialUsage(body["usage"]), exclusion_reason=body.get("exclusion_reason"),
                        first=FirstResponseJudgement(body["first"]) if body.get("first") else None,
                        cues=[CueType(c) for c in body.get("cues", [])],
                        post=PostCueJudgement(body["post"]) if body.get("post") else None,
                        tags=[ObservationTag(x) for x in body.get("tags", [])], note=body.get("note", ""),
                        therapist_transcripts=body.get("transcripts"), onset_correction=body.get("onset"),
                        modification_reason=ModificationReason(body["reason"]) if body.get("reason") else None,
                        hold_reason=body.get("hold_reason"))
                    return self._send(200, {"saved": True, "row_version": t.row_version, "status": t.review.review_status.value})
                if parts[:2] == ["api", "sessions"] and parts[3] == "finalize":
                    s = session_service.finalize_result(repo, user, parts[2], body.get("interpretation", ""), body.get("acknowledge_holds", False))
                    return self._send(200, {"state": s.state.value, "result_version": s.result_version})
                if parts[:2] == ["api", "sessions"] and parts[3] == "plan":
                    p = planner.build_plan(repo, user, parts[2], body.get("prev_session_id"))
                    return self._send(200, p.to_dict())
                if parts[:2] == ["api", "plans"] and parts[3] == "proposals":
                    p = planner.decide_proposal(repo, user, parts[2], parts[4], ProposalDecision(body["decision"]), body.get("edit"))
                    return self._send(200, p.to_dict())
                if parts[:2] == ["api", "plans"] and parts[3] == "approve":
                    p = planner.approve_plan(repo, user, parts[2]); return self._send(200, {"state": p.state.value})
                if parts[:2] == ["api", "plans"] and parts[3] == "home-assign":
                    ha = planner.assign_home_practice(repo, user, parts[2], body["proposal_id"], body.get("guidance", []), body.get("stop_rule", ""))
                    return self._send(200, ha.to_dict())
                return self._send(404, {"error": "not found"})
            except SaveError as e:
                return self._send(503, {"saved": False, "error": str(e), "retry": True})
            except ConflictError as e:
                return self._send(409, {"saved": False, "error": str(e), "conflict": True})
            except Exception as e:
                return self._send(400, {"error": str(e)})
    return H


def serve(repo: Repo, users: dict, port: int = 8000):
    HTTPServer(("0.0.0.0", port), make_handler(repo, users)).serve_forever()
