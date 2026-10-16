# 전기공사 AI 플랫폼 통합 MVP 베타 릴리즈 노트 (v0.2.0-beta)

> **문서 버전:** v0.2.0-beta  
> **마일스톤:** [Issue #32](https://github.com/Junebooky/electrical-ai-platform/issues/32) 최우선 제품 마일스톤 (통합 MVP & 베타 출시 준비)  
> **기준 브랜치:** `feat/issue-32-integrated-mvp-beta`  
> **대상:** Product Owner (PO), 도메인 엔지니어, 실무 적산사  

---

## 1. 개요 및 릴리즈 목적

본 릴리즈는 분산 개발되었던 개별 PR 기능들(DXF MVP #1, 이미지 도면 #14, PDF 다중 도면 #21, 벡터 피처 #24, 기호 자동 탐지 #25, 범례 매핑 템플릿·실전 데모 #27, 유사 기호 드래그 검색·E2E 자동화 #30)을 **사용자가 브라우저에서 직접 원클릭으로 구동하여 실제 전등·전열 적산 업무를 완결할 수 있는 단일 실행 통합 MVP**로 조립한 결과물입니다.

과도한 QA 병목을 해소하고, 실제 전기공사 실무자가 로컬 브라우저에서 multi-format 도면을 업로드하고 검수한 뒤 엑셀로 내보낼 수 있는 작동 검증된 출시 후보(RC)를 제공합니다.

---

## 2. 통합 MVP 핵심 기능 요약

### 1) 3대 멀티포맷 도면 원클릭 분석 및 렌더링
- **AutoCAD DXF**: R12 ~ 2018 ASCII 및 Binary DXF 고속 파싱, 2D SVG 인터랙티브 뷰어, 레이어 On/Off 토글.
  - *R12 LWPOLYLINE 구체적 진단*: 비표준 R12 파일 업로드 시 모호한 에러 대신 `AutoCAD 2000 DXF(AC1015) 이상으로 다시 저장(Save As)`하라는 구체적 조치 배너 안내.
- **스캔/래스터 이미지 (PNG, JPG, JPEG)**: 픽셀 좌표계 기반 렌더링, `[0, W) x [0, H)` 반열린 구간 좌표 안전성 및 EA 전용 단위 강제.
- **벡터/스캔 PDF**: pypdf/pdfplumber 기반 다중 페이지 도면 렌더링, 페이지 전환 툴바, PDF 벡터 텍스트 및 선/도형 피처 하이라이트.

### 2) 사용자 정의 유사 기호 시각 검색 (Visual Symbol Search)
- 도면 캔버스에서 마우스 드래그로 기호 영역을 지정(Crop)하여 전체 도면 내 유사 기호를 실시간 탐지.
- OpenCV 기반 정규화 상호상관(TM_CCOEFF_NORMED) 및 다중 각도(0°, 90°, 180°, 270°) 회전 매칭.
- IoU 기반 NMS(Non-Maximum Suppression) 및 공간 중복 제거로 동일 물리 위치 중복 집계 원천 차단.

### 3) 전문가급 단축키 검수 워크플로우 (Inspection & Shortcuts)
- 단일 키보드 단축키 지원: `A` (승인 / Accept), `R` (반려 / Reject), 상/하 방향키(후보 탐색).
- 일괄 승인/거부(`ACCEPT_ALL`, `REJECT_ALL`, 품목별 필터링) 지원.
- **검수 불변성 보장 (P0-REVIEW-01/02 방어)**: 이미 승인/반려된 기구는 추후 재검색을 수행하더라도 사용자의 검수 결정, 품목 정의, 타임스탬프, 메모가 절대 덮어씌워지지 않음.

### 4) 범례 매핑 템플릿 관리 시스템
- 표준 상가/오피스 전기 매핑 템플릿(`tpl_standard_elec`) 기본 탑재.
- 템플릿 적용 전략: **병합(MERGE)** (기존 매핑 보존) vs **전체 대체(REPLACE)** 선택 가능.
- 사용자가 도면에서 구성한 매핑을 새 템플릿으로 저장하거나 삭제하는 사용자 정의 템플릿 라이프사이클 완비.

### 5) 양방향 검수 및 잠정/확정 엑셀(XLSX)·CSV 내보내기
- 산출표 행 클릭 시 도면 내 해당 기구 하이라이트 및 개별 WCS 좌표·근거 추적.
- 누락 기구 현장 마커 수동 추가(Click-to-Add) 및 오탐 제외/복원.
- Excel 내보내기: openpyxl 기반 스타일링 및 수식 주입(Formula Injection) 방어된 2개 시트(`Takeoff Summary` + `Takeoff Evidence`) 자동 생성.
- 실무 안전을 위해 항상 잠정(`provisional`) 상태 헤더 명시.

### 6) 실전 3종 도면 원클릭 데모 시드
- 헤더의 **[⚡ 실전 데모 프로젝트 불러오기]** 버튼 클릭 한 번으로 IMAGE(평면도), DXF(기구 배치도), PDF(전기도면) 3종 도면이 즉시 구성되어 대기 시간 없이 시연 가능.
- 멱등성(Idempotency) 보장: 재클릭 시 도면이 중복 생성되지 않고 기존 검수 상태 보존.

---

## 3. 기능 지원 현황 매트릭스 (지원 / 미지원 / 백로그)

| 기능 분류 | 세부 기능 | 지원 여부 | 비고 |
|:---|:---|:---:|:---|
| **도면 포맷** | AutoCAD DXF (ASCII & Binary) | **지원** | 2D 평면도, R12~2018 |
| | 스캔 이미지 도면 (PNG, JPG) | **지원** | 캔버스 픽셀 좌표계 |
| | 다중 페이지 PDF 도면 | **지원** | 페이지 전환, 벡터 텍스트/도형 추출 |
| | AutoCAD DWG 파일 직접 파싱 | *미지원 (Scope Out)* | CAD 프로그램에서 DXF로 변환 후 업로드 |
| **기호 탐지** | 색상/기하 기반 기호 후보 자동 탐지 | **지원** | 3종 포맷 전체 자동 제안 |
| | 사용자 지정 드래그 크롭 시각 검색 | **지원** | 다중 회전 템플릿 매칭 |
| | 공간 중복 제거 (Spatial Deduplication) | **지원** | 동일 물리 위치 1 EA 제한 |
| **검수 도구** | 단일키 단축키 (`A`/`R`) 검수 | **지원** | 실시간 상태 뱃지 전이 |
| | 일괄 승인 / 거부 / 초기화 | **지원** | 품목별 필터링 일괄 처리 |
| | 누락 기구 수동 마커 추가 (Click-to-Add) | **지원** | WCS/픽셀 정밀 좌표 등록 |
| | 오탐 제외 / 복원 | **지원** | 산출표 즉각 실시간 반영 |
| **산출 & 출력** | 물량산출 요약표 & 근거 내보내기 | **지원** | 양방향 캔버스 연동 |
| | CSV 내보내기 (Summary / Evidence) | **지원** | UTF-8-BOM (Excel 한글 호환) |
| | Excel (XLSX) 내보내기 | **지원** | 2개 시트 구조, 수식 위생화 |
| | 자동 배관/배선 길이 산출 | *미지원 (Phase 2)* | 3D 입체 배관은 차기 마일스톤 이관 |
| | KEC 전기설비기술기준 법규 적합성 판정 | *미지원 (Scope Out)* | 법규 해석 엔진은 별도 서비스 영역 |
| | 유료 외부 AI API 전송 | *미지원 (보안 원칙)* | 도면 외부 유출 차단 (100% 로컬 연산) |

---

## 4. 알려진 제약 사항 (Known Issues)

1. **초대형 DXF 파일 (50 MiB 이상)**:
   - 복잡한 3D 메시나 대용량 등고선이 포함된 파일은 웹 브라우저의 SVG DOM 처리 한계로 렌더링 지연이 발생할 수 있습니다. (현재 50 MiB 업로드 제한 적용 중)
2. **비표준 중첩 블록 (Nested Block Hierarchy)**:
   - 블록 내부의 블록(조명 그룹 등)은 P0 도메인 원칙상 수량 과다 계상을 막기 위해 기본 `UNRESOLVED`(보류)로 격리됩니다. 필요 시 수동 마커로 승인합니다.
3. **심한 왜곡 또는 손글씨 스캔 도면**:
   - 도면이 심하게 기울어졌거나 구겨진 스캔본의 경우 템플릿 매칭 신뢰도가 낮아질 수 있으며, 이 경우 임계값(Threshold)을 0.60 수준으로 낮추거나 수동 마커를 병행합니다.
4. **산출물 법적 면책 고지**:
   - 모든 산출표와 엑셀 파일은 `잠정 / 검수 진행 중(Provisional)` 상태로 생성되며, 최종 시공 발주 및 안전 판단은 공인 전기 적산 기술자의 최종 검수를 필요로 합니다.

---

## 5. 품질 검증 및 테스트 통과 증거

본 통합 브랜치는 다음의 정적 분석 및 엔드투엔드 테스트를 100% 통과했습니다:

```bash
# 1. Python 백엔드 테스트 (pytest)
$ uv run pytest
# => 104 passed, 1 warning (2.68s)

# 2. Python 린트 & 타입 검사 (ruff / mypy)
$ uv run ruff check . && uv run mypy .
# => All checks passed!
# => Success: no issues found in 30 source files

# 3. Next.js 프론트엔드 린트 & 빌드
$ (cd apps/web && npm run lint && npm run build)
# => Compiled successfully (Turbopack static optimization pass)

# 4. Playwright E2E 자동화 스모크 (7개 실전 시나리오)
$ (cd apps/web && npm run test:playwright)
# => ALL PLAYWRIGHT SMOKE TESTS PASSED: 10 Passed, 0 Failed
```

---

## 6. PO 시연 시작 방법 (3분 퀵스타트)

1. **원클릭 구동 스크립트 실행**:
   ```bash
   ./scripts/dev-start.sh
   ```
2. **브라우저 접속**:
   - 웹 대시보드: `http://localhost:3000`
   - API 스웨거: `http://127.0.0.1:8000/docs`
3. **실전 데모 체험**:
   - **[다중 도면 데모 (Issue #35)]**: 1F REV0(6) + 2F(8) = 14 LIGHT $\rightarrow$ 1F REV1(10) 교체 시 18 LIGHT (+4 EA) $\rightarrow$ 설계변경 비교 & 4시트 엑셀 내보내기 검증.
   - **[실전 종합 데모]**: `floorplan_sample.png` 선택 후 상단 툴바 **[기호 검색]** 탭 클릭 $\rightarrow$ 조명 심벌 드래그 크롭 $\rightarrow$ [기호 검색 실행] $\rightarrow$ 키보드 `A`/`R`로 검수 $\rightarrow$ [일괄 승인] $\rightarrow$ [물량산출표] 탭에서 `LIGHT` 수량 확인 $\rightarrow$ [Excel 내보내기].
4. **종료**:
   - 터미널에서 `Ctrl + C` 누르거나 별도 창에서 `./scripts/dev-stop.sh` 실행.

상세 시연 클릭 가이드는 [USER_SMOKE_TEST.md](file:///Users/gotow/Documents/neonfamily101/electrical-ai-platform/docs/USER_SMOKE_TEST.md)를 참고해 주십시오.

---

## 7. 2차 출시 후보 (Issue #35 다중 도면·리비전 통합 RC) 및 PO 승인 요청 사항

- [x] Multi-format (DXF, Image, PDF) 단일 통합 파이프라인 완성
- [x] 사용자 지정 기호 드래그 검색 및 단축키 검수 워크플로우 완성
- [x] 범례 매핑 템플릿 시스템 및 2시트/4시트 엑셀 내보내기 완성
- [x] 원클릭 로컬 구동 스크립트 및 2종 실전 데모 시드 완성
- [x] **[Issue #35] 다중 도면 스코프 등록부 (`sheet_key`, `floor`, `zone`, `sheet_role`, `active_for_takeoff`) 완성**
- [x] **[Issue #35] 층/구역 단위 충돌 방지 및 단일 sheet_key 당 1개 활성 REV 배타성 완성**
- [x] **[Issue #35] 프로젝트 통합 적산 API (`GET /api/projects/{id}/takeoff`) 및 단위 분리 안전성 완성**
- [x] **[Issue #35] 설계변경 실용적 차이 분석 (`GET /api/projects/{id}/revisions/compare`) 및 4시트 엑셀 완성**
- [x] **[Issue #35] 합성 DXF 픽스처 4종 및 14 $\rightarrow$ 18 (+4 EA) 정답 검증 완료 (pytest 111건 + E2E Playwright 통과)**
- [ ] **PO 명시 승인 요청:** main 브랜치 통합 및 제한적 사내 사용자 베타 배포 진행 승인
