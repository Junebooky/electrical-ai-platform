export type Point2 = [number, number];

export type WarningCode =
  | "UNITS_UNDEFINED"
  | "XREF_UNRESOLVED"
  | "ANONYMOUS_BLOCK"
  | "DYNAMIC_BLOCK"
  | "NESTED_BLOCK"
  | "NESTING_TOO_DEEP"
  | "CIRCULAR_BLOCK_REFERENCE"
  | "MINSERT_EXPANDED"
  | "HIDDEN_LAYER"
  | "MISSING_BLOCK_DEFINITION"
  | "PAPER_SPACE_IGNORED"
  | "UNSUPPORTED_ENTITY"
  | "EMPTY_MODELSPACE"
  | "AUDIT_FIXES_APPLIED"
  | "AUDIT_ERRORS"
  | "GEOMETRY_ERROR"
  | "PRIMITIVE_LIMIT_REACHED";

export interface DrawingWarning {
  code: WarningCode;
  severity: "INFO" | "WARNING" | "ERROR";
  message: string;
  object_ids: string[];
  details: Record<string, unknown>;
}

export interface BBox {
  min: Point2;
  max: Point2;
}

export interface LayerInfo {
  name: string;
  color: number;
  is_off: boolean;
  is_frozen: boolean;
  is_locked: boolean;
  object_count: number;
}

export interface BlockInfo {
  name: string;
  effective_name: string;
  is_xref: boolean;
  is_anonymous: boolean;
  is_dynamic_reference: boolean;
  base_point: [number, number, number];
  entity_count: number;
  top_level_insert_count: number;
  nested_insert_count: number;
}

export interface SourceObject {
  id: string;
  drawing_id: string;
  raw_handle: string;
  insert_path: string[];
  parent_id: string | null;
  depth: number;
  entity_type: string;
  layer: string;
  visible: boolean;
  block_name?: string | null;
  effective_block_name?: string | null;
  insert_point?: Point2 | null;
  rotation_deg?: number | null;
  scale?: [number, number, number] | null;
  bbox?: BBox | null;
  attributes: Record<string, string>;
  text?: string | null;
  geometric_length?: number | null;
  is_count_candidate: boolean;
  warnings: WarningCode[];
}

export interface Primitive {
  object_id: string;
  kind: "polyline" | "text";
  layer: string;
  color: string;
  points: Point2[];
  closed?: boolean;
  text?: string | null;
  height?: number | null;
  rotation_deg?: number | null;
}

export interface NormalizedDrawing {
  schema_version: string;
  drawing_id: string;
  source: {
    filename: string;
    sha256: string;
    size_bytes: number;
  };
  dxf: {
    version: string;
    release: string;
    encoding: string;
    insunits: number;
    units_name: string;
    units_defined: boolean;
    measurement: number | null;
  };
  extents: BBox | null;
  layers: LayerInfo[];
  blocks: BlockInfo[];
  objects: SourceObject[];
  primitives: Primitive[];
  warnings: DrawingWarning[];
  stats: {
    modelspace_entities: number;
    paperspace_entities: number;
    source_objects: number;
    primitives: number;
    primitive_points: number;
    parse_ms: number;
  };
}

export interface ItemMappingRule {
  block_name: string;
  layer?: string | null;
  item_code: string;
  item_name?: string | null;
  specification?: string | null;
  unit: string;
}

export interface EvidenceReviewItem {
  source_object_id: string;
  inclusion_status: "INCLUDED" | "EXCLUDED" | "MANUAL_ADDED";
  mapped_item_code?: string | null;
  review_status: "UNREVIEWED" | "REVIEWED" | "UNRESOLVED";
  reason: string;
  updated_at?: string;
}

export interface ManualObjectItem {
  id: string;
  drawing_id: string;
  x: number;
  y: number;
  item_code: string;
  item_name?: string | null;
  unit: string;
  note: string;
  created_at?: string;
}

export interface TakeoffSummaryRow {
  item_code: string;
  item_name: string;
  specification: string;
  unit: string;
  quantity: number;
  quantity_method: "CAD_BLOCK" | "MANUAL" | "MIXED";
  review_status: "UNREVIEWED" | "REVIEWED" | "UNRESOLVED";
  drawing_name: string;
  drawing_revision: string;
  notes: string;
}

export interface TakeoffEvidenceRow {
  source_object_id: string;
  drawing_id: string;
  parent_source_id: string | null;
  block_name: string;
  layer_name: string;
  entity_type: string;
  x: number;
  y: number;
  mapped_item_code: string;
  inclusion_status: "INCLUDED" | "EXCLUDED" | "MANUAL_ADDED";
  review_status: "UNREVIEWED" | "REVIEWED" | "UNRESOLVED";
  review_reason: string;
}

export interface TakeoffResult {
  drawing_id: string;
  drawing_name: string;
  drawing_revision: string;
  summary: TakeoffSummaryRow[];
  evidence: TakeoffEvidenceRow[];
  warnings_count: number;
}

export interface ProjectMetadata {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  drawing_count: number;
}
