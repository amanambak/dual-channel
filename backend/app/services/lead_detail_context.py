import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.text_utils import collapse_text, normalize_text


logger = logging.getLogger(__name__)

PRIORITY_FIELDS_PATH = Path(__file__).resolve().parents[3] / "priority_fields.json"
_PRIORITY_FIELDS_CACHE: tuple[float | None, list[str]] | None = None
_PRIORITY_SET_CACHE: tuple[tuple[str, ...], set[str]] | None = None
FIELD_FILTER_CONFIDENCE_THRESHOLD = 0.7
MISSING_FIELDS_NONE_REPLY = "Missing fields: None found in loaded lead data."


SCOPE_MAP = {
    "property": ["property_details"],
    "income": ["salary", "income"],
    "credit": ["cibil", "credit"],
    "loan": ["loan", "emi"],
}


@dataclass(frozen=True)
class LeadFieldSpec:
    path: str
    groups: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    priority: bool = False
    section: str = ""


def load_priority_field_paths(path: Path = PRIORITY_FIELDS_PATH) -> list[str]:
    global _PRIORITY_FIELDS_CACHE

    try:
        stat = path.stat()
    except OSError:
        _PRIORITY_FIELDS_CACHE = (None, [])
        return []

    cached_mtime = _PRIORITY_FIELDS_CACHE[0] if _PRIORITY_FIELDS_CACHE else None
    if _PRIORITY_FIELDS_CACHE is not None and cached_mtime == stat.st_mtime:
        return list(_PRIORITY_FIELDS_CACHE[1])

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = []

    paths = [
        str(item).strip()
        for item in payload
        if str(item).strip() and not str(item).strip().endswith("__typename")
    ] if isinstance(payload, list) else []
    unique_paths = list(dict.fromkeys(paths))
    _PRIORITY_FIELDS_CACHE = (stat.st_mtime, unique_paths)
    return list(unique_paths)


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _missing_reason(value: Any, *, exists: bool = True) -> str:
    if not exists:
        return "not loaded"
    if value is None:
        return "null"
    if isinstance(value, str) and value.strip() == "":
        return "empty string"
    if isinstance(value, list) and not value:
        return "empty array"
    if isinstance(value, dict) and not value:
        return "empty object"
    return "missing"


IMPORTANT_PATHS = {
    "id",
    "ref_lead_id",
    "loan_type",
    "loan_sub_type",
    "loan_sub_type_name",
    "kyc_status",
    "followup_date",
    "followup_type",
    "followup_status",
    "partner_name",
    "partner_mobile",
    "partner_email",
    "customer.first_name",
    "customer.last_name",
    "customer.mobile",
    "customer.email",
    "customer.marital_status",
    "customer.pancard_no",
    "lead_details.loan_amount",
    "lead_details.monthly_salary",
    "lead_details.cibil_score",
    "lead_details.property_city",
    "lead_details.property_state",
    "lead_details.is_property_identified",
    "lead_details.bank.banklang.bank_name",
}


OFFER_PATH_ALIASES = {
    "lead_details.lead_id": ["lead_details.lead_id", "id", "ref_lead_id"],
    "lead_details.is_property_decided": [
        "lead_details.is_property_decided",
        "lead_details.is_property_identified",
        "property_details.is_property_identified",
    ],
    "property_details.is_property_identified": [
        "property_details.is_property_identified",
        "lead_details.is_property_identified",
        "lead_details.is_property_decided",
    ],
    "property_details.property_city": ["property_details.property_city", "lead_details.property_city"],
    "property_details.property_state": ["property_details.property_state", "lead_details.property_state"],
    "property_details.expected_market_value": [
        "property_details.expected_market_value",
        "lead_details.expected_market_value",
        "lead_details.expected_property_value",
        "lead_details.property_value",
    ],
    "property_details.registration_value": [
        "property_details.registration_value",
        "lead_details.registration_value",
    ],
    "property_details.property_type": ["property_details.property_type", "lead_details.property_type"],
    "property_details.property_sub_type": [
        "property_details.property_sub_type",
        "lead_details.property_sub_type",
    ],
    "property_details.agreement_type": ["property_details.agreement_type", "lead_details.agreement_type"],
    "property_details.builder_id": ["property_details.builder_id", "lead_details.builder_id"],
    "property_details.project_id": ["property_details.project_id", "lead_details.project_id"],
    "property_details.check_oc_cc": ["property_details.check_oc_cc", "lead_details.check_oc_cc"],
    "property_details.ready_for_registration": [
        "property_details.ready_for_registration",
        "lead_details.ready_for_registration",
    ],
}


