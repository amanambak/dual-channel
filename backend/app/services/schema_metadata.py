import csv
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SchemaFieldSpec:
    name: str
    meaning: str
    types: tuple[str, ...]
    enum_values: tuple[str, ...] = ()

    def prompt_description(self) -> str:
        parts = [f"type={','.join(self.types)}"]
        if self.enum_values:
            parts.append(f"allowed={','.join(self.enum_values)}")
        if self.meaning:
            parts.append(self.meaning)
        return " | ".join(parts)


@dataclass
class SchemaMetadata:
    fields: dict[str, str] = field(default_factory=dict)
    flat_keys: dict[str, str] = field(default_factory=dict)
    field_types: dict[str, str] = field(default_factory=dict)
    field_type_options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    field_enum_values: dict[str, tuple[str, ...]] = field(default_factory=dict)


class SchemaMetadataLoader:
    def __init__(self, csv_path: Path, json_path: Path) -> None:
        self.csv_path = csv_path
        self.json_path = json_path

    def load(self) -> SchemaMetadata:
        metadata = SchemaMetadata()

        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    raw_field = (row.get("Field") or "").strip()
                    meaning = (row.get("Meaning") or "").strip()
                    for field_name in self._split_field_names(raw_field):
                        metadata.fields.setdefault(field_name, meaning)
                        metadata.flat_keys.setdefault(field_name, field_name)
                        if field_name.startswith("know_"):
                            metadata.fields.setdefault(field_name, "Known field")

        if self.json_path.exists():
            with self.json_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._walk_json_schema(payload, path_parts=[], metadata=metadata)

        return metadata

    def _walk_json_schema(
        self,
        node: dict,
        path_parts: list[str],
        metadata: SchemaMetadata,
    ) -> None:
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            return

        for key, value in properties.items():
            if not isinstance(value, dict):
                continue
            current_path_parts = [*path_parts, key]
            field_types = self._normalize_schema_types(value.get("type"))
            field_type = field_types[0]

            if field_type == "object" and isinstance(value.get("properties"), dict):
                self._walk_json_schema(value, current_path_parts, metadata)
                continue

            full_path = ".".join(current_path_parts)
            metadata.fields.setdefault(key, f"Schema field of type {field_type}")
            metadata.flat_keys[key] = full_path
            metadata.field_types[key] = field_type
            metadata.field_type_options[key] = field_types
            metadata.field_enum_values[key] = tuple(str(item) for item in value.get("enum", ()))

    def _normalize_schema_types(self, schema_type: object) -> tuple[str, ...]:
        if isinstance(schema_type, list):
            normalized = tuple(
                item.lower()
                for item in schema_type
                if isinstance(item, str) and item.strip()
            )
            return normalized or ("string",)
        if isinstance(schema_type, str):
            return (schema_type.lower(),)
        return ("string",)

    def _split_field_names(self, raw_field: str) -> list[str]:
        if not raw_field:
            return []
        if "/" in raw_field:
            return [part.strip() for part in raw_field.split("/") if part.strip()]
        return [raw_field]
