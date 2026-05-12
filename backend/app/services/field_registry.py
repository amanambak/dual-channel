import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.core_field_mapping import load_core_field_mappings
from app.services.lead_detail_context import iter_leaf_entries


APP_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = APP_DIR / "config"
PRIORITY_FIELDS_PATH = REPO_DIR / "priority_fields.json"
FIELD_MAPPING_CORE_PATH = REPO_DIR / "FIELD_MAPPING_CORE.json"


@dataclass
class FieldDefinition:
    id: str
    label: str
    category_hint: str | None = None
    types: list[str] = field(default_factory=lambda: ["string"])
    priority: str = "normal"
    graphql_paths: list[str] = field(default_factory=list)
    realtime_keys: list[str] = field(default_factory=list)
    json_schema_paths: list[str] = field(default_factory=list)
    csv_keys: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        return _unique(
            [
                self.id,
                *self.graphql_paths,
                *self.realtime_keys,
                *self.json_schema_paths,
                *self.csv_keys,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "category_hint": self.category_hint,
            "types": list(self.types),
            "priority": self.priority,
            "graphql_paths": list(self.graphql_paths),
            "realtime_keys": list(self.realtime_keys),
            "json_schema_paths": list(self.json_schema_paths),
            "csv_keys": list(self.csv_keys),
            "aliases": list(self.aliases),
            "options": list(self.options),
            "derived_from": list(self.derived_from),
        }


class FieldRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, FieldDefinition] = {}
        self._key_index: dict[str, str] = {}
        self.conflicts: list[dict[str, str]] = []

    def clone(self) -> "FieldRegistry":
        cloned = FieldRegistry()
        cloned.definitions = deepcopy(self.definitions)
        cloned._key_index = dict(self._key_index)
        cloned.conflicts = list(self.conflicts)
        return cloned

    def add_definition(self, definition: FieldDefinition) -> None:
        existing = self.definitions.get(definition.id)
        if existing is None:
            self.definitions[definition.id] = definition
        else:
            existing.label = definition.label or existing.label
            existing.category_hint = definition.category_hint or existing.category_hint
            existing.types = _unique([*existing.types, *definition.types])
            existing.priority = _higher_priority(existing.priority, definition.priority)
            existing.graphql_paths = _unique([*existing.graphql_paths, *definition.graphql_paths])
            existing.realtime_keys = _unique([*existing.realtime_keys, *definition.realtime_keys])
            existing.json_schema_paths = _unique([*existing.json_schema_paths, *definition.json_schema_paths])
            existing.csv_keys = _unique([*existing.csv_keys, *definition.csv_keys])
            existing.aliases = _unique([*existing.aliases, *definition.aliases])
            existing.options = _unique([*existing.options, *definition.options])
            existing.derived_from = _unique([*existing.derived_from, *definition.derived_from])
            definition = existing

        for key in definition.keys:
            self._index_key(key, definition.id)
        for alias in definition.aliases:
            self._index_key(alias, definition.id, override=False)

    def add_dynamic_graphql_paths(self, lead_detail: dict[str, Any] | None) -> None:
        if not isinstance(lead_detail, dict):
            return
        for path, _value in iter_leaf_entries(lead_detail, include_blank=True):
            if self.resolve(path):
                continue
            field_id = _dynamic_field_id(path)
            self.add_definition(
                FieldDefinition(
                    id=field_id,
                    label=_label_from_key(path),
                    category_hint=path.split(".", 1)[0] if "." in path else None,
                    graphql_paths=[path],
                )
            )

    def resolve(self, key_or_path: str) -> str | None:
        normalized = _normalize_lookup_key(key_or_path)
        if not normalized:
            return None
        if normalized in self._key_index:
            return self._key_index[normalized]
        compact = normalized.replace(".", "_")
        return self._key_index.get(compact)

    def definition(self, field_id: str) -> FieldDefinition | None:
        resolved = self.resolve(field_id) or field_id
        return self.definitions.get(resolved)

    def paths_for(self, field_id: str) -> list[str]:
        definition = self.definition(field_id)
        return list(definition.graphql_paths) if definition else []

    def extraction_keys_for(self, field_id: str) -> list[str]:
        definition = self.definition(field_id)
        return list(definition.realtime_keys) if definition else []

    def category_hint(self, field_id: str) -> str | None:
        definition = self.definition(field_id)
        return definition.category_hint if definition else None

    def _index_key(self, raw_key: str, field_id: str, *, override: bool = True) -> None:
        key = _normalize_lookup_key(raw_key)
        if not key:
            return
        previous = self._key_index.get(key)
        if previous and previous != field_id:
            self.conflicts.append(
                {"key": raw_key, "first_field": previous, "second_field": field_id}
            )
            if not override:
                return
        self._key_index[key] = field_id


