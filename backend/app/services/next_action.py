from typing import Any

from app.services.field_registry import get_field_registry
from app.services.workflow_schema import WorkflowSchema
from app.services.workflow_schema import load_workflow_schema


QUESTION_TEMPLATES = {
    "loan_type": "Sir loan type confirm kar dijiye: home loan, balance transfer ya top-up?",
    "loan_amount": "Sir loan amount kitna required hai?",
    "remaining_loan_amount": "Sir current loan ka outstanding amount kitna bacha hai?",
    "previous_current_roi": "Sir current loan ka ROI kitna chal raha hai?",
    "previous_loan_amount": "Sir previous loan amount kitna tha?",
    "previous_emi_amount": "Sir existing loan ki monthly EMI kitni chal rahi hai?",
    "previous_tenure": "Sir previous loan ka remaining tenure kitna hai?",
    "previous_loan_start_date": "Sir previous loan kab start hua tha?",
    "customer_mobile": "Sir mobile number confirm kar dijiye.",
    "customer_dob": "Sir DOB confirm kar dijiye, offer check ke liye required hai.",
    "customer_pan": "Sir PAN number confirm kar dijiye.",
    "customer_city": "Sir current city confirm kar dijiye.",
    "customer_state": "Sir current state confirm kar dijiye.",
    "customer_address_line1": "Sir current address line confirm kar dijiye.",
    "customer_spouse_name": "Sir spouse name kya update karna hai?",
    "coapplicant_mobile": "Sir co-applicant ka mobile number confirm kar dijiye.",
    "coapplicant_pan": "Sir co-applicant ka PAN number confirm kar dijiye.",
    "profession": "Sir profession confirm kar dijiye: salaried ya self-employed?",
    "monthly_salary": "Sir monthly in-hand salary kitni hai?",
    "income_calculation_mode": "Sir business income kis basis par calculate karni hai?",
    "is_property_identified": "Sir property identify ho gayi hai kya?",
    "property_city": "Sir property kis city mein hai?",
    "property_state": "Sir property ka state confirm kar dijiye.",
    "expected_market_value": "Sir property ka expected market value kitna hai?",
    "registration_value": "Sir registration value kitni hai?",
    "property_type": "Sir property type confirm kar dijiye.",
    "builder_id": "Sir builder name confirm kar dijiye.",
    "project_id": "Sir project name confirm kar dijiye.",
    "cibil_score": "Sir customer ka CIBIL score confirm kar dijiye.",
    "fulfillment_type": "Sir fulfillment/process type confirm kar dijiye.",
}


def select_next_action(
    workflow_state: dict[str, Any],
    route: dict[str, Any],
    last_action: dict[str, Any] | None = None,
    *,
    schema: WorkflowSchema | None = None,
) -> dict[str, Any]:
    workflow_schema = schema or load_workflow_schema()
    category_state = workflow_state.get("category_state") or {}
    current_category = route.get("previous_category") or workflow_state.get("active_category")
    routed_category = route.get("category") or current_category
    routed_state = category_state.get(routed_category or "", {})

    if (
        routed_category
        and current_category
        and routed_category != current_category
        and route.get("confidence", 0) >= 0.55
        and routed_state.get("status") != "complete"
    ):
        return _switch_category_action(
            from_category=current_category,
            to_category=routed_category,
            state=routed_state,
            reason=route.get("reason") or "Customer changed topic",
        )

    active_category = routed_category or current_category or _first_incomplete_category(category_state, workflow_schema)
    active_state = category_state.get(active_category or "", {})
    if active_state.get("status") != "complete":
        field_id = active_state.get("next_field")
        if field_id:
            return _ask_field_action(
                category_id=active_category,
                field_id=str(field_id),
                reason="Highest-priority missing field for active category",
            )

    next_category = _first_incomplete_category(category_state, workflow_schema, exclude=active_category)
    if next_category:
        next_state = category_state.get(next_category, {})
        return {
            "type": "category_complete",
            "category": active_category,
            "next_category": next_category,
            "field": next_state.get("next_field"),
            "label": _field_label(next_state.get("next_field")),
            "question": _question_for_field(next_state.get("next_field")),
            "reason": "Current category is complete; next priority category has missing fields",
        }

    return {
        "type": "process_confirmation",
        "category": active_category,
        "reason": "All configured workflow categories are complete",
        "question": "Sir high-priority details complete dikh rahe hain. Ab process/document status confirm kar lein?",
    }


def _switch_category_action(
    *,
    from_category: str,
    to_category: str,
    state: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    field_id = state.get("next_field")
    return {
        "type": "switch_category",
        "from_category": from_category,
        "to_category": to_category,
        "category": to_category,
        "field": field_id,
        "label": _field_label(field_id),
        "question": _question_for_field(field_id),
        "reason": reason,
    }


def _ask_field_action(category_id: str | None, field_id: str, reason: str) -> dict[str, Any]:
    return {
        "type": "ask_field",
        "category": category_id,
        "field": field_id,
        "label": _field_label(field_id),
        "question": _question_for_field(field_id),
        "reason": reason,
    }


def _first_incomplete_category(
    category_state: dict[str, Any],
    schema: WorkflowSchema,
    *,
    exclude: str | None = None,
) -> str | None:
    for category_id in schema.ordered_category_ids():
        if category_id == exclude:
            continue
        state = category_state.get(category_id, {})
        if state.get("status") != "complete":
            return category_id
    return None


def _field_label(field_id: Any) -> str:
    if not field_id:
        return ""
    definition = get_field_registry().definition(str(field_id))
    return definition.label if definition else str(field_id).replace("_", " ").title()


def _question_for_field(field_id: Any) -> str:
    if not field_id:
        return ""
    field_name = str(field_id)
    return QUESTION_TEMPLATES.get(
        field_name,
        f"Sir {_field_label(field_name)} confirm kar dijiye.",
    )
