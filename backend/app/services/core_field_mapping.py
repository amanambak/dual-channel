import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CoreFieldMapping:
    table: str
    field_name: str
    label: str
    category_hint: str | None
    field_types: list[str]
    lookup_paths: list[str]
    graphql_paths: list[str]
    aliases: list[str]
    options: list[str]


TABLE_PATH_CONTEXT: dict[str, dict[str, Any]] = {
    "finex_lead": {
        "prefixes": ["lead"],
        "category_hint": "lead",
        "allow_bare_fields": True,
    },
    "finex_lead_detail": {
        "prefixes": ["lead_details", "lead_detail"],
        "category_hint": "lead_details",
        "allow_bare_fields": True,
    },
    "finex_customer": {
        "prefixes": ["customer", "customer_details"],
        "category_hint": "customer_details",
        "allow_bare_fields": True,
    },
    "finex_customer_co_applicant": {
        "prefixes": ["co_applicant", "coapplicant"],
        "category_hint": "customer_details",
        "field_prefixes_to_strip": ["ca_"],
        "allow_bare_fields": True,
        "allow_stripped_bare_fields": False,
    },
    "finex_split_payment": {
        "prefixes": ["split_payment", "split_payments"],
        "category_hint": "disbursal",
        "allow_bare_fields": False,
    },
}


def load_core_field_mappings(path: Path) -> list[CoreFieldMapping]:
    payload = _load_json(path)
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict):
        return []

    mappings: list[CoreFieldMapping] = []
    for table, table_spec in tables.items():
        if not isinstance(table_spec, dict):
            continue
        fields = table_spec.get("fields")
        if not isinstance(fields, dict):
            continue
        for field_name, field_spec in fields.items():
            if not isinstance(field_spec, dict):
                continue
            mappings.append(_build_mapping(str(table), str(field_name), field_spec))
    return mappings


def _build_mapping(
    table: str,
    field_name: str,
    field_spec: dict[str, Any],
) -> CoreFieldMapping:
    context = TABLE_PATH_CONTEXT.get(table, {})
    category_hint = context.get("category_hint")
    field_variants = _field_variants(field_name, context)
    table_paths = [f"{table}.{variant}" for variant in field_variants]
    prefixed_paths = [
        f"{prefix}.{variant}"
        for prefix in _as_string_list(context.get("prefixes"))
        for variant in field_variants
    ]
    bare_paths = [field_name] if context.get("allow_bare_fields") else []
    if context.get("allow_stripped_bare_fields", True):
        bare_paths.extend(variant for variant in field_variants if variant != field_name)

    lookup_paths = _unique([*bare_paths, *prefixed_paths, *table_paths])
    graphql_paths = _unique([*prefixed_paths, *table_paths, *bare_paths])
    label = _label_from_key(field_name)
    purpose = str(field_spec.get("purpose") or "").strip()
    options = _key_value_options(field_spec.get("key_values"))
    aliases = _unique([label, purpose, *options])

    return CoreFieldMapping(
        table=table,
        field_name=field_name,
        label=label,
        category_hint=str(category_hint) if category_hint else None,
        field_types=_field_types(field_spec.get("type")),
        lookup_paths=lookup_paths,
        graphql_paths=graphql_paths,
        aliases=aliases,
        options=options,
    )


def _field_variants(field_name: str, context: dict[str, Any]) -> list[str]:
    variants = [field_name]
    for prefix in _as_string_list(context.get("field_prefixes_to_strip")):
        if field_name.startswith(prefix):
            variants.append(field_name[len(prefix) :])
    return _unique(variants)


def _field_types(raw_type: Any) -> list[str]:
    normalized = str(raw_type or "").strip().lower()
    if not normalized:
        return ["string"]
    if any(token in normalized for token in ("int", "decimal", "float", "double")):
        return ["number"]
    if "date" in normalized or "time" in normalized:
        return ["date"]
    if "enum" in normalized:
        return ["string", "enum"]
    return ["string"]


def _key_value_options(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    options: list[str] = []
    for key, label in value.items():
        key_text = str(key).strip()
        label_text = str(label).strip()
        if key_text:
            options.append(key_text)
        if label_text:
            options.append(label_text)
    return _unique(options)


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    candidate = str(value).strip()
    return [candidate] if candidate else []


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _label_from_key(value: str) -> str:
    return re.sub(r"[_\s]+", " ", value).strip().title()
