# 성인 언어재활 임상지원 플랫폼 (1단계 구현)

세 문서(아이디어 회의 기획서 · 상세 자료수집 · 치료사 검토 화면 UI 설계)의 요구사항을 **빠짐없이 코드로 옮긴** 1단계 제품입니다.
대상 범위는 문서 14장의 초기 제안 그대로 **"치료사의 평가가 완료된 뇌졸중 후 실어증 성인 중 구조화 과제(이름대기)를 수행할 수 있는 대상자"**이며, 자동 진단은 포함하지 않습니다.

## 구성
```
slp_platform/
├─ backend/app/
│  ├─ enums.py            문서의 모든 상태값·분류(역할, 임상 영역, 정보 출처/상태, 단서, 판정, 분석 상태, 확정 상태 …)
│  ├─ models.py           필수 데이터 객체: 대상자→평가→목표→회기→활동→문항별 시도→분석→검토→계획 (+버전·이력·동의·접근로그·기관 서식)
│  ├─ permissions.py      6개 사용자 역할별 권한. 확인하지 않으면 확정되지 않는 구조
│  ├─ repository.py       저장소(저장 실패·동시 수정 충돌 처리 포함)
│  ├─ speech_analysis.py  음성 분석 6층 분리(품질→전사→시간→음향·말→언어 반응→임상 검토), 적용 범위 밖/판정 불가 상태
│  ├─ review_service.py   치료사 검토(①문항 검토): AI값/치료사값 분리 저장, 수정 이력, 채점 기준 변경 시 재확인
│  ├─ metrics_engine.py   데이터 계산 엔진: 분자·분모·포함 문항이 붙은 7개 성과지표, 이전 회기 비교 경고
│  ├─ rule_engine.py      규칙 엔진: 문서의 7가지 관찰 패턴 → 검토 후보(근거·제한·확인 조건 포함)
│  ├─ evidence_repo.py    근거 자료 저장소(SFA/PCA/VNeST/스크립트/읽기지원/상대자훈련/말실행증/마비말장애/AAC/인지-의사소통) + 미확보 근거 목록
│  ├─ planner.py          다음 회기 계획 = 규칙 + 근거 + 문서화. 제안 카드, 분리 승인, 실습생→지도자 승인, 가정 연습 별도 배정
│  ├─ session_service.py  회기 설계·실행·결과 확정, 회기 전 계획서
│  ├─ reports.py          회기 후 결과보고서(기관 서식), 가정 연습 보고, 대상자 요약, 대상자 '오늘' 화면
│  └─ api.py              REST API(표준 라이브러리; FastAPI로 교체 가능)
├─ backend/demo.py        전체 흐름 시연(가상 데이터) → demo_state.json
├─ backend/tests/test_core.py  설계 원칙 14개 테스트
├─ frontend/review.html   치료사 검토 화면(①문항 검토 3단 → ②회기 결과 → ③다음 계획) — 단일 HTML, 바로 열어서 사용
├─ schema/schema.sql      PostgreSQL 스키마
└─ docs/REQUIREMENTS_TRACE.md  문서 요구사항 ↔ 코드 매핑표
```

## 실행
```bash
cd backend
python demo.py                 # 전체 흐름 시연
python tests/test_core.py      # 14개 원칙 테스트
python -c "from app.api import serve; import demo; repo,users,*_=demo.build_world(); serve(repo, users, 8000)"
```
프런트: `frontend/review.html`을 브라우저로 열기. `review.html?role=실습생` 으로 열면 실습생 권한(승인 버튼 대신 승인 요청)으로 동작.

## 반드시 알아야 할 것
- `speech_analysis.MockAdapter`는 구조 검증용입니다. 실제 한국어 ASR·음향 분석 엔진을 `SpeechAdapter` 프로토콜로 연결해야 하며, `VALIDATED_SCOPE`는 **검증 결과가 있는 범위만** 넓혀야 합니다.
- `planner.TemplateWriter`는 LLM 자리입니다. LLM을 붙이더라도 역할은 "확인된 데이터를 문장으로 정리"로 제한되어 있고, 수치 계산·규칙 적용·승인은 분리되어 있습니다.
- `rule_engine.RuleConfig`의 기본 임계값은 임상 처방이 아니며 치료사 설정·임상 검증이 필요합니다.
- `evidence_repo.VALIDATION_SEED`의 12개 항목은 문서가 "조사 완료로 표시하면 안 된다"고 한 **미확보 근거**입니다. 출시 전 확인 지표(분석 성능·임상 타당성·계획 품질·업무 효과·가정 사용성·임상 효과·사업성)와 함께 관리하세요.
- 디지털의료기기 해당 여부(식약처 AI·LLM·전문가용 DMD 가이드라인)는 사용 목적·출력물 기준 확정 후 별도 검토가 필요합니다.
