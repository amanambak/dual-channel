import re

from app.services.field_registry import get_field_registry
from app.services.schema_normalizer import derive_extracted_fields
from app.services.schema_normalizer import normalize_date_value
from app.services.schema_normalizer import normalize_extracted_fields
from app.services.schema_normalizer import normalize_pan_value

_CURRENT_ADDRESS_KEYS = {"customer_city", "customer_state", "customer_pincode"}
_PROPERTY_LOCATION_KEYS = {"property_city", "property_state", "property_pincode"}
_NAME_KEYS = {"customer_first_name", "customer_last_name"}
_ADDRESS_DETAIL_KEYS = {
    "customer_address_line1",
    "customer_address_line2",
    "property_address1",
    "property_address2",
}


def normalize_contextual_extracted_fields(
    raw_fields: dict[str, object],
    *,
    expected_field: str | None = None,
    utterance: str = "",
    agent_utterance: str = "",
) -> dict[str, str]:
    normalized = normalize_extracted_fields(raw_fields)
    allowed_keys = _allowed_keys_for_expected_field(expected_field)
    normalized.update(_fallback_allowed_fields(raw_fields, allowed_keys))
    normalized.update(_fallback_strict_standalone_fields(raw_fields))
    normalized = _filter_contextually_unsafe_fields(
        normalized,
        allowed_keys,
        utterance=utterance,
        agent_utterance=agent_utterance,
    )
    derive_extracted_fields(normalized)
    return normalized


def _allowed_keys_for_expected_field(expected_field: str | None) -> set[str]:
    if not expected_field:
        return set()
    registry = get_field_registry()
    resolved = registry.resolve(expected_field) or expected_field
    definition = registry.definition(resolved)
    return {definition.id if definition else resolved}


def _fallback_allowed_fields(
    raw_fields: dict[str, object],
    allowed_keys: set[str],
) -> dict[str, str]:
    if not allowed_keys:
        return {}

    fallback: dict[str, str] = {}
    registry = get_field_registry()
    for raw_key, raw_value in raw_fields.items():
        resolved = registry.resolve(str(raw_key)) or str(raw_key)
        key = resolved
        if key not in allowed_keys or key in fallback:
            continue
        value = _normalize_allowed_value(key, raw_value)
        if value:
            fallback[key] = value
    return fallback


def _fallback_strict_standalone_fields(raw_fields: dict[str, object]) -> dict[str, str]:
    fallback: dict[str, str] = {}
    registry = get_field_registry()
    for raw_key, raw_value in raw_fields.items():
        resolved = registry.resolve(str(raw_key)) or str(raw_key)
        key = resolved
        if not _is_strict_standalone_field(key) or key in fallback:
            continue
        value = _normalize_allowed_value(key, raw_value)
        if value:
            fallback[key] = value
    return fallback


def _normalize_allowed_value(field_name: str, raw_value: object) -> str | None:
    candidate = re.sub(r"\s+", " ", str(raw_value or "")).strip()
    if not candidate:
        return None
    if field_name in {"customer_pan", "coapplicant_pan", "pancard_no", "ca_pancard_no"}:
        return normalize_pan_value(candidate)
    if field_name in {"customer_dob", "coapplicant_dob", "dob", "ca_dob"}:
        return normalize_date_value(candidate)
    if field_name in {"customer_mobile", "coapplicant_mobile", "mobile", "ca_mobile"}:
        digits = re.sub(r"\D+", "", candidate)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        return digits if len(digits) == 10 else None
    if field_name in {"customer_city", "customer_state", "property_city", "property_state"}:
        return re.sub(r"[^A-Za-z\s-]+", "", candidate).strip().lower() or None
    if field_name in {"customer_first_name", "customer_last_name"}:
        return re.sub(r"[^A-Za-z\s'-]+", "", candidate).strip() or None
    return candidate


def _is_strict_standalone_field(field_name: str) -> bool:
    return field_name in {"loan_amount", "customer_pan", "customer_dob", "customer_mobile"}


def _filter_contextually_unsafe_fields(
    fields: dict[str, str],
    allowed_keys: set[str],
    *,
    utterance: str = "",
    agent_utterance: str = "",
) -> dict[str, str]:
    if not fields:
        return {}
    safe_fields: dict[str, str] = {}
    for key, value in fields.items():
        if key in _NAME_KEYS and not _has_name_context(
            key,
            allowed_keys,
            value,
            fields,
            utterance=utterance,
            agent_utterance=agent_utterance,
        ):
            continue
        if _is_address_detail_key(key) and key not in allowed_keys:
            continue
        if key in _CURRENT_ADDRESS_KEYS and allowed_keys & _CURRENT_ADDRESS_KEYS:
            safe_fields[key] = value
            continue
        if key in _PROPERTY_LOCATION_KEYS and allowed_keys & _PROPERTY_LOCATION_KEYS:
            safe_fields[key] = value
            continue
        safe_fields[key] = value
    return safe_fields


def _has_name_context(
    key: str,
    allowed_keys: set[str],
    value: str,
    fields: dict[str, str],
    *,
    utterance: str,
    agent_utterance: str,
) -> bool:
    if key in allowed_keys:
        return True
    if key == "customer_last_name" and fields.get("customer_first_name"):
        return True
    if key == "customer_first_name" and fields.get("customer_last_name"):
        return True
    candidate = str(value or "").strip()
    if len(candidate.split()) >= 2:
        return True
    if _utterance_self_identifies_name(utterance):
        return True
    if _agent_asked_for_name(agent_utterance):
        return True
    return False


def _is_address_detail_key(key: str) -> bool:
    return (
        key in _ADDRESS_DETAIL_KEYS
        or key.endswith("_house_number")
        or key.endswith("_street")
        or key.endswith("_address1")
        or key.endswith("_address2")
    )


def _utterance_self_identifies_name(utterance: str) -> bool:
    normalized = _normalize_transcript_text(utterance)
    if not normalized:
        return False
    return bool(
        re.search(r"\b(main|mein|mai|my|name|naam)\b", normalized)
        and re.search(r"\b(bol|speaking|naam|name)\b", normalized)
    )


def _agent_asked_for_name(agent_utterance: str) -> bool:
    normalized = _normalize_transcript_text(agent_utterance)
    if not normalized:
        return False
    return bool(
        re.search(r"\b(name|naam|first|last)\b", normalized)
        or "नाम" in str(agent_utterance or "")
    )


def _normalize_transcript_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())
