import re
from dataclasses import dataclass
from typing import Any

from app.services.field_registry import get_field_registry
from app.services.workflow_schema import WorkflowSchema
from app.services.workflow_schema import load_workflow_schema


@dataclass(frozen=True)
class CategoryRoute:
    category: str | None
    confidence: float
    reason: str
    scores: dict[str, float]
    needs_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "reason": self.reason,
            "scores": dict(self.scores),
            "needs_llm": self.needs_llm,
        }


def route_category(
    utterance: str,
    extracted_fields: dict[str, Any] | None,
    field_state: dict[str, Any] | None,
    previous_category: str | None,
    agent_last_utterance: str = "",
    *,
    workflow_state: dict[str, Any] | None = None,
    schema: WorkflowSchema | None = None,
) -> CategoryRoute:
    workflow_schema = schema or load_workflow_schema()
    registry = get_field_registry()
    normalized_utterance = _normalize(utterance)
    normalized_agent = _normalize(agent_last_utterance)
    resolved_extracted = {
        registry.resolve(str(field)) or str(field)
        for field in (extracted_fields or {}).keys()
    }
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    extracted_categories = _categories_for_fields(workflow_schema, resolved_extracted)

    for category in workflow_schema.categories:
        category_id = str(category.get("id") or "")
        if not category_id:
            continue
        score = 0.0
        reason_parts: list[str] = []

        triggers = [str(item).lower() for item in category.get("topic_triggers") or []]
        if any(_trigger_matches(normalized_utterance, trigger) for trigger in triggers):
            score += 0.50
            reason_parts.append("topic trigger matched")

        category_fields = set(workflow_schema.fields_for_category(category_id))
        if resolved_extracted & category_fields:
            score += 0.55
            reason_parts.append("new field belongs to category")

        has_current_field_signal = bool(extracted_categories)
        category_has_current_field = category_id in extracted_categories
        should_use_previous_context = not has_current_field_signal or category_has_current_field

        if should_use_previous_context and any(
            _trigger_matches(normalized_agent, trigger) for trigger in triggers
        ):
            score += 0.30
            reason_parts.append("agent last question targeted category")

        if should_use_previous_context and previous_category == category_id:
            score += 0.15
            reason_parts.append("continuing active category")

        category_state = (workflow_state or {}).get("category_state", {}).get(category_id, {})
        if category_state.get("status") == "complete":
            score -= 0.30
            reason_parts.append("category already complete")

        priority = int(category.get("priority") or 999)
        if category_state.get("status") != "complete":
            score += max(0.0, (100 - priority) / 1000)

        scores[category_id] = round(score, 4)
        reasons[category_id] = reason_parts

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return CategoryRoute(
            category=previous_category or workflow_schema.ordered_category_ids()[0],
            confidence=0.0,
            reason="no deterministic signal",
            scores=scores,
            needs_llm=False,
        )

    top_category, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = min(0.99, max(0.0, top_score))
    needs_llm = top_score < 0.55 or (top_score - second_score) < 0.15

    return CategoryRoute(
        category=top_category,
        confidence=confidence,
        reason=", ".join(reasons.get(top_category) or ["highest deterministic score"]),
        scores=scores,
        needs_llm=needs_llm and top_score > 0.2,
    )


def _categories_for_fields(schema: WorkflowSchema, field_ids: set[str]) -> set[str]:
    if not field_ids:
        return set()

    categories: set[str] = set()
    for category in schema.categories:
        category_id = str(category.get("id") or "")
        if category_id and field_ids & set(schema.fields_for_category(category_id)):
            categories.add(category_id)
    return categories


def _trigger_matches(normalized_text: str, trigger: str) -> bool:
    normalized_trigger = _normalize(trigger)
    if not normalized_trigger:
        return False
    if " " in normalized_trigger:
        return normalized_trigger in normalized_text
    return normalized_trigger in set(normalized_text.split())


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()
