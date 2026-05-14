import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING_PATH = PROJECT_ROOT / "mapping.json"

COLLECTION_BY_FIELD: dict[str, str] = {
    "state": "state_list",
    "cra_state": "state_list",
    "pa_state": "state_list",
    "property_state": "state_list",
    "ca_cra_state": "state_list",
    "ca_pa_state": "state_list",
    "city": "city",
    "cra_city": "city",
    "pa_city": "city",
    "property_city": "city",
    "ca_cra_city": "city",
    "ca_pa_city": "city",
    "property_authority_id": "authority_names",
    "qualification": "qualification",
    "ca_qualification": "qualification",
    "duration_of_stay": "duration_of_stay",
    "ca_duration_of_stay": "duration_of_stay",
    "company_type": "company_type",
    "ca_company_type": "company_type",
    "property_type": "property_type",
    "property_sub_type": "property_sub_type",
    "loan_type": "loan_type",
    "agreement_type": "agreement_type",
    "usage_type": "usage_type",
    "marital_status": "marital_status",
    "ca_marital_status": "marital_status",
    "fulfillment_type": "fulfillment_type",
    "profession": "profession",
    "ca_profession": "profession",
    "salary_credit_mode": "salary_credit_mode",
    "ca_salary_credit_mode": "salary_credit_mode",
    "relationship_with_customer": "relationship",
    "relationship": "relationship",
    "transaction_mode": "transaction_mode",
    "loan_sub_type": "loan_sub_type",
    "subvension_type_id": "subvension_type",
    "cross_sell_type_id": "cross_sell_product_type",
    "source_id": "subsource_type",
    "sub_source_id": "subsource_type",
    "language_id": "preferred_language",
    "preferred_language": "preferred_language",
    "circle_id": "circle_list",
    "relation_id": "relation_mapping",
    "additional_income_type": "additional_income_type",
    "obligation_type": "obligation_type",
    "report_month": "report_month_list",
    "report_year": "report_year_list",
    "report_status": "report_status_list",
    "checklist_id": "checklist_name_master",
}

DISPLAY_KEYS = (
    "label",
    "name",
    "authority_name",
    "relation_name",
    "sub_source_name",
    "source_name",
    "loan_type_name",
)


def apply_value_mappings_to_facts(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    mapped: dict[str, Any] = {}
    metadata: dict[str, dict[str, Any]] = {}
    mapper = get_value_mapper()

    for path, value in facts.items():
        label = mapper.label_for_path(path, value)
        if label is None:
            mapped[path] = value
            continue
        mapped[path] = label
        metadata[path] = {"raw": value, "display": label}

    return mapped, metadata


@lru_cache(maxsize=1)
def get_value_mapper() -> "ValueMapper":
    return ValueMapper(load_mapping_collections(DEFAULT_MAPPING_PATH))


class ValueMapper:
    def __init__(self, collections: dict[str, list[dict[str, Any]]]):
        self._indexes = {
            name: _build_collection_index(rows)
            for name, rows in collections.items()
            if rows
        }

    def label_for_path(self, path: str, value: Any) -> str | None:
        if value in (None, "") or isinstance(value, (dict, list)):
            return None
        collection = _collection_for_path(path)
        if not collection:
            return None
        return self._indexes.get(collection, {}).get(_normalize_lookup_value(value))


def load_mapping_collections(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
        data = payload.get("data") if isinstance(payload, dict) else None
        return {
            str(key): value
            for key, value in (data or {}).items()
            if isinstance(value, list)
        }
    except json.JSONDecodeError:
        return _load_relaxed_mapping_collections(text)


def _load_relaxed_mapping_collections(text: str) -> dict[str, list[dict[str, Any]]]:
    collections: dict[str, list[dict[str, Any]]] = {}
    current_name: str | None = None
    buffer: list[str] = []
    depth = 0

    for line in text.splitlines():
        section = re.match(r'\s*"([^"]+)"\s*:\s*\[\s*$', line)
        if section:
            current_name = section.group(1)
            collections.setdefault(current_name, [])
            continue
        if not current_name:
            continue

        if "{" in line:
            buffer.append(line.strip().rstrip(","))
            depth += line.count("{") - line.count("}")
            if depth > 0:
                continue
        elif buffer:
            buffer.append(line.strip().rstrip(","))
            depth += line.count("{") - line.count("}")
            if depth > 0:
                continue
        elif line.strip().startswith("]"):
            current_name = None
            continue

        if buffer and depth <= 0:
            item = _parse_relaxed_object(" ".join(buffer))
            if item is not None:
                collections[current_name].append(item)
            buffer = []
            depth = 0

    return collections


def _parse_relaxed_object(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r",\s*}", "}", text.strip().rstrip(","))
    try:
        item = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return item if isinstance(item, dict) else None


def _build_collection_index(rows: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for row in rows:
        label = _display_label(row)
        if not label:
            continue
        for key in ("id", "value"):
            if key in row:
                index[_normalize_lookup_value(row[key])] = label
    return index


def _display_label(row: dict[str, Any]) -> str | None:
    for key in DISPLAY_KEYS:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _collection_for_path(path: str) -> str | None:
    leaf = str(path or "").replace("[", ".").replace("]", "").split(".")[-1].lower()
    if leaf in COLLECTION_BY_FIELD:
        return COLLECTION_BY_FIELD[leaf]
    stripped = leaf[3:] if leaf.startswith("ca_") else leaf
    if stripped in COLLECTION_BY_FIELD:
        return COLLECTION_BY_FIELD[stripped]
    if stripped.endswith("_state") or stripped == "state":
        return "state_list"
    if stripped.endswith("_city") or stripped == "city":
        return "city"
    return COLLECTION_BY_FIELD.get(stripped)


def _normalize_lookup_value(value: Any) -> str:
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text
