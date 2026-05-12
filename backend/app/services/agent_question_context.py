import re
from typing import Any

from app.models.session import SessionState
from app.services.field_registry import get_field_registry


def current_spoken_expected_field(state: SessionState) -> str | None:
    action = state.last_next_action or {}
    if not isinstance(action, dict):
        return None

    field = action.get("field")
    if not isinstance(field, str) or not field.strip():
        return None

    created_after_agent_turns = _int_or_none(action.get("_created_after_agent_turns"))
    if (
        created_after_agent_turns is not None
        and len(state.agent_history) <= created_after_agent_turns
    ):
        return None

    if not agent_utterance_matches_field(state.agent_last_utterance, field, action):
        return None

    return field


def stamp_next_action(action: dict[str, Any], state: SessionState) -> dict[str, Any]:
    stamped = dict(action)
    stamped["_created_after_agent_turns"] = len(state.agent_history)
    return stamped


def agent_utterance_matches_field(
    agent_utterance: str,
    field_id: str,
    action: dict[str, Any] | None = None,
) -> bool:
    agent_tokens = _token_set(agent_utterance)
    if not agent_tokens or not _looks_like_question_or_request(agent_utterance):
        return False

    reference_tokens = _field_reference_tokens(field_id, action or {})
    if not reference_tokens:
        return False

    overlap = agent_tokens & reference_tokens
    if len(overlap) >= 2:
        return True

    strong_tokens = reference_tokens - _WEAK_FIELD_TOKENS
    return bool(overlap & strong_tokens)


def _field_reference_tokens(field_id: str, action: dict[str, Any]) -> set[str]:
    registry = get_field_registry()
    definition = registry.definition(field_id)
    parts = [
        field_id,
        action.get("label"),
        action.get("question"),
    ]
    if definition:
        parts.extend(
            [
                definition.id,
                definition.label,
                *definition.aliases,
                *definition.realtime_keys,
                *definition.keys,
            ]
        )
    return _token_set(" ".join(str(part or "") for part in parts))


def _looks_like_question_or_request(text: str) -> bool:
    normalized = str(text or "").lower()
    return bool(
        "?" in normalized
        or re.search(
            r"\b(kya|what|which|confirm|bata|bataye|bataiye|dijiye|please)\b",
            normalized,
        )
        or re.search(r"(क्या|बत|दीजिए|कन्फर्म|कंफर्म)", normalized)
    )


def _token_set(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if len(token) >= 2
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_WEAK_FIELD_TOKENS = {
    "applicant",
    "borrower",
    "customer",
    "confirm",
    "current",
    "details",
    "field",
    "please",
    "required",
    "sir",
}
