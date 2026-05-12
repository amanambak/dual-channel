from dataclasses import dataclass
from typing import Any

from app.services.field_registry import FieldRegistry
from app.services.field_registry import get_field_registry
from app.services.workflow_schema import WorkflowSchema
from app.services.workflow_schema import load_workflow_schema


@dataclass(frozen=True)
class MappingIssue:
    code: str
    message: str
    field_id: str = ""
    key: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "field_id": self.field_id,
            "key": self.key,
        }


def audit_field_registry(
    registry: FieldRegistry | None = None,
    workflow_schema: WorkflowSchema | dict[str, Any] | None = None,
) -> list[MappingIssue]:
    active_registry = registry or get_field_registry()
    schema = (
        workflow_schema
        if isinstance(workflow_schema, WorkflowSchema)
        else load_workflow_schema()
    )
    issues: list[MappingIssue] = []

    for conflict in active_registry.conflicts:
        issues.append(
            MappingIssue(
                code="conflicting_raw_key",
                message=(
                    f"Raw key maps to both {conflict.get('first_field')} "
                    f"and {conflict.get('second_field')}"
                ),
                key=str(conflict.get("key") or ""),
            )
        )

    for definition in active_registry.definitions.values():
        if not definition.graphql_paths and definition.priority == "high":
            issues.append(
                MappingIssue(
                    code="priority_field_without_graphql_path",
                    message="High-priority logical field has no GraphQL path",
                    field_id=definition.id,
                )
            )

    for category in schema.categories:
        for field_id in schema.fields_for_category(str(category.get("id") or "")):
            if not active_registry.definition(field_id):
                issues.append(
                    MappingIssue(
                        code="workflow_field_missing_from_registry",
                        message="Workflow references a field missing from the registry",
                        field_id=field_id,
                    )
                )

    return issues