LEAD_FIELD_CATALOG = (
    LeadFieldSpec(
        "lead_details.prev_emi_amount",
        groups=("existing_loan_bt",),
        aliases=("previous emi", "old emi", "bt emi", "existing loan emi"),
        priority=True,
        section="lead_details",
    ),
    LeadFieldSpec(
        "lead_details.prev_loan_amount",
        groups=("existing_loan_bt",),
        aliases=("previous loan amount", "old loan amount", "bt loan amount", "existing loan amount"),
        priority=True,
        section="lead_details",
    ),
    LeadFieldSpec(
        "lead_details.prev_loan_start_date",
        groups=("existing_loan_bt",),
        aliases=("previous loan start date", "old loan start date", "bt start date", "existing loan start date"),
        priority=True,
        section="lead_details",
    ),
    LeadFieldSpec(
        "lead_details.prev_tenure",
        groups=("existing_loan_bt",),
        aliases=("previous tenure", "old loan tenure", "bt tenure", "existing loan tenure"),
        priority=True,
        section="lead_details",
    ),
    LeadFieldSpec(
        "lead_details.prev_current_roi",
        groups=("existing_loan_bt",),
        aliases=("previous roi", "old loan roi", "bt roi", "existing loan roi", "current roi"),
        priority=True,
        section="lead_details",
    ),
    LeadFieldSpec(
        "lead_details.remaining_loan_amount",
        groups=("existing_loan_bt",),
        aliases=("remaining loan", "remaining loan amount", "outstanding loan", "bt outstanding"),
        priority=True,
        section="lead_details",
    ),
)


QUERY_STOPWORDS = {
    "about",
    "are",
    "batao",
    "btao",
    "details",
    "detail",
    "field",
    "fields",
    "give",
    "hai",
    "hain",
    "high",
    "highest",
    "is",
    "all",
    "ka",
    "kaun",
    "kaunsa",
    "kaunse",
    "kaunsi",
    "kar",
    "kare",
    "karen",
    "karo",
    "ke",
    "ki",
    "kon",
    "konsa",
    "konse",
    "konsi",
    "kya",
    "list",
    "do",
    "me",
    "mei",
    "mein",
    "missing",
    "pending",
    "priority",
    "se",
    "si",
    "top",
    "show",
    "tell",
    "the",
    "what",
    "which",
}


def iter_leaf_entries(
    value: Any,
    prefix: str = "",
    *,
    include_blank: bool = False,
) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_leaf_entries(
                nested_value,
                prefix=nested_prefix,
                include_blank=include_blank,
            )
        return

    if isinstance(value, list):
        for index, nested_value in enumerate(value[:25]):
            nested_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from iter_leaf_entries(
                nested_value,
                prefix=nested_prefix,
                include_blank=include_blank,
            )
        return

    if include_blank or value not in (None, ""):
        yield prefix, value


def _format_value(value: Any, *, max_chars: int = 500) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "Missing"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > max_chars:
        return f"{text[: max_chars - 3]}..."
    return text


def _format_label(path: str) -> str:
    leaf = path.split(".")[-1]
    leaf = re.sub(r"\[\d+\]", "", leaf)
    return leaf.replace("_", " ").strip().capitalize()


def _format_group_label(path: str) -> str:
    label = re.sub(r"\[\d+\]", "", path).strip("_")
    label = re.sub(r"_id$", "", label)
    normalized = label.replace("_", " ").strip()
    acronym = normalized.replace(" ", "").upper()
    if acronym in {"RM", "ABM", "SBM", "NH", "SH"}:
        return acronym
    return normalized.title()


def _format_section_heading(prefix: str) -> str:
    label = _format_label(prefix)
    if label.lower().endswith("details"):
        return f"{label}:"
    return f"{label} details:"


def _path_value(lead_detail: dict[str, Any], path: str) -> tuple[bool, Any]:
    if path in lead_detail:
        return True, lead_detail.get(path)

    indexed_path = f"[0].{path}"
    if indexed_path in lead_detail:
        return True, lead_detail.get(indexed_path)

    current: Any = lead_detail
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            break
        current = current[part]
    else:
        return True, current

    if isinstance(lead_detail, list) and lead_detail:
        first_item = lead_detail[0]
        if isinstance(first_item, dict):
            return _path_value(first_item, path)

    return False, None


def _equivalent_offer_paths(path: str) -> list[str]:
    candidates = list(OFFER_PATH_ALIASES.get(path, [path]))
    if path.startswith("property_details."):
        candidates.append("lead_details." + path.split(".", 1)[1])
    if path.startswith("lead_details."):
        candidates.append(path.split(".", 1)[1])

    expanded_candidates: list[str] = []
    for candidate in candidates:
        expanded_candidates.append(candidate)
        if not candidate.startswith("[0]."):
            expanded_candidates.append(f"[0].{candidate}")
    return list(dict.fromkeys(candidate for candidate in expanded_candidates if candidate))


