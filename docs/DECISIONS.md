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
