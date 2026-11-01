# 요구사항 추적 매트릭스(RTM — Requirements Traceability Matrix)

본 문서는 **음성·발화 분석 및 언어재활 지원 플랫폼(UniRehab)** 제품 요구사항 문서(PRD) 및 요구사항 인벤토리(`REQ-001` ~ `REQ-016`) 전 항목의 구현 파일, 자동화 검증 테스트, 결과 및 설계 의사결정 노트를 기록해요.

## 1. 미응답 질문에 대한 합리적 기본값 결정 사항

- **질문**: 실습생과 지도교수가 시스템에 처음 로그인할 때 학교나 병원 등 기관 계정으로 로그인하게 되나요, 아니면 일반 회원가입 후 관리자가 승인하는 방식인가요?
- **적용한 합리적 기본값(`ORG_SSO_WITH_ADMIN_APPROVAL_FALLBACK`)**:
  1. **기본 경로(기관 계정 SSO 로그인 — `ORG_SSO`)**: 대학병원 언어재활실·대학교 언어병리학과·복지관 등 협약 기관 도메인 계정으로 로그인하면 소속 테넌트(`tenant_id`)와 역할(`지도교수`, `언어재활사`, `실습생`)이 즉시 매핑되어 `ACTIVE` 상태로 진입해요.
  2. **보조 경로(일반 가입 후 기관 관리자 승인 — `SELF_SIGNUP_ADMIN_APPROVAL`)**: 기관 이메일이 없는 외부 실습 파견생은 일반 가입 신청 후 해당 기관 관리자가 승인(`approved_by`)하면 활성화되도록 `core/db.py`의 `org_accounts` 테이블과 `/api/org-accounts` 엔드포인트에 두 방식을 모두 구현했어요.

---

## 2. 요구사항별 추적 표(`REQ-001` ~ `REQ-016`)