def _resolve_offer_path_value(lead_detail: dict[str, Any], path: str) -> tuple[bool, Any, str]:
    for candidate in _equivalent_offer_paths(path):
        exists, value = _path_value(lead_detail, candidate)
        if exists:
            return True, value, candidate
    return False, None, path


def _equivalent_missing_item(
    existing_missing: dict[str, dict[str, Any]],
    path: str,
) -> dict[str, Any] | None:
    for candidate in _equivalent_offer_paths(path):
        if candidate in existing_missing:
            return existing_missing[candidate]
    return None


def _all_values(lead_detail: dict[str, Any]) -> dict[str, Any]:
    return dict(iter_leaf_entries(lead_detail, include_blank=True))


def build_lead_field_index(lead_detail: dict[str, Any] | None, *, max_fields: int = 700) -> list[dict[str, str]]:
    if not lead_detail:
        return []

    fields: list[dict[str, str]] = []
    for path, value in iter_leaf_entries(lead_detail, include_blank=True):
        if path.endswith(".__typename") or path.endswith("__typename"):
            continue
        fields.append(
            {
                "path": path,
                "label": _format_label(path),
                "status": "missing" if _format_value(value) == "Missing" else "available",
            }
        )
        if len(fields) >= max_fields:
            break
    return fields


def discover_lead_field_paths(
    lead_detail: dict[str, Any] | None,
    lead_missing_fields: list[dict[str, Any]] | None = None,
) -> set[str]:
    paths = {
        path
        for path, _value in iter_leaf_entries(lead_detail or {}, include_blank=True)
        if path and not path.endswith(".__typename") and not path.endswith("__typename")
    }
    paths.update(load_priority_field_paths())
    paths.update(spec.path for spec in LEAD_FIELD_CATALOG)
    paths.update(
        str(item.get("path") or "").strip()
        for item in (lead_missing_fields or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    )
    return {path for path in paths if path}


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, confidence))


def _resolve_valid_field_path(field: Any, all_fields: set[str]) -> str | None:
    path = str(field or "").strip().strip(".")
    if not path:
        return None
    if path in all_fields:
        return path
    for candidate in _equivalent_offer_paths(path):
        if candidate in all_fields:
            return candidate
    return None


def sanitize_lead_query_plan(plan: dict | None, all_fields: set[str]) -> dict | None:
    if not isinstance(plan, dict):
        return plan

    action = str(plan.get("action") or "fallback").strip().lower()
    confidence = _coerce_confidence(plan.get("confidence", 1.0))
    raw_fields = plan.get("fields")
    if not isinstance(raw_fields, list):
        raw_fields = plan.get("paths") if isinstance(plan.get("paths"), list) else []

    fields = list(
        dict.fromkeys(
            resolved
            for raw_field in raw_fields
            if (resolved := _resolve_valid_field_path(raw_field, all_fields))
        )
    )
    if confidence < FIELD_FILTER_CONFIDENCE_THRESHOLD:
        fields = []

    scope_hint = str(plan.get("scope_hint") or "").strip().lower() or None
    if scope_hint not in SCOPE_MAP or confidence < FIELD_FILTER_CONFIDENCE_THRESHOLD:
        scope_hint = None

    sanitized = {
        "action": action,
        "fields": fields,
        "confidence": confidence,
        "scope_hint": scope_hint,
    }

    if action == "fields":
        sanitized["paths"] = fields
    if plan.get("section_path"):
        sanitized["section_path"] = plan.get("section_path")
    if isinstance(plan.get("scope_prefixes"), list):
        sanitized["scope_prefixes"] = plan["scope_prefixes"]
    if isinstance(plan.get("field_groups"), list):
        sanitized["field_groups"] = plan["field_groups"]
    if "priority_only" in plan:
        sanitized["priority_only"] = bool(plan.get("priority_only"))

    return sanitized


def build_lead_field_index_prompt(lead_detail: dict[str, Any] | None) -> str:
    fields = build_lead_field_index(lead_detail)
    if not fields:
        return "No loaded lead fields available."
    return "\n".join(
        f"- {field['path']} | {field['label']}"
        for field in fields
    )


def _format_rows(rows: list[tuple[str, Any]]) -> str:
    return "\n".join(f"{label}: {_format_value(value)}" for label, value in rows)


