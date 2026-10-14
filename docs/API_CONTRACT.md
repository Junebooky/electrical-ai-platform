# FastAPI REST API Contract (v0.1.0)

- **문서 ID:** EAI-API-001
- **기준 포트:** `http://localhost:8000`
- **구현 모듈:** `apps/api/src/eai_api/app.py`

---

## 1. 헬스체크 및 다이렉트 파싱

### `GET /api/health`
서비스 상태 확인.
- **응답 (200 OK)**: `{"status": "ok", "version": "0.1.0"}`

### `POST /api/dxf/parse-direct`
프로젝트 생성 없이 DXF 파일 바이트를 전달받아 즉시 정규화된 `NormalizedDrawing` JSON을 반환합니다.
- **Content-Type:** `multipart/form-data` (file 필드)
- **오류 (400 Bad Request):**
  ```json
  {
    "error": "DXF_LOAD_ERROR",
    "code": "DWG_NOT_SUPPORTED",
    "message": "DWG 파일은 현재 지원하지 않습니다. ...",
    "detail": null
  }
  ```

---

## 2. 프로젝트 관리

### `POST /api/projects`
신규 로컬 프로젝트 생성.
- **Request Body:** `{"name": "프로젝트명", "description": "설명"}`
- **응답 (200 OK):** `ProjectMetadata` 객체

### `GET /api/projects`
로컬 프로젝트 목록 반환.
- **응답 (200 OK):** `ProjectMetadata[]`

### `GET /api/projects/{project_id}`
프로젝트 단건 조회.

---

## 3. 도면 및 매핑/검수 워크플로우

### `POST /api/projects/{project_id}/drawings`
DXF 도면 파일 업로드, 파싱 및 프로젝트 내 저장.
- **Query Params:** `revision` (기본값 `"REV0"`)
- **응답 (200 OK):**
  ```json
  {
    "project_id": "proj_123",
    "drawing_id": "d485412ca5955da2b",
    "filename": "floor_plan.dxf",
    "revision": "REV0",
    "objects_count": 18,
    "warnings_count": 0
  }
  ```

### `GET /api/projects/{project_id}/drawings/{drawing_id}`
정규화된 도면 전체 데이터(`NormalizedDrawing`) 반환.

### `GET /api/projects/{project_id}/drawings/{drawing_id}/mappings`
저장된 블록-품목 매핑 규칙 목록 반환.

### `PUT /api/projects/{project_id}/drawings/{drawing_id}/mappings`
블록-품목 매핑 규칙 목록 저장.
- **Request Body:**
  ```json
  [
    {
      "block_name": "LT-DL",
      "item_code": "LIGHT",
      "item_name": "다운라이트 LED 6인치",
      "specification": "15W",
      "unit": "EA"
    }
  ]
  ```

### `PUT /api/projects/{project_id}/drawings/{drawing_id}/reviews`
개별 객체 검수 결과(제외, 복원, 품목 재분류, 사유) 저장.
- **Request Body:**
  ```json
  [
    {
      "source_object_id": "d485412ca5955da2b:1F",
      "inclusion_status": "EXCLUDED",
      "mapped_item_code": "LIGHT",
      "review_status": "REVIEWED",
      "reason": "오탐 제외 (도면 표기 불일치)"
    }
  ]
  ```

### `POST /api/projects/{project_id}/drawings/{drawing_id}/manual-objects`
도면상 누락된 기구 수동 추가.
- **Request Body:**
  ```json
  {
    "id": "manual_1728860000",
    "drawing_id": "d485412ca5955da2b",
    "x": 2500.0,
    "y": 1500.0,
    "item_code": "LIGHT",
    "item_name": "다운라이트 LED",
    "unit": "EA",
    "note": "현장 추가 배선"
  }
  ```

---

## 4. 물량산출 및 내보내기

### `GET /api/projects/{project_id}/drawings/{drawing_id}/takeoff`
현재 집계 및 검수 상태가 반영된 물량산출표(Summary + Evidence) 반환.
- **응답 (200 OK):** `TakeoffResult`

### `GET /api/projects/{project_id}/drawings/{drawing_id}/export/csv?type=summary|evidence`
CSV 파일 스트리밍 다운로드 (UTF-8 with BOM 인코딩).

### `GET /api/projects/{project_id}/drawings/{drawing_id}/export/xlsx`
Excel 통합 파일 다운로드 (Summary와 Evidence 2개 시트 포함).
