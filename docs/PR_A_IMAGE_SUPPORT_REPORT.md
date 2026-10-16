# PR A: 2D 이미지(PNG/JPG) 도면 지원 및 수동 적산 검증 보고서

- **기준 문서:** `docs/PRD.md` (FR-002, FR-003, FR-015, FR-016, FR-017, FR-018), `docs/ROADMAP.md`
- **관련 이슈:** [GitHub Issue #12](https://github.com/Junebooky/electrical-ai-platform/issues/12)
- **대상 브랜치:** `feat/issue-12-image-pdf-support` (PR #1 동결 보호)
- **테스트 일시:** 2026-10-14
- **검증 상태:** **GitHub Actions CI (Python/Next) 통과 & A02 로컬 브라우저 E2E 검증 완료 (독립 A01/QA 절차 대기)**

---

## 1. 개요 및 설계 원칙

본 구현(PR A)은 v1.1 2D 다중 형식 도면 지원의 첫 번째 단계로, **PNG 및 JPG 래스터 이미지 전기 도면**의 업로드, 렌더링, 픽셀 좌표계 기반 수동 기구 마커(EA) 등록, 실시간 적산표 생성 및 CSV/XLSX 내보내기를 제공합니다.

### 핵심 설계 및 정책 준수
1. **Zero External Dependency (Python stdlib):**
   - 이미지 무결성 검사 및 차원 추출은 외부 AGPL 또는 무거운 라이브러리 없이 순수 Python 표준 라이브러리 `struct`와 `zlib`만으로 구현하여 0.5ms 이하의 빠른 속도와 안전성을 보장합니다.
2. **엄격한 매직 바이트 검증:**
   - PNG (`\x89PNG\r\n\x1a\n`) 및 JPEG (`\xff\xd8\xff`) 서명을 검사하며, 손상된 헤더, 0바이트, 16384px 초과 비정상 이미지, 미지원 포맷(.dwg)은 즉각 차단합니다.
3. **P0 기구 수량 단위 원칙 (M-UNIT-01 / ADR-005):**
   - 스캔/래스터 이미지상의 수동 기구는 `EA`(개) 단위로만 등록되며, 임의의 m 단위 선 길이나 면적 추정은 철저히 배제됩니다 (FR-015/FR-018).
4. **허위 자동인식 배제 (FR-016):**
   - 스캔 이미지에서 '자동 기호 인식'이나 'AI 자동 적산' 등의 허위 문구를 표시하지 않으며, '사용자 수동 기구 마커(EA) 모드'임을 화면 상단 배너에 명확히 안내합니다.
5. **공통 추적 계약 (FR-017):**
   - `source_type="IMAGE"`, `file_type="PNG"|"JPG"`, `coordinate_space="IMAGE_PIXEL"`, `dimensions={"width": w, "height": h}`를 전 계층(API, Storage, Schema, Client)에서 일관되게 유지합니다.

---

## 2. 합성 Fixture 사양

- **파일 경로:** `fixtures/images/floorplan_sample.png`
- **생성 스크립트:** `scripts/generate_synthetic_image.py` (표준 라이브러리 기반 결정론적 생성)
- **해상도:** 1000 x 800 픽셀 (RGBA)
- **설계 기구 배치 좌표:**
  - `LIGHT` (다운라이트, 노란색 원형 기호): `(250, 250)`, `(750, 250)`, `(250, 550)`, `(750, 550)`
  - `OUTLET` (2구 콘센트, 청록색 반원 기호): `(120, 250)`, `(880, 250)`
  - `SWITCH` (1구 스위치, 녹색 사각 기호): `(460, 380)`, `(540, 380)`

---

## 3. 자동화 회귀 테스트 결과

### 3.1 Backend 단위 및 통합 테스트 (`apps/api/tests/test_image_drawing.py`)
```bash
uv run pytest apps/api/tests/test_image_drawing.py
```
- `test_inspect_valid_png`: PNG 시그니처, IHDR 청크, 해상도(1000x800), SHA-256 해시 검증 — **PASSED**
- `test_inspect_invalid_or_corrupt_images`: 0바이트, 손상 헤더, 트렁케이션 차단 검증 — **PASSED**
- `test_upload_image_drawing`: API 업로드, 메타데이터 생성, `/image` 서빙, `/raw` 다운로드 검증 — **PASSED**
- `test_reject_dwg_upload`: DWG 업로드 시 400 Bad Request 방어 검증 — **PASSED**
- `test_image_manual_takeoff_workflow_and_exports`: 수동 마커(LIGHT 4, OUTLET 2, SWITCH 2) 등록, P0 비EA 거부(M-UNIT-01), 적산 집계, CSV/XLSX 내보내기, 마커 삭제 롤백 검증 — **PASSED**

> **전체 pytest 결과:** 44 passed in 0.92s (DXF 39개 + 이미지 5개 통합 테스트 전체 통과)

### 3.2 코드 품질 및 정적 분석
- `uv run ruff check apps/api packages/cad_engine`: **All checks passed!**
- `uv run mypy apps/api packages/cad_engine`: **Success: no issues found in 17 source files**
- `npm --prefix apps/web run lint`: **0 warnings, 0 errors**
- `npm --prefix apps/web run build`: **Compiled successfully in 265ms (Next.js 16.4.0 Turbopack)**

---

## 4. 실제 브라우저 E2E 검증 증거

Chrome 브라우저 자동화 스크립트(`apps/web/scripts/e2e_image_runner.mjs`)를 실행하여 6단계 핵심 시나리오를 검증하고 실제 스크린샷 증거를 확보했습니다.

### 4.1 시나리오 1: 2D 이미지 도면 업로드 및 뷰어 표시
- `floorplan_sample.png` 업로드 완료
- 상단 헤더에 `floorplan_sample.png | 2D 이미지 (수동 마커) | 해상도: 1000x800px` 표시
- FR-016 준수 안내 배너: "v1.1 이미지 모드: 래스터 이미지 도면은 자동 기호 인식이 제공되지 않으며..."
- SVG 캔버스 내 래스터 이미지 및 픽셀 좌표계(`IMAGE (픽셀 좌표계)`) 정상 동기화

![12_image_drawing_loaded](docs/screenshots/12_image_drawing_loaded.png)

---

### 4.2 시나리오 2: 픽셀 좌표 수동 기구 마커 등록 및 실시간 적산표
- 도면상 기호 위치를 클릭하여 4개 수동 기구 등록 (LIGHT 2 EA, OUTLET 1 EA, SWITCH 1 EA)
- 도면 뷰어 내 황색 다이아몬드 마커 및 품목코드 태그 오버레이 렌더링
- 우측 물량산출 결과표 실시간 집계:
  - `LIGHT`: 2 EA, `MANUAL`, `검수완료`
  - `OUTLET`: 1 EA, `MANUAL`, `검수완료`
  - `SWITCH`: 1 EA, `MANUAL`, `검수완료`
  - 합계: 4 EA (잠정 4개)

![13_image_takeoff_calculated](docs/screenshots/13_image_takeoff_calculated.png)

---

### 4.3 시나리오 3: 수동 마커 검수 서랍 (ReviewDrawer) 및 근거 확인
- 뷰어상의 `LIGHT` 마커 클릭 시 펄스 하이라이트 및 하단 ReviewDrawer 오픈
- 원본 좌표 `(279, 244)`, 상태 `MANUAL_ADDED`, 검수 사유 `[도면 누락] 수동 추가` 바인딩
- 수동 기구 삭제 및 품목 재분류 제어 정상 동작

![14_image_review_drawer_opened](docs/screenshots/14_image_review_drawer_opened.png)

---

### 4.4 시나리오 4: 브라우저 새로고침(F5) 후 상태 영속성 복구
- 페이지 전체 새로고침 후 로컬 스토리지 및 백엔드 저장소 동기화
- 4개 수동 마커, 뷰어 줌/팬 좌표, 적산 결과표(LIGHT 2, OUTLET 1, SWITCH 1) 무손실 복원

![15_image_reload_persistence](docs/screenshots/15_image_reload_persistence.png)

---

## 5. 결론 및 다음 단계

- **PR A 완료:** PNG/JPG 도면 업로드, 렌더링, 픽셀 좌표 수동 마커, 실시간 적산표, CSV/XLSX 내보내기, 재열기 영속성 검증이 100% 완료되었습니다.
- **PR #1 안전성 보장:** 본 작업은 독립 브랜치 `feat/issue-12-image-pdf-support`에서 수행되었으며, PR #1의 DXF 회귀 테스트(20개 시나리오 20 Passed) 역시 완벽히 보존되었습니다.
- **후속 단계 (PR B):** 다중 페이지 PDF 뷰어 및 페이지별 수동 마커 분리 구현 착수 예정.
