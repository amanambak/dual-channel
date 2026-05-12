import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "lead_workflow_schema.json"


@dataclass(frozen=True)
class WorkflowSchema:
    version: int
    categories: list[dict[str, Any]]

    def category(self, category_id: str | None) -> dict[str, Any] | None:
        if not category_id:
            return None
        for category in self.categories:
            if category.get("id") == category_id:
                return category
        return None

    def category_for_field(self, field_id: str) -> str | None:
        for category in self.categories:
            if field_id in fields_for_category(category):
                return str(category.get("id"))
        return None

    def fields_for_category(self, category_id: str) -> list[str]:
        category = self.category(category_id)
        return fields_for_category(category) if category else []

    def ordered_category_ids(self) -> list[str]:
        return [
            str(category.get("id"))
            for category in sorted(
                self.categories,
                key=lambda item: int(item.get("priority") or 999),
            )
            if category.get("id")
        ]


@lru_cache(maxsize=1)
def load_workflow_schema() -> WorkflowSchema:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    categories = payload.get("categories") if isinstance(payload, dict) else []
    return WorkflowSchema(
        version=int(payload.get("version") or 1),
        categories=[item for item in categories if isinstance(item, dict)],
    )


def category_for_field(field_id: str) -> str | None:
    return load_workflow_schema().category_for_field(field_id)


def fields_for_category(category: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    fields.extend(_as_list(category.get("base_required_fields")))
    fields.extend(_as_list(category.get("field_priority")))
    for section in _as_list(category.get("sections")):
        if isinstance(section, dict):
            fields.extend(_as_list(section.get("fields")))
    for branch in _as_list(category.get("branches")):
        if isinstance(branch, dict):
            fields.extend(_as_list(branch.get("required_fields")))
            fields.extend(_condition_fields(branch.get("when")))
    return _unique(fields)


def _condition_fields(condition: Any) -> list[str]:
    if not isinstance(condition, dict):
        return []
    fields: list[str] = []
    if condition.get("field"):
        fields.append(str(condition["field"]))
    for key in ("all", "any"):
        for nested in _as_list(condition.get(key)):
            fields.extend(_condition_fields(nested))
    return fields


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result
