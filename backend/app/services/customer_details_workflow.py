from typing import Any

from app.services.workflow_state import compute_workflow_state


def compute_customer_details_state(field_state: dict[str, Any]) -> dict[str, Any]:
    workflow_state = compute_workflow_state(field_state, active_category="customer_details")
    return workflow_state.get("category_state", {}).get("customer_details", {})
