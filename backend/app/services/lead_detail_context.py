import json
import re
from collections.abc import Iterator
from typing import Any


IMPORTANT_PATHS = {
    "id",
    "ref_lead_id",
    "loan_type",
    "loan_sub_type_name",
    "kyc_status",
    "followup_date",
    "followup_type",
    "partner_name",
    "partner_mobile",
    "partner_email",
    "assign_user.name",
    "assign_user.email",
    "assign_user.mobile",
    "rmdetails.label",
    "rmdetails.mobile",
    "rmdetails.email",
    "status_info.statuslang.status_name",
    "sub_status_info.substatuslang.sub_status_name",
    "customer.customer_id",
    "customer.first_name",
    "customer.last_name",
    "customer.mobile",
    "customer.email",
    "customer.pancard_no",
    "customer.dob",
    "customer.gender",
    "customer.marital_status",
    "customer.occupation",
    "customer.official_email_id",
    "customer.employment.employer_name",
    "customer.employment.designation",
    "customer.employment.gross_monthly_income",
    "customer.employment.year_with_company",
    "customer.bank_details.bank_id",
    "customer.bank_details.branch_name",
    "customer.bank_details.account_name",
    "customer.bank_details.account_type",
    "lead_details.lead_id",
    "lead_details.bank_id",
    "lead_details.loan_amount",
    "lead_details.login_amount",
    "lead_details.approved_amount",
    "lead_details.tenure",
    "lead_details.annual_income",
    "lead_details.monthly_salary",
    "lead_details.cibil_score",
    "lead_details.company_name",
    "lead_details.profession",
    "lead_details.property_city",
    "lead_details.property_state",
    "lead_details.property_address1",
    "lead_details.property_address2",
    "lead_details.property_pincode",
    "lead_details.property_value",
    "lead_details.expected_property_value",
    "lead_details.bank.banklang.bank_name",
}

QUESTION_STOPWORDS = {
    "a",
    "about",
    "batao",
    "bataiye",
    "hai",
    "is",
    "kya",
    "me",
    "mein",
    "name",
    "of",
    "please",
    "tell",
    "the",
    "this",
    "what",
    "which",
}


