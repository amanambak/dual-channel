import re
from dataclasses import dataclass
from typing import Any

from app.services.field_registry import FieldDefinition
from app.services.field_registry import FieldRegistry
from app.services.field_registry import get_field_registry
from app.services.field_spec import FieldSpec
from app.services.workflow_schema import WorkflowSchema
from app.services.workflow_schema import load_workflow_schema


DEFAULT_MAX_EXTRACTION_FIELDS = 40


@dataclass(frozen=True)
class ExtractionFieldSelection:
    specs: dict[str, FieldSpec]

    @property
    def field_ids(self) -> list[str]:
        return list(self.specs)

    def format_for_prompt(self) -> str:
        return "\n".join(
            f"- {field_id}: {spec.prompt_description()}"
            for field_id, spec in self.specs.items()
        )


def select_extraction_fields(
    *,
    utterance: str,
    agent_utterance: str = "",
    known_fields: dict[str, Any] | None = None,
    expected_field: str | None = None,
    active_category: str | None = None,
    workflow_state: dict[str, Any] | None = None,
    max_fields: int = DEFAULT_MAX_EXTRACTION_FIELDS,
    registry: FieldRegistry | None = None,
    workflow_schema: WorkflowSchema | None = None,
) -> ExtractionFieldSelection:
    active_registry = registry or get_field_registry()
    active_workflow = workflow_schema or load_workflow_schema()
    ordered_ids = _ordered_candidate_ids(
        utterance=utterance,
        agent_utterance=agent_utterance,
        known_fields=known_fields or {},
        expected_field=expected_field,
        active_category=active_category,
        workflow_state=workflow_state or {},
        registry=active_registry,
        workflow_schema=active_workflow,
    )
    specs: dict[str, FieldSpec] = {}
    for field_id in ordered_ids:
        definition = active_registry.definition(field_id)
        if not definition or definition.id in specs:
            continue
        specs[definition.id] = field_spec_from_definition(definition)
        if len(specs) >= max_fields:
            break
    return ExtractionFieldSelection(specs=specs)


def field_spec_from_definition(definition: FieldDefinition) -> FieldSpec:
    return FieldSpec(
        name=definition.id,
        meaning=_definition_prompt_description(definition),
        types=tuple(definition.types or ["string"]),
        enum_values=tuple(definition.options or ()),
    )


def format_field_registry_for_prompt(field_ids: list[str] | None = None) -> str:
    registry = get_field_registry()
    selected_ids = field_ids or sorted(registry.definitions)
    lines: list[str] = []
    for field_id in selected_ids:
        definition = registry.definition(field_id)
        if not definition:
            continue
        spec = field_spec_from_definition(definition)
        lines.append(f"- {definition.id}: {spec.prompt_description()}")
    return "\n".join(lines)


def _ordered_candidate_ids(
    *,
    utterance: str,
    agent_utterance: str,
    known_fields: dict[str, Any],
    expected_field: str | None,
    active_category: str | None,
    workflow_state: dict[str, Any],
    registry: FieldRegistry,
    workflow_schema: WorkflowSchema,
) -> list[str]:
    candidates: list[str] = []

    candidates.extend(_resolve_many([expected_field], registry))
    candidates.extend(_last_action_fields(workflow_state, registry))
    candidates.extend(_workflow_state_fields(workflow_state, active_category, registry))

    expected_category = workflow_schema.category_for_field(str(expected_field or ""))
    category_ids = _unique([active_category, expected_category])
    for category_id in category_ids:
        candidates.extend(_resolve_many(workflow_schema.fields_for_category(category_id), registry))

    candidates.extend(_text_matched_fields(utterance, agent_utterance, registry))
    candidates.extend(_known_field_neighbors(known_fields, registry, workflow_schema))
    candidates.extend(_priority_workflow_fields(workflow_schema, registry))

    return _unique(candidates)


