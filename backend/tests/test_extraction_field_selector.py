import unittest

from app.services.extraction_field_selector import select_extraction_fields
from app.services.field_registry import load_field_registry
from app.services.field_resolver import build_resolved_field_state
from app.services.workflow_state import compute_workflow_state


class ExtractionFieldSelectorTest(unittest.TestCase):
    def test_default_selection_is_capped_to_fifteen_fields(self):
        selection = select_extraction_fields(
            utterance="loan amount 30 lakh, salary 1 lakh, cibil 760, property noida",
            agent_utterance="Sir details bata dijiye.",
        )

        self.assertLessEqual(len(selection.specs), 15)

    def test_expected_field_fast_path_caps_to_five_fields(self):
        selection = select_extraction_fields(
            utterance="7 July 2000",
            agent_utterance="Sir DOB bata dijiye.",
            expected_field="dob",
        )

        self.assertLessEqual(len(selection.specs), 5)
        self.assertIn("customer_dob", selection.specs)

    def test_core_json_only_field_is_available_without_csv_entry(self):
        registry = load_field_registry()

        self.assertEqual(registry.resolve("doc_status"), "doc_status")

        selection = select_extraction_fields(
            utterance="doc status uploaded hai",
            agent_utterance="Sir document status confirm kar dijiye.",
            registry=registry,
        )

        self.assertIn("doc_status", selection.specs)
        self.assertIn("Uploaded", selection.specs["doc_status"].prompt_description())

    def test_duplicate_core_field_names_do_not_claim_ambiguous_bare_key(self):
        registry = load_field_registry()

        self.assertIsNone(registry.resolve("id"))
        self.assertEqual(registry.resolve("finex_lead.id"), "dynamic_finex_lead_id")

    def test_expected_field_is_selected_even_when_it_is_a_realtime_alias(self):
        selection = select_extraction_fields(
            utterance="7 July 2000",
            agent_utterance="Sir DOB bata dijiye.",
            expected_field="dob",
        )

        self.assertIn("customer_dob", selection.specs)

    def test_profession_branch_selects_relevant_income_field(self):
        field_state = build_resolved_field_state(
            extracted_fields={"profession": "salaried"}
        )
        workflow_state = compute_workflow_state(
            field_state,
            active_category="income_details",
        )

        selection = select_extraction_fields(
            utterance="salary 1 lakh hai",
            agent_utterance="Sir monthly in-hand salary kitni hai?",
            active_category="income_details",
            workflow_state=workflow_state,
        )

        self.assertIn("monthly_salary", selection.specs)


if __name__ == "__main__":
    unittest.main()