def _iter_leaf_values(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _iter_leaf_values(nested_value, nested_prefix)
        return

    if isinstance(value, list):
        for index, nested_value in enumerate(value[:10]):
            nested_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from _iter_leaf_values(nested_value, nested_prefix)
        return

    if value not in (None, ""):
        yield prefix, value


def _format_value(value: Any, *, max_chars: int = 500) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > max_chars:
        return f"{text[: max_chars - 3]}..."
    return text


def _format_label(path: str) -> str:
    leaf = path.split(".")[-1]
    leaf = re.sub(r"\[\d+\]", "", leaf)
    return leaf.replace("_", " ").strip().capitalize()


def _format_direct_answer(rows: list[tuple[str, Any]]) -> str:
    return "\n".join(
        f"{label}: {_format_value(value)}" for label, value in rows if value not in (None, "")
    )


def _first_value(lead_detail: dict[str, Any], paths: list[str]) -> Any:
    values = dict(_iter_leaf_values(lead_detail))
    for path in paths:
        value = values.get(path)
        if value not in (None, ""):
            return value
    return None


def _maybe_grouped_direct_answer(message: str, lead_detail: dict[str, Any]) -> str:
    normalized = _normalize_lookup_text(message)

    if "customer" in normalized and "name" in normalized and "first" not in normalized and "last" not in normalized:
        first_name = _first_value(lead_detail, ["customer.first_name"])
        last_name = _first_value(lead_detail, ["customer.last_name"])
        full_name = " ".join(str(part).strip() for part in (first_name, last_name) if part)
        if full_name:
            return _format_direct_answer([("Customer name", full_name)])

    if "followup" in normalized or "follow up" in normalized:
        rows = [
            ("Followup date", _first_value(lead_detail, ["followup_date"])),
            ("Followup type", _first_value(lead_detail, ["followup_type"])),
            ("Followup status", _first_value(lead_detail, ["followup_status"])),
        ]
        return _format_direct_answer(rows)

    return ""


def _normalize_lookup_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _path_aliases(path: str) -> set[str]:
    parts = [part for part in re.split(r"[.\[\]]+", path) if part and not part.isdigit()]
    aliases = {_normalize_lookup_text(path), _normalize_lookup_text(path.replace(".", " "))}
    if parts:
        leaf = parts[-1]
        aliases.add(_normalize_lookup_text(leaf))
        aliases.add(_normalize_lookup_text(leaf.replace("_", " ")))
    if len(parts) >= 2:
        aliases.add(_normalize_lookup_text(" ".join(parts[-2:])))
        aliases.add(_normalize_lookup_text(" ".join(part.replace("_", " ") for part in parts[-2:])))
    return {alias for alias in aliases if alias}


def _looks_like_lead_detail_question(message: str) -> bool:
    normalized = _normalize_lookup_text(message)
    if not normalized:
        return False
    lead_terms = {
        "amount",
        "bank",
        "cibil",
        "company",
        "customer",
        "email",
        "followup",
        "lead",
        "loan",
        "mobile",
        "name",
        "partner",
        "property",
        "rm",
        "salary",
        "status",
        "tenure",
    }
    return bool(set(normalized.split()) & lead_terms)


def find_direct_lead_detail_answer(message: str, lead_detail: dict[str, Any] | None) -> str:
    if not lead_detail or not _looks_like_lead_detail_question(message):
        return ""

    grouped_answer = _maybe_grouped_direct_answer(message, lead_detail)
    if grouped_answer:
        return grouped_answer

    normalized_message = _normalize_lookup_text(message)
    message_tokens = {
        token for token in normalized_message.split() if token not in QUESTION_STOPWORDS
    }

    best_match: tuple[int, str, Any] | None = None
    for path, value in _iter_leaf_values(lead_detail):
        aliases = _path_aliases(path)
        score = 0
        for alias in aliases:
            alias_tokens = set(alias.split())
            if alias and alias in normalized_message:
                score = max(score, 100 + len(alias_tokens))
            elif alias_tokens and alias_tokens.issubset(message_tokens):
                score = max(score, 80 + len(alias_tokens))
            else:
                overlap = len(alias_tokens & message_tokens)
                if overlap:
                    score = max(score, overlap)
        if score and (best_match is None or score > best_match[0]):
            best_match = (score, path, value)

    if best_match is None or best_match[0] < 2:
        return ""

    _, path, value = best_match
    return _format_direct_answer([(_format_label(path), value)])


def build_lead_detail_chat_context(
    *,
    lead_id: str | int | None,
    lead_detail: dict[str, Any] | None,
    max_flat_fields: int = 160,
) -> str:
    if not lead_detail:
        return ""

    flattened = list(_iter_leaf_values(lead_detail))
    important_lines: list[str] = []
    searchable_lines: list[str] = []
    seen_paths: set[str] = set()

    for path, value in flattened:
        if path in IMPORTANT_PATHS:
            important_lines.append(f"- {path}: {_format_value(value)}")
            seen_paths.add(path)

    for path, value in flattened:
        if path in seen_paths:
            continue
        searchable_lines.append(f"- {path}: {_format_value(value)}")
        if len(searchable_lines) >= max_flat_fields:
            break

    lead_label = lead_id or lead_detail.get("id") or lead_detail.get("ref_lead_id") or "unknown"
    sections = [
        "Loaded Ambak lead detail context. Use this customer/lead data first when the user asks about this lead.",
        f"Lead ID: {lead_label}",
        "Answer only from these loaded lead details when the question is about customer, loan, lead, status, bank, RM, partner, property, income, CIBIL, or contact fields.",
    ]

    if important_lines:
        sections.append("Important loaded fields:\n" + "\n".join(important_lines))
    if searchable_lines:
        sections.append("Additional searchable loaded fields:\n" + "\n".join(searchable_lines))

    return "\n\n".join(sections)
