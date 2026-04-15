import csv
import json
from functools import lru_cache
from pathlib import Path


class SchemaRegistry:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2]
        self.csv_path = self.base_dir / "home_loan_schema.csv"
        self.json_path = self.base_dir / "customer_info.json"
        self.fields = self._load_fields()

    def _load_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}

        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    raw_field = (row.get("Field") or "").strip()
                    meaning = (row.get("Meaning") or "").strip()
                    for field in self._split_field_names(raw_field):
                        fields.setdefault(field, meaning)

        if self.json_path.exists():
            with self.json_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._walk_json_schema(payload, fields)

        return fields

    def _walk_json_schema(self, node: dict, fields: dict[str, str]) -> None:
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            return

        for key, value in properties.items():
            if not isinstance(value, dict):
                continue
            if value.get("type") == "object":
                self._walk_json_schema(value, fields)
            else:
                field_type = value.get("type", "string")
                fields.setdefault(key, f"Schema field of type {field_type}")

    def _split_field_names(self, raw_field: str) -> list[str]:
        if not raw_field:
            return []
        if "/" in raw_field:
            return [part.strip() for part in raw_field.split("/") if part.strip()]
        return [raw_field]

    def format_for_prompt(self) -> str:
        return "\n".join(f"- {field}: {meaning}" for field, meaning in sorted(self.fields.items()))


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    return SchemaRegistry()
