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

---

## 2. 빠른 시작 (Quick Start)

### 🚀 원클릭 시연 실행 (추천)
단 한 번의 명령으로 사전 점검, 백엔드 API, 프론트엔드 웹 앱을 동시에 실행합니다:

```bash
# 로컬 개발 및 시연 서버 원클릭 실행 (macOS / Linux)
./scripts/dev-start.sh
```

- 실행 후 브라우저에서 **`http://localhost:3000`** 접속
- API Swagger 문서: **`http://127.0.0.1:8000/docs`**
- 대표 샘플 도면: **`fixtures/dxf/basic_devices.dxf`**
- **PO 8단계 시연 가이드:** [`docs/USER_SMOKE_TEST.md`](docs/USER_SMOKE_TEST.md)
- 서버 종료: 터미널에서 `Ctrl + C` 또는 `./scripts/dev-stop.sh`

---

### 수동 실행 (Manual Setup)

#### 사전 준비물
- Python 3.12+ 및 [`uv`](https://github.com/astral-sh/uv)
- Node.js 20+ 및 `npm`

#### 1) 의존성 설치
```bash
# Python 백엔드 및 cad_engine
uv sync

# 프론트엔드 (Next.js)
npm --prefix apps/web install
```

#### 2) 백엔드 API 서버 실행 (포트 8000)
```bash
# 로컬 단일 사용자 보안 정책에 따라 127.0.0.1 루프백 바인딩을 기본 권장합니다.
PYTHONPATH=apps/api/src:packages/cad_engine/src uv run uvicorn eai_api.app:app --host 127.0.0.1 --port 8000 --reload
```

#### 3) 프론트엔드 웹 앱 실행 (포트 3000)
```bash
npm --prefix apps/web run dev
```
브라우저에서 `http://localhost:3000`에 접속합니다.

---

## 3. 테스트 및 품질 검증

```bash
# 1. 린트 및 포매팅 검사
uv run ruff check .
npm --prefix apps/web run lint

# 2. 정적 타입 검사
uv run mypy .

# 3. 단위 및 통합 테스트 실행 (18개 테스트 전체)
uv run pytest

# 4. 프론트엔드 프로덕션 빌드 검증
npm --prefix apps/web run build
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
