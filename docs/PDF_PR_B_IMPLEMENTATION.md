# PDF 다중 페이지 뷰어 및 수동 EA 적산 구현 명세서 (PR B)

**관련 이슈**: [Issue #17](https://github.com/Junebooky/electrical-ai-platform/issues/17), [Issue #12](https://github.com/Junebooky/electrical-ai-platform/issues/12)  
**기반 브랜치**: `feat/issue-12-image-pdf-support` (PR #14)  
**작업 브랜치**: `feat/issue-12-pdf-pr-b`  
**라이브러리 라이선스 준수**: `pypdf` (BSD-3-Clause), `pypdfium2` (Apache-2.0 / BSD-3-Clause) — ADR-001 AGPL 배제 원칙 엄격 준수

---

## 1. 개요 및 배경

본 문서는 Issue #17에 명시된 **[PR B] PDF 다중 페이지 뷰어 및 수동 EA 적산 기능**의 설계, 좌표 변환 수식, 메모리 안전성, 보안 방어 및 검증 결과를 기술합니다.

PR B는 자동 기호 추출(벡터 파싱)을 제외하고, 대용량 PDF 도면을 **페이지별로 안전하게 래스터 렌더링**하고 **정규 pt 단위 좌표계(`PDF_PAGE_POINT`)** 위에서 사용자가 수동으로 기구(EA)를 등록·검수·적산할 수 있도록 구현되었습니다.

---

## 2. 좌표 체계 및 변환 수식 (`PDF_PAGE_POINT`)

### 2.1 정규 좌표계 정의
- **좌표계 명칭**: `PDF_PAGE_POINT`
- **원점**: 화면에 표시되는 대상 페이지 CropBox의 **좌상단(Top-Left)** `(0.0, 0.0)`
- **방향**: $+x$ 우측(가로), $+y$ 하측(세로) (SVG 및 브라우저 화면 공간과 1:1 일치)
- **단위**: Canonical Point (`pt`, $1\,\text{pt} = 1/72\,\text{inch}$)
- **유효 범위**: 반열림 구간 $[0.0, W_{\text{pt}}) \times [0.0, H_{\text{pt}})$ ($W_{\text{pt}}, H_{\text{pt}}$는 회전 각도 적용 후 표시 크기)

### 2.2 내부 PDF Native 좌표 $\leftrightarrow$ 정규 표시 좌표 변환
PDF 사양(ISO 32000-1)에서 네이티브 좌표는 좌하단 원점, $+v$ 상향입니다. 또한 페이지마다 `/Rotate` ($0^\circ, 90^\circ, 180^\circ, 270^\circ$) 및 `/CropBox` $[cx_0, cy_0, cx_1, cy_1]$ 오프셋이 적용될 수 있습니다.

#### (1) Canonical $\to$ Native PDF 좌표 변환 (`canonical_to_pdf_native`)
- **$0^\circ$**:
  $$u = cx_0 + x_{\text{pt}}, \quad v = cy_1 - y_{\text{pt}}$$
- **$90^\circ$**:
  $$u = cx_0 + y_{\text{pt}}, \quad v = cy_0 + x_{\text{pt}}$$
- **$180^\circ$**:
  $$u = cx_1 - x_{\text{pt}}, \quad v = cy_0 + y_{\text{pt}}$$
- **$270^\circ$**:
  $$u = cx_1 - y_{\text{pt}}, \quad v = cy_1 - x_{\text{pt}}$$

#### (2) Native PDF $\to$ Canonical 좌표 변환 (`pdf_native_to_canonical`)
- **$0^\circ$**:
  $$x_{\text{pt}} = u - cx_0, \quad y_{\text{pt}} = cy_1 - v$$
- **$90^\circ$**:
  $$x_{\text{pt}} = v - cy_0, \quad y_{\text{pt}} = u - cx_0$$
- **$180^\circ$**:
  $$x_{\text{pt}} = cx_1 - u, \quad y_{\text{pt}} = v - cy_0$$
- **$270^\circ$**:
  $$x_{\text{pt}} = cy_1 - v, \quad y_{\text{pt}} = cx_1 - u$$

> **수치 검증**: `fixtures/pdf/pdf_b_02_rotated_cropbox.pdf` ($90^\circ$ 회전 및 비영 CropBox) 대상 왕복 변환 테스트 결과, 오차 $|\Delta| < 10^{-6}\,\text{pt}$로 완전 일치를 증명함.

---

## 3. 백엔드 아키텍처 및 안전성 설계

### 3.1 메모리 안전 On-demand 렌더링
- 대용량 다중 페이지 PDF(최대 100페이지) 업로드 시 모든 페이지를 한 번에 메모리에 압축 해제하지 않습니다.
- 업로드 단계에서는 메타데이터(페이지 수, 페이지별 표시 크기, 회전 각도)만 경량 추출하고, 원본은 `raw.pdf`로 안전하게 보존합니다.
- 사용자가 조회하는 페이지만 144 DPI ($2.0\times$ 스케일)로 단일 페이지 렌더링하여 `pages/page_{page_index}.png` 디스크 캐시에 보관하고 스트리밍합니다 (`GET /drawings/{id}/pages/{page_index}/image`).

### 3.2 보안 및 거부 정책
1. **용량 및 페이지 수 제한**: 50 MiB 초과 시 HTTP 413, 100페이지 초과 시 HTTP 400 반환.
2. **암호화 문서 거부**: 암호화/비밀번호 보호된 PDF 업로드 시 `PdfEncryptedError`를 포착하여 명확한 안내 메시지와 함께 HTTP 400 반환.
3. **손상 문서 거부**: 트레일러/헤더가 손상된 파일은 `PdfCorruptError`를 통해 HTTP 400 반환.
4. **엄격한 수동 기구 좌표 검증**:
   - `math.isfinite(x) and math.isfinite(y)` 필수 검증 (NaN / Inf 차단).
   - `page_index` 유효 범위 검증: $[0, \text{page\_count})$.
   - 페이지별 개별 표시 크기 반열림 구간 $[0, W_{\text{pt}}) \times [0, H_{\text{pt}})$ 검증.
5. **EA 단위 고정 원칙 (P0 M-UNIT-01)**:
   - PDF 도면의 수동 마커 및 품목 매핑은 원칙상 `EA` 단위만 허용 (비EA 요청 시 HTTP 400 차단).

### 3.3 내보내기 메타데이터 추적성
- **CSV Evidence**: `source_object_id`, ..., `exported_at`, `page_index`, `source_type`, `file_type`, `coordinate_space` 18개 컬럼 출력. 수식 인젝션 방어 (`'`, `+`, `-`, `=`, `@` 이스케이프) 유지.
- **XLSX 2개 시트**:
  - 시트 1: "Takeoff Summary" (품목별 잠정 수량 및 비고 표기)
  - 시트 2: "Takeoff Evidence" (페이지 번호 `page_index`, 도면 유형, 파일 유형, 좌표계 명시)

---

## 4. 프론트엔드 UI/UX 구현

1. **다중 페이지 내비게이션 바**:
   - 다중 페이지 PDF 로드 시 상단에 `◀ 1 / N 페이지 ▶` 컨트롤 제공.
   - 현재 페이지 번호 및 페이지별 치수 표기 (예: `1 / 2 페이지 (595.3 × 841.9 pt)`).
2. **독립적 페이지 뷰어 (`CadViewer`)**:
   - SVG 좌표계를 정규 `pt` 단위로 구성하여 클릭 좌표 `(wx, wy)`가 스케일링 오차 없이 직접 정규 `pt`로 매핑됨.
   - 하단 상태바에 `PDF (페이지 좌표계 pt) [P.1/2]` 및 실시간 pt 마우스 좌표 표시.
   - 현재 페이지에 속한 수동 마커만 필터링하여 표시 (`page_index` 분리).
3. **사용자 가이드 배너**:
   - "PDF 도면을 표시했습니다. 기구 위치를 직접 표시해 주세요. (잠정 수량)" 문구 명시.
4. **검수 드로어 (`ReviewDrawer`)**:
   - 좌표 라벨을 `PDF 페이지 좌표 (pt) [P.1]` 형식으로 자동 분기 표기.
5. **적산표 (`TakeoffTable`)**:
   - 산출 근거 목록에 `[P.1]`, `[P.2]` 배지를 표시하여 다중 페이지 위치 직관화.

---

## 5. 합성 테스트 픽스처 및 테스트 커버리지

### 5.1 합성 픽스처 (`fixtures/pdf/`)
1. `pdf_b_01_two_pages.pdf`: 2페이지 다중 규격 PDF
   - Page 0: A4 세로 (595.28 × 841.89 pt)
   - Page 1: A4 가로 (841.89 × 595.28 pt)
2. `pdf_b_02_rotated_cropbox.pdf`: $90^\circ$ 회전 및 CropBox 오프셋 포함 페이지
3. `corrupt.pdf`: 손상된 바이너리 구조 파일
4. `encrypted.pdf`: 비밀번호 암호화 파일

### 5.2 테스트 결과 (`apps/api/tests/test_pdf_drawing.py`)
- `test_pdf_upload_metadata_multipage`: 다중 페이지 메타데이터, 치수, 경고 문구 검증
- `test_pdf_page_image_rendering_endpoint`: 단일 페이지 On-demand 렌더링 및 404 경계 검증
- `test_pdf_multipage_manual_takeoff_scenario`: 1페이지(3 LIGHT) + 2페이지(2 OUTLET), 동일 좌표 `(200, 300)` 분리 및 총 5개 잠정 수량 적산 검증
- `test_pdf_boundary_and_validation_defense`: 페이지별 상이한 너비 경계, 음수/초과 좌표, 비EA 단위 차단 검증
- `test_pdf_rotated_cropbox_support`: $90^\circ$ 회전 도면의 가로/세로 반전 표시 치수 및 좌표 검증
- `test_pdf_security_rejections`: 손상 문서 및 암호화 문서 400 거부 검증
- `test_pdf_csv_and_xlsx_exports`: CSV/XLSX 내 `page_index`, `source_type` 컬럼 및 수식 인젝션 방어 검증
- `test_pdf_raw_preservation_and_download`: 원본 PDF 100% 바이너리 일치 다운로드 검증

**전체 테스트 결과**: 총 60개 테스트 통과 (DXF, IMAGE, PDF 전체 무결성 검증 완료).

---

## 6. PR C 로드맵 및 향후 과제
- PDF 내장 벡터 패스(라인/폴리라인) 및 텍스트 폰트 블록 자동 파싱
- 벡터 기호 템플릿 매칭을 통한 자동 카운팅
- 도면 축척(Scale Bar) 인식 및 배선 케이블 길이(M) 산출 엔진
