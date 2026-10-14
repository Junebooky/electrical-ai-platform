# Architecture Decision Records (ADR)

- **문서 ID:** EAI-DEC-001
- **최신 갱신:** 2026-10-13
- **책임자:** A02 Principal Full-Stack Engineering Agent

---

## ADR-001: 초기 기술 스택 및 오픈소스 라이선스 채택

### 상태
**확정 (Accepted)**

### 배경
한국형 전기공사 AI 플랫폼 MVP 1(DXF 스마트 물량산출)을 위해 비용 0원 목표, 빠른 프로토타이핑, 높은 신뢰성, 상업적 배포 가능성을 모두 충족하는 기술 스택을 선정해야 함.

### 결정 사항
1. **Frontend**: Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4.
   - 선정 이유: 고성능 반응형 엔지니어링 UI, TypeScript를 통한 스키마 일관성.
2. **Backend**: FastAPI + Pydantic v2 + Uvicorn.
   - 선정 이유: Python CAD 생태계와의 직접 결합, 비동기 I/O, 강력한 타입 검증.
3. **CAD Processing Engine**: `ezdxf` (순수 Python).
   - 선정 이유: MIT 라이선스, C/C++ 네이티브 바인딩 의존성 없는 완전한 이식성, `ezdxf.recover`를 통한 강력한 손상 도면 복구 지원.
4. **Excel Export**: `openpyxl`.
   - 선정 이유: MIT 라이선스, 서식/멀티시트 완벽 지원.

### 라이선스 검토 결과
| 라이브러리 | 라이선스 | 상업적 이용 | 평가 |
|---|---|---|---|
| `ezdxf` | MIT | 가능 | 적합 (Core 채택) |
| `FastAPI` / `Pydantic` | MIT | 가능 | 적합 |
| `openpyxl` | MIT | 가능 | 적합 |
| `Next.js` / `React` | MIT | 가능 | 적합 |
| `PyMuPDF` | AGPLv3 | 조건부 (소스 공개 의무) | **MVP 채택 제외** (P1 PDF 도입 시 pypdfium2 검토) |
| `LibreDWG` | GPLv3 | 조건부 (전체 전염 위험) | **서버 임베딩 금지** |

---

## ADR-002: DWG 및 DXF 지원 범위 (DEC-001 준수)

### 상태
**확정 (Accepted)**

### 결정 사항
- **MVP 1(P0)은 DXF 파일만 처리**합니다.
- 업로드된 파일이 `.dwg` 확장자이거나, 바이너리 헤더가 AutoCAD DWG 매직 바이트(`AC10xx`)로 시작할 경우, 서버는 즉시 `DWG_NOT_SUPPORTED` 에러(HTTP 400)를 반환하고 "CAD 프로그램에서 DXF로 변환 후 업로드"하라는 명확한 한국어 안내를 제공합니다.
- 이유: DWG 상용 파서(Autodesk APS, ODA SDK)는 고액의 라이선스 비용이 발생하며, GPLv3 라이브러리는 상업 소프트웨어 배포에 법적 위험이 존재함.

---

## ADR-003: 2D 도면 뷰어 렌더링 엔진 (SVG 채택)

### 상태
**확정 (Accepted)**

### 결정 사항
- MVP 1은 **SVG 기반 2D 벡터 뷰어**를 채택합니다.
- 선정 이유:
  1. 각 CAD 요소(`SourceObject`)에 고유 DOM 식별자 및 이벤트 핸들러를 직접 바인딩할 수 있어 클릭 선택, 하이라이트 글로우 효과가 자연스러움.
  2. Canvas/WebGL 대비 상태 관리(React State)와의 동기화가 용이하고 코드 복잡도가 낮음.
- 한계 및 대응: 수십만 개 이상의 프리미티브를 가진 대용량 도면에서 프레임 저하가 발생할 경우, 레이어 필터링으로 렌더링 부하를 제어하며 향후 Canvas 전환을 검토함.

---

## ADR-004: CSV 및 XLSX 인코딩 및 멀티시트 계약

### 상태
**확정 (Accepted)**

### 결정 사항
- **CSV 내보내기**:
  - 한국어 윈도우 엑셀 환경에서 한글 깨짐을 방지하기 위해 **UTF-8 with BOM (`utf-8-sig`)** 인코딩을 적용합니다.
  - 요약(Summary)과 근거(Evidence)를 별도 파일로 다운로드 제공합니다.
