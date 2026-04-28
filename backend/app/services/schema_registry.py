from functools import lru_cache
from pathlib import Path

from app.services.schema_extraction import SchemaExtractionSupport
from app.services.schema_field_logic import SchemaFieldLogic
from app.services.schema_metadata import SchemaFieldSpec
from app.services.schema_metadata import SchemaMetadataLoader


class SchemaRegistry:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2]
        self.csv_path = self.base_dir / "home_loan_schema.csv"
        self.json_path = self.base_dir / "customer_info.json"

        metadata = SchemaMetadataLoader(self.csv_path, self.json_path).load()
        self.fields = metadata.fields
        self.flat_keys = metadata.flat_keys
        self.field_types = metadata.field_types
        self.field_type_options = metadata.field_type_options
        self.field_enum_values = metadata.field_enum_values

        self.field_logic = SchemaFieldLogic(self.fields, self.flat_keys, self.field_types)
        self.field_groups = self.field_logic.build_field_groups()
        self.field_triggers = self.field_logic.generate_triggers()
        self.extraction_support = SchemaExtractionSupport(
            self.fields,
            self.field_triggers,
            self.field_logic,
        )

    def build_local_field_updates(self, text: str, state: dict) -> dict[str, str]:
        return self.extraction_support.build_local_field_updates(text, state)

    def select_candidate_fields(self, text: str, state: dict) -> dict[str, str]:
        return self.extraction_support.select_candidate_fields(text, state)

    def detect_triggered_fields(self, text: str, state: dict) -> list[str]:
        return self.extraction_support.detect_triggered_fields(text, state)

    def get_missing_fields(self, state: dict) -> dict[str, None]:
        filled_fields = set((state or {}).keys())
        return {field: None for field in self.fields if field not in filled_fields}

    def format_for_prompt(self) -> str:
        return "\n".join(
            f"- {field}: {self.get_field_spec(field).prompt_description()}"
            for field in sorted(self.fields)
        )

    def get_field_spec(self, field: str) -> SchemaFieldSpec:
        return SchemaFieldSpec(
            name=field,
            meaning=self.fields.get(field, "Schema field"),
            types=self.field_type_options.get(field, ("string",)),
            enum_values=self.field_enum_values.get(field, ()),
        )


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    return SchemaRegistry()
