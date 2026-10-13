"""Deterministic block→item aggregation (spike scope, A02-T002).

This is intentionally *not* the full review/export engine (A02-T003). It answers one
question reproducibly: given user mappings (PRD DEC-002) and a counting policy,
which SourceObjects are counted, which are excluded, and which are unresolved?

Counting policy defaults are conservative and **pending A05 (EAI-E001)**:
* only top-level INSERTs are counted (nested blocks are reported, not counted)
* objects on off/frozen layers are UNRESOLVED, never silently counted
* XREF / missing-definition references are UNRESOLVED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .schema import NormalizedDrawing, SourceObject, WarningCode

EXCLUDE = "EXCLUDE"


class Disposition(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    UNRESOLVED = "UNRESOLVED"
    UNMAPPED = "UNMAPPED"


class BlockMapping(BaseModel):
    """Map a block (by effective name, optionally restricted to a layer) to an item."""

    model_config = ConfigDict(extra="forbid")

    block_name: str
    layer: str | None = None
    item_code: str = Field(description=f"Provisional item code, or '{EXCLUDE}'")

    def matches(self, obj: SourceObject) -> bool:
        name = obj.effective_block_name or obj.block_name
        if name != self.block_name and obj.block_name != self.block_name:
            return False
        return self.layer is None or self.layer == obj.layer


@dataclass(frozen=True, slots=True)
class CountPolicy:
    count_nested: bool = False
    count_hidden_layers: bool = False


@dataclass(slots=True)
class ObjectResult:
    object_id: str
    disposition: Disposition
    item_code: str | None
    reason: str


@dataclass(slots=True)
class AggregateResult:
    counts: dict[str, int] = field(default_factory=dict)
    objects: list[ObjectResult] = field(default_factory=list)

    def ids(self, disposition: Disposition) -> list[str]:
        return [o.object_id for o in self.objects if o.disposition == disposition]


_BLOCKING = {
    WarningCode.XREF_UNRESOLVED: "외부참조는 집계하지 않음",
    WarningCode.MISSING_BLOCK_DEFINITION: "블록 정의 없음",
}


def aggregate(
    drawing: NormalizedDrawing,
    mappings: list[BlockMapping],
    policy: CountPolicy | None = None,
) -> AggregateResult:
    policy = policy or CountPolicy()
    result = AggregateResult()
    for obj in drawing.objects:
        if obj.entity_type != "INSERT":
            continue
        mapping = next((m for m in mappings if m.matches(obj)), None)
        if mapping is None:
            if obj.depth == 0:
                result.objects.append(
                    ObjectResult(obj.id, Disposition.UNMAPPED, None, "매핑되지 않은 블록")
                )
            continue
        if mapping.item_code == EXCLUDE:
            result.objects.append(ObjectResult(obj.id, Disposition.EXCLUDED, None, "매핑에서 제외"))
            continue
        reason = _unresolved_reason(obj, policy)
        if reason is not None:
            result.objects.append(
                ObjectResult(obj.id, Disposition.UNRESOLVED, mapping.item_code, reason)
            )
            continue
        result.objects.append(
            ObjectResult(obj.id, Disposition.INCLUDED, mapping.item_code, "CAD_BLOCK")
        )
        result.counts[mapping.item_code] = result.counts.get(mapping.item_code, 0) + 1
    result.counts = dict(sorted(result.counts.items()))
    return result


def _unresolved_reason(obj: SourceObject, policy: CountPolicy) -> str | None:
    for code, reason in _BLOCKING.items():
        if code in obj.warnings:
            return reason
    if obj.depth > 0 and not policy.count_nested:
        return "중첩 블록: 집계 기준 미확정(A05)"
    if not obj.visible and not policy.count_hidden_layers:
        return "꺼짐/동결 레이어"
    return None
