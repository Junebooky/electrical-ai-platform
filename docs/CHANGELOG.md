# Changelog

All notable changes to the Electrical AI Platform are documented here.

## [0.1.0] - 2026-10-13

### Added
- **Monorepo & Toolchain**: uv workspace with `packages/cad_engine`, `apps/api`, `apps/web`.
- **cad_engine**:
  - Deterministic DXF loader with sniffing, DWG rejection, and truncated file defense.
  - Normalization engine parsing Model Space entities into `SourceObject` and `Primitive` with WCS coordinates.
  - Chained matrix transformations for rotated, scaled, mirrored, and nested blocks.
  - Dynamic block effective name resolution via XData (`AcDbBlockRepBTag`).
  - MINSERT expansion into discrete objects.
  - Aggregation engine evaluating user mappings and counting policies.
  - CLI `eai-cad parse` for offline inspection.
  - 14 synthetic DXF fixtures with independent ground-truth expectations.
- **apps/api**:
  - FastAPI application providing upload, direct parse, project management, mapping, reviews, and manual objects.
  - Local file-based JSON persistence.
  - CSV export with `utf-8-sig` encoding (summary and evidence).
  - Multi-sheet XLSX export using `openpyxl`.
- **apps/web**:
  - Next.js 16 + React 19 + Tailwind CSS workspace dashboard.
  - 2D SVG CAD viewer supporting smooth zoom, pan, layer toggles, and click selection.
  - Interactive block-to-item mapping panel.
  - Takeoff table with bidirectional object highlighting.
  - Object review drawer (exclude false positives, restore, update mappings).
  - Manual object placement tool on canvas.
  - Warning banner showing drawing issues.
- **Domain & Takeoff Safety (DEC-010 ~ DEC-014 / ADR-005)**:
  - Fail-closed collision detection on `(item_code, unit, specification)` mappings.
  - Review override defense rejecting `INCLUDED` on dynamic/anonymous blocks (`QA-09-C`).
  - Strict withholding of nested hierarchy (both parents and children) from CAD auto count (`QA-09-D`), with verified installations tracked via manual objects (`MIXED` takeoff).

