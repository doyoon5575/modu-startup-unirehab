"""
규칙 엔진(기획서 8-2, 자료수집 '다음 회기 제안 규칙').
자동 처방이 아니라 치료사 검토를 위한 후보 생성 규칙. 각 후보는 근거 데이터·해석 한계·먼저 확인할 조건·치료사 확인 항목을 함께 출력한다.
임계값은 치료사가 설정 가능(RuleConfig). 기본값은 임상 처방이 아니며 검증이 필요하다.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from .enums import *
from .repository import Repo
from .metrics_engine import compute_session_metrics, compare_with_previous


@dataclass
class RuleConfig:
    min_trials_for_judgement: int = 8        # 자료 부족 기준
    indep_increase_pp: float = 10.0          # 독립 수행 증가로 볼 %p
    back_half_drop_pp: float = 20.0          # 뒤쪽 과제 저하
    home_drop_pp: float = 20.0               # 가정에서만 저하
    probe_gap_pp: float = 30.0               # 연습 vs 새 자극 차이
    unanalyzable_ratio: float = 0.3          # 분석 불가 비율
    high_indep_pct: float = 80.0             # 목표 달성 확인 검토를 띄울 독립 수행 비율


@dataclass
class Candidate:
    rule_key: str
    title: str
    goal_id: str
    rationale_data: str
    review_direction: str
    precheck: str
    uncertainty: str
    needs_confirmation: str
    related_trial_ids: List[str] = field(default_factory=list)
    activity_draft: str = ""
    evidence_approach_keys: List[str] = field(default_factory=list)


def generate_candidates(repo: Repo, session_id: str, prev_session_id: Optional[str] = None,
                        cfg: RuleConfig = RuleConfig()) -> List[Candidate]:
    m = compute_session_metrics(repo, session_id)
    cmp = compare_with_previous(repo, session_id, prev_session_id) if prev_session_id else None
    trials = repo.trials_of_session(session_id)
    out: List[Candidate] = []

    # 녹음 품질 불안정 / 분석 불가 증가 → 난이도 변경보다 수집 조건 개선 우선
    bad = [t for t in trials if t.analysis and t.analysis.status in (AnalysisStatus.POOR_RECORDING,)]
    if trials and len(bad) / len(trials) >= cfg.unanalyzable_ratio:
        out.append(Candidate("COLLECTION_FIRST", "수집 조건 개선 우선", trials[0].goal_id,
            f"분석 불가 문항 {len(bad)}/{len(trials)}", "난이도 변경보다 녹음 환경·기기·마이크 위치 개선",
            "임상 변화로 해석하지 않기", "이번 회기 자료로 수행 변화를 판단할 수 없음", "녹음 환경 점검 후 동일 과제 재실시 여부",
            [t.id for t in bad], "같은 자극 세트를 개선된 녹음 조건에서 재실시"))

    for gid, gm in m["목표별"].items():
        g = repo.goals[gid]
        indep = gm["독립 수행"]; post = gm["도움 후 성공"]
        n = indep["분모"] or 0
        # 자료 부족 → 확정적 판단 보류
        if n < cfg.min_trials_for_judgement:
            out.append(Candidate("MORE_OBSERVATION", "추가 관찰 제안", gid,
                f"결과 포함 문항 {n}개(기준 {cfg.min_trials_for_judgement}개 미만)", "성급한 향상·악화 판단 보류, 동일 조건 추가 관찰",
                "제외·보류 문항 사유 확인", "자료가 적어 진전 여부를 판단할 수 없음", "다음 회기 문항 수와 제외 기준",
                indep["포함 문항"], f"{g.context_material}에서 동일 조건으로 문항 수를 늘려 재실시"))
        # 독립 수행 증가 → 유지 또는 새 자극 확인 (자료 부족 시 진전 판단은 보류)
        if n >= cfg.min_trials_for_judgement and cmp and gid in cmp["목표별 변화"] and cmp["목표별 변화"][gid]["독립 수행 변화(%p)"] >= cfg.indep_increase_pp:
            out.append(Candidate("INDEP_INCREASED", "현재 목표 유지 또는 새 자극으로 확인", gid,
                f"독립 수행 {cmp['목표별 변화'][gid]['이전']['비율']}% → {indep['비율']}% ({indep['분자']}/{indep['분모']})",
                "도움 감소 또는 새 자극 확인", "과제와 채점 조건의 동일성 (경고: " + ", ".join(cmp["경고"]) + ")" if cmp["경고"] else "과제와 채점 조건의 동일성",
                "조건 차이가 있으면 수치 비교가 제한됨", "자극 친숙도와 과제 적합성",
                indep["포함 문항"], "연습하지 않은 자극을 포함해 독립 이름대기 확인", ["SFA", "PCA"]))
        # 단서 후에만 성공 → 단서 조건 유지, 독립 반응 변화 확인
        if (indep["비율"] or 0) < 50 and (post["비율"] or 0) >= 50:
            out.append(Candidate("CUE_DEPENDENT", "단서 조건 유지하며 독립 반응 변화 확인", gid,
                f"독립 {indep['분자']}/{indep['분모']}, 도움 후 성공 {post['분자']}/{post['분모']}; 단서별: {gm['단서 사용']}",
                "도움 수준과 독립 시도 기회 검토", "반복 노출의 영향", "반복 제시의 영향이 있어 단서 효과를 확정할 수 없음",
                "독립 반응을 먼저 측정한 뒤 단서 제공", post["포함 문항"],
                "독립 시도 기회를 먼저 주고, 효과가 관찰된 단서를 동일 순서로 제공", ["SFA", "PCA"]))
        # 연습 문항은 성공, 새 문항은 어려움 → 일반화 확인
        pr = gm["연습 자극 독립 수행"]; pb = gm["새 자극 독립 수행"]
        if pb["분모"] == 0:
            out.append(Candidate("NO_PROBE", "새로운 자극에서 수행 확인", gid,
                "연습한 자극의 수행 기록은 있으나 새 자극 기록이 없음", "다른 자극·상황에서 확인", "새 자극의 친숙도",
                "현재 자료로 생활 상황의 일반화는 판단하지 않음", "치료사가 자극의 친숙도와 과제 적합성을 검토",
                pr.get("포함 문항", indep["포함 문항"]), "새로운 생활용품 사진을 포함하여 독립 이름대기를 확인", ["SFA"]))
        elif pr["비율"] is not None and pb["비율"] is not None and pr["비율"] - pb["비율"] >= cfg.probe_gap_pp:
            out.append(Candidate("GENERALIZATION", "일반화 확인 과제 포함", gid,
                f"연습 자극 {pr['비율']}% vs 새 자극 {pb['비율']}%", "다른 자극·상황에서 확인", "새 자극의 친숙도",
                "외운 항목 성공을 일반화로 표시하지 않음", "새 자극 선정 기준", indep["포함 문항"],
                "새 자극 비율을 늘리고 생활 상황(예: 마트 장보기)으로 확장", ["SFA", "SCRIPT"]))
        # 뒤쪽 과제에서 수행 저하 → 순서·분량·휴식·피로
        f = gm["앞 절반 독립 수행"]; b = gm["뒤 절반 독립 수행"]
        if f["비율"] is not None and b["비율"] is not None and f["비율"] - b["비율"] >= cfg.back_half_drop_pp:
            out.append(Candidate("FATIGUE", "과제 순서·분량·휴식 검토", gid,
                f"앞 절반 {f['비율']}% → 뒤 절반 {b['비율']}%", "분량·순서·휴식 검토", "피로·환경·과제 난이도",
                "순서 효과와 난이도 효과를 이번 자료로 구분할 수 없음", "휴식 삽입 또는 분량 조정 여부", indep["포함 문항"],
                "문항 수를 줄이거나 중간 휴식을 넣고 순서를 바꿔 재실시"))
        # 가정에서만 수행 저하
        c = gm["치료실 독립 수행"]; h = gm["가정 독립 수행"]
        if c["비율"] is not None and h["비율"] is not None and c["비율"] - h["비율"] >= cfg.home_drop_pp:
            out.append(Candidate("HOME_DROP", "가정 기기·안내·도움 방식 확인", gid,
                f"치료실 {c['비율']}% vs 가정 {h['비율']}%", "기기·안내·도움 방식 확인", "치료실과 가정 조건의 차이",
                "가정 녹음은 자동 분석 검증 범위 밖", "보호자 도움 수준 기록 확인", indep["포함 문항"],
                "보호자 안내(기다리기·선택지 제공)를 재교육하고 기기 설정 점검", ["PARTNER_TRAINING"]))
        # 독립 수행이 높고 다른 규칙이 없음 → 목표 달성 여부는 치료사가 판단, 유지·생활 상황 확인 제안
        if not any(c.goal_id == gid for c in out) and (indep["비율"] or 0) >= cfg.high_indep_pct:
            out.append(Candidate("CRITERION_CHECK", "목표 달성 여부 확인 및 유지·생활 상황 확인", gid,
                f"독립 수행 {indep['분자']}/{indep['분모']} ({indep['비율']}%)", "현재 목표 유지 여부와 다음 목표(생활 상황) 검토",
                "달성 기준과 비교 가능한 조건인지", "일정 기간 뒤 유지 결과와 생활 상황 수행은 아직 확인되지 않음",
                "목표 달성 판정과 다음 목표 설정", indep["포함 문항"], "유지 확인용 자극과 생활 상황(예: 마트 장보기) 과제를 포함", ["SCRIPT"]))
    return out
