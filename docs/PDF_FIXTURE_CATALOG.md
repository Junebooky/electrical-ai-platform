# PDF Fixture Catalog & Public License Verification

> **Issue Reference**: [Issue #20](https://github.com/Junebooky/electrical-ai-platform/issues/20), [Issue #17](https://github.com/Junebooky/electrical-ai-platform/issues/17) / [PR #21](https://github.com/Junebooky/electrical-ai-platform/pull/21)  
> **Status**: Completed & Verified  
> **Author**: A02 · Development  
> **Base Policy**: ADR-001 (License-Safe PDF Parsing: `pypdf` BSD-3-Clause, `pypdfium2` Apache-2.0 / BSD-3-Clause, strictly AGPLv3-free)

---

## 1. 개요 및 목적 (Overview)

본 문서는 PDF PR B([Issue #17](https://github.com/Junebooky/electrical-ai-platform/issues/17)) 및 PDF 정답셋/라이선스 검증([Issue #20](https://github.com/Junebooky/electrical-ai-platform/issues/20))의 핵심 산출물로서 다음 두 가지 요구사항을 완결합니다:

1. **산출물 A (합성 Fixture 카탈로그 및 결정론적 정답셋)**:
   - 다중 페이지(A4 세로/가로 혼합), 회전(90°) 및 CropBox 오프셋, 스캔(래스터 단일 페이지)+벡터 혼합 도면, 보안 예외(손상/암호화)를 포괄하는 100% 재현 가능한 합성 PDF fixture 세트 구축.
   - 기계 판독 가능한 `fixtures/pdf/expected.json` 및 `expected_takeoff.json` 정답 오라클 스키마 정의 및 CI 통합 검증.
2. **산출물 B (공개 전기 도면 라이선스 검증 보고서)**:
   - 오픈소스 및 공개 저장소에 등록된 실제 전기 도면 PDF의 저작권/라이선스 적법성, 개인정보(PII) 포함 여부, KEC 표준 기호 적합성을 사전 검토하여 PR C(자동 인식)로 이어지는 데이터 전략 수립.

---

## 2. 산출물 A: 합성 Fixture 카탈로그 (Synthetic Fixtures)

모든 합성 Fixture는 외부 의존성 없이 `scripts/generate_pdf_fixtures.py` 스크립트를 통해 언제든지 바이트 단위로 100% 동일하게 재생성할 수 있습니다 (`SELF_GENERATED`).

### 2.1 재생성 명령

```bash
uv run python scripts/generate_pdf_fixtures.py
```

### 2.2 Fixture 인벤토리 및 메타데이터

| 파일명 | 크기 (bytes) | SHA-256 (앞 16자리) | 페이지 수 | 주요 특성 및 시험 목적 | 라이선스 |
|---|---|---|---|---|---|
| `pdf_b_2page_electrical.pdf` (별칭 `pdf_b_01_two_pages.pdf`) | 985 | `225165c52c040d9b` | 2 | QA_PDF_B_MATRIX PB-01 정답 일치: 1페이지 612×792 pt (ROT0), 2페이지 552×752 pt (CropBox `[24, 24, 776, 576]`, ROT90). 동일 좌표 `(100, 150)`에서의 `page_index` 격리 및 잠정(provisional) 5 EA 적산 검증 | SELF_GENERATED |
| `pdf_b_rotated_cropbox.pdf` (별칭 `pdf_b_02_rotated_cropbox.pdf`) | 625 | `a08db849b2fffcfa` | 1 | 90° 회전 및 비원점 CropBox `[50, 60, 550, 740]` 적용. 정규 좌표계(`PDF_PAGE_POINT`, 680×500 pt) 변환 및 화면 경계 검증 | SELF_GENERATED |
| `pdf_b_scanned_mixed.pdf` | 24,439 | `31f62203716d1ba5` | 2 | 1페이지 스캔 도면(Pillow 래스터 이미지 임베딩), 2페이지 벡터 전기 도면. PR B의 "OCR 미지원 / 수동 마커 전용" 고지 배너 노출 및 래스터/벡터 페이지 모두 수동 마커 삽입 가능 검증 | SELF_GENERATED |
| `pdf_b_oversized_dimension.pdf` | 435 | `b497560da1fc2194` | 1 | 12,000×12,000 pt (축당 10,000 px 및 40MP 초과). P0-03 리소스 DoS 방어 (HTTP 400 거부) 검증 | SELF_GENERATED |
| `corrupt.pdf` | 94 | `1c404492bf285f57` | 0 (손상) | 비정상 헤더/바이트 누락 PDF. HTTP 400 Bad Request 및 명확한 에러 메시지 반환 검증 | SELF_GENERATED |
| `encrypted.pdf` | 828 | `e64e1a896d84a7d4` | 1 (암호화) | `password123` 표준 암호화 적용 PDF. HTTP 400 거부 및 "암호화된 PDF는 지원하지 않습니다" 안내 검증 | SELF_GENERATED |

---

### 2.3 Fixture별 상세 Ground Truth 사양

#### 1) `pdf_b_2page_electrical.pdf`
- **페이지 구성**:
  - `page_index: 0`: 폭 612.0 pt, 높이 792.0 pt, 회전 0°
  - `page_index: 1`: 표시 폭 552.0 pt, 표시 높이 752.0 pt (원본 800×600 pt, CropBox `[24, 24, 776, 576]`, 회전 90°)
- **마커 정답셋 (Ground Truth Markers)**:
  - Page 0:
    1. `p0_lt_1`: `item_code: LIGHT`, `item_name: 다운라이트`, `x: 100.0`, `y: 150.0`, `unit: EA` (Page 1과 동일 좌표)
    2. `p0_lt_2`: `item_code: LIGHT`, `item_name: 다운라이트`, `x: 300.0`, `y: 220.0`, `unit: EA`
    3. `p0_lt_3`: `item_code: LIGHT`, `item_name: 다운라이트`, `x: 500.0`, `y: 650.0`, `unit: EA`
  - Page 1:
    4. `p1_ot_1`: `item_code: OUTLET`, `item_name: 콘센트`, `x: 100.0`, `y: 150.0`, `unit: EA` (Page 0과 동일 좌표)
    5. `p1_ot_2`: `item_code: OUTLET`, `item_name: 콘센트`, `x: 400.0`, `y: 500.0`, `unit: EA`
- **예상 집계 결과 (Expected Takeoff)**:
  - 총 수량: **5 EA** (`is_provisional: true`)
  - 품목별: `LIGHT: 3 EA`, `OUTLET: 2 EA`
- **검수 조작 테스트 (Operations Expected)**:
  - `p0_lt_1` 마커 제외(EXCLUDE) 시: 총 수량 4 EA
  - `p0_lt_1` 마커 복원(RESTORE) 시: 총 수량 5 EA
  - 재조회(Reload) 시: 5개 마커 유지 및 페이지 인덱스 보존

#### 2) `pdf_b_rotated_cropbox.pdf`
- **페이지 구성**:
  - `page_index: 0`: 원본 MediaBox `[0, 0, 600, 800]`, CropBox `[50, 60, 550, 740]`, 회전 90°
  - 계산된 표시 크기: 폭 680.0 pt, 높이 500.0 pt
- **마커 정답셋**:
  - `rot_m1`: `item_code: LIGHT`, `x: 340.0`, `y: 250.0`, `unit: EA`
- **예상 집계 결과**:
  - 총 수량: **1 EA** (`LIGHT: 1 EA`, `is_provisional: true`)

#### 3) `pdf_b_scanned_mixed.pdf`
- **페이지 구성**:
  - `page_index: 0`: 800.0 × 600.0 pt (스캔 래스터 평면도 이미지 임베딩)
  - `page_index: 1`: 800.0 × 600.0 pt (순수 벡터 선/도형 전기 평면도)
- **마커 정답셋**:
  - Page 0 (래스터): `scan_m1` (`item_code: SWITCH`, `item_name: 스위치`, `x: 215.0`, `y: 215.0`, `unit: EA`)
  - Page 1 (벡터): `vec_m1` (`item_code: LIGHT`, `item_name: 조명`, `x: 325.0`, `y: 325.0`, `unit: EA`)
- **예상 집계 결과**:
  - 총 수량: **2 EA** (`SWITCH: 1 EA`, `LIGHT: 1 EA`, `is_provisional: true`)

---

## 3. 산출물 B: 공개 전기 도면 라이선스 검증 보고서 (Public License Audit)

향후 PR C(기호/문자 자동 감지 모델 파이프라인) 및 대형 실제 도면 성능 벤치마크를 위해 오픈소스 커뮤니티의 공개 전기 도면 후보군을 사전 검증하였습니다.

### 3.1 후보 1: `xundullah/W--KN-BD-residential-electrical-design`

| 항목 | 상세 내용 |
|---|---|
| **저장소 URL** | `https://github.com/xundullah/W--KN-BD-residential-electrical-design` |
| **적용 라이선스** | **MIT License** (저장소 최상위 `LICENSE` 파일 확인) |
| **도면 내용** | 방글라데시 주택 전기 설계 웹/HTML 기반 다이어그램 자료 (단선결선도, 분전반 스케줄, 조명/전열 배선 다이어그램) |
| **저작권 적법성** | 상업적 이용, 복제, 수정, 배포, 서브라이선스 부여가 법적으로 허용됨. 재배포 시 저작권 고지만 유지하면 됨 |
| **기술적 적합성** | 웹/벡터 기반 주택 전기 도면 다이어그램. 실제 엔지니어링 CAD 도면과는 레이아웃 차이가 있으나 외부 참고 다이어그램으로 분류 가능 |
| **한계 및 주의점** | 방글라데시/남아시아 규격 기반의 웹 다이어그램 자료로, KEC(한국전기설비규정/KS C IEC 60364) 심볼 및 실제 국내 아파트/건축 전기 도면과 규격 차이가 큼. PR C 자동 적산 학습 데이터로는 국내 KEC 표준 도면 데이터셋이 필수적임 |
| **보안 및 PII 검토** | 일반 샘플 다이어그램으로서 실 거주자 개인정보(PII), 기밀 계약 정보, 민감 주소 등이 포함되어 있지 않음 |
| **채택 의견** | **외부 참고용 후보로 분류** (CI/저장소 비대화 방지 및 KEC 표준과의 괴리로 인해 단위 테스트에는 저장소 내 합성 Fixture 사용) |

---

### 3.2 후보 2: Wikimedia Commons `Cvt.pdf`

| 항목 | 상세 내용 |
|---|---|
| **저장소 URL** | `https://commons.wikimedia.org/wiki/File:Cvt.pdf` |
| **적용 라이선스** | **Public Domain (CC-PD-Mark / CC0)** |
| **도면 내용** | 정전압 변압기(Constant-voltage transformer, CVT) 전기 회로 단면도 |
| **저작권 적법성** | 퍼블릭 도메인으로 저작권 제약 전무, 완전 자유 재사용 가능 |
| **기술적 적합성** | 순수 벡터 선 경로로 구성된 단일 페이지 회로도. 심플한 단일 페이지 렌더링 및 마커 좌표 변환 검증에 적합 |
| **한계 및 주의점** | 건축 평면도가 아닌 장비 회로도이므로 수동/자동 적산 대상 품목(조명/콘센트)이 없음 |
| **채택 의견** | **단순 회로도 렌더링 참고용으로 적합** |

---

## 4. 아키텍처 및 CI 데이터 정책 요약

1. **CI 결정론(Determinism) 보장**:
   - 외부 네트워크 의존성 및 업스트림 삭제 위험을 방지하기 위해 GitHub Actions CI 파이프라인(`CI/Python Lint, Type-Check & Test`)은 **100% 저장소 내 합성 Fixture(`fixtures/pdf/`)**만을 사용하여 실행됩니다.
2. **법적 리스크 원천 차단**:
   - `scripts/generate_pdf_fixtures.py`로 생성된 합성 fixture는 라이선스 분쟁 소지가 없는 자체 생성물(`SELF_GENERATED`)입니다.
   - 외부 라이브러리는 ADR-001에 따라 `pypdf`(BSD-3-Clause) 및 `pypdfium2`(Apache-2.0 / BSD-3-Clause)만 허용되며, AGPLv3 계열은 엄격히 차단됩니다.
3. **자동화 오라클 검증**:
   - `apps/api/tests/test_pdf_drawing.py::test_pdf_expected_catalog_oracle`이 매 커밋마다 `fixtures/pdf/expected.json`의 해시, 바이트, 수량, 단위(EA), 잠정(is_provisional) 여부, 검수 조작(제외/복원)을 100% 자동 검증합니다.
