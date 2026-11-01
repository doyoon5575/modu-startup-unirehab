# 요구사항 추적표 — 문서 ↔ 구현

## 문서 1: 아이디어 회의(기획서)
| 장 | 요구사항 | 구현 위치 |
|---|---|---|
| 1 | 서비스 정의·3대 가치(개인화/연속성/설명 가능성) | README, planner(근거·불확실성 표시), metrics(연속성: 이전 회기 비교) |
| 1 | 실어증·마비말장애·말실행증을 하나로 묶어 자동 처리 금지 | enums.ClinicalDomain 중복 선택, speech_analysis.VALIDATED_SCOPE |
| 2-1 | 5개 임상 영역 + 확장 영역(발달성/유창성/음성) 초기 미지원 | enums.ClinicalDomain, PHASE1_SUPPORTED_DOMAINS, EXTENSION_DOMAINS |
| 2-2 | 같은 진단명 안에서 기능 분리 입력(7개 질문) | models.FunctionalProfile |
| 3 | 6개 사용자 역할·권한, 실습생 초안→지도자 피드백→승인 | permissions.py, planner.request_supervisor_approval/supervisor_feedback |
| 3 | 가정용 화면: 오늘 연습/도움 방법/멈추는 방법 | reports.patient_today_view |
| 4-1 | 기본 프로필 8개 묶음 | models.Patient/ClinicalBackground/FunctionalProfile/HomeEnvironment/StandardizedTestScore/LifeGoal |
| 4-2 | 정보마다 출처·확인 상태, 미입력≠정상 | models.InfoField(.display → "정보 미입력"), InfoSource/InfoStatus |
| 5 | 8개 모듈 | ①Patient ②Assessment ③Goal ④session_service.plan_session/add_activity ⑤record_trial ⑥speech_analysis+review_service ⑦rule_engine+planner ⑧HomeAssignment/HomePracticeReport |
| 6-1 | 문항별 시도 기본 단위(12개 기록 항목) | models.Trial/AttemptRecord/TimingMarks/AutoAnalysis/TherapistReview |
| 6-2 | 목표 작성 틀, 목표→지표→활동→자극→단서→반응→결과→다음 결정 | models.Goal.sentence(), Activity.goal_id, Trial.goal_id, Proposal.linked_goal_id |
| 7-1 | 분석 6층 분리 | speech_analysis.analyze_trial 단계 1~5 + review_service(임상 검토) |
| 7 | 목표어 일치 확인과 실제 전사 분리 / 몰래 교정 금지 | AttemptRecord.ai_target_match vs ai_transcript |
| 7-2 | 느린 반응·반복을 말더듬으로 자동 연결 금지 | AutoAnalysis.repetitions/pauses(관찰값) + limits 문구 |
| 7-3 | 분석 상태 4종 이상, "인식 못함"≠"틀림" | enums.AnalysisStatus(6종), CollectionOutcome, TrialUsage |
| 8 | 규칙+근거+AI 문서화, LLM 자유 작성 금지 | rule_engine → evidence_repo → planner.TemplateWriter(DocumentWriter) |
| 8-2 | 7개 관찰 패턴 → 제안 방향 | rule_engine.generate_candidates (INDEP_INCREASED, CUE_DEPENDENT, NO_PROBE/GENERALIZATION, FATIGUE, HOME_DROP, COLLECTION_FIRST, MORE_OBSERVATION) |
| 8-2 | 진행성·중증: 기능 유지·보상 목표 | enums.GoalType(기능 유지/보상 수단/활동·참여) |
| 8-3 | 제안마다 근거·불확실성·확인 필요 | models.Proposal(rationale_data/uncertainty/needs_confirmation/evidence_ids) |
| 9-1 | 회기 전 계획서 | session_service.pre_session_plan_document |
| 9-2/9-3 | 회기 후 결과보고서(분모·대표 반응·제외·비교 범위·제안·상태) | reports.session_report |
| 10 | 역할별 엔진, 필수 객체, 버전·이력·동의·접근 이력·기관 서식 | 전체 구조; Stimulus.version, AutoAnalysis.model_version, GoalVersion, ReviewVersion, Consent, AccessLog, Organization.report_template |
| 11 | 근거 자료 저장 형식 9항목, 표준화검사 점수 입력과 문항 탑재 분리, 연습 점수≠검사 점수 | models.EvidenceItem, StandardizedTestScore + ContentRights, reports.DISCLAIMER |
| 12 | 사업모델(기관 중심) | README 범위 메모(요금 미확정 원칙 유지) |
| 13 | 동의 분리, 외부 AI 전송, 기관 분리, AI 초안/승인 문서 구분, 변경 근거 기록 | enums.ConsentType, Organization.data_partition, PlanState/SessionState, StateTransition |
| 14 | 1단계 범위(이름대기, 녹음·반응 시간, 치료사 채점, 보고서, 계획 초안, 승인된 가정 연습) | demo.py 전체 흐름; VALIDATED_SCOPE |
| 14 | 출시 전 확인 지표·미확보 항목 | evidence_repo.VALIDATION_SEED |