def _format_grouped_section_rows(rows: list[tuple[str, Any]]) -> str:
    grouped: dict[str, list[tuple[str, Any]]] = {}
    for path, value in rows:
        group_key, field_path = path.split(".", 1)
        grouped.setdefault(group_key, []).append((_format_label(field_path), value))

    groups: list[str] = []
    for group_key, group_rows in grouped.items():
        group_lines = [f"- {label}: {_format_value(value)}" for label, value in group_rows]
        groups.append(f"{_format_group_label(group_key)}:\n" + "\n".join(group_lines))
    return "\n\n".join(groups)


def _execute_fields(lead_detail: dict[str, Any], paths: list[Any]) -> str:
    rows: list[tuple[str, Any]] = []
    for raw_path in paths:
        path = str(raw_path).strip()
        if not path:
            continue
        exists, value = _path_value(lead_detail, path)
        if exists:
            rows.append((_format_label(path), value))
    return _format_rows(rows)


def _execute_section(lead_detail: dict[str, Any], section_path: Any) -> str:
    prefix = str(section_path or "").strip().strip(".")
    if not prefix:
        return ""

    rows: list[tuple[str, Any]] = []
    for path, value in iter_leaf_entries(lead_detail, include_blank=True):
        if path == prefix:
            rows.append((path, value))
            continue
        if not path.startswith(f"{prefix}."):
            continue
        if path.endswith(".__typename") or path.endswith("__typename"):
            continue
        rows.append((path[len(prefix) + 1 :], value))

    if not rows:
        return ""

    has_direct_rows = any("." not in path for path, _value in rows)
    section_rows = (
        _format_grouped_section_rows(rows)
        if not has_direct_rows
        else _format_rows([(_format_label(path), value) for path, value in rows])
    )
    return f"{_format_section_heading(prefix)}\n" + section_rows


def _valid_scope_prefixes(lead_detail: dict[str, Any], scope_prefixes: list[Any]) -> list[str]:
    requested_prefixes = [
        str(prefix).strip().strip(".")
        for prefix in scope_prefixes
        if str(prefix).strip().strip(".")
    ]
    if not requested_prefixes:
        return []

    leaf_paths = [
        path
        for path, _value in iter_leaf_entries(lead_detail, include_blank=True)
        if not path.endswith(".__typename") and not path.endswith("__typename")
    ]
    valid_prefixes: list[str] = []
    for prefix in requested_prefixes:
        if any(path == prefix or path.startswith(f"{prefix}.") for path in leaf_paths):
            valid_prefixes.append(prefix)

    return valid_prefixes


def _is_priority_path(path: str) -> bool:
    global _PRIORITY_SET_CACHE
    priority_paths = tuple(load_priority_field_paths())
    if _PRIORITY_SET_CACHE is None or _PRIORITY_SET_CACHE[0] != priority_paths:
        _PRIORITY_SET_CACHE = (priority_paths, set(priority_paths))
    normalized_path = re.sub(r"^\[\d+\]\.", "", path)
    candidates = {path, normalized_path}
    for candidate in list(candidates):
        candidates.update(re.sub(r"^\[\d+\]\.", "", alias) for alias in _equivalent_offer_paths(candidate))
    return bool(candidates & _PRIORITY_SET_CACHE[1])


def _normalize_query_text(value: str) -> str:
    return collapse_text(value)


def _tokenize_search_text(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if token and token not in QUERY_STOPWORDS and len(token) > 1
    }


def _path_search_tokens(path: str) -> set[str]:
    tokens = _tokenize_search_text(path)
    tokens.update(_tokenize_search_text(_format_label(path)))
    for candidate in _equivalent_offer_paths(path):
        tokens.update(_tokenize_search_text(candidate))
    return tokens


def _catalog_paths_for_groups(groups: list[str]) -> set[str]:
    normalized_groups = {group.strip().lower() for group in groups if group.strip()}
    return {
        spec.path
        for spec in LEAD_FIELD_CATALOG
        if normalized_groups.intersection(spec.groups)
    }


def _matches_any_scope(path: str, scope_prefixes: list[str]) -> bool:
    if not scope_prefixes:
        return True
    candidates = _equivalent_offer_paths(path)
    return any(
        candidate == prefix or candidate.startswith(f"{prefix}.")
        for candidate in candidates
        for prefix in scope_prefixes
    )


def _matches_any_field_group(path: str, field_groups: list[str]) -> bool:
    groups = [group.strip().lower() for group in field_groups if group.strip()]
    if not groups:
        return True

    allowed_paths = _catalog_paths_for_groups(groups)

    if not allowed_paths:
        return True

    candidates = set(_equivalent_offer_paths(path))
    expanded_allowed = {
        candidate
        for allowed_path in allowed_paths
        for candidate in _equivalent_offer_paths(allowed_path)
    }
    return bool(candidates & expanded_allowed)