- **XLSX 내보내기**:
  - `openpyxl`을 사용하여 단일 엑셀 파일 내에 **"Takeoff Summary"**와 **"Takeoff Evidence"** 2개 시트를 생성합니다.
  - 헤더 스타일링(어두운 배경, 볼드 폰트)과 수량 우측 정렬, 자동 열 너비 조정을 적용합니다.

---

## ADR-005: 도메인 안전 규칙 및 품목 식별 키 계약 (DEC-010 ~ DEC-014 준수)

### 상태
**확정 (Accepted)**

### 결정 사항
1. **정규 품목 식별 키 (Canonical Item Key) 및 1 item_code = 1 canonical definition 원칙**:
   - P0 산출 엔진 및 API 스토리지 계층에서 품목 집계의 고유 기준 키는 `item_code`입니다 (PRD §7.1 준수).
   - **API 및 엔진 정합성 계약**:
     - `PUT /mappings` 요청 시 동일 도면 내에서 동일 `item_code`에 대해 단위(`unit`) 또는 규격(`specification`)이 상충하는 규칙이 포함된 경우(동일 블록 및 서로 다른 블록 간 모두 포함), API는 **HTTP 400 Bad Request**로 즉시 거부합니다.
     - 매핑 및 수동 기구의 단위(`unit`)는 공백이나 빈 문자열을 허용하지 않으며, P0 실물 기구는 유효한 단위(예: 'EA', 'SET', 'M' 등)를 명시해야 합니다. 누락 시 **HTTP 400 Bad Request**로 즉시 거부합니다.
     - `POST /manual-objects` 시:
       - 지정된 `item_code`가 도면 매핑에 존재하는 경우: 매핑에 정의된 정규 단위와 다르면 **HTTP 400 Bad Request**로 거부합니다.
       - 지정된 `item_code`가 매핑에 없는 수동 전용 품목인 경우: 해당 품목의 단위(예: 'SET')를 정규 단위로 채택하여 Summary/CSV/XLSX에 정확히 출력하며, 동일 수동 품목에 대해 서로 다른 단위(예: 'SET'과 'EA')가 혼합 입력되면 **HTTP 400 Bad Request**로 거부합니다.
     - API에서 엔진으로 매핑을 전달할 때 `unit`과 `specification`을 누락 없이 전달(`BlockMapping(..., unit=m.unit, specification=m.specification)`)하여 엔진 레벨의 동순위 상충 감지가 누락되지 않도록 보장합니다.
     - 레거시 데이터나 파일 직접 조작으로 충돌 매핑 또는 수동 단위 불일치가 스토리지에 존재하는 경우라도, 집계 빌드 경로(`build_takeoff_result`)에서 상충 품목을 감지하여 임의의 메타데이터 덮어쓰기나 서로 다른 단위(EA/SET)의 자동 합산을 엄격히 금지하고, 수량 0 EA 및 `UNRESOLVED`(`품목 정의 충돌`)로 fail-closed 격리합니다.
   - 복수 규격/단위의 다차원 품목 분류 체계 확장은 P1 과제로 분리합니다.
2. **구조적 결함 및 미검증 CAD 블록의 검수 오버라이드 차단**:
   - 외부참조(`XREF_UNRESOLVED`), 블록 정의 누락(`MISSING_BLOCK_DEFINITION`), 순환 참조(`CIRCULAR_BLOCK_REFERENCE`)는 물론, 동적 블록(`DYNAMIC_BLOCK`), 익명 블록(`ANONYMOUS_BLOCK`), 중첩 계층(`NESTED_BLOCK` 하위 객체 및 상위 어셈블리 컨테이너)은 P0에서 CAD 자동 집계 및 사용자 `INCLUDED` 검수 오버라이드를 원천 차단합니다.
   - 사유: 도면 범례 및 설치 상세 검증 없이 임의의 CAD 요소를 실물 기구로 확정할 수 없으며, 필요 시 현장 검수를 거친 별도 수동 마커(`MANUAL_ADDED`)로만 보수 집계합니다.
3. **도면 범위 미검증 시 보수적 잠정 기본값 고정**:
   - 도면 범례/범위(`count_scope_verified`) 검증 승인 체계가 도입되기 전까지 모든 물량산출은 `is_provisional = True`를 고정 기본값으로 유지하며, UI 및 CSV/XLSX에서 성급한 완료 배지 노출을 엄격히 금지합니다.
   - 내보내기 응답 헤더(`X-Takeoff-Completeness`, `X-Takeoff-Unresolved-Count`)를 통해 전송 계층에서도 잠정 상태를 명시합니다.