## 문서 2: 상세 자료 수집
| 절 | 요구사항 | 구현 위치 |
|---|---|---|
| 조사 방향 | 7개 개발 질문 | 각 모듈의 데이터 필드(Trial.helper/help_level/setting 등) |
| 장애보다 기능 | 영역별 설계 제안 5건, 실어증≠인지장애 전제 | FunctionalProfile, ClinicalBackground.assume_cognitive_impairment=False |
| 입력 화면 | 9개 입력 묶음, 정보 상태 4종 | FunctionalProfile(접근성 포함), InfoStatus |
| 중재 자료 | SFA/PCA/VNeST/스크립트/읽기지원/상대자훈련 + 별도 확인 사항 | evidence_repo.SEED(limitations 필드) |
| 중재 자료 | "검증된 치료 효과" 대신 "치료사가 선택한 접근에 기반한 연습" | evidence_repo.feature_label, verified_effect_in_app=False |
| 말운동 | 6개 기능 후보와 저장 조건(따라 말하기≠독립 산출) | enums.ProductionCondition, Activity.length_level/rate_rhythm_support/feedback_setting, metrics(독립 수행 분모 제한) |
| 생활 과제 | '마트 장보기' 상황에 8개 목표 연결, 콘텐츠 7개 메타 | models.Stimulus(situation, familiarity, personal_relevance, length_complexity, allowed_cues, cue_order, accepted/needs_review_expressions, purpose, rights) |
| 음성 분석 | 8개 분석 기능별 산출·함께 저장할 정보 | AutoAnalysis, TimingMarks(definition, exclusion_rule, auto_values) |
| 음성 분석 | 세 시간 분리, 기침·타인 말 처리 규칙 | TimingMarks.response_latency/post_cue_latency/completion_duration, exclusion_rule |
| 판정 불가 | 6개 상태 | AnalysisStatus + CollectionOutcome + TrialUsage |
| 문항별 기록 | 9개 묶음 데이터 사전 | Trial 필드 전체, schema.sql |
| 성과지표 | 7개 지표 분리, 도움 후 성공 분모 명시 | metrics_engine.compute_session_metrics |
| 제안 규칙 | 7개 패턴 + 먼저 확인할 조건 | rule_engine.Candidate.precheck |
| 문서 요구 | 회기 결과보고서 9항목, 다음 회기 계획서 7항목 | reports.session_report, models.NextSessionPlan |
| AAC·보호자 | 6개 기능(표현판, 반응 방식 전환, 보호자 안내, 도움 기록, 생활 수행 기록, 대체 경로) | Patient.aac_board, ResponseMode, HomeAssignment.caregiver_guidance/offline_fallback, HelpLevel, HomePracticeReport.life_goal_events |
| 미확보 근거 | 10개 항목, 조사 완료로 표시 금지 | evidence_repo.VALIDATION_SEED(status="미확보") |

## 문서 3: 치료사 검토 화면 UI
| 영역 | 요구사항 | 구현 위치(frontend/review.html + backend) |
|---|---|---|
| 전체 | ①문항 검토 → ②회기 결과 → ③다음 계획 3단계 | steps 탭, go() |
| 비율 | 20/48/32, 작은 화면에서 목록 접고 상하 배치 | main grid + @media |
| 상단 | 대상자/회기/목표/채점 기준/진행 수/저장 상태, 각 클릭 동작 | header, goalbar, openPanel(profile/session/criterion) |
| 상단 | 채점 기준 변경 시 재확인 표시 | changeCriterion(), review_service.change_scoring_criterion |
| 왼쪽 | 문항 카드(상태·AI 제안·확인 사유), 6개 필터, 시행 순서 기본, 색상+상태명+아이콘 | renderList, ICON, review_service.trial_card/filter_trials |
| 왼쪽 | AI 확신 항목도 자동 검토 완료 금지 | speech_analysis(UNREVIEWED), 일괄 승인 버튼 없음 |
| 가운데 | 자극→원음→실제 반응→AI 분석 우선순위, 시도별 탭, 타임라인 마커 | renderEvidence |
| 가운데 | AI 전사 읽기 전용 / 치료사 전사 수정 / 차이 표시 / '자동 분석 제안' 배지 / 분석 제한 | 표 + diffHtml + badge.ai + notice |
| 가운데 | 재생속도는 듣기 편의용, 반응 시간은 원본 기준 | 안내 문구 + timing 분리 |
| 가운데 | 시간 수정 4단계(원래값·수정값 함께 표시, 저장 시 재계산) | onsetInput, TimingMarks.auto_values, review_trial(onset_correction) |
| 오른쪽 | 자료 사용 여부/최초 반응/도움 기록/도움 후 반응/관찰/수정 이유 | renderJudge, TherapistReview |
| 오른쪽 | '다른 반응' 5개 태그, 진단 자동 확정 금지 | ObservationTag |
| 오른쪽 | 버튼: 저장·다음 / 보류 후 이동 / 변경 취소 / 수정 이력, 일괄 승인 없음 | saveTrial, holdAndNext, cancelEdit, openPanel('history') |
| ② | 미해결 수·계산 범위·분자분모·클릭하면 문항으로·비교 제한 경고·보류 확인 후 확정 | renderResult, finalize, metrics_engine, session_service.finalize_result |
| ③ | 제안별 카드(연결 목표·근거·관련 문항·활동 초안 편집·판단 제한·수락/수정/채택하지 않음) | renderPlan, planner.decide_proposal |
| ③ | 참고자료 미연결 시 '근거 자료 연결 필요' | Proposal.evidence_label |
| ③ | 계획 초안 저장 / 다음 회기 계획 승인 / 가정 연습 배정 분리, 승인≠자동 배정 | planner.save_draft/approve_plan/assign_home_practice |
| 예외 | AI 분석 없음→수동 검토, 재생 실패, 녹음 누락≠무반응, 저장 실패, 다른 사용자 수정, 확정 후 수정→재검토, 기초 결과 변경→재승인, 실습생, 권한 없음 | AnalysisStatus.NOT_ANALYZED, playFail, CollectionOutcome, SaveError, ConflictError, SessionState.BASIS_CHANGED, PlanState.REAPPROVAL_REQUIRED, permissions |
| 상태 | 검토 중→회기 결과 확정→계획 승인, 작성자·승인자·시간 | SessionState, StateTransition |
| 첫 구현 범위 | 8개 항목 | 전부 구현(test_core.py로 검증) |
