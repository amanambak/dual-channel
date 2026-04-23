import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
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


class SchemaRegistry:
    def __init__(self) -> None:
        self.base_dir = Path(__file__).resolve().parents[2]
        self.csv_path = self.base_dir / "home_loan_schema.csv"
        self.json_path = self.base_dir / "customer_info.json"
        self.fields: dict[str, str] = {}
        self.flat_keys: dict[str, str] = {}
        self.field_groups: dict[str, list[str]] = {}
        self.field_triggers: dict[str, list[str]] = {}
        self.field_types: dict[str, str] = {}
        self.field_type_options: dict[str, tuple[str, ...]] = {}
        self.field_enum_values: dict[str, tuple[str, ...]] = {}

        self._load_fields()
        self._build_field_groups()
        self._generate_triggers()

    def _load_fields(self) -> None:
        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    raw_field = (row.get("Field") or "").strip()
                    meaning = (row.get("Meaning") or "").strip()
                    for field in self._split_field_names(raw_field):
                        self.fields.setdefault(field, meaning)
                        self.flat_keys.setdefault(field, field)
                        if field.startswith("know_"):
                            self.fields.setdefault(field, "Known field")

        if self.json_path.exists():
            with self.json_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._walk_json_schema(payload, path_parts=[])

    def _walk_json_schema(self, node: dict, path_parts: list[str]) -> None:
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
                self._walk_json_schema(value, current_path_parts)
                continue

            full_path = ".".join(current_path_parts)
            self.fields.setdefault(key, f"Schema field of type {field_type}")
            self.flat_keys[key] = full_path
            self.field_types[key] = field_type
            self.field_type_options[key] = field_types
            self.field_enum_values[key] = tuple(str(item) for item in value.get("enum", ()))

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

    def _build_field_groups(self) -> None:
        groups: dict[str, list[str]] = defaultdict(list)

        for field in self.fields:
            path = self.flat_keys.get(field, field)
            if "." in path:
                group_name = path.split(".", 1)[0]
            elif "_" in field:
                group_name = field.split("_", 1)[0]
            else:
                group_name = field

            if field not in groups[group_name]:
                groups[group_name].append(field)

        self.field_groups = dict(groups)

    def _field_group_name(self, field: str) -> str:
        path = self.flat_keys.get(field, field)
        if "." in path:
            return path.split(".", 1)[0]
        if "_" in field:
            return field.split("_", 1)[0]
        return field

    def _is_boolean_field(self, field: str) -> bool:
        return field.startswith("is_") or self.field_types.get(field) == "boolean"

    def _generate_triggers(self) -> None:
        self.field_triggers = {
            field: self._generate_field_triggers(field) for field in self.fields
        }

    def _generate_field_triggers(self, field: str) -> list[str]:
        triggers: list[str] = []
        ignore_keywords = {
            "is","a","an","and","of","or","the","to","for","yes","no",
        }
        base_keywords = [
            keyword.lower()
            for keyword in re.split(r"[_\s]+", field)
            if keyword and keyword.lower() not in ignore_keywords
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

        field_type = self.field_types.get(field, "")
        if field.startswith("is_") or field_type == "boolean":
            add_keywords(["yes", "no", "haan", "nahi"])

        return triggers

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def _trigger_matches(self, normalized_text: str, trigger: str) -> bool:
        if not trigger:
            return False

        if " " in trigger:
            return trigger in normalized_text

        words = set(normalized_text.split())
        return trigger in words

    def _normalize_value(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip(" ,.;:-")

    def _extract_yes_no_value(self, text: str) -> str | None:
        normalized = self._normalize_text(text)
        tokens = set(normalized.split())

        positive_tokens = {
            "yes",
            "y",
            "haan",
            "han",
            "ji",
            "ok",
            "okay",
            "confirmed",
            "confirm",
            "done",
            "available",
            "true",
        }
        negative_tokens = {
            "no",
            "nahin",
            "nahi",
            "nai",
            "not",
            "none",
            "false",
            "dont",
            "doesnt",
        }

        if tokens & positive_tokens and not tokens & negative_tokens:
            return "yes"
        if tokens & negative_tokens and not tokens & positive_tokens:
            return "no"
        return None

    def _extract_numeric_value(self, text: str) -> str | None:
        cleaned = text.replace(",", " ")
        patterns = [
            r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k|months?|years?)?\b",
            r"(?P<number>\d{1,3}(?:\s+\d{2,3})+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                number = match.group("number").replace(" ", "")
                unit = (match.groupdict().get("unit") or "").lower()
                try:
                    numeric_value = float(number)
                except ValueError:
                    return number
                if unit in {"crore", "cr"}:
                    return str(int(numeric_value * 10000000))
                if unit in {"lakh", "lac", "lakhs", "lacs"}:
                    return str(int(numeric_value * 100000))
                if unit in {"thousand", "k"}:
                    return str(int(numeric_value * 1000))
                if unit in {"month", "months"}:
                    return str(int(numeric_value))
                if unit in {"year", "years"}:
                    return str(int(numeric_value))
                return str(int(numeric_value)) if numeric_value.is_integer() else str(numeric_value)
        return None

    def _extract_location_value(self, text: str) -> str | None:
        patterns = [
            r"(?:property\s+)?\b(?:location|city|area|address|place|in|at|from|near)\b\s+(?P<value>[A-Za-z][A-Za-z0-9\s-]{1,40})",
            r"(?P<prefix>[A-Za-z][A-Za-z0-9\s-]{1,80}?)\s+(?:me|mein|main)\s+(?:property|ghar|flat|plot)\b",
            r"(?:located\s+in|based\s+in|living\s+in|residing\s+in)\s+(?P<value>[A-Za-z][A-Za-z0-9\s-]{1,40})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.groupdict().get("value") or match.groupdict().get("prefix") or ""
                value = self._normalize_value(value)
                value = self._cleanup_location_phrase(value)
                value = re.split(r"\b(?:and|or|but|with|for|to|from)\b", value, maxsplit=1)[0]
                value = self._normalize_value(value)
                if value:
                    return value
        return None

    def _cleanup_location_phrase(self, value: str) -> str:
        tokens = value.split()
        stop_words = {
            "sir",
            "mujhe",
            "main",
            "mai",
            "mera",
            "meri",
            "mere",
            "hum",
            "hume",
            "hame",
            "ka",
            "ki",
            "ke",
            "mein",
            "me",
            "loan",
            "loans",
            "chahiye",
            "chahie",
            "requirement",
            "need",
            "needed",
            "property",
            "ghar",
            "flat",
            "plot",
            "hai",
            "hai",
            "hota",
            "hoti",
            "ho",
        }
        collected: list[str] = []
        for token in reversed(tokens):
            if token.lower() in stop_words:
                if collected:
                    break
                continue
            collected.append(token)
        cleaned = list(reversed(collected))
        if len(cleaned) > 3:
            cleaned = cleaned[-3:]
        return " ".join(cleaned)

    def _extract_pincode_value(self, text: str) -> str | None:
        match = re.search(r"\b(\d{6})\b", text)
        if match:
            return match.group(1)
        return None

    def _extract_cibil_value(self, text: str) -> str | None:
        match = re.search(r"\b(\d{3})\b", text)
        if match:
            score = int(match.group(1))
            if 300 <= score <= 900:
                return match.group(1)
        return None

    def _extract_derived_value(self, field: str, text: str) -> str | None:
        field_type = self.field_types.get(field, "")
        normalized_field = field.lower()
        normalized_text = self._normalize_text(text)

        if self._is_boolean_field(field):
            return self._extract_yes_no_value(text)

        if normalized_field == "cibil_score":
            return self._extract_cibil_value(text)

        if normalized_field in {"cibil_status", "cibil_pdf"}:
            return None

        if normalized_field in {"property_city", "property_location"}:
            return self._extract_location_value(text)

        if "pincode" in normalized_field or normalized_field.endswith("pin"):
            return self._extract_pincode_value(text)

        if normalized_field == "property_type":
            for token in ("flat", "plot", "villa", "apartment", "independent"):
                if token in normalized_text:
                    return token
            return None

        if normalized_field == "loan_amount":
            if any(token in normalized_text for token in {"loan", "budget", "requirement", "need", "needed"}):
                return self._extract_numeric_value(text)
            return None

        if normalized_field in {
            "monthly_salary",
            "gross_monthly_salary",
            "in_hand_monthly_cash_salary",
        }:
            if any(
                token in normalized_text
                for token in {"salary", "income", "mahina", "monthly", "gross", "cash"}
            ):
                return self._extract_numeric_value(text)
            return None

        if normalized_field in {"annual_income", "gross_annual_income"}:
            if any(token in normalized_text for token in {"annual", "yearly", "year", "income"}):
                return self._extract_numeric_value(text)
            return None

        if normalized_field in {
            "customer_contribution",
            "property_value",
            "expected_property_value",
            "property_agreement_value",
            "house_item_value",
            "user_paid_token_amount",
            "existing_emi_amount",
            "emi_ending_six_month",
            "login_amount",
        }:
            if any(
                token in normalized_text
                for token in {
                    "amount",
                    "value",
                    "price",
                    "cost",
                    "worth",
                    "down",
                    "payment",
                    "contribution",
                    "house",
                    "item",
                    "furniture",
                    "token",
                    "booking",
                    "paid",
                    "emi",
                }
            ):
                return self._extract_numeric_value(text)
            return None

        if normalized_field in {
            "tenure",
            "work_experience",
            "time_in_current_co",
            "business_vintage_years",
            "no_of_dependent",
        }:
            if any(
                token in normalized_text
                for token in {
                    "tenure",
                    "experience",
                    "years",
                    "months",
                    "month",
                    "dependents",
                    "dependent",
                }
            ):
                return self._extract_numeric_value(text)
            return None

        if normalized_field == "no_of_emi":
            if "emi" in normalized_text:
                return self._extract_numeric_value(text)
            return None

        return None

    def _field_token_set(self, field: str) -> set[str]:
        return {
            token
            for token in re.split(r"[_\s]+", field.lower())
            if token and token not in {"is", "a", "an", "and", "of", "or", "the", "to", "for"}
        }

    def _should_query_field(self, field: str, text: str) -> bool:
        normalized_text = self._normalize_text(text or "")
        if not normalized_text:
            return False

        normalized_field = field.lower()
        if normalized_field in {"cibil_pdf", "cibil_status"}:
            return False

        field_type = self.field_types.get(field, "")
        numeric_value_present = self._extract_numeric_value(text) is not None
        trigger_candidates = {
            trigger
            for trigger in self.field_triggers.get(field, [])
            if trigger not in {"property", "loan", "income", "salary", "lakh", "lac", "lakhs", "lacs", "crore", "cr", "thousand", "k"}
        }
        specific_trigger_present = any(
            self._trigger_matches(normalized_text, trigger)
            for trigger in trigger_candidates
        )

        if self._is_boolean_field(field):
            return False

        if specific_trigger_present:
            return True

        if normalized_field == "cibil_score":
            return self._extract_cibil_value(text) is not None or "cibil" in normalized_text

        if normalized_field in {"cibil_pdf", "cibil_status"}:
            return False

        if "pincode" in normalized_field or normalized_field.endswith("pin"):
            return self._extract_pincode_value(text) is not None

        if normalized_field in {"property_city", "property_location"}:
            return self._extract_location_value(text) is not None

        if normalized_field in {"pa_city", "cra_city"}:
            return self._extract_location_value(text) is not None and any(
                token in normalized_text
                for token in {"current", "permanent", "residential", "home", "office", "resident"}
            )

        if "state" in normalized_field or "address" in normalized_field:
            return False

        if "loan" in normalized_field:
            return numeric_value_present and ("loan" in normalized_text or specific_trigger_present)

        if "salary" in normalized_field or "income" in normalized_field:
            return numeric_value_present and any(
                token in normalized_text
                for token in {"salary", "income", "mahina", "monthly", "gross", "cash"}
            )

        if normalized_field in {
            "customer_contribution",
            "property_value",
            "expected_property_value",
            "property_agreement_value",
            "house_item_value",
            "user_paid_token_amount",
        }:
            if "property_value" in normalized_field or "expected_property_value" in normalized_field or "property_agreement_value" in normalized_field:
                return numeric_value_present and any(
                    token in normalized_text for token in {"value", "price", "cost", "worth"}
                )
            if "house_item_value" in normalized_field:
                return numeric_value_present and any(token in normalized_text for token in {"house", "item", "furniture", "value"})
            if "user_paid_token_amount" in normalized_field:
                return numeric_value_present and any(token in normalized_text for token in {"token", "booking", "paid"})
            if "customer_contribution" in normalized_field:
                return numeric_value_present and any(token in normalized_text for token in {"contribution", "down", "payment", "own", "self"})
            return False

        if normalized_field in {"existing_emi_amount", "emi_ending_six_month", "no_of_emi"}:
            return numeric_value_present and "emi" in normalized_text

        if normalized_field == "tenure":
            return numeric_value_present and any(
                token in normalized_text for token in {"tenure", "month", "months", "year", "years"}
            )

        if normalized_field in {"work_experience", "time_in_current_co", "business_vintage_years"}:
            return numeric_value_present and any(
                token in normalized_text for token in {"experience", "year", "years", "month", "months", "vintage"}
            )

        if normalized_field == "no_of_dependent":
            return numeric_value_present and "dependent" in normalized_text

        if normalized_field in {"login_amount", "registration", "house_item_value"}:
            return numeric_value_present and any(
                token in normalized_text for token in {"login", "register", "registration", "house", "token"}
            )

        return False

    def build_local_field_updates(self, text: str, state: dict) -> dict[str, str]:
        normalized_text = self._normalize_text(text or "")
        if not normalized_text:
            return {}

        current_state = state or {}
        triggered_fields = self.detect_triggered_fields(text, current_state)
        updates: dict[str, str] = {}

        for field in triggered_fields:
            if field in current_state:
                continue
            value = self._extract_derived_value(field, text)
            if value is not None and str(value).strip():
                updates[field] = str(value)

        implied_boolean_updates: dict[str, str] = {}
        for field in self.fields:
            if field in current_state or field in updates or not self._is_boolean_field(field):
                continue

            field_tokens = self._field_token_set(field) - {"is", "identified", "details"}
            if not field_tokens:
                continue

            related_hit = any(token in normalized_text for token in field_tokens)
            sibling_triggered = any(
                triggered_field != field
                and self._field_token_set(triggered_field) & field_tokens
                for triggered_field in triggered_fields
            )
            if field.startswith("is_") and related_hit and sibling_triggered:
                implied_boolean_updates[field] = "yes"

        updates.update(implied_boolean_updates)
        return updates

    def select_candidate_fields(self, text: str, state: dict) -> dict[str, str]:
        current_state = state or {}
        local_updates = self.build_local_field_updates(text, current_state)
        candidate_fields: dict[str, str] = {}

        for field in self.fields:
            if field in current_state or field in local_updates:
                continue
            if self._should_query_field(field, text):
                candidate_fields[field] = self.fields[field]

        if not candidate_fields:
            return {}

        return candidate_fields

    def detect_triggered_fields(self, text: str, state: dict) -> list[str]:
        normalized_text = self._normalize_text(text or "")
        if not normalized_text:
            return []

        filled_fields = set((state or {}).keys())
        triggered_fields: list[str] = []

        for field, triggers in self.field_triggers.items():
            if field in filled_fields:
                continue
            if any(self._trigger_matches(normalized_text, trigger) for trigger in triggers):
                triggered_fields.append(field)

        return triggered_fields

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
