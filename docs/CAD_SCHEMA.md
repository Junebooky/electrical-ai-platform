# CAD Normalization Schema Specification (v0.1.0)

- **문서 ID:** EAI-SCHEMA-001
- **버전:** 0.1.0
- **모듈:** `packages/cad_engine/src/cad_engine/schema.py`

---

## 1. 개요

`NormalizedDrawing`은 `ezdxf`를 통해 원본 DXF로부터 추출된 결정론적 정규화 데이터 구조입니다.
모든 좌표는 AutoCAD Model Space의 **WCS(월드 좌표계)** 기준 실수값입니다.

---

## 2. 최상위 구조 (`NormalizedDrawing`)

```json
{
  "schema_version": "0.1.0",
  "drawing_id": "d485412ca5955da2b",
  "source": {
    "filename": "basic_devices.dxf",
    "sha256": "...",
    "size_bytes": 10240
  },
  "dxf": {
    "version": "AC1032",
    "release": "R2018",
    "encoding": "utf-8",
    "insunits": 4,
    "units_name": "Millimeters",
    "units_defined": true,
    "measurement": 1
  },
  "extents": {
    "min": [0.0, 0.0],
    "max": [8000.0, 6000.0]
  },
  "layers": [ ... ],
  "blocks": [ ... ],
  "objects": [ ... ],
  "primitives": [ ... ],
  "warnings": [ ... ],
  "stats": { ... }
}
```

---

## 3. 세부 모델 명세

### 3.1 `SourceObject` (추적 가능한 CAD 객체)
물량산출 근거 행(Takeoff Evidence)과 1:1로 매핑되는 단위입니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | `string` | `{drawing_id}:{h0}/{h1}...` 형태의 재현 가능한 고유 식별자 |
| `raw_handle` | `string` | 엔티티 원본 DXF 핸들 (예: `"2A"`) |
| `insert_path` | `string[]` | 중첩 블록 참조 체인 핸들 배열 |
| `parent_id` | `string \| null` | 상위 참조 객체 ID |
| `depth` | `int` | 중첩 깊이 (0: 모델 스페이스 최상위) |
| `entity_type` | `string` | `"INSERT"`, `"LINE"`, `"LWPOLYLINE"`, `"TEXT"`, `"MTEXT"` 등 |
| `layer` | `string` | 엔티티가 속한 실효 레이어명 |
| `visible` | `bool` | 레이어 꺼짐/동결 상태 반영 가시성 |
| `block_name` | `string?` | 블록 정의 이름 |
| `effective_block_name` | `string?` | 동적 블록(`*U`)의 원본 블록 추정명 |
| `insert_point` | `[x, y]?` | WCS 삽입 좌표 |
| `rotation_deg` | `float?` | 회전각 (도, 도면 기준) |
| `scale` | `[sx, sy, sz]?` | 스케일 배율 |
| `bbox` | `{min: [x, y], max: [x, y]}?` | 객체 바운딩 박스 |
| `attributes` | `Record<string, string>` | 블록 속성 태그/값 (예: `{"CIRCUIT": "P-1"}`) |
| `is_count_candidate` | `bool` | 집계 대상 후보 여부 (최상위 INSERT 및 비XREF) |
| `warnings` | `WarningCode[]` | 객체 단위 경고 배열 |

### 3.2 `Primitive` (화면 렌더링용 기하 데이터)
뷰어(SVG/Canvas)에서 선과 텍스트를 빠르게 그리기 위한 경량 기하 요소입니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `object_id` | `string` | 소유한 `SourceObject`의 ID |
| `kind` | `"polyline" \| "text"` | 프리미티브 유형 |
| `layer` | `string` | 레이어명 |
| `color` | `string` | Hex 색상 코드 (예: `"#38bdf8"`) |
| `points` | `[x, y][]` | 정점 좌표 배열 (곡선은 허용오차 내에서 평탄화됨) |
| `closed` | `bool` | 닫힌 도형 여부 |
| `text` | `string?` | 텍스트 내용 |
| `height` | `float?` | 텍스트 높이 |
| `rotation_deg` | `float?` | 텍스트 회전각 |

### 3.3 `DrawingWarning` (경고 및 오류)
불확실성을 숨기지 않고 사용자에게 보고하기 위한 구조체입니다.

- `UNITS_UNDEFINED`: `$INSUNITS` 누락(0)
- `XREF_UNRESOLVED`: 외부참조 도면 미포함
- `ANONYMOUS_BLOCK`: `*U` 익명 블록
- `DYNAMIC_BLOCK`: 동적 블록 참조
- `NESTED_BLOCK`: 중첩 블록 발견
- `HIDDEN_LAYER`: 꺼짐/동결 레이어 상의 객체
- `TRUNCATED_FILE`: 파일 전송 중 잘림 손상
