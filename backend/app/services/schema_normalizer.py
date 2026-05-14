import re

from app.services.field_registry import get_field_registry
from app.services.field_spec import FieldSpec

_TRUTHY_VALUES = {
    "1", "true", "yes", "y", "haan", "han", "ha", "confirmed", "confirm", "available",
}
_FALSY_VALUES = {
    "0", "false", "no", "n", "nahi", "nahi", "nahin", "not", "none",
}
_SAFE_ALIASES = {
    "employment_type": "profession",
    "property_location": "property_city",
    "total_monthly_emi": "existing_emi_amount",
    "monthly_emi": "existing_emi_amount",
    "emi_amount": "existing_emi_amount",
    "emi_outflow": "existing_emi_amount",
    "monthly_emi_outflow": "existing_emi_amount",
}
_OBLIGATION_DETAIL_FIELDS = {
    "existing_emi_amount", "no_of_emi", "emi_ending_six_month",
}
_CASH_INCOME_DETAIL_FIELDS = {
    "in_hand_monthly_cash_salary", "customer_income_cash_salary_certificate",
}


def normalize_field_name(field_name: str) -> str:
    return _SAFE_ALIASES.get(field_name, field_name)


def normalize_extracted_fields(raw_fields: dict[str, object]) -> dict[str, str]:
    registry = get_field_registry()
    normalized: dict[str, str] = {}

    for raw_key, raw_value in raw_fields.items():
        field_name = registry.resolve(normalize_field_name(str(raw_key))) or normalize_field_name(str(raw_key))
        definition = registry.definition(field_name)
        if definition is None:
            continue
        spec = FieldSpec(
            name=definition.id,
            meaning=definition.label,
            types=tuple(definition.types or ["string"]),
            enum_values=tuple(definition.options or ()),
        )
        value = _normalize_by_spec(definition.id, raw_value, spec)
        if value is not None:
            normalized[definition.id] = value

    derive_extracted_fields(normalized)
    return normalized


def normalize_field_value(field_name: str, raw_value: object) -> str | None:
    field_registry = get_field_registry()
    definition = field_registry.definition(field_name)
    if definition:
        spec = FieldSpec(
            name=definition.id,
            meaning=definition.label,
            types=tuple(definition.types or ["string"]),
            enum_values=tuple(definition.options or ()),
        )
        return _normalize_by_spec(definition.id, raw_value, spec)
    return None


def derive_extracted_fields(extracted_fields: dict[str, str]) -> None:
    registry = get_field_registry()
    has_property_detail = any(
        value
        and registry.category_hint(field) == "property_details"
        and field != "is_property_identified"
        for field, value in extracted_fields.items()
    )
    if has_property_detail and "is_property_identified" not in extracted_fields:
        extracted_fields["is_property_identified"] = "yes"

    if any(extracted_fields.get(field) for field in _OBLIGATION_DETAIL_FIELDS):
        extracted_fields.setdefault("existing_emi", "yes")
        extracted_fields.setdefault("is_obligation", "yes")

    no_of_emi = extracted_fields.get("no_of_emi")
    if no_of_emi is not None:
        try:
            if int(float(no_of_emi)) <= 0:
                extracted_fields.setdefault("existing_emi", "no")
            else:
                extracted_fields.setdefault("existing_emi", "yes")
                extracted_fields.setdefault("is_obligation", "yes")
        except ValueError:
            pass

    if any(extracted_fields.get(field) for field in _CASH_INCOME_DETAIL_FIELDS):
        extracted_fields.setdefault("customer_earn_cash_income", "yes")
    if extracted_fields.get("salary_credit_mode") == "cash":
        extracted_fields.setdefault("customer_earn_cash_income", "yes")


def _normalize_by_spec(field_name: str, raw_value: object, spec: FieldSpec) -> str | None:
    if raw_value is None:
        return None

    if isinstance(raw_value, str):
        candidate = re.sub(r"\s+", " ", raw_value).strip()
    else:
        candidate = str(raw_value).strip()
    if not candidate:
        return None

    if _is_pan_field(field_name):
        return normalize_pan_value(candidate)

    if _is_dob_field(field_name):
        return normalize_date_value(candidate) or _format_string_value(field_name, candidate)

    if _is_amount_field(field_name):
        return normalize_amount_value(candidate) or _normalize_number_value(candidate)

    enum_value = _normalize_enum_value(candidate, spec.enum_values)
    if enum_value is not None:
        return _format_string_value(field_name, enum_value)

    field_types = spec.types or ("string",)
    if "boolean" in field_types:
        boolean_value = _normalize_boolean_value(candidate)
        if boolean_value is not None:
            return boolean_value

    if "integer" in field_types:
        integer_value = _normalize_integer_value(candidate)
        if integer_value is not None:
            return integer_value

    if "number" in field_types:
        number_value = _normalize_number_value(candidate)
        if number_value is not None:
            return number_value

    if _is_digits_only_field(field_name):
        digits_only = re.sub(r"\D+", "", candidate)
        return digits_only or None

    return _format_string_value(field_name, candidate)