def _matches_any_field_path(path: str, field_paths: set[str]) -> bool:
    if not field_paths:
        return True
    candidates = set(_equivalent_offer_paths(path))
    expanded_allowed = {
        candidate
        for field_path in field_paths
        for candidate in _equivalent_offer_paths(field_path)
    }
    return bool(candidates & expanded_allowed)


def _scope_hint_paths(scope_hint: Any, candidate_paths: list[str]) -> set[str] | None:
    hint = str(scope_hint or "").strip().lower()
    scope_terms = SCOPE_MAP.get(hint)
    if not scope_terms:
        return None

    if hint == "loan":
        allowed_paths = _catalog_paths_for_groups(["existing_loan_bt"])
        expanded_allowed = {
            candidate
            for allowed_path in allowed_paths
            for candidate in _equivalent_offer_paths(allowed_path)
        }
        return {
            path
            for path in candidate_paths
            if set(_equivalent_offer_paths(path)) & expanded_allowed
        }

    matched_paths: set[str] = set()
    for path in candidate_paths:
        equivalent_paths = _equivalent_offer_paths(path)
        for term in scope_terms:
            normalized_term = _normalize_query_text(term)
            if any(
                candidate == term or candidate.startswith(f"{term}.")
                for candidate in equivalent_paths
            ):
                matched_paths.add(path)
                break

            searchable_tokens: set[str] = set()
            for candidate in equivalent_paths:
                searchable_tokens.update(_path_search_tokens(candidate))
            searchable_tokens.update(_tokenize_search_text(_format_label(path)))
            if normalized_term in searchable_tokens:
                matched_paths.add(path)
                break

    return matched_paths


def _format_missing_field_rows(rows: list[tuple[str, str, bool]]) -> str:
    if not rows:
        return MISSING_FIELDS_NONE_REPLY

    priority_lines: list[str] = []
    other_lines: list[str] = []
    seen: set[str] = set()
    for label, reason, is_priority in rows:
        key = f"{label}|{reason}|{is_priority}"
        if key in seen:
            continue
        seen.add(key)
        suffix = f" ({reason})" if reason else ""
        line = f"- {label}{suffix}"
        if is_priority:
            priority_lines.append(line)
        else:
            other_lines.append(line)

    if priority_lines and other_lines:
        return "High priority missing fields:\n" + "\n".join(priority_lines) + "\n\nOther missing fields:\n" + "\n".join(other_lines)
    if priority_lines:
        return "High priority missing fields:\n" + "\n".join(priority_lines)
    return "Missing fields:\n" + "\n".join(other_lines)


def build_priority_missing_fields(
    lead_detail: dict[str, Any] | None,
    lead_missing_fields: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    priority_paths = load_priority_field_paths()
    if not priority_paths:
        return []

    detail = lead_detail or {}
    existing_missing = {
        str(item.get("path") or ""): item
        for item in (lead_missing_fields or [])
        if isinstance(item, dict) and item.get("path")
    }

    priority_missing: list[dict[str, str]] = []
    resolved_debug: list[dict[str, Any]] = []
    missing_debug: list[dict[str, Any]] = []
    for priority_path in priority_paths:
        exists, value, resolved_path = (
            _resolve_offer_path_value(detail, priority_path)
            if detail
            else (False, None, priority_path)
        )
        source_item = _equivalent_missing_item(existing_missing, priority_path)
        if exists and not _is_missing_value(value):
            resolved_debug.append({"path": priority_path, "resolved_path": resolved_path, "value": _format_value(value, max_chars=80)})
            continue
        if exists:
            reason = _missing_reason(value, exists=True)
        elif source_item:
            reason = str(source_item.get("reason") or _missing_reason(value, exists=False)).replace("_", " ").strip()
        else:
            reason = _missing_reason(value, exists=False)
        missing_debug.append({"path": priority_path, "resolved_path": resolved_path, "reason": reason, "had_source_item": bool(source_item)})

        priority_missing.append(
            {
                "path": priority_path,
                "resolved_path": resolved_path,
                "label": str(source_item.get("label") if source_item else _format_label(priority_path)),
                "reason": reason,
                "priority": "high",
            }
        )

    logger.info(
        "[LeadDebug][backend] priority resolution: loaded_priority=%s missing_priority=%s loaded_sample=%s missing_sample=%s detail_key_count=%d",
        len(resolved_debug),
        len(priority_missing),
        resolved_debug[:12],
        missing_debug[:12],
        len(detail),
    )
    return priority_missing


def format_priority_missing_context(priority_missing_fields: list[dict[str, Any]], *, limit: int = 8) -> str:
    rows: list[str] = []
    for item in priority_missing_fields[:limit]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or _format_label(str(item.get("path") or ""))).strip()
        path = str(item.get("path") or "").strip()
        reason = str(item.get("reason") or "missing").replace("_", " ").strip()
        if label and path:
            rows.append(f"- {label} ({path}, {reason})")
    return "\n".join(rows)


