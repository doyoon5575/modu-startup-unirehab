-- 성인 언어재활 임상지원 플랫폼 — 데이터 스키마(PostgreSQL 기준)
-- 필수 객체: 대상자 → 평가 → 목표 → 회기 → 활동 → 문항별 시도 → 분석 → 검토 → 계획
-- 별도 관리: 과제·자료 버전, 분석 모델 버전, 목표·계획 변경 이력, AI 결과/치료사 수정값, 동의·접근 이력, 기관별 서식

CREATE TABLE organization (id TEXT PRIMARY KEY, name TEXT NOT NULL, report_template JSONB, data_partition TEXT NOT NULL);
CREATE TABLE app_user (id TEXT PRIMARY KEY, org_id TEXT REFERENCES organization(id), name TEXT, role TEXT NOT NULL
  CHECK (role IN ('언어재활사','병원·치료실 관리자','실습생','지도자·슈퍼바이저','대상자','보호자·의사소통 상대자')),
  supervisor_id TEXT REFERENCES app_user(id), clinical_access BOOLEAN DEFAULT TRUE);

CREATE TABLE patient (id TEXT PRIMARY KEY, org_id TEXT REFERENCES organization(id), code TEXT NOT NULL, name_masked TEXT,
  domains TEXT[] NOT NULL DEFAULT '{}', assigned_therapist_id TEXT, assigned_trainee_id TEXT, aac_board JSONB, created_at TIMESTAMPTZ DEFAULT now());
-- 모든 프로필 항목은 값 + 출처 + 확인 상태 ('미입력'을 정상으로 해석하지 않음)
CREATE TABLE patient_info_field (patient_id TEXT REFERENCES patient(id), field_key TEXT, value TEXT,
  source TEXT CHECK (source IN ('의무기록에서 확인','치료사 직접 관찰','대상자·보호자 보고','AI 제안(미확인)')),
  status TEXT NOT NULL DEFAULT '미입력' CHECK (status IN ('확인됨','보고받음','관찰됨','미확인','미입력')),
  confirmed_by TEXT, document_ref TEXT, PRIMARY KEY (patient_id, field_key));
CREATE TABLE life_goal (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), who TEXT, place TEXT, what TEXT, priority INT, reported_by TEXT);
CREATE TABLE consent (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), consent_type TEXT NOT NULL
  CHECK (consent_type IN ('서비스 이용 동의','연구·모델 학습 이용 동의','보호자 열람 동의','외부 AI 서비스 전송 동의')),
  granted BOOLEAN NOT NULL, granted_at TIMESTAMPTZ, scope_note TEXT);
CREATE TABLE access_log (id BIGSERIAL PRIMARY KEY, user_id TEXT, patient_id TEXT, action TEXT, at TIMESTAMPTZ DEFAULT now());
CREATE TABLE standardized_test_score (id BIGSERIAL PRIMARY KEY, patient_id TEXT REFERENCES patient(id), test_name TEXT, administered_on DATE, scores JSONB, administered_by TEXT, note TEXT);
-- 검사 문항 탑재는 권리 확인 후: content_rights 로 분리

CREATE TABLE assessment (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), date DATE, assessor_id TEXT, domain_observations JSONB, structured_task_results JSONB, baseline JSONB);

CREATE TABLE goal (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), goal_type TEXT CHECK (goal_type IN ('기능 향상','기능 유지','보상 수단 사용','활동·참여')),
  long_term BOOLEAN, parent_goal_id TEXT REFERENCES goal(id), context_material TEXT, support_condition TEXT, criterion TEXT, target_behavior TEXT,
  indicator TEXT, response_mode TEXT, linked_domain TEXT, status TEXT, created_by TEXT, approved_by TEXT);
CREATE TABLE goal_history (id BIGSERIAL PRIMARY KEY, goal_id TEXT REFERENCES goal(id), version INT, text TEXT, changed_by TEXT, changed_at TIMESTAMPTZ, reason TEXT);
CREATE TABLE goal_life_goal (goal_id TEXT REFERENCES goal(id), life_goal_id TEXT REFERENCES life_goal(id), PRIMARY KEY (goal_id, life_goal_id));

CREATE TABLE content_rights (id BIGSERIAL PRIMARY KEY, license TEXT DEFAULT '미확인', redistribution_allowed BOOLEAN, modification_allowed BOOLEAN, verified_by TEXT);
CREATE TABLE stimulus (id TEXT, version INT, label TEXT, media_ref TEXT, linked_goal_function TEXT, response_mode TEXT, familiarity TEXT, personal_relevance TEXT,
  length_complexity TEXT, allowed_cues TEXT[], cue_order TEXT[], accepted_expressions TEXT[], needs_review_expressions TEXT[],
  purpose TEXT CHECK (purpose IN ('연습용','새 자극 확인용','유지 확인용')), rights_id BIGINT REFERENCES content_rights(id), situation TEXT, PRIMARY KEY (id, version));
