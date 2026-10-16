# Electrical AI Platform (한국형 전기공사 AI 통합 플랫폼)

> **MVP 1: DXF 기반 전기 도면 스마트 물량산출 (Smart Takeoff)**

대한민국 전기공사업체와 전문 전기기술자가 CAD 전기설계도(DXF)를 업로드하여 기구를 자동으로 인식·매핑하고, 도면 위에서 직접 검수한 뒤 근거를 갖춘 물량산출표(CSV/Excel)를 즉시 산출하는 전문가용 소프트웨어입니다.

---

## 1. 주요 기능 (MVP 1)

1. **결정론적 DXF 분석 및 2D 평면도 렌더링**:
   - AutoCAD DXF(ASCII/바이너리) 파싱 및 WCS 기준 2D 벡터 평면도 렌더링.
   - 줌/팬, 레이어 가시성 켜기/끄기, 블록 선택 및 글로우 하이라이트.
   - DWG 감지 시 친절한 변환 안내, 손상/잘린 파일 안전 복구 및 예외 방어.
2. **도면 블록 → 품목 반자동 매핑**:
   - 도면 내 CAD 블록을 조명(LIGHT), 콘센트(OUTLET), 스위치(SWITCH), 집계 제외(EXCLUDE) 등으로 원클릭 매핑.
3. **양방향 하이라이트 및 물량산출표**:
   - 매핑 즉시 도면 위 객체와 연동된 수량 집계표 산출.
   - 산출표 행 클릭 시 도면 내 해당 기구들 일괄 강조.
4. **오탐 제외 및 누락 기구 수동 추가**:
   - 개별 객체 클릭 후 "오탐 제외(EXCLUDED)" 및 사유 기록, "복원(INCLUDED)".
   - 도면 클릭을 통한 누락 기구 수동 추가 (`MANUAL_ADDED`).
5. **CSV & Excel 내보내기**:
   - 한국어 엑셀 호환 UTF-8 BOM CSV.
   - Summary와 Evidence 2개 시트가 포함된 스타일링된 `.xlsx` 파일 즉시 다운로드.
6. **투명한 도면 경고**:
   - 단위 미설정(`$INSUNITS=0`), 외부참조(XREF), 중첩/동적 블록을 숨기지 않고 경고로 안내.
7. **다중 도면 스코프 및 리비전 관리 (Issue #35)**:
   - 층/구역(`floor`, `zone`, `sheet_key`, `sheet_role`) 단위 스코프 분리 및 통합 적산.
   - 단일 `sheet_key` 당 정확히 1개 활성 REV 배타성 강제 및 구도면 중복 집계 원천 차단.
   - 참조도면(`sheet_role: REFERENCE`) 자동 적산 제외 및 스코프 중복 경고.
   - 설계변경 물량 증감(Revision Pragmatic Diff, Delta +/-) 및 객체 단위 매칭 추적.
   - 4시트 전문 Excel(`Project Summary`, `Drawing Breakdown`, `Revision Delta`, `Evidence`) 및 CSV 내보내기 (수식 주입 방어 적용).
8. **축척 보정 및 2D 계획 경로 측정 (Issue #37)**:
   - 2점 클릭 축척 보정 (`pixel_distance` $\rightarrow$ `real_distance_m`, 도면당 영속 저장).
   - 배선/전선관 2D 폴리라인 인터랙티브 측정 (실시간 길이 누적 배지, Enter 완료, Backspace 취소, ESC 취소).
   - 단위 격리 원칙: 기구 수량(`EA`)과 선형 연장(`m`)의 합산 원천 차단 및 독립 KPI 카드 표기.
   - 잠정(`provisional`) m 물량 안전 태그 및 엑셀 `Route Measurements` 시트 자동 생성 (수식 주입 방어 적용).
   - 1-클릭 7.00m 오라클 데모 탑재 (100px=10m 스케일 바, 70px=7.00m 2분기 배선 검증).

---

## 2. 빠른 시작 (One-Click Local Setup)

### 원클릭 로컬 구동 (권장)
```bash
./scripts/dev-start.sh
```
- 사전 필수 환경(Python 3.12+, Node 20+) 및 포트 충돌(8000, 3000)을 자동 진단하고 백엔드와 프론트엔드를 한 번에 실행합니다.
- 웹 브라우저에서 **`http://localhost:3000`** 접속 후:
  - **[2D 경로 데모 (7m) (Issue #37)]**: 축척 보정(100px=10m) 및 7.00m 배선 경로 검증, 단위 격리(EA vs m) 확인.
  - **[다중 도면 데모 (Issue #35)]**: 14 EA $\rightarrow$ 18 EA (+4 EA) 리비전 교체 및 4시트 엑셀 검증.
  - **[실전 데모 (Live Demo)]**: 3종 멀티포맷(IMAGE, DXF, PDF) 기호 시각 검색 및 검수.
- 서비스 종료 시 터미널에서 `Ctrl + C` 또는 `./scripts/dev-stop.sh`를 실행합니다.

### 상세 문서 안내
- 📖 **PO 시연 클릭 매뉴얼**: [`docs/USER_SMOKE_TEST.md`](docs/USER_SMOKE_TEST.md)
- 🚀 **통합 MVP 베타 릴리즈 노트**: [`docs/MVP_BETA_RELEASE_NOTES.md`](docs/MVP_BETA_RELEASE_NOTES.md)
- 🛠️ **AutoCAD R12 호환성 가이드**: [`docs/DXF_R12_COMPATIBILITY_GUIDE.md`](docs/DXF_R12_COMPATIBILITY_GUIDE.md)

### 수동 실행 (Manual Setup)
```bash
# 1. 의존성 설치
uv sync
npm --prefix apps/web install

# 2. 백엔드 API 실행 (포트 8000)
PYTHONPATH=apps/api/src:packages/cad_engine/src uv run uvicorn eai_api.app:app --host 127.0.0.1 --port 8000

# 3. 프론트엔드 실행 (포트 3000)
npm --prefix apps/web run dev
```

---

## 3. 테스트 및 품질 검증

```bash
# 1. 린트 및 포매팅 검사
uv run ruff check .
npm --prefix apps/web run lint

# 2. 정적 타입 검사
uv run mypy .

# 3. 단위 및 통합 테스트 실행 (111개 테스트 전체 통과)
uv run pytest

# 4. 프론트엔드 프로덕션 빌드 및 E2E 테스트 검증
npm --prefix apps/web run build
npm --prefix apps/web run test:multi-drawing
```

---

## 4. 디렉터리 구조

```
electrical-ai-platform/
├── apps/
│   ├── web/               # Next.js 16 + React 19 웹 프론트엔드
│   └── api/               # FastAPI 로컬 백엔드 서비스
├── packages/
│   └── cad_engine/        # ezdxf 기반 결정론적 DXF 파서 및 정규화 엔진
├── fixtures/dxf/          # 14종 합성 DXF 픽스처 및 독립 기대값 JSON
├── docs/                  # PRD, 아키텍처, ADR, CAD 스키마, API 계약 문서
└── pyproject.toml         # uv 모노레포 워크스페이스 설정
```

---

## 5. 라이선스 및 비용 원칙
- 모든 라이브러리는 MIT/Apache-2.0 상업 이용 가능 오픈소스를 채택했습니다.
- 유료 외부 AI API 및 클라우드 호스팅 결제 없이 로컬에서 **비용 0원**으로 구동됩니다.
