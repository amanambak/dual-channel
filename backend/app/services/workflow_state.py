import re
from typing import Any

from app.services.field_resolver import field_values_as_simple_dict
from app.services.workflow_schema import WorkflowSchema
from app.services.workflow_schema import load_workflow_schema


TRUTHY_VALUES = {"1", "true", "yes", "y", "haan", "han", "ha", "available", "present"}
FALSY_VALUES = {"0", "false", "no", "n", "nahi", "nahin", "none", "not"}


def compute_workflow_state(
    field_state: dict[str, Any],
    active_category: str | None = None,
    *,
    schema: WorkflowSchema | None = None,
) -> dict[str, Any]:
    workflow_schema = schema or load_workflow_schema()
    values = field_values_as_simple_dict(field_state)
    category_state: dict[str, Any] = {}

    for category in workflow_schema.categories:
        category_id = str(category.get("id") or "")
        if not category_id:
            continue
        state = _compute_category_state(category, values)
        category_state[category_id] = state

    return {
        "active_category": active_category,
        "category_state": category_state,
        "all_complete": all(
            state.get("status") == "complete" for state in category_state.values()
        ),
    }


def _compute_category_state(category: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    category_id = str(category.get("id") or "")
    base_required = _as_string_list(category.get("base_required_fields"))
    active_branches: list[dict[str, Any]] = []
    branch_required: list[str] = []

    for branch in _as_list(category.get("branches")):
        if not isinstance(branch, dict):
            continue
        if condition_matches(branch.get("when"), values):
            active_branches.append(
                {
                    "id": branch.get("id"),
                    "label": branch.get("label") or branch.get("id"),
                    "required_fields": _as_string_list(branch.get("required_fields")),
                }
            )
            branch_required.extend(_as_string_list(branch.get("required_fields")))

    required_fields = _unique([*base_required, *branch_required])
    filled_fields = [field for field in required_fields if _is_filled(values.get(field))]
    missing_fields = [field for field in required_fields if field not in filled_fields]

    return {
        "category": category_id,
        "label": category.get("label") or category_id,
        "status": "complete" if not missing_fields else "in_progress",
        "active_sections": _active_sections(category, required_fields),
        "active_branches": [branch["id"] for branch in active_branches if branch.get("id")],
        "active_branch_details": active_branches,
        "filled_fields": filled_fields,
        "missing_fields": missing_fields,
        "base_missing_fields": [field for field in base_required if field in missing_fields],
        "branch_missing_fields": [field for field in branch_required if field in missing_fields],
        "next_field": select_next_missing_field(category, missing_fields, active_branches),
    }


def select_next_missing_field(
    category: dict[str, Any],
    missing_fields: list[str],
    active_branches: list[dict[str, Any]] | None = None,
) -> str | None:
    missing_set = set(missing_fields)
    for branch in active_branches or []:
        for field in branch.get("required_fields") or []:
            if field in missing_set:
                return str(field)

    for field in _as_string_list(category.get("field_priority")):
        if field in missing_set:
            return field

    for field in _as_string_list(category.get("base_required_fields")):
        if field in missing_set:
            return field

    return missing_fields[0] if missing_fields else None


def condition_matches(condition: Any, values: dict[str, Any]) -> bool:
    if not isinstance(condition, dict):
        return False
    if "all" in condition:
        return all(condition_matches(item, values) for item in _as_list(condition.get("all")))
    if "any" in condition:
        return any(condition_matches(item, values) for item in _as_list(condition.get("any")))

    field = str(condition.get("field") or "")
    operator = str(condition.get("operator") or "equals").lower()
    value = values.get(field)
    expected = condition.get("value")

    if operator == "exists":
        return _is_filled(value)
    if operator == "not_exists":
        return not _is_filled(value)
    if operator == "truthy":
        return _is_truthy(value)
    if operator == "falsy":
        return _is_falsy(value)
    if operator in {"equals", "eq"}:
        return _normalized(value) == _normalized(expected)
    if operator in {"in", "equals_any"}:
        return _normalized(value) in {_normalized(item) for item in _as_list(expected)}
    if operator == "matches_any":
        normalized_value = _normalized(value)
        return any(_normalized(item) in normalized_value for item in _as_list(expected))
    return False


def _active_sections(category: dict[str, Any], required_fields: list[str]) -> list[str]:
    required = set(required_fields)
    sections: list[str] = []
    for section in _as_list(category.get("sections")):
        if not isinstance(section, dict):
            continue
        fields = set(_as_string_list(section.get("fields")))
        if required & fields and section.get("id"):
            sections.append(str(section["id"]))
    return sections


def _is_truthy(value: Any) -> bool:
    return _normalized(value) in TRUTHY_VALUES


def _is_falsy(value: Any) -> bool:
    normalized = _normalized(value)
    return normalized in FALSY_VALUES or normalized == ""


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _normalized(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _as_string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
