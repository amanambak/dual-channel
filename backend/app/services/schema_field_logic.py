import re
from collections import defaultdict


class SchemaFieldLogic:
    def __init__(
        self,
        fields: dict[str, str],
        flat_keys: dict[str, str],
        field_types: dict[str, str],
    ) -> None:
        self.fields = fields
        self.flat_keys = flat_keys
        self.field_types = field_types

    def build_field_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)

        for field in self.fields:
            group_name = self.field_group_name(field)
            if field not in groups[group_name]:
                groups[group_name].append(field)

        return dict(groups)

    def field_group_name(self, field: str) -> str:
        path = self.flat_keys.get(field, field)
        if "." in path:
            return path.split(".", 1)[0]
        if "_" in field:
            return field.split("_", 1)[0]
        return field

    def is_boolean_field(self, field: str) -> bool:
        return field.startswith("is_") or self.field_types.get(field) == "boolean"

    def generate_triggers(self) -> dict[str, list[str]]:
        return {field: self.generate_field_triggers(field) for field in self.fields}

    def generate_field_triggers(self, field: str) -> list[str]:
        triggers: list[str] = []
        base_keywords = [
            keyword.lower()
            for keyword in re.split(r"[_\s]+", field)
            if keyword and keyword.lower() not in self.ignored_trigger_tokens()
        ]

        def add_keywords(values: list[str]) -> None:
            for value in values:
                keyword = value.strip().lower()
                if keyword and keyword not in triggers:
                    triggers.append(keyword)

        add_keywords(base_keywords)

        if any(keyword in {"amount", "value"} for keyword in base_keywords):
            add_keywords(["lakh", "crore", "price"])

        if any(keyword in {"salary", "income"} for keyword in base_keywords):
            add_keywords(["salary", "income", "mahina"])

        if "property" in base_keywords:
            add_keywords(["ghar", "flat"])

        if "emi" in base_keywords:
            add_keywords(["emi"])

        if "loan" in base_keywords:
            add_keywords(["loan"])

        if "cibil" in base_keywords:
            add_keywords(["cibil", "credit score"])

        if self.is_boolean_field(field):
            add_keywords(["yes", "no", "haan", "nahi"])

        return triggers

    def normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def trigger_matches(self, normalized_text: str, trigger: str) -> bool:
        if not trigger:
            return False

        if " " in trigger:
            return trigger in normalized_text

        words = set(normalized_text.split())
        return trigger in words

    def field_token_set(self, field: str) -> set[str]:
        return {
            token
            for token in re.split(r"[_\s]+", field.lower())
            if token and token not in self.ignored_field_tokens()
        }

    def ignored_trigger_tokens(self) -> set[str]:
        return {*self.ignored_field_tokens(), "yes", "no"}

    def ignored_field_tokens(self) -> set[str]:
        return {"is", "a", "an", "and", "of", "or", "the", "to", "for"}