def _last_action_fields(
    workflow_state: dict[str, Any],
    registry: FieldRegistry,
) -> list[str]:
    action = workflow_state.get("last_next_action")
    if not isinstance(action, dict):
        return []
    return _resolve_many([action.get("field")], registry)


def _workflow_state_fields(
    workflow_state: dict[str, Any],
    active_category: str | None,
    registry: FieldRegistry,
) -> list[str]:
    category_state = workflow_state.get("category_state")
    if not isinstance(category_state, dict):
        return []

    selected_states: list[dict[str, Any]] = []
    if active_category and isinstance(category_state.get(active_category), dict):
        selected_states.append(category_state[active_category])
    for state in category_state.values():
        if isinstance(state, dict) and state.get("status") != "complete":
            selected_states.append(state)

    fields: list[str] = []
    for state in selected_states:
        fields.extend(_as_list(state.get("next_field")))
        fields.extend(_as_list(state.get("missing_fields")))
        fields.extend(_as_list(state.get("base_missing_fields")))
        fields.extend(_as_list(state.get("branch_missing_fields")))
    return _resolve_many(fields, registry)


def _text_matched_fields(
    utterance: str,
    agent_utterance: str,
    registry: FieldRegistry,
) -> list[str]:
    tokens = _token_set(f"{agent_utterance} {utterance}")
    if not tokens:
        return []

    scored: list[tuple[int, str]] = []
    for definition in registry.definitions.values():
        score = _definition_match_score(definition, tokens)
        if score > 0:
            scored.append((score, definition.id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [field_id for _score, field_id in scored]


def _known_field_neighbors(
    known_fields: dict[str, Any],
    registry: FieldRegistry,
    workflow_schema: WorkflowSchema,
) -> list[str]:
    neighbors: list[str] = []
    for key in known_fields:
        field_id = registry.resolve(str(key))
        category_id = workflow_schema.category_for_field(field_id or str(key))
        if category_id:
            neighbors.extend(workflow_schema.fields_for_category(category_id))
    return _resolve_many(neighbors, registry)


def _priority_workflow_fields(
    workflow_schema: WorkflowSchema,
    registry: FieldRegistry,
) -> list[str]:
    fields: list[str] = []
    for category_id in workflow_schema.ordered_category_ids():
        category = workflow_schema.category(category_id)
        if not category:
            continue
        fields.extend(_as_list(category.get("field_priority")))
        fields.extend(_as_list(category.get("base_required_fields")))
    return _resolve_many(fields, registry)


def _definition_match_score(definition: FieldDefinition, tokens: set[str]) -> int:
    score = 0
    searchable_parts = [
        definition.id,
        definition.label,
        *definition.aliases,
        *definition.realtime_keys,
        *definition.graphql_paths,
        *definition.csv_keys,
    ]
    for part in searchable_parts:
        part_tokens = _token_set(part)
        if not part_tokens:
            continue
        overlap = tokens & part_tokens
        if overlap:
            score += len(overlap)
        if part_tokens and part_tokens <= tokens:
            score += 3
    return score


def _definition_prompt_description(definition: FieldDefinition) -> str:
    parts = [definition.label]
    if definition.category_hint:
        parts.append(f"category={definition.category_hint}")
    if definition.realtime_keys:
        parts.append(f"accepted_keys={','.join(definition.realtime_keys[:6])}")
    if definition.graphql_paths:
        parts.append(f"db_paths={','.join(definition.graphql_paths[:4])}")
    if definition.aliases:
        parts.append(f"meaning={'; '.join(definition.aliases[:6])}")
    return " | ".join(part for part in parts if part)


def _resolve_many(values: list[Any], registry: FieldRegistry) -> list[str]:
    resolved: list[str] = []
    for value in values:
        if value is None:
            continue
        field_id = registry.resolve(str(value)) or str(value)
        if registry.definition(field_id):
            resolved.append(field_id)
    return resolved


def _token_set(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if len(token) >= 2
    }


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result