def _execute_precomputed_missing_fields(
    lead_detail: dict[str, Any],
    lead_missing_fields: list[dict[str, Any]],
    scope_prefixes: list[Any],
    field_groups: list[Any],
    fields: list[Any],
    scope_hint: Any,
    *,
    priority_only: bool = False,
) -> str:
    loaded_paths = [str(item.get("path") or "") for item in lead_missing_fields if isinstance(item, dict)]
    valid_prefixes, requested_groups = _resolve_prefixes_and_groups(
        scope_prefixes, field_groups, loaded_paths=loaded_paths
    )
    valid_fields = {
        resolved
        for field in fields
        if (resolved := _resolve_valid_field_path(field, set(loaded_paths)))
    }
    scope_paths = None if valid_fields else _scope_hint_paths(scope_hint, loaded_paths)
    filtering_applied = bool(valid_fields or scope_paths or valid_prefixes or requested_groups)

    verified_loaded_debug: list[dict[str, Any]] = []
    verified_missing_debug: list[dict[str, Any]] = []
    rows: list[tuple[str, str, bool]] = []
    for item in lead_missing_fields:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path.endswith(".__typename") or path.endswith("__typename"):
            continue
        is_priority = item.get("priority") == "high" or _is_priority_path(path)
        if priority_only and not is_priority:
            continue
        if is_priority:
            exists, value, _resolved_path = _resolve_offer_path_value(lead_detail, path)
            if exists and not _is_missing_value(value):
                verified_loaded_debug.append({"path": path, "resolved_path": _resolved_path, "value": _format_value(value, max_chars=80)})
                continue
            if exists:
                item = {**item, "reason": _missing_reason(value, exists=True)}
                verified_missing_debug.append({"path": path, "resolved_path": _resolved_path, "reason": item["reason"]})
            else:
                verified_missing_debug.append({"path": path, "resolved_path": _resolved_path, "reason": item.get("reason")})
        if valid_fields and not _matches_any_field_path(path, valid_fields):
            continue
        if scope_paths is not None and not _matches_any_field_path(path, scope_paths):
            continue
        if valid_prefixes and not _matches_any_scope(path, valid_prefixes):
            continue
        if not _matches_any_field_group(path, requested_groups):
            continue
        label = str(item.get("label") or _format_label(path)).strip()
        reason = str(item.get("reason") or "").replace("_", " ").strip()
        rows.append((label, reason, is_priority))

    logger.info(
        "[LeadDebug][backend] precomputed missing verification: input_missing=%d returned_rows=%d filtering_applied=%s fields=%s scope_hint=%s verified_loaded_sample=%s verified_missing_sample=%s lead_detail_keys=%s",
        len(lead_missing_fields),
        len(rows),
        filtering_applied,
        sorted(valid_fields),
        scope_hint,
        verified_loaded_debug[:12],
        verified_missing_debug[:12],
        list(lead_detail.keys())[:30],
    )
    return _format_missing_field_rows(rows)