def load_field_registry() -> FieldRegistry:
    registry = FieldRegistry()
    _load_manual_aliases(registry, CONFIG_DIR / "field_aliases.json")
    _load_manual_aliases(registry, CONFIG_DIR / "customer_details_field_aliases.json")
    _load_core_field_mapping(registry, FIELD_MAPPING_CORE_PATH)
    _load_canonical_mapping(registry, CONFIG_DIR / "canonical_field_mapping.json")
    _mark_priority_fields(registry)
    return registry


@lru_cache(maxsize=1)
def get_field_registry() -> FieldRegistry:
    return load_field_registry()


def resolve_field_key(key_or_path: str) -> str | None:
    return get_field_registry().resolve(key_or_path)


def get_field_definition(field_id: str) -> FieldDefinition | None:
    return get_field_registry().definition(field_id)


def registry_with_lead_detail(lead_detail: dict[str, Any] | None) -> FieldRegistry:
    registry = get_field_registry().clone()
    registry.add_dynamic_graphql_paths(lead_detail)
    return registry


def _load_manual_aliases(registry: FieldRegistry, path: Path) -> None:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return

    for field_id, raw_definition in payload.items():
        if not isinstance(raw_definition, dict):
            continue
        keys = _as_string_list(raw_definition.get("keys"))
        graphql_paths = _as_string_list(raw_definition.get("graphql_paths"))
        realtime_keys = _as_string_list(raw_definition.get("realtime_keys"))
        json_schema_paths = _as_string_list(raw_definition.get("json_schema_paths"))
        csv_keys = _as_string_list(raw_definition.get("csv_keys"))
        aliases = _as_string_list(raw_definition.get("aliases"))
        ui_labels = _as_string_list(raw_definition.get("ui_labels"))

        registry.add_definition(
            FieldDefinition(
                id=str(field_id),
                label=str(raw_definition.get("label") or _label_from_key(str(field_id))),
                category_hint=raw_definition.get("category_hint"),
                types=_as_string_list(raw_definition.get("types")) or ["string"],
                priority=str(raw_definition.get("priority") or "normal"),
                graphql_paths=_unique([*graphql_paths, *(key for key in keys if "." in key)]),
                realtime_keys=_unique([*realtime_keys, *(key for key in keys if "." not in key)]),
                json_schema_paths=json_schema_paths,
                csv_keys=csv_keys,
                aliases=_unique([*aliases, *ui_labels]),
                options=_as_string_list(raw_definition.get("options")),
                derived_from=_as_string_list(raw_definition.get("derived_from")),
            )
        )


def _load_canonical_mapping(registry: FieldRegistry, path: Path) -> None:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        return

    for field_id, raw_definition in payload.items():
        if not isinstance(raw_definition, dict):
            continue
        graphql_paths = _as_string_list(raw_definition.get("graphql_paths"))
        if raw_definition.get("graphql_path"):
            graphql_paths.append(str(raw_definition["graphql_path"]))
        realtime_keys = _as_string_list(raw_definition.get("realtime_keys"))
        if raw_definition.get("realtime_key"):
            realtime_keys.append(str(raw_definition["realtime_key"]))
        registry.add_definition(
            FieldDefinition(
                id=str(field_id),
                label=str(raw_definition.get("label") or _label_from_key(str(field_id))),
                category_hint=raw_definition.get("category_hint"),
                types=_as_string_list(raw_definition.get("types")) or ["string"],
                priority=str(raw_definition.get("priority") or "normal"),
                graphql_paths=graphql_paths,
                realtime_keys=realtime_keys,
                aliases=_as_string_list(raw_definition.get("aliases")),
                options=_as_string_list(raw_definition.get("options")),
            )
        )


