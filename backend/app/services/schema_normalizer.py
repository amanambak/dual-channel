import re

from app.services.schema_registry import SchemaFieldSpec
from app.services.schema_registry import get_schema_registry

_TRUTHY_VALUES = {
    "1", "true", "yes", "y", "haan", "han", "ha", "confirmed", "confirm", "available",
}
_FALSY_VALUES = {
    "0", "false", "no", "n", "nahi", "nahi", "nahin", "not", "none",
}
_DIGITS_ONLY_FIELDS = {
    "mobile", "customer_mobile", "pan_link_mobile", "alt_phone",
    "aadhar_no", "property_pincode", "pa_pincode", "cra_pincode",
}
_LOWERCASE_FIELDS = {
    "property_city", "property_state", "pa_city", "pa_state", "cra_city", "cra_state",
    "property_type", "property_sub_type", "property_usage", "occupancy_status",
    "profession", "company_type", "salary_credit_mode", "house_type",
}
_UPPERCASE_FIELDS = {"pancard_no"}
_SAFE_ALIASES = {
    "employment_type": "profession",
    "property_location": "property_city",
    "total_monthly_emi": "existing_emi_amount",
    "monthly_emi": "existing_emi_amount",
    "emi_amount": "existing_emi_amount",
    "emi_outflow": "existing_emi_amount",
    "monthly_emi_outflow": "existing_emi_amount",
}
_PROPERTY_DETAIL_FIELDS = {
    "property_value", "expected_property_value", "property_agreement_value",
    "property_type", "property_sub_type", "property_pincode", "property_city",
    "property_state", "property_address1", "property_address2", "project_name",
    "preferred_project_name", "builder_name_id",
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
    registry = get_schema_registry()
    normalized: dict[str, str] = {}

    for raw_key, raw_value in raw_fields.items():
        field_name = normalize_field_name(str(raw_key))
        if field_name not in registry.fields:
            continue
        value = normalize_field_value(field_name, raw_value)
        if value is not None:
            normalized[field_name] = value

    derive_extracted_fields(normalized)
    return normalized


def build_high_confidence_local_updates(text: str) -> dict[str, str]:
    registry = get_schema_registry()
    normalized_text = re.sub(r"\s+", " ", text or "").lower()
    updates: dict[str, str] = {}

    location = registry._extract_location_value(text)
    if location:
        updates["property_city"] = location.lower()

    pincode = registry._extract_pincode_value(text)
    if pincode:
        updates["property_pincode"] = pincode

    cibil_score = registry._extract_cibil_value(text)
    if cibil_score:
        updates["cibil_score"] = cibil_score

    loan_amount = _extract_amount_if_explicit(
        normalized_text,
        text,
        {"loan", "budget", "requirement", "needed", "need"},
    )
    if loan_amount:
        updates["loan_amount"] = loan_amount

    gross_monthly_salary = _extract_amount_near_terms(
        normalized_text,
        text,
        {"gross", "monthly", "salary"},
    )
    if gross_monthly_salary:
        updates["gross_monthly_salary"] = gross_monthly_salary

    monthly_salary = _extract_amount_near_terms(
        normalized_text,
        text,
        {"monthly", "salary"},
    )
    if monthly_salary and "gross" not in normalized_text:
        updates["monthly_salary"] = monthly_salary

    annual_income = _extract_amount_near_terms(
        normalized_text,
        text,
        {"annual", "yearly", "income"},
    )
    if annual_income:
        updates["annual_income"] = annual_income
        updates["gross_annual_income"] = annual_income

    if "cash" in normalized_text and "salary" in normalized_text:
        cash_salary = _extract_amount_near_terms(
            normalized_text,
            text,
            {"cash", "salary"},
        )
    else:
        cash_salary = None
    if cash_salary:
        updates["in_hand_monthly_cash_salary"] = cash_salary
        updates["customer_earn_cash_income"] = "yes"

    emi_amount = _extract_emi_amount(normalized_text, text)
    if emi_amount:
        updates["existing_emi_amount"] = emi_amount

    if any(token in normalized_text for token in {"salaried", "salary", "job"}):
        updates.setdefault("profession", "salaried")
    elif any(token in normalized_text for token in {"self-employed", "self employed", "business", "self employed"}):
        updates.setdefault("profession", "self-employed")

    property_type = _extract_property_type(normalized_text)
    if property_type:
        updates["property_type"] = property_type

    no_of_emi = _extract_emi_count(normalized_text, text)
    if no_of_emi:
        updates["no_of_emi"] = no_of_emi
        updates["existing_emi"] = "yes"

    if "property" in normalized_text and (
        "city" in normalized_text or location or pincode or property_type
    ):
        updates["is_property_identified"] = "yes"

    derive_extracted_fields(updates)
    return updates


def normalize_field_value(field_name: str, raw_value: object) -> str | None:
    registry = get_schema_registry()
    spec = registry.get_field_spec(field_name)
    return _normalize_by_spec(field_name, raw_value, spec)


def derive_extracted_fields(extracted_fields: dict[str, str]) -> None:
    has_property_detail = any(extracted_fields.get(field) for field in _PROPERTY_DETAIL_FIELDS)
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


def _normalize_by_spec(field_name: str, raw_value: object, spec: SchemaFieldSpec) -> str | None:
    if raw_value is None:
        return None

    if isinstance(raw_value, str):
        candidate = re.sub(r"\s+", " ", raw_value).strip()
    else:
        candidate = str(raw_value).strip()
    if not candidate:
        return None

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

    if field_name in _DIGITS_ONLY_FIELDS:
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


def _extract_amount_if_explicit(
    normalized_text: str, raw_text: str, required_tokens: set[str]
) -> str | None:
    if not any(token in normalized_text for token in required_tokens):
        return None
    return _extract_amount_near_terms(normalized_text, raw_text, required_tokens)


def _extract_amount_near_terms(
    normalized_text: str, raw_text: str, required_tokens: set[str]
) -> str | None:
    if not any(token in normalized_text for token in required_tokens):
        return None

    patterns = [
        r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k)?\s*(?:ka|ki|ke)?\s*(?:" + "|".join(required_tokens) + r")\b",
        r"(?:"
        + "|".join(required_tokens)
        + r")\b\s*(?:ka|ki|ke|is|hai|hoon|hun|hu)\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>crore|cr|lakh|lac|lakhs|lacs|thousand|k)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            number = match.group("number")
            unit = (match.groupdict().get("unit") or "").lower()
            try:
                numeric_value = float(number)
            except ValueError:
                return None
            if unit in {"crore", "cr"}:
                return str(int(numeric_value * 10000000))
            if unit in {"lakh", "lac", "lakhs", "lacs"}:
                return str(int(numeric_value * 100000))
            if unit in {"thousand", "k"}:
                return str(int(numeric_value * 1000))
            return str(int(numeric_value)) if numeric_value.is_integer() else str(numeric_value)
    return None


def _extract_property_type(normalized_text: str) -> str | None:
    for token in ("flat", "plot", "villa", "apartment", "independent"):
        if token in normalized_text:
            return token
    return None


def _extract_emi_count(normalized_text: str, raw_text: str) -> str | None:
    if "emi" not in normalized_text:
        return None
    amount_markers = {"amount", "outflow", "outgoing", "monthly", "total", "value", "cost"}
    if any(marker in normalized_text for marker in amount_markers):
        count_patterns = [
            r"\b(?P<number>\d+)\s*(?:active\s+)?emis?\b",
            r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+emis?\b",
            r"\b(?:number(?:s)? of|count of)\s+emis?\s*(?:is|are|hai|hain|tha|thi|the)?\s*(?P<number>\d+)\b",
        ]
    else:
        count_patterns = [
            r"\b(?P<number>\d+)\s*(?:nos?\.?|number(?:s)? of)?\s*emis?\b",
            r"\b(?:no\.?|number(?:s)? of|count of)\s*emis?\b\s*(?:is|are|hai|hain|tha|thi|the)\s*(?P<number>\d+)\b",
        ]

    for pattern in count_patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if match:
            value = match.group("number")
            if value.isdigit():
                return str(int(value))
            return value
    word_count_map = {
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    for word, value in word_count_map.items():
        if re.search(rf"\b{word}\s+emis?\b", normalized_text):
            return value
    return None


def _extract_emi_amount(normalized_text: str, raw_text: str) -> str | None:
    if "emi" not in normalized_text:
        return None
    patterns = [
        r"(?:total\s+)?(?:monthly\s+)?(?:emi\s+outflow|monthly\s+emi)\D*(?P<number>\d[\d,]*(?:\.\d+)?)",
        r"(?:outflow|outgoing)\D*(?P<number>\d[\d,]*(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if not match:
            continue
        number = match.group("number").replace(",", "")
        try:
            numeric_value = float(number)
        except ValueError:
            continue
        return str(int(numeric_value)) if numeric_value.is_integer() else str(numeric_value)
    return None


def _format_string_value(field_name: str, value: str) -> str:
    if field_name in _DIGITS_ONLY_FIELDS:
        return re.sub(r"\D+", "", value)
    if field_name in _UPPERCASE_FIELDS:
        return value.replace(" ", "").upper()
    if field_name in _LOWERCASE_FIELDS:
        return value.lower()
    if field_name in {"email", "official_email_id"}:
        return value.lower()
    return value