def _normalize_enum_value(candidate: str, enum_values: tuple[str, ...]) -> str | None:
    if not enum_values:
        return None

    lowered_enum = {value.lower(): value for value in enum_values}
    normalized = candidate.lower()
    if normalized in lowered_enum:
        return lowered_enum[normalized]

    boolean_value = _normalize_boolean_value(candidate)
    if boolean_value is None:
        return None

    if boolean_value in lowered_enum:
        return lowered_enum[boolean_value]
    if boolean_value == "yes" and "1" in lowered_enum:
        return lowered_enum["1"]
    if boolean_value == "no" and "0" in lowered_enum:
        return lowered_enum["0"]
    return None


def _normalize_boolean_value(candidate: str) -> str | None:
    normalized = candidate.lower()
    if normalized in _TRUTHY_VALUES:
        return "yes"
    if normalized in _FALSY_VALUES:
        return "no"
    return None


def _normalize_integer_value(candidate: str) -> str | None:
    cleaned = candidate.replace(",", "").strip()
    match = re.search(
        r"(?P<number>-?\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k|l)?\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        number = match.group("number")
        unit = (match.group("unit") or "").lower()
        try:
            numeric_value = float(number)
        except ValueError:
            numeric_value = None
        if numeric_value is not None:
            if unit in {"crore", "cr"}:
                numeric_value *= 10000000
            elif unit in {"lakh", "lac", "lakhs", "lacs", "l"}:
                numeric_value *= 100000
            elif unit in {"thousand", "k"}:
                numeric_value *= 1000
            return str(int(numeric_value)) if numeric_value.is_integer() else str(numeric_value)

    normalized = _extract_numeric_token(candidate)
    if normalized is None:
        return None
    return str(int(float(normalized)))


def _normalize_number_value(candidate: str) -> str | None:
    cleaned = candidate.replace(",", "").strip()
    match = re.search(
        r"(?P<number>-?\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k|l)?\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        number = match.group("number")
        unit = (match.group("unit") or "").lower()
        try:
            numeric_value = float(number)
        except ValueError:
            numeric_value = None
        if numeric_value is not None:
            if unit in {"crore", "cr"}:
                numeric_value *= 10000000
            elif unit in {"lakh", "lac", "lakhs", "lacs", "l"}:
                numeric_value *= 100000
            elif unit in {"thousand", "k"}:
                numeric_value *= 1000
            return str(int(numeric_value)) if numeric_value.is_integer() else str(numeric_value)

    normalized = _extract_numeric_token(candidate)
    if normalized is None:
        return None
    numeric = float(normalized)
    return str(int(numeric)) if numeric.is_integer() else str(numeric)


def _extract_numeric_token(candidate: str) -> str | None:
    cleaned = candidate.replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return match.group(0) if match else None


def _format_string_value(field_name: str, value: str) -> str:
    if _is_digits_only_field(field_name):
        return re.sub(r"\D+", "", value)
    if _is_pan_field(field_name):
        return value.replace(" ", "").upper()
    if _should_lowercase_field(field_name):
        return value.lower()
    if field_name in {"email", "official_email_id"}:
        return value.lower()
    return value


def _is_pan_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return "pan" in normalized and "link" not in normalized


def _is_dob_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return normalized == "dob" or normalized.endswith("_dob")


def _is_amount_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return any(
        token in normalized
        for token in (
            "amount",
            "salary",
            "income",
            "value",
            "contribution",
            "roi",
        )
    )


def _is_digits_only_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return any(
        token in normalized
        for token in ("mobile", "phone", "pincode", "aadhaar", "aadhar", "pan_link")
    )


def _should_lowercase_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return any(
        token in normalized
        for token in (
            "city",
            "state",
            "status",
            "qualification",
            "relationship",
            "type",
            "usage",
            "profession",
            "mode",
            "occupation",
        )
    )


def normalize_pan_value(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value or "").upper()
    if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", cleaned):
        return cleaned
    return None


def normalize_date_value(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", value or "").strip().lower()
    if not candidate:
        return None

    iso = re.search(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b", candidate)
    if iso:
        return _format_date_parts(
            iso.group("year"), iso.group("month"), iso.group("day")
        )

    numeric = re.search(r"\b(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>\d{4})\b", candidate)
    if numeric:
        return _format_date_parts(
            numeric.group("year"), numeric.group("month"), numeric.group("day")
        )
    return None


def normalize_amount_value(value: str) -> str | None:
    candidate = re.sub(r"\s+", " ", str(value or "")).strip().lower().replace(",", "")
    if not candidate:
        return None

    match = re.search(
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k)?\b",
        candidate,
        flags=re.IGNORECASE,
    )
    if match and match.group("unit"):
        return _format_amount(float(match.group("number")), match.group("unit"))
    return None


def _format_date_parts(year: str, month: str, day: str) -> str | None:
    year_int = int(year)
    month_int = int(month)
    day_int = int(day)
    if not (1900 <= year_int <= 2100 and 1 <= month_int <= 12 and 1 <= day_int <= 31):
        return None
    return f"{year_int:04d}-{month_int:02d}-{day_int:02d}"


def _format_amount(number: float, unit: str) -> str:
    normalized_unit = unit.lower()
    if normalized_unit in {"crore", "cr"}:
        number *= 10000000
    elif normalized_unit in {"lakh", "lac", "lakhs", "lacs"}:
        number *= 100000
    elif normalized_unit in {"thousand", "k"}:
        number *= 1000
    return str(int(number)) if number.is_integer() else str(number)