def _load_core_field_mapping(registry: FieldRegistry, path: Path) -> None:
    mappings = load_core_field_mappings(path)
    field_name_counts: dict[str, int] = {}
    for mapping in mappings:
        field_name_counts[mapping.field_name] = field_name_counts.get(mapping.field_name, 0) + 1
    dynamic_definitions: list[FieldDefinition] = []

    for mapping in mappings:
        field_id = _resolve_core_mapping_field_id(registry, mapping.lookup_paths)
        graphql_paths = _core_mapping_graphql_paths(mapping, field_name_counts, bool(field_id))
        definition = FieldDefinition(
            id=field_id or _core_mapping_field_id(mapping, field_name_counts),
            label=mapping.label,
            category_hint=mapping.category_hint,
            types=mapping.field_types,
            graphql_paths=graphql_paths,
            aliases=_core_mapping_aliases(mapping, field_name_counts, bool(field_id)),
            options=mapping.options,
            derived_from=[f"{mapping.table}.{mapping.field_name}"],
        )
        if field_id:
            registry.add_definition(definition)
        else:
            dynamic_definitions.append(definition)

    for definition in dynamic_definitions:
        registry.add_definition(definition)


def _core_mapping_field_id(
    mapping,
    field_name_counts: dict[str, int],
) -> str:
    if field_name_counts.get(mapping.field_name, 0) == 1:
        return mapping.field_name
    return _dynamic_core_field_id(mapping.table, mapping.field_name)


def _core_mapping_graphql_paths(
    mapping,
    field_name_counts: dict[str, int],
    resolved_existing_field: bool,
) -> list[str]:
    if resolved_existing_field or field_name_counts.get(mapping.field_name, 0) == 1:
        return list(mapping.graphql_paths)
    return [path for path in mapping.graphql_paths if path != mapping.field_name]


def _core_mapping_aliases(
    mapping,
    field_name_counts: dict[str, int],
    resolved_existing_field: bool,
) -> list[str]:
    if resolved_existing_field or field_name_counts.get(mapping.field_name, 0) == 1:
        return list(mapping.aliases)
    ambiguous = {
        mapping.field_name.lower(),
        mapping.label.lower(),
        mapping.label.lower().replace(" ", "_"),
    }
    return [
        alias
        for alias in mapping.aliases
        if alias.lower().replace(" ", "_") not in ambiguous
    ]


def _resolve_core_mapping_field_id(
    registry: FieldRegistry,
    lookup_paths: list[str],
) -> str | None:
    for path in lookup_paths:
        field_id = registry.resolve(path)
        if field_id:
            return field_id
    return None


def _mark_priority_fields(registry: FieldRegistry) -> None:
    priority_paths = _load_json(PRIORITY_FIELDS_PATH, [])
    if not isinstance(priority_paths, list):
        return
    for raw_path in priority_paths:
        path = str(raw_path).strip()
        field_id = registry.resolve(path)
        if not field_id:
            continue
        definition = registry.definitions.get(field_id)
        if definition:
            definition.priority = "high"


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    candidate = str(value).strip()
    return [candidate] if candidate else []


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _higher_priority(left: str, right: str) -> str:
    order = {"low": 0, "normal": 1, "medium": 2, "high": 3}
    return left if order.get(left, 1) >= order.get(right, 1) else right


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        unique_values.append(candidate)
    return unique_values


def _normalize_lookup_key(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    normalized = re.sub(r"\[\d+\]", "", normalized).strip(".")
    return normalized


def _dynamic_field_id(path: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    return f"dynamic_{sanitized}" if sanitized else "dynamic_field"


def _dynamic_core_field_id(table: str, field_name: str) -> str:
    return _dynamic_field_id(f"{table}.{field_name}")


def _label_from_key(value: str) -> str:
    key = str(value).split(".")[-1]
    return re.sub(r"[_\s]+", " ", key).strip().title()