| REQ-ID | 분류·중요도 | 요구사항 명칭 | 상태 | 구현 파일 경로 | 검증 테스트 및 결과 | 비고(Note) |
|---|---|---|---|---|---|---|
| `REQ-001` | 기능·필수 | 치료계획 수립 및 SOAP 결과보고서 자동 초안 생성 보조 | 구현 | `core/clinical_service.py`, `app.py`, `static/index.html` | `tests/test_clinical_and_approval.py`, `tests/test_http_e2e.py` (통과) | ASHA NOMS/FCM 단계별 장·단기 목표 제안 및 분자/분모(`16/20 (80.0%)`) 명시 통계·SOAP(S/O/A/P) 초안 자동 생성 |
| `REQ-002` | 기능·필수 | 지도교수 온라인 검토·승인 워크플로우 | 구현 | `core/clinical_service.py`, `app.py`, `static/index.html` | `tests/test_clinical_and_approval.py`, `tests/test_http_e2e.py` (통과) | `DRAFT` → `PENDING_SUPERVISOR` → `APPROVED` / `REVISION_REQUESTED` 상태 머신 및 지도교수 코멘트·승인 시각 기록 |
| `REQ-003` | 기능·필수 | AI 기반 성인 생활맥락 맞춤형 교구 및 힌트 단서 자동 생성기 | 구현 | `core/material_service.py`, `app.py`, `static/index.html` | `tests/test_material_generator.py`, `tests/test_http_e2e.py` (통과) | 병원·약국, 마트·장보기, 대중교통·이동, 은행·관공서 맥락별 한국어 어휘·문장 과제 및 3단계 힌트(의미·문장완성·시각적 보기 3지선다) 생성 |
| `REQ-004` | 기능·필수 | 음성·발화 분석 6층 분리 아키텍처 및 3단 검토 화면 | 구현 | `core/speech_analysis_service.py`, `app.py`, `static/index.html` | `tests/test_speech_analysis_and_recheck.py`, `tests/test_http_e2e.py` (통과) | 6개 층(오디오 품질확인·자동전사·시간측정·음향관찰·언어반응분류·치료사검토) 분리, Onset 수동 보정 시 반응시간 실시간 재계산, AI 일괄 승인 배제(`422 BULK_APPROVAL_PROHIBITED`), 3단 검토 레이아웃 구현 |
| `REQ-005` | 기능·권장 | 카메라 기반 안면·구강 움직임 동시 인식 멀티모달 분석 | 구현 | `core/speech_analysis_service.py`, `app.py`, `static/index.html` | `tests/test_speech_analysis_and_recheck.py` (통과) | 입술 개구도(`lip_aperture_mm`), 안면 좌우 비대칭(`facial_asymmetry_idx`), 조음 탐색 동작(`groping_detected`) 및 시각 시작점(`visual_onset_ms`) vs 음향 시작점(`audio_onset_ms`) 격차 실시간 계산 |
| `REQ-006` | 기능·필수 | 실습생 권한 분리 및 지도교수 승인 요청 제한 | 구현 | `core/clinical_service.py`, `core/speech_analysis_service.py`, `app.py`, `static/index.html` | `tests/test_clinical_and_approval.py`, `tests/test_http_e2e.py` (통과) | `?role=실습생` 진입 시 UI 최종 승인 버튼 비활성화(`disabled`) 및 백엔드 최종 승인 API 호출 시 `403 TRAINEE_FINAL_APPROVAL_FORBIDDEN` 차단, 지도교수 승인 요청만 허용 |
| `REQ-007` | 기능·권장 | 장애 발화 특화 한국어 ASR 엔진 연동 | 구현 | `core/speech_analysis_service.py`, `app.py`, `static/index.html` | `tests/test_speech_analysis_and_recheck.py` (통과) | AI 허브 구음장애 음성인식 데이터셋 기반 파인튜닝 Conformer/Whisper 한국어 ASR 프로필(`aihub-dysarthria-conformer-ko-v2.1`) 연동 및 음소열·신뢰도 전사 |
| `REQ-008` | 기능·권장 | 승인형 가정 훈련(홈케어) 배정 및 관리 모듈 | 구현 | `core/extensions_and_homecare.py`, `app.py`, `static/index.html` | `tests/test_extensions_homecare_slmm.py`, `tests/test_http_e2e.py` (통과) | 퇴원 성인 환자 및 복지관 대기자 대상 승인형 과제 배정 및 수행 회기별 분자/분모 정량 이력(`8/10 (80.0%)`) 누적 관리 |
| `REQ-009` | 기능·선택 | 영역별 확장 모듈(마비말장애, 말실행증, AAC, 시니어 인지) 지원 | 구현 | `core/extensions_and_homecare.py`, `app.py`, `static/index.html` | `tests/test_extensions_homecare_slmm.py`, `tests/test_http_e2e.py` (통과) | `DYSARTHRIA`, `APRAXIA_OF_SPEECH`, `AAC_BOARD`, `SENIOR_COGNITION` 4대 영역 플러그인 레지스트리 및 실시간 활성화 토글 지원 |
| `REQ-010` | 기능·선택 | 한국어 경량 모델(sLMM) 온디바이스/로컬 구동 옵션 | 구현 | `core/extensions_and_homecare.py`, `core/material_service.py`, `app.py`, `static/index.html` | `tests/test_extensions_homecare_slmm.py`, `tests/test_material_generator.py` (통과) | 망분리·보안 환경을 위한 `Ko-Rehab-sLMM-3B-OnDevice-GGUF` 및 `Ko-Speech-sLMM-1.8B-ONNX-Edge` 로컬 구동 인터페이스 제공 |
| `REQ-011` | 비기능·필수 | 개인정보 동의 4종 분리 수집 및 외부 AI 미동의 시 차단 | 구현 | `core/db.py`, `core/material_service.py`, `app.py`, `static/index.html` | `tests/test_security_and_compliance.py`, `tests/test_material_generator.py` (통과) | 이용약관·음성 수집·외부 AI 전송·가명 연구 활용 4종 분리 수집, 외부 AI 미동의(`external_ai_transfer=False`) 시 외부 LLM 호출 즉시 `403 EXTERNAL_AI_CONSENT_BLOCKED` 자동 차단 |
| `REQ-012` | 비기능·필수 | 식별정보와 음성·임상 데이터 물리 격리 및 UUID 가명화 | 구현 | `core/db.py`, `app.py`, `static/index.html` | `tests/test_security_and_compliance.py` (통과) | 식별정보 DB(`data/pii_vault/pii_<tenant>.db`)와 임상·음성 DB(`data/clinical_store/clinical_<tenant>.db`) 물리적 파일 분리 및 `pt-<uuid4>` 가명화 매핑 적용 |
| `REQ-013` | 비기능·필수 | 기관별 테넌트 DB 격리 및 관리자 접근 제한 | 구현 | `core/db.py`, `app.py`, `static/index.html` | `tests/test_security_and_compliance.py`, `tests/test_http_e2e.py` (통과) | 기관별 독립 DB 파일 격리(타 테넌트 접근 시 `404`), 기관 관리자(`role=관리자/admin`)의 임상·음성 데이터 직접 열람 `403 ADMIN_CLINICAL_ACCESS_BLOCKED` 차단 |
| `REQ-014` | 비기능·필수 | 전수 접근 로그 및 상태 변경 이력 감사 추적 | 구현 | `core/db.py`, `app.py`, `static/index.html` | `tests/test_security_and_compliance.py`, `tests/test_http_e2e.py` (통과) | 모든 API/데이터 접근(`access_logs`)과 치료계획·동의·음성검토·채점기준 상태 전이(`state_change_history`)를 감사 DB(`audit_<tenant>.db`)에 전수 기록 |
| `REQ-015` | 비기능·필수 | 비의료 일상생활 훈련 소프트웨어 문구 표기 강제 | 구현 | `core/db.py`, `core/clinical_service.py`, `core/material_service.py`, `static/index.html` | `tests/test_security_and_compliance.py`, `tests/test_http_e2e.py` (통과) | 상단 고정 배너, SOAP 보고서, 교구 카드, Layer 6 검토 패널에 `'치료사가 선택한 접근에 기반한 연습'` 및 `'비의료 일상생활 훈련'` 문구 상시 강제 표기 |
| `REQ-016` | 비기능·필수 | 채점 기준 변경 시 검토 문항 재확인 자동 전환 | 구현 | `core/speech_analysis_service.py`, `app.py`, `static/index.html` | `tests/test_speech_analysis_and_recheck.py`, `tests/test_http_e2e.py` (통과) | 채점 기준(반응시간 임계값·정확도 기준) 변경 시 기존 `REVIEWED` 완료 문항을 전수 `RECHECK_REQUIRED`(`재확인 필요`) 상태로 자동 전환 및 감사 이력 기록 |
