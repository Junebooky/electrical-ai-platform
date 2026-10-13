# AGENT_WORKFLOW v1.0 — Electrical AI Platform

> 문서 ID: EAI-GOV-001 · 작성: A01 Product & Research · 2026-10-13
> 공식 PRD: [docs/PRD.md](./PRD.md) (현재 v1.1)
> Repository: `Junebooky/electrical-ai-platform` · **Public 유지**
> 원칙: **중앙 기획(A01) + 분산 실무 협업(A02–A05)**

## 1. 책임 분담

| Agent | 전담 업무 | 핵심 권한 |
|---|---|---|
| **A01 Product & Research / Orchestrator** | 제품 전략, PRD, 로드맵, 백로그, 작업 배분, 우선순위, 의존성 관리, 통합 수용 기준 및 릴리스 준비도 | 제품 범위·우선순위 결정; 개발팀의 모든 기술/디자인 결정을 대신하지 않음 |
| **A02 Full-Stack Engineering (Antigravity)** | 아키텍처, 프론트·백엔드, CAD/PDF/AI 구현, CI, 테스트, PR 관리 | 승인된 범위의 기술적 구현·일반 PR 자율 병합 |
| **A03 Design (ChatGPT)** | 사용자 흐름, 도면 뷰어 UX, 인터랙션, 디자인 시스템, 접근성 | UX 세부 결정; 제품 범위 변경 시 A01 협의 |
| **A04 Test & QA (ChatGPT)** | 독립적인 기능·정확도·회귀·성능·보안 QA와 버그 보고 | 출시 Go/No-Go **권고**, 직접 테스트하지 않은 기능은 NOT TESTED |
| **A05 Electrical Domain (ChatGPT)** | 전기 도면 기호, 적산·수량산출, 시방서/KEC의 전기 기술적 판단 | 도메인 규칙의 전문 검증; 규정 불명확하면 UNVERIFIED |
| **사용자(Product Owner)** | 중요 투자·배포·실데이터 처리·출시 최종 의사결정 | 유료 서비스·기밀자료·정식 배포·최종 출시 승인 |

A01은 전체 오케스트레이션을 책임지지만, 매번 A02 코드 Merge를 승인하거나 A04 검증을 대체하지 않는다.

## 2. 공통 정보 소스

1. `docs/PRD.md` — A01 관리 제품 요구사항, FR/AC, 범위 및 정책.
2. GitHub Issues — 업무 지시, 담당, 현재 상태, 의존성, 전문 검토 결과.
3. Pull Requests — 코드 변경, 테스트 증거, 리뷰, 병합 기록.
4. `docs/AGENT_WORKFLOW.md` — 공식 협업 규칙.
5. `docs/`의 아키텍처/디자인/도메인/테스트 문서 — 실제 존재 여부 확인 후 참조.

**독립 ChatGPT 채팅과 Antigravity Agent가 스스로 서로 대화하거나 메시지를 수신하지는 않는다.** 사용자가 대상 채팅에서 이슈 링크와 작업 지시를 전달하거나, Agent가 연결된 GitHub 읽기/쓰기 도구를 사용하여 최신 정보를 가져와야 한다. 중요한 판단은 반드시 저장소 Issue/PR/문서에 남긴다.

## 3. 표준 작업 오케스트레이션

1. **INTAKE:** 사용자 요청, Agent 제안, QA 버그, 도메인 이슈 수집.
2. **TRIAGE (A01):** 필요성·범위 검토, `Task ID`, 우선순위 `P0/P1/P2`, 책임자/협업자, FR/AC, 결과물 정의.
3. **SPECIALIST REVIEW:** 기호·계산 규칙은 A05, UX는 A03, 테스트 범위는 A04에 사전 검토 요청. 동시에 진행할 수 있다.
4. **READY FOR DEVELOPMENT:** 요구사항/예외/수용 기준이 명확하면 A02에 GitHub Issue로 개발 인계.
5. **IMPLEMENTATION:** A02가 브랜치 → 코드 → 자체 테스트 → PR → CI 실행.
6. **VALIDATION:** 일반 변경은 자동 검사 우선; 중요 변경은 해당 전문 Agent의 독립 검토 증거 요구.
7. **INTEGRATION:** 일반 PR은 조건 충족 시 A02가 자율 병합. 중대한 정확성·보안·규칙 변경은 관련 검증을 마친 뒤 병합.
8. **RELEASE:** `main` 병합은 정식 출시 승인이 아님. A04 QA 권고 + A01 PRD 충족 확인 + 사용자 출시 승인으로 별도 판정.

**CI PASS ≠ QA PASS ≠ 정식 릴리스 승인.**

## 4. Agent 간 직접 협업 정책

아래 상황은 **A01을 거치지 말고 GitHub Issue/PR에서 직접 협의**한다.

- **A02 ↔ A04:** 오류 재현, 수정, 테스트 케이스, 회귀 검증
- **A02 ↔ A05:** CAD 블록→전기 품목, 수량 집계 기준, 미확인/제외 판정, 근거 데이터
- **A02 ↔ A03:** 컴포넌트 구조, 상호작용, 화면/반응형 세부 구현
- **A03 ↔ A05:** 기호·도면 용어의 UI 표현, 사용자가 이해할 수 있는 경고/검수 문구
- **A04 ↔ A05:** 전기 도메인 정답셋, 기대 수량, 계산/규정 검증

