from dataclasses import dataclass, field
from typing import Any

from app.services.field_registry import FieldRegistry
from app.services.field_registry import get_field_registry
from app.services.field_registry import registry_with_lead_detail
from app.services.lead_detail_context import iter_leaf_entries


SOURCE_PRIORITY = {
    "derived": 10,
    "legacy": 20,
    "graphql": 30,
    "agent_confirmed": 40,
    "realtime": 50,
}


@dataclass
class FieldValue:
    field_id: str
    value: Any
    source: str
    status: str = "filled"
    raw_values: list[dict[str, Any]] = field(default_factory=list)
    resolved_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "value": self.value,
            "source": self.source,
            "status": self.status,
            "raw_values": list(self.raw_values),
            "resolved_from": self.resolved_from,
        }


def resolve_graphql_facts(
    facts: dict[str, Any] | None,
    *,
    registry: FieldRegistry | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(facts, dict):
        return {}

    active_registry = registry or registry_with_lead_detail(facts)
    resolved: dict[str, dict[str, Any]] = {}
    for path, value in iter_leaf_entries(facts, include_blank=True):
        field_id = active_registry.resolve(path)
        if not field_id:
            continue
        resolved = merge_field_values(
            resolved,
            {
                field_id: FieldValue(
                    field_id=field_id,
                    value=value,
                    source="graphql",
                    status=_status_for_value(value),
                    raw_values=[{"key": path, "value": value, "source": "graphql"}],
                    resolved_from=path,
                ).to_dict()
            },
        )
    return resolved


def resolve_extracted_fields(
    fields: dict[str, Any] | None,
    *,
    registry: FieldRegistry | None = None,
    source: str = "realtime",
) -> dict[str, dict[str, Any]]:
    if not isinstance(fields, dict):
        return {}

    active_registry = registry or get_field_registry()
    resolved: dict[str, dict[str, Any]] = {}
    for raw_key, value in fields.items():
        field_id = active_registry.resolve(str(raw_key))
        if not field_id:
            continue
        resolved = merge_field_values(
            resolved,
            {
                field_id: FieldValue(
                    field_id=field_id,
                    value=value,
                    source=source,
                    status=_status_for_value(value),
                    raw_values=[{"key": str(raw_key), "value": value, "source": source}],
                    resolved_from=str(raw_key),
                ).to_dict()
            },
        )
    return resolved


def merge_field_values(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    merged = {
        field_id: _coerce_field_value(field_id, value)
        for field_id, value in (existing or {}).items()
    }

    for field_id, raw_value in (incoming or {}).items():
        incoming_value = _coerce_field_value(field_id, raw_value)
        current = merged.get(field_id)
        if current is None:
            merged[field_id] = incoming_value
            continue

        current["raw_values"] = [
            *current.get("raw_values", []),
            *incoming_value.get("raw_values", []),
        ]
        if _should_replace_value(current, incoming_value):
            current.update(
                {
                    "value": incoming_value.get("value"),
                    "source": incoming_value.get("source"),
                    "status": incoming_value.get("status"),
                    "resolved_from": incoming_value.get("resolved_from"),
                }
            )
    return merged


def build_resolved_field_state(
    *,
    existing: dict[str, Any] | None = None,
    lead_detail: dict[str, Any] | None = None,
    lead_facts: dict[str, Any] | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    registry = registry_with_lead_detail(lead_detail or lead_facts)
    field_state = merge_field_values({}, existing or {})
    field_state = merge_field_values(
        field_state,
        resolve_graphql_facts(lead_facts, registry=registry),
    )
    field_state = merge_field_values(
        field_state,
        resolve_graphql_facts(lead_detail, registry=registry),
    )
    field_state = merge_field_values(
        field_state,
        resolve_extracted_fields(extracted_fields, registry=registry, source="realtime"),
    )
    return field_state


def field_values_as_simple_dict(field_state: dict[str, Any] | None) -> dict[str, Any]:
    simple: dict[str, Any] = {}
    for field_id, raw_value in (field_state or {}).items():
        value = _coerce_field_value(field_id, raw_value)
        if value.get("status") == "filled":
            simple[field_id] = value.get("value")
    return simple


def _coerce_field_value(field_id: str, raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict) and "value" in raw_value:
        value = raw_value.get("value")
        return {
            "field_id": str(raw_value.get("field_id") or field_id),
            "value": value,
            "source": str(raw_value.get("source") or "legacy"),
            "status": str(raw_value.get("status") or _status_for_value(value)),
            "raw_values": list(raw_value.get("raw_values") or []),
            "resolved_from": str(raw_value.get("resolved_from") or field_id),
        }
    return FieldValue(
        field_id=field_id,
        value=raw_value,
        source="legacy",
        status=_status_for_value(raw_value),
        raw_values=[{"key": field_id, "value": raw_value, "source": "legacy"}],
        resolved_from=field_id,
    ).to_dict()


def _should_replace_value(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    if incoming.get("status") != "filled":
        return False
    if current.get("status") != "filled":
        return True
    current_priority = SOURCE_PRIORITY.get(str(current.get("source")), 0)
    incoming_priority = SOURCE_PRIORITY.get(str(incoming.get("source")), 0)
    return incoming_priority >= current_priority


def _status_for_value(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, str) and not value.strip():
        return "missing"
    if isinstance(value, (list, dict)) and not value:
        return "missing"
    return "filled"