CREATE TABLE scoring_criterion (id TEXT, version INT, description TEXT, accepted_expressions_policy TEXT, cue_conditions TEXT, changed_by TEXT, changed_at TIMESTAMPTZ, PRIMARY KEY (id, version));

CREATE TABLE evidence_item (id TEXT PRIMARY KEY, title TEXT, target_population TEXT, target_function TEXT, intervention TEXT, evidence_level TEXT, outcome_measures TEXT,
  limitations TEXT, korean_applicability TEXT, usage_rights TEXT, linked_feature TEXT, reviewer TEXT, reviewed_at TIMESTAMPTZ, update_status TEXT, url TEXT,
  approach_key TEXT, verified_effect_in_app BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE validation_item (key TEXT PRIMARY KEY, required_material TEXT, reason TEXT, status TEXT NOT NULL DEFAULT '미확보');

CREATE TABLE session (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), date DATE, setting TEXT CHECK (setting IN ('치료실','가정')), therapist_id TEXT,
  state TEXT NOT NULL CHECK (state IN ('계획됨','실시 중','검토 중','회기 결과 확정','계획 승인','기초 결과 변경됨')),
  therapist_interpretation TEXT, result_finalized_by TEXT, result_finalized_at TIMESTAMPTZ, result_version INT DEFAULT 0, rest_stop_condition TEXT, author_id TEXT, reviewer_id TEXT);
CREATE TABLE session_goal (session_id TEXT REFERENCES session(id), goal_id TEXT REFERENCES goal(id), PRIMARY KEY (session_id, goal_id));
CREATE TABLE session_transition (id BIGSERIAL PRIMARY KEY, session_id TEXT REFERENCES session(id), from_state TEXT, to_state TEXT, actor_id TEXT, at TIMESTAMPTZ, note TEXT);

CREATE TABLE activity (id TEXT PRIMARY KEY, session_id TEXT REFERENCES session(id), goal_id TEXT REFERENCES goal(id), name TEXT, approach_key TEXT, stimulus_ids TEXT[],
  response_mode TEXT, cue_sequence TEXT[], target_response_form TEXT, error_no_response_handling TEXT, measurement_method TEXT,
  production_condition TEXT CHECK (production_condition IN ('혼자 말하기','모델 보고 따라 말하기(음성만)','모델 보고 따라 말하기(음성+영상)','함께 말하기')),
  length_level TEXT, rate_rhythm_support TEXT, feedback_setting JSONB, rest_stop_condition TEXT, order_in_session INT, planned BOOLEAN, actually_performed BOOLEAN);

-- 문항별 시도: 기본 저장 단위
CREATE TABLE trial (id TEXT PRIMARY KEY, session_id TEXT REFERENCES session(id), activity_id TEXT REFERENCES activity(id), goal_id TEXT REFERENCES goal(id),
  stimulus_id TEXT, stimulus_version INT, trial_order INT, presentation_mode TEXT, presented_at TIMESTAMPTZ, response_mode TEXT, setting TEXT,
  collection TEXT CHECK (collection IN ('수집됨','대상자 무반응','수집 실패')), scoring_criterion_id TEXT, scoring_criterion_version INT,
  helper TEXT, help_level TEXT, distractions TEXT, production_condition TEXT, stimulus_purpose TEXT, note TEXT, row_version INT NOT NULL DEFAULT 1,
  FOREIGN KEY (stimulus_id, stimulus_version) REFERENCES stimulus(id, version));
-- 첫 반응과 도움 후 반응을 덮어쓰지 않고 모두 남김. AI 전사(읽기 전용)와 치료사 전사 분리.
CREATE TABLE attempt (id BIGSERIAL PRIMARY KEY, trial_id TEXT REFERENCES trial(id), attempt_type TEXT, audio_ref TEXT, audio_start_s NUMERIC, audio_end_s NUMERIC,
  ai_transcript TEXT, therapist_transcript TEXT, cue_before TEXT, cue_given_at TIMESTAMPTZ, ai_target_match BOOLEAN, ai_classification TEXT, ai_confidence NUMERIC);
-- 세 시간 분리 + 측정 정의 + 자동값 보존
CREATE TABLE timing (trial_id TEXT PRIMARY KEY REFERENCES trial(id), stimulus_end_s NUMERIC, first_speech_onset_s NUMERIC, cue_given_s NUMERIC, post_cue_onset_s NUMERIC,
  target_completed_s NUMERIC, definition TEXT, exclusion_rule TEXT, auto_values JSONB, corrected_by TEXT);