이슈에 남기는 모든 전문 의견은 **확인한 사실 / 가정 / 미확인 / 필요한 결정**으로 구분한다.

## 5. A01으로 에스컬레이션할 조건

- 새 기능 추가·삭제 또는 PRD P0/P1/P2 변경
- 제품 목표/사용자 흐름과 상충하는 UI·기술 구현
- 여러 Agent의 판단 충돌 또는 우선순위/일정 재조정
- 주요 품질 결함, 심각한 계산 오류, 출시 보류 권고
- 공통 데이터 계약의 파괴적 변경 또는 타 Agent 작업 중단 필요
- 무료 개발 범위를 벗어나는 비용/외부 서비스 제안

사용자에게만 가능한 최종 결정: **유료 서비스 도입, 실제 고객 기밀 정보 외부 전송, 파괴적 운영 데이터 변경, Public/Private 정책 변경, 정식 대외 공개·출시**. 현재 저장소는 사용자의 결정에 따라 Public 유지.

## 6. 위험 기반 검증

- **일반 변경:** 문서, 명확한 버그 수정, 기존 승인 UX 내 UI 개선 → 자체 테스트·CI 성공이면 A02 자율 병합 가능.
- **중요 변경:** CAD 도면 파싱, 전기 기호 품목 매핑, 확정 수량 집계, 저장/재열기, 보안, 다중 형식 공통 스키마 → 자동 테스트와 관련 전문가 검토 필요.
- **차단 결함:** 오산을 '검수 완료'로 표시, 원본 데이터 손실, 심각한 보안 문제, 재현되는 핵심 기능 손상 → 수정/검증 전 병합·출시 중단 권고.
- **A04의 테스트 결과는 PASS / FAIL / BLOCKED / NOT TESTED** 로 구분.
- **A05의 근거는 VERIFIED / CONDITIONAL / UNVERIFIED** 로 구분.

GitHub `main`은 통합 브랜치다. 제품 릴리스는 별도 승인·태그·배포 정책으로 관리한다.

## 7. 업무 Issue 템플릿

```md
Task ID: EAI-...
Owner: A0x
Collaborators: A0x, ...
Type: Feature | Bug | Design | QA | Electrical Rule
Priority: P0 | P1 | P2
Source: docs/PRD.md / FR-... / AC-...
Dependencies: #issue or none

Problem / goal:
Scope (IN / OUT):
Expected deliverables:
Acceptance Criteria (testable):
Risks / assumptions:
Status: OPEN | IN_PROGRESS | BLOCKED | REVIEW | DONE
```

보고/인계 메시지:

```md
[FROM A0x → TO A0y]
Task: EAI-... / Issue #...
Decision or work needed:
Verified findings:
Assumptions and NOT TESTED:
Proposed change:
Evidence / link:
Next action:
```

**문서·코드·테스트 없이 "완료"라고 주장하지 않는다.** 도메인 규칙이 검증되지 않았다면 A05 확인 후 확정한다.

## 8. 현재 공통 작업 큐

| Agent | Task | 대상 |
|---|---|---|
| A02 | A02-T001/T002/T003 | [PR #1 — 최초 DXF MVP 통합](https://github.com/Junebooky/electrical-ai-platform/pull/1) |
| A04 | EAI-Q001 | [Issue #2 — DXF MVP QA](https://github.com/Junebooky/electrical-ai-platform/issues/2) |
| A05 | EAI-E001 | [Issue #3 — 기호·수량 규칙 검토](https://github.com/Junebooky/electrical-ai-platform/issues/3) |
| A03 | EAI-D001 | [Issue #4 — 통합 2D 뷰어 UX](https://github.com/Junebooky/electrical-ai-platform/issues/4) |
| A02 (차기) | A02-T002B | PRD v1.1 PDF/이미지 도면의 표시·부분 추출 기술 Spike |

A01은 모든 요청에서 최신 GitHub 이슈/PR 상태를 확인하여 차단 이슈와 다음 1~3개 우선 과제를 정리하고 적절한 Agent에 배분한다.

## 9. 자동화 한계 및 비용

이 운영 규칙은 **업무 수행 지침**이지 외부 Agent를 백그라운드에서 작동시키는 프로그램이 아니다. ChatGPT 대화는 스스로 GitHub 변경을 실시간 감시하거나 타 대화에 자동으로 작업을 시작시킬 수 없다.

당분간 **A01은 사용자의 요청이 있을 때 또는 대화가 재개됐을 때** GitHub의 최신 상태를 확인해 다음 작업을 배분한다. Agent 채팅을 시작하는 최초 트리거는 사용자가 이슈 링크를 전달한다. 이후 반복적인 일정 보고/조건 감시가 필요하면 별도 예약 작업을 명시적으로 구성한다. 초기 비용을 아끼기 위해 SDK 기반 멀티에이전트 오케스트레이터는 구현하지 않는다.

## 10. 변경 관리

A01이 운영 정책을 업데이트할 때 이 문서를 PR/CI 경유로 변경한다. 다른 Agent는 제안할 수 있으나 제품 범위와 우선순위는 A01이 조정한다. 사용자 최종 승인 대상은 변경하지 않는다.