def _resolve_prefixes_and_groups(
    scope_prefixes: list[Any],
    field_groups: list[Any],
    loaded_paths: list[str] | None = None,
    lead_detail: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Extract and validate explicit scope prefixes and field groups."""
    plan_prefixes = [
        str(prefix).strip().strip(".")
        for prefix in scope_prefixes
        if str(prefix).strip().strip(".")
    ]
    requested_prefixes = plan_prefixes

    plan_groups = [
        str(group).strip().lower()
        for group in field_groups
        if str(group).strip()
    ]
    requested_groups = plan_groups

    valid_prefixes = requested_prefixes
    if lead_detail is not None and loaded_paths is None:
        valid_prefixes = _valid_scope_prefixes(lead_detail, requested_prefixes)

    if loaded_paths is not None:
        valid_prefixes = [
            prefix
            for prefix in requested_prefixes
            if any(path == prefix or path.startswith(f"{prefix}.") for path in loaded_paths)
        ]

    return valid_prefixes, requested_groups


def _execute_missing_fields(
    lead_detail: dict[str, Any],
    scope_prefixes: list[Any],
    field_groups: list[Any],
    fields: list[Any],
    scope_hint: Any,
    *,
    priority_only: bool = False,
) -> str:
    prefixes, groups = _resolve_prefixes_and_groups(
        scope_prefixes, field_groups, lead_detail=lead_detail
    )
    candidate_paths = (
        [
            path
            for path, _ in iter_leaf_entries(lead_detail, include_blank=True)
            if not path.endswith(".__typename") and not path.endswith("__typename")
        ]
        + load_priority_field_paths()
    )
    candidate_path_set = set(candidate_paths)
    valid_fields = {
        resolved
        for field in fields
        if (resolved := _resolve_valid_field_path(field, candidate_path_set))
    }
    scope_paths = None if valid_fields else _scope_hint_paths(scope_hint, candidate_paths)
    filtering_applied = bool(valid_fields or scope_paths or prefixes or groups)
    missing: list[tuple[str, str, bool]] = [
        (item["label"], item["reason"], True)
        for item in build_priority_missing_fields(lead_detail, None)
        if _matches_any_field_path(item["path"], valid_fields)
        and (scope_paths is None or _matches_any_field_path(item["path"], scope_paths))
        and _matches_any_scope(item["path"], prefixes)
        and _matches_any_field_group(item["path"], groups)
    ]
    for path, _v in iter_leaf_entries(lead_detail, include_blank=True):
        if path.endswith(".__typename") or path.endswith("__typename"):
            continue
        is_priority = _is_priority_path(path)
        if priority_only and not is_priority:
            continue
        if valid_fields and not _matches_any_field_path(path, valid_fields):
            continue
        if scope_paths is not None and not _matches_any_field_path(path, scope_paths):
            continue
        if prefixes and not _matches_any_scope(path, prefixes):
            continue
        if not _matches_any_field_group(path, groups):
            continue
        if _format_value(_v) == "Missing":
            missing.append((_format_label(path), _missing_reason(_v), is_priority))

    logger.info(
        "[LeadDebug][backend] dynamic missing execution: returned_rows=%d filtering_applied=%s fields=%s scope_hint=%s prefixes=%s groups=%s",
        len(missing),
        filtering_applied,
        sorted(valid_fields),
        scope_hint,
        prefixes,
        groups,
    )
    return _format_missing_field_rows(missing)


def _doc_group_label(group: dict[str, Any], fallback: str) -> str:
    for key in ("label", "name", "doc_name", "document_name", "doc_id", "parent_doc_id"):
        value = group.get(key)
        if value not in (None, ""):
            label = str(value).replace("_", " ").strip()
            return f"doc {label}" if key.endswith("id") else label
    return fallback


def _is_uploaded_doc_group(group: dict[str, Any]) -> bool:
    upload_value = group.get("is_doc_uploaded")
    if str(upload_value).strip().lower() in {"1", "true", "yes", "uploaded"}:
        return True

    status_value = str(group.get("status") or group.get("doc_status") or "").strip().lower()
    if status_value in {"1", "2", "active", "approved", "complete", "completed", "done", "uploaded", "verified"}:
        return True

    upload_url = group.get("doc_upload_url") or group.get("doc_path")
    return bool(upload_url)


def _execute_next_step(
    lead_detail: dict[str, Any],
    lead_missing_fields: list[dict[str, Any]] | None = None,
) -> str:
    priority_missing = build_priority_missing_fields(lead_detail, lead_missing_fields)
    source = priority_missing
    if not source and lead_missing_fields:
        source = [item for item in lead_missing_fields if isinstance(item, dict)]

    if not source:
        return "Next step: High-priority offer fields complete dikh rahe hain. Ab customer se remaining process/document status confirm karein."

    labels = []
    for item in source[:3]:
        label = str(item.get("label") or _format_label(str(item.get("path") or ""))).strip()
        if label and label not in labels:
            labels.append(label)

    if not labels:
        return ""
    joined = ", ".join(labels)
    return f"Next step: Customer se {joined} confirm karein, kyunki ye high-priority offer fields missing hain."


def _execute_missing_documents(lead_detail: dict[str, Any]) -> str:
    doc_groups: dict[str, dict[str, Any]] = {}
    for path, value in iter_leaf_entries(lead_detail, include_blank=True):
        if "recommended_docs" not in path and "leaddocs" not in path:
            continue
        match = re.match(r"(.+?\[\d+\])\.(.+)$", path)
        if not match:
            continue
        group_key, field_name = match.groups()
        doc_groups.setdefault(group_key, {})[field_name] = value

    if not doc_groups:
        return "Missing documents: Not available in loaded lead data."

    missing: list[str] = []
    for group_key, group in sorted(doc_groups.items()):
        if "recommended_docs" in group_key and not _is_uploaded_doc_group(group):
            missing.append(_doc_group_label(group, group_key))

    if not missing:
        return "Missing documents: None found in loaded recommended docs."
    return "Missing documents:\n" + "\n".join(f"- {label}" for label in missing)


def execute_lead_query_plan(
    lead_detail: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    *,
    lead_missing_fields: list[dict[str, Any]] | None = None,
) -> str:
    if not lead_detail or not isinstance(plan, dict):
        return ""

    action = str(plan.get("action") or "").strip().lower()
    if action == "fields":
        paths = plan.get("fields") if isinstance(plan.get("fields"), list) else []
        if not paths:
            paths = plan.get("paths") if isinstance(plan.get("paths"), list) else []
        return _execute_fields(lead_detail, paths)
    if action == "section":
        return _execute_section(lead_detail, plan.get("section_path"))
    if action == "missing_fields":
        scope_prefixes = plan.get("scope_prefixes") if isinstance(plan.get("scope_prefixes"), list) else []
        field_groups = plan.get("field_groups") if isinstance(plan.get("field_groups"), list) else []
        fields = plan.get("fields") if isinstance(plan.get("fields"), list) else []
        scope_hint = plan.get("scope_hint")
        priority_only = bool(plan.get("priority_only"))
        filtering_requested = bool(fields or scope_hint or scope_prefixes or field_groups)
        if lead_missing_fields:
            combined_missing = list(lead_missing_fields)
            existing_paths = {
                str(item.get("path") or "")
                for item in combined_missing
                if isinstance(item, dict)
            }
            for priority_item in build_priority_missing_fields(lead_detail, lead_missing_fields):
                if priority_item["path"] not in existing_paths:
                    combined_missing.append(priority_item)
            result = _execute_precomputed_missing_fields(
                lead_detail,
                combined_missing,
                scope_prefixes,
                field_groups,
                fields,
                scope_hint,
                priority_only=priority_only,
            )
            if filtering_requested and result == MISSING_FIELDS_NONE_REPLY:
                logger.info(
                    "[LeadDebug][backend] missing fields filtered result empty; retrying broad execution"
                )
                result = _execute_precomputed_missing_fields(
                    lead_detail,
                    combined_missing,
                    [],
                    [],
                    [],
                    None,
                    priority_only=priority_only,
                )
            return result
        result = _execute_missing_fields(
            lead_detail,
            scope_prefixes,
            field_groups,
            fields,
            scope_hint,
            priority_only=priority_only,
        )
        if filtering_requested and result == MISSING_FIELDS_NONE_REPLY:
            logger.info(
                "[LeadDebug][backend] missing fields filtered result empty; retrying broad execution"
            )
            result = _execute_missing_fields(
                lead_detail,
                [],
                [],
                [],
                None,
                priority_only=priority_only,
            )
        return result
    if action == "missing_documents":
        return _execute_missing_documents(lead_detail)
    if action == "next_step":
        return _execute_next_step(lead_detail, lead_missing_fields)
    return ""


def build_lead_detail_chat_context(
    *,
    lead_id: str | int | None,
    lead_detail: dict[str, Any] | None,
    max_flat_fields: int = 160,
) -> str:
    if not lead_detail:
        return ""

    flattened = list(iter_leaf_entries(lead_detail, include_blank=True))
    important_lines: list[str] = []
    searchable_lines: list[str] = []
    seen_paths: set[str] = set()

    for path, value in flattened:
        if path in IMPORTANT_PATHS:
            important_lines.append(f"- {path}: {_format_value(value)}")
            seen_paths.add(path)

    for path, value in flattened:
        if path in seen_paths or path.endswith("__typename"):
            continue
        searchable_lines.append(f"- {path}: {_format_value(value)}")
        if len(searchable_lines) >= max_flat_fields:
            break

    lead_label = lead_id or lead_detail.get("id") or lead_detail.get("ref_lead_id") or "unknown"
    sections = [
        "Loaded Ambak lead detail context. Use this customer/lead data first when the user asks about this lead.",
        f"Lead ID: {lead_label}",
        "Answer only from these loaded lead details when the question is about customer, loan, lead, status, bank, RM, partner, property, income, CIBIL, or contact fields.",
    ]

    if important_lines:
        sections.append("Important loaded fields:\n" + "\n".join(important_lines))
    if searchable_lines:
        sections.append("Additional searchable loaded fields:\n" + "\n".join(searchable_lines))

    return "\n\n".join(sections)
