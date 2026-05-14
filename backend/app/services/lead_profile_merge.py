from copy import deepcopy
from typing import Any

from app.services.field_registry import get_field_registry
from app.services.field_resolver import build_resolved_field_state
from app.services.lead_detail_context import build_lead_context
from app.services.lead_detail_context import iter_leaf_entries
from app.services.lead_detail_context import normalize_lead_detail_payload
from app.services.schema_normalizer import normalize_extracted_fields
from app.services.value_mapping import apply_value_mappings_to_facts
from app.services.workflow_state import compute_workflow_state


def build_lead_profile(
    *,
    lead_id: Any = None,
    lead_detail: Any = None,
    lead_facts: Any = None,
    lead_dre_documents: Any = None,
    lead_dre_document_error: str | None = None,
    lead_document_status: Any = None,
) -> dict[str, Any]:
    detail = deepcopy(normalize_lead_detail_payload(lead_detail) or {})
    raw_facts = _build_facts(detail)
    if isinstance(lead_facts, dict):
        raw_facts = {**lead_facts, **raw_facts}
    display_facts, mapping_metadata = apply_value_mappings_to_facts(raw_facts)
    missing_fields = _build_missing_fields(detail)
    context = build_lead_context(
        lead_id=lead_id,
        lead_detail=detail,
        lead_dre_documents=lead_dre_documents,
        lead_dre_document_error=lead_dre_document_error,
        lead_document_status=lead_document_status,
        lead_facts=display_facts,
    )
    context["facts"] = display_facts
    stage_state = _build_stage_state(detail, display_facts)
    profile = _build_universal_profile(
        lead_id=context.get("lead_id") or lead_id,
        detail=detail,
        raw_facts=raw_facts,
        display_facts=display_facts,
        missing_fields=missing_fields,
        context=context,
        stage_state=stage_state,
        mapping_metadata=mapping_metadata,
    )
    return {
        "lead_id": context.get("lead_id") or lead_id,
        "lead_detail": detail,
        "lead_facts": display_facts,
        "lead_raw_facts": raw_facts,
        "lead_missing_fields": missing_fields,
        "lead_context": context,
        "profile": profile,
    }


def merge_extracted_fields_into_lead(
    *,
    lead_id: Any = None,
    lead_detail: Any = None,
    lead_facts: Any = None,
    extracted_fields: dict[str, Any] | None = None,
    lead_dre_documents: Any = None,
    lead_dre_document_error: str | None = None,
    lead_document_status: Any = None,
) -> dict[str, Any]:
    detail = deepcopy(normalize_lead_detail_payload(lead_detail) or {})
    normalized_fields = normalize_extracted_fields(extracted_fields or {})
    registry = get_field_registry()

    for field_id, value in normalized_fields.items():
        definition = registry.definition(field_id)
        if not definition or not definition.graphql_paths:
            continue
        _set_first_applicable_path(detail, definition.graphql_paths, value)

    profile = build_lead_profile(
        lead_id=lead_id,
        lead_detail=detail,
        lead_facts=lead_facts,
        lead_dre_documents=lead_dre_documents,
        lead_dre_document_error=lead_dre_document_error,
        lead_document_status=lead_document_status,
    )
    return {
        **profile,
        "extracted_fields": normalized_fields,
    }


def _build_facts(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        path: value
        for path, value in iter_leaf_entries(detail, include_blank=True)
        if path
    }


def _build_universal_profile(
    *,
    lead_id: Any,
    detail: dict[str, Any],
    raw_facts: dict[str, Any],
    display_facts: dict[str, Any],
    missing_fields: list[dict[str, str]],
    context: dict[str, Any],
    stage_state: dict[str, Any],
    mapping_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "lead_id": lead_id,
        "raw": detail,
        "raw_facts": raw_facts,
        "display": display_facts,
        "facts": display_facts,
        "missing_fields": missing_fields,
        "stage_state": stage_state,
        "document_status": context.get("document_status") or {},
        "metadata": {
            "value_mappings_applied": bool(mapping_metadata),
            "value_mappings": mapping_metadata,
        },
    }


def _build_stage_state(detail: dict[str, Any], display_facts: dict[str, Any]) -> dict[str, Any]:
    field_state = build_resolved_field_state(
        lead_detail=detail,
        lead_facts=display_facts,
    )
    workflow = compute_workflow_state(field_state)
    return {
        "active_stage": workflow.get("active_category"),
        "category_state": workflow.get("category_state") or {},
        "overall_status": workflow.get("overall_status"),
    }


def _build_missing_fields(detail: dict[str, Any], max_fields: int = 500) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for path, value in iter_leaf_entries(detail, include_blank=True):
        if len(missing) >= max_fields or not path or path.endswith("__typename"):
            continue
        reason = ""
        if value is None:
            reason = "null"
        elif isinstance(value, str) and not value.strip():
            reason = "empty_string"
        elif isinstance(value, (list, dict)) and not value:
            reason = "empty_collection"
        if reason:
            missing.append(
                {
                    "path": path,
                    "label": _label_for_path(path),
                    "reason": reason,
                }
            )
    return missing


def _set_first_applicable_path(detail: dict[str, Any], paths: list[str], value: Any) -> None:
    ranked_paths = sorted(paths, key=_path_rank)
    existing_paths = set(_build_facts(detail))
    for path in ranked_paths:
        adapted_path = _adapt_path_to_detail(detail, path)
        if adapted_path in existing_paths:
            _set_path_value(detail, adapted_path, value)
            return
    if ranked_paths:
        _set_path_value(detail, _adapt_path_to_detail(detail, ranked_paths[0]), value)


def _adapt_path_to_detail(detail: dict[str, Any], path: str) -> str:
    parts = _path_parts(path)
    if not parts:
        return path
    root = parts[0]
    if root in {"co_applicant", "coapplicant"} and isinstance(detail.get("co_applicant"), list):
        rest = parts[2:] if root == "co_applicant" and len(parts) > 1 and parts[1].isdigit() else parts[1:]
        return "co_applicant[0]" + (f".{'.'.join(rest)}" if rest else "")
    return path


def _set_path_value(detail: dict[str, Any], path: str, value: Any) -> None:
    parts = _path_parts(path)
    if not parts:
        return
    current: Any = detail
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(current, list):
            item_index = int(part) if part.isdigit() else 0
            while len(current) <= item_index:
                current.append({})
            current = current[item_index]
            continue
        if next_part.isdigit():
            current = current.setdefault(part, [])
        else:
            current = current.setdefault(part, {})
    leaf = parts[-1]
    if isinstance(current, list):
        item_index = int(leaf) if leaf.isdigit() else 0
        while len(current) <= item_index:
            current.append(None)
        current[item_index] = value
    else:
        current[leaf] = value


def _path_parts(path: str) -> list[str]:
    normalized = str(path or "").replace("[", ".").replace("]", "")
    return [part for part in normalized.split(".") if part]


def _path_rank(path: str) -> tuple[int, int, str]:
    root = str(path).split(".", 1)[0]
    root_rank = {
        "customer": 0,
        "co_applicant": 0,
        "lead_details": 0,
        "lead": 1,
        "rmdetails": 1,
        "lead_breadcrumb": 1,
        "status_info": 1,
        "sub_status_info": 1,
        "lead_bt_info": 1,
    }.get(root, 5)
    finex_rank = 4 if root.startswith("finex_") else 0
    return (root_rank + finex_rank, len(path), path)


def _label_for_path(path: str) -> str:
    leaf = str(path).split(".")[-1]
    return leaf.replace("_", " ").strip().title()
