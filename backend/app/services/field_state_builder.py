from typing import Any

from app.services.field_resolver import build_resolved_field_state


def build_field_state(
    *,
    existing: dict[str, Any] | None = None,
    lead_detail: dict[str, Any] | None = None,
    lead_facts: dict[str, Any] | None = None,
    extracted_fields: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return build_resolved_field_state(
        existing=existing,
        lead_detail=lead_detail,
        lead_facts=lead_facts,
        extracted_fields=extracted_fields,
    )