CREATE TABLE auto_analysis (trial_id TEXT PRIMARY KEY REFERENCES trial(id), model_version TEXT NOT NULL, recording_quality TEXT, recording_issues TEXT[],
  status TEXT CHECK (status IN ('자동 분석 후 검토 완료','자동 분석 후 검토 대기','치료사 확인 필요','녹음 품질 부족','현재 모델의 검증 범위 밖','분석 대기')),
  limits TEXT[], speech_rate NUMERIC, speech_rate_unit TEXT, speech_rate_segment TEXT, repetitions JSONB, pauses JSONB, analyzed_at TIMESTAMPTZ);
CREATE TABLE therapist_review (trial_id TEXT PRIMARY KEY REFERENCES trial(id),
  review_status TEXT CHECK (review_status IN ('미검토','검토 중','검토 완료','확인 필요','수정됨','판정 보류','제외','재확인 필요')),
  usage TEXT CHECK (usage IN ('결과에 포함','결과에서 제외','보류')), exclusion_reason TEXT,
  first_judgement TEXT CHECK (first_judgement IN ('독립 성공','다른 반응','무반응','판정 보류')), cues_given TEXT[],
  post_cue_judgement TEXT CHECK (post_cue_judgement IN ('성공','다른 반응','무반응','판정 보류','해당 없음')),
  observation_tags TEXT[], observation_note TEXT, hold_reason TEXT, modification_reason TEXT, reviewer_id TEXT, reviewed_at TIMESTAMPTZ, clinician_speech_ratings JSONB,
  CHECK (usage <> '결과에서 제외' OR exclusion_reason IS NOT NULL));
CREATE TABLE review_history (id BIGSERIAL PRIMARY KEY, trial_id TEXT REFERENCES trial(id), version INT, reviewer_id TEXT, at TIMESTAMPTZ, previous JSONB, current JSONB, reason TEXT, note TEXT);

CREATE TABLE next_session_plan (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), based_on_session_id TEXT REFERENCES session(id), based_on_result_version INT,
  state TEXT CHECK (state IN ('초안','수정 중','지도자 승인 대기','확정','재승인 필요')), goals_to_keep JSONB, conditions_to_change JSONB, selection_rationale TEXT,
  probe_tasks TEXT[], home_practice_candidates TEXT[], stop_adjust_conditions TEXT, document_draft TEXT, author_id TEXT, approved_by TEXT, approved_at TIMESTAMPTZ, supervisor_feedback JSONB);
CREATE TABLE plan_history (id BIGSERIAL PRIMARY KEY, plan_id TEXT REFERENCES next_session_plan(id), at TIMESTAMPTZ, by_user TEXT, event TEXT);
CREATE TABLE proposal (id TEXT PRIMARY KEY, plan_id TEXT REFERENCES next_session_plan(id), title TEXT, linked_goal_id TEXT REFERENCES goal(id), rationale_data TEXT,
  related_trial_ids TEXT[], activity_draft TEXT, uncertainty TEXT, needs_confirmation TEXT, rule_key TEXT, precheck_condition TEXT,
  decision TEXT CHECK (decision IN ('AI 초안','수락','수정','채택하지 않음')), therapist_edit TEXT, decided_by TEXT, decided_at TIMESTAMPTZ);
CREATE TABLE proposal_evidence (proposal_id TEXT REFERENCES proposal(id), evidence_id TEXT REFERENCES evidence_item(id), PRIMARY KEY (proposal_id, evidence_id));

-- 승인된 활동만 별도 배정(계획 승인만으로 자동 배정 금지는 애플리케이션 계층에서 강제)
CREATE TABLE home_assignment (id TEXT PRIMARY KEY, patient_id TEXT REFERENCES patient(id), plan_id TEXT REFERENCES next_session_plan(id), proposal_id TEXT REFERENCES proposal(id),
  activity_description TEXT, caregiver_guidance TEXT[], stop_rule TEXT, assigned_by TEXT, assigned_at TIMESTAMPTZ, offline_fallback TEXT);
CREATE TABLE home_practice_report (id TEXT PRIMARY KEY, assignment_id TEXT REFERENCES home_assignment(id), performed_at TIMESTAMPTZ, performed_alone BOOLEAN, helper TEXT,
  help_level TEXT CHECK (help_level IN ('도움 없음','안내만 함','선택지 제공','답을 대신 제공')), environment_note TEXT, trial_ids TEXT[], life_goal_events JSONB);

CREATE INDEX ON trial (session_id, trial_order);
CREATE INDEX ON access_log (patient_id, at);
