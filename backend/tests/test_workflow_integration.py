import os
import sys
import unittest


sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.services.field_registry import get_field_registry
from app.services.field_resolver import build_resolved_field_state
from app.services.field_resolver import resolve_graphql_facts
from app.services.field_resolver import resolve_extracted_fields
from app.services.category_router import route_category
from app.services.next_action import select_next_action
from app.services.workflow_state import compute_workflow_state


def resolved_state(**fields):
    return build_resolved_field_state(extracted_fields=fields)


class WorkflowIntegrationTest(unittest.TestCase):
    def test_backend_merges_extracted_fields_into_lead_detail_from_registry(self):
        from app.services.lead_profile_merge import merge_extracted_fields_into_lead

        result = merge_extracted_fields_into_lead(
            lead_id=668,
            lead_detail={
                "id": 668,
                "customer": {"first_name": "", "mobile": "9999999999"},
                "co_applicant": [{"ca_first_name": ""}],
            },
            extracted_fields={
                "customer_first_name": "Aman",
                "coapplicant_first_name": "Neha",
                "cibil_score": "760",
            },
        )

        self.assertEqual(result["lead_detail"]["customer"]["first_name"], "Aman")
        self.assertEqual(result["lead_detail"]["co_applicant"][0]["ca_first_name"], "Neha")
        self.assertEqual(result["lead_detail"]["lead_details"]["cibil_score"], "760")
        self.assertEqual(result["lead_facts"]["customer.first_name"], "Aman")
        self.assertEqual(result["lead_facts"]["co_applicant[0].ca_first_name"], "Neha")
        self.assertEqual(result["lead_facts"]["lead_details.cibil_score"], "760")
        self.assertFalse(
            any(item.get("path") == "customer.first_name" for item in result["lead_missing_fields"])
        )

    def test_universal_profile_maps_ids_for_display_without_changing_raw_values(self):
        from app.services.lead_profile_merge import build_lead_profile

        result = build_lead_profile(
            lead_id=668,
            lead_detail={
                "id": 668,
                "loan_type": 1,
                "customer": {
                    "first_name": "Aman",
                    "cra_state": 180,
                    "cra_city": 99,
                    "marital_status": "married",
                    "qualification": "graduate",
                    "language_id": 2,
                },
                "lead_details": {
                    "profession": 1,
                    "property_state": 293,
                    "property_city": 300,
                    "usage_type": 2,
                },
            },
        )

        profile = result["profile"]

        self.assertEqual(profile["raw"]["customer"]["cra_state"], 180)
        self.assertEqual(profile["raw_facts"]["lead_details.profession"], 1)
        self.assertEqual(profile["display"]["customer.cra_state"], "Maharashtra")
        self.assertEqual(profile["display"]["customer.cra_city"], "Bangalore")
        self.assertEqual(profile["display"]["customer.language_id"], "Hindi")
        self.assertEqual(profile["display"]["lead_details.profession"], "Salaried")
        self.assertEqual(profile["display"]["lead_details.property_state"], "Uttar Pradesh")
        self.assertEqual(profile["display"]["lead_details.property_city"], "Lucknow")
        self.assertEqual(profile["display"]["lead_details.usage_type"], "Residential")
        self.assertEqual(result["lead_facts"]["lead_details.profession"], "Salaried")
        self.assertEqual(result["lead_context"]["facts"]["customer.cra_state"], "Maharashtra")
        self.assertIn("category_state", profile["stage_state"])
        self.assertTrue(profile["metadata"]["value_mappings_applied"])

    def test_mobile_key_variants_resolve_to_customer_mobile(self):
        registry = get_field_registry()

        self.assertEqual(registry.resolve("mobile"), "customer_mobile")
        self.assertEqual(registry.resolve("customer.mobile"), "customer_mobile")
        self.assertEqual(registry.resolve("contact_details.mobile"), "customer_mobile")
        self.assertEqual(registry.resolve("customer_mobile"), "customer_mobile")

    def test_customer_mobile_graphql_value_fills_logical_field(self):
        resolved = resolve_graphql_facts({"customer": {"mobile": "9876543210"}})

        self.assertEqual(resolved["customer_mobile"]["value"], "9876543210")
        self.assertEqual(resolved["customer_mobile"]["source"], "graphql")
        self.assertEqual(resolved["customer_mobile"]["status"], "filled")

    def test_indexed_flat_customer_name_fills_logical_field(self):
        field_state = build_resolved_field_state(
            lead_facts={"[0].customer.first_name": "Aman"}
        )
        workflow = compute_workflow_state(field_state, active_category="customer_details")

        self.assertEqual(field_state["customer_first_name"]["value"], "Aman")
        self.assertEqual(
            workflow["category_state"]["customer_details"]["next_field"],
            "customer_last_name",
        )

    def test_loaded_customer_name_is_not_asked_again(self):
        field_state = build_resolved_field_state(
            lead_facts={
                "[0].customer.first_name": "Aman",
                "[0].customer.last_name": "Kumar",
            }
        )
        workflow = compute_workflow_state(field_state, active_category="customer_details")
        action = select_next_action(
            workflow,
            {"category": "customer_details", "confidence": 0.9},
            {},
        )

        self.assertEqual(action["category"], "customer_details")
        self.assertEqual(action["field"], "customer_mobile")

    def test_core_mapping_customer_table_name_fills_customer_name(self):
        field_state = build_resolved_field_state(
            lead_facts={
                "[0].finex_customer.first_name": "Aman",
                "[0].finex_customer.last_name": "Kumar",
            }
        )
        workflow = compute_workflow_state(field_state, active_category="customer_details")
        action = select_next_action(
            workflow,
            {"category": "customer_details", "confidence": 0.9},
            {},
        )

        self.assertEqual(field_state["customer_first_name"]["value"], "Aman")
        self.assertEqual(field_state["customer_last_name"]["value"], "Kumar")
        self.assertEqual(action["field"], "customer_mobile")

    def test_core_mapping_lead_detail_table_name_fills_loan_fields(self):
        field_state = build_resolved_field_state(
            lead_facts={
                "finex_lead_detail.loan_amount": "3000000",
                "finex_lead_detail.profession": "1",
            }
        )

        self.assertEqual(field_state["loan_amount"]["value"], "3000000")
        self.assertEqual(field_state["profession"]["value"], "1")

    def test_core_mapping_coapplicant_ca_fields_fill_workflow_fields(self):
        field_state = build_resolved_field_state(
            lead_detail={
                "co_applicant": [
                    {
                        "relationship_with_customer": "spouse",
                        "ca_first_name": "Neha",
                        "ca_last_name": "Kumar",
                        "ca_mobile": "9999999999",
                        "ca_qualification": "graduate",
                        "ca_type": "financial",
                        "same_as_cus_addr": "1",
                    }
                ]
            }
        )

        self.assertEqual(field_state["has_co_applicant"]["value"], "yes")
        self.assertEqual(field_state["coapplicant_relationship"]["value"], "spouse")
        self.assertEqual(field_state["coapplicant_first_name"]["value"], "Neha")
        self.assertEqual(field_state["coapplicant_last_name"]["value"], "Kumar")
        self.assertEqual(field_state["coapplicant_mobile"]["value"], "9999999999")
        self.assertEqual(field_state["coapplicant_qualification"]["value"], "graduate")
        self.assertEqual(field_state["coapplicant_type"]["value"], "financial")
        self.assertEqual(field_state["coapplicant_same_as_customer_address"]["value"], "1")

    def test_empty_fetched_coapplicant_marks_customer_without_coapplicant(self):
        field_state = build_resolved_field_state(lead_detail={"co_applicant": []})

        self.assertEqual(field_state["has_co_applicant"]["value"], "no")

    def test_realtime_value_overrides_missing_graphql_value(self):
        state = build_resolved_field_state(
            lead_detail={"customer": {"mobile": ""}},
            extracted_fields={"mobile": "9876543210"},
        )

        self.assertEqual(state["customer_mobile"]["value"], "9876543210")
        self.assertEqual(state["customer_mobile"]["source"], "realtime")
        self.assertEqual(len(state["customer_mobile"]["raw_values"]), 2)

    def test_married_status_activates_spouse_name(self):
        workflow = compute_workflow_state(
            resolved_state(customer_marital_status="married"),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertIn("married_customer", state["active_branches"])
        self.assertIn("customer_spouse_name", state["missing_fields"])

    def test_unmarried_status_does_not_ask_spouse_name(self):
        workflow = compute_workflow_state(
            resolved_state(customer_marital_status="single"),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertNotIn("married_customer", state["active_branches"])
        self.assertNotIn("customer_spouse_name", state["missing_fields"])

    def test_coapplicant_present_activates_coapplicant_fields(self):
        workflow = compute_workflow_state(
            resolved_state(has_co_applicant="yes"),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertIn("co_applicant_present", state["active_branches"])
        self.assertIn("coapplicant_relationship", state["missing_fields"])
        self.assertIn("coapplicant_mobile", state["missing_fields"])
        self.assertIn("coapplicant_pan", state["missing_fields"])
        self.assertIn("coapplicant_same_as_customer_address", state["missing_fields"])
        self.assertNotIn("coapplicant_address_required", state["active_branches"])

    def test_same_customer_address_skips_coapplicant_address_fields(self):
        workflow = compute_workflow_state(
            resolved_state(
                has_co_applicant="yes",
                coapplicant_same_as_customer_address="yes",
            ),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertNotIn("coapplicant_address_required", state["active_branches"])
        self.assertNotIn("coapplicant_city", state["missing_fields"])

    def test_not_same_coapplicant_address_activates_address_fields(self):
        workflow = compute_workflow_state(
            resolved_state(
                has_co_applicant="yes",
                coapplicant_same_as_customer_address="0",
            ),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertIn("coapplicant_address_required", state["active_branches"])
        self.assertIn("coapplicant_city", state["missing_fields"])
        self.assertIn("coapplicant_address_line2", state["missing_fields"])

    def test_married_coapplicant_activates_spouse_name_only_when_present(self):
        workflow = compute_workflow_state(
            resolved_state(
                has_co_applicant="yes",
                coapplicant_marital_status="married",
            ),
            active_category="customer_details",
        )
        state = workflow["category_state"]["customer_details"]

        self.assertIn("married_coapplicant", state["active_branches"])
        self.assertIn("coapplicant_spouse_name", state["missing_fields"])

    def test_completed_customer_details_moves_to_next_incomplete_category(self):
        field_state = resolved_state(
            loan_type="1",
            loan_amount="3000000",
            is_property_identified="no",
            customer_first_name="Rahul",
            customer_last_name="Sharma",
            customer_gender="male",
            customer_mobile="9876543210",
            customer_dob="1990-01-01",
            customer_pan="ABCDE1234F",
            customer_aadhaar="123412341234",
            customer_email="rahul@example.com",
            customer_marital_status="single",
            customer_pincode="400001",
            customer_city="Mumbai",
            customer_state="Maharashtra",
            customer_address_line1="Line 1",
            customer_address_line2="Line 2",
            customer_mother_name="Sunita",
            customer_qualification="graduate",
            customer_preferred_language="hindi",
            customer_office_address="Office address",
            customer_dependents="2",
            customer_designation="Manager",
            customer_occupation="salaried",
            customer_official_email="rahul@company.com",
            has_co_applicant="no",
            profession="salaried",
            monthly_salary="150000",
        )
        workflow = compute_workflow_state(field_state, active_category="customer_details")
        action = select_next_action(
            workflow,
            {"category": "customer_details", "confidence": 0.9},
            {},
        )

        self.assertEqual(action["type"], "category_complete")
        self.assertEqual(action["category"], "customer_details")
        self.assertEqual(action["next_category"], "offer_check")
        self.assertEqual(action["field"], "cibil_score")

    def test_identified_property_fills_home_loan_property_requirement(self):
        workflow = compute_workflow_state(
            resolved_state(
                loan_type="home loan",
                loan_amount="8000000",
                is_property_identified="yes",
            ),
            active_category="loan_requirement",
        )
        state = workflow["category_state"]["loan_requirement"]

        self.assertEqual(state["status"], "complete")
        self.assertNotIn("is_property_identified", state["missing_fields"])

    def test_opening_call_starts_with_customer_details_not_property(self):
        field_state = resolved_state()
        workflow = compute_workflow_state(field_state, active_category=None)
        route = route_category(
            utterance="haan main vikas bol raha hoon aap kaun bol rahe hain",
            extracted_fields={},
            field_state=field_state,
            previous_category=None,
            workflow_state=workflow,
        ).to_dict()
        action = select_next_action(workflow, route, {})

        self.assertEqual(route["category"], "customer_details")
        self.assertEqual(action["category"], "customer_details")
        self.assertNotIn("property", action["field"])

    def test_customer_name_keeps_suggestion_in_customer_details(self):
        field_state = resolved_state(customer_first_name="Vikas")
        workflow = compute_workflow_state(field_state, active_category="customer_details")
        route = route_category(
            utterance="haan main vikas bol raha hoon",
            extracted_fields=resolve_extracted_fields({"customer_first_name": "Vikas"}),
            field_state=field_state,
            previous_category=None,
            workflow_state=workflow,
        ).to_dict()
        action = select_next_action(workflow, route, {})

        self.assertEqual(route["category"], "customer_details")
        self.assertEqual(action["category"], "customer_details")
        self.assertEqual(action["field"], "customer_last_name")

    def test_profession_salaried_activates_salary_field(self):
        workflow = compute_workflow_state(
            resolved_state(profession="salaried"),
            active_category="income_details",
        )
        state = workflow["category_state"]["income_details"]

        self.assertIn("salaried", state["active_branches"])
        self.assertIn("monthly_salary", state["missing_fields"])
        self.assertEqual(state["next_field"], "monthly_salary")

    def test_profession_business_activates_business_income_field(self):
        workflow = compute_workflow_state(
            resolved_state(profession="business"),
            active_category="income_details",
        )
        state = workflow["category_state"]["income_details"]

        self.assertIn("self_employed", state["active_branches"])
        self.assertIn("income_calculation_mode", state["missing_fields"])
        self.assertEqual(state["next_field"], "income_calculation_mode")

    def test_last_answered_field_is_not_repeated(self):
        field_state = resolved_state(
            customer_first_name="Rahul",
            customer_last_name="Sharma",
            customer_mobile="9876543210",
        )
        workflow = compute_workflow_state(field_state, active_category="customer_details")
        action = select_next_action(
            workflow,
            {"category": "customer_details", "confidence": 0.9},
            {"type": "ask_field", "field": "customer_mobile"},
        )

        self.assertNotEqual(action["field"], "customer_mobile")
        self.assertEqual(action["field"], "customer_dob")

    def test_topic_change_returns_switch_category_action(self):
        workflow = compute_workflow_state(
            resolved_state(property_city="Noida"),
            active_category="property_details",
        )
        action = select_next_action(
            workflow,
            {
                "category": "property_details",
                "previous_category": "loan_requirement",
                "confidence": 0.9,
                "reason": "topic trigger matched",
            },
            {},
        )

        self.assertEqual(action["type"], "switch_category")
        self.assertEqual(action["from_category"], "loan_requirement")
        self.assertEqual(action["to_category"], "property_details")

    def test_newly_extracted_field_overrides_previous_agent_topic(self):
        field_state = resolved_state(
            is_property_identified="yes",
            property_city="Noida",
            property_state="Uttar Pradesh",
        )
        workflow = compute_workflow_state(field_state, active_category="property_details")
        route = route_category(
            utterance="haan 1 lakh",
            extracted_fields=resolve_extracted_fields({"monthly_salary": "100000"}),
            field_state=field_state,
            previous_category="property_details",
            agent_last_utterance="Sir property ka expected market value kitna hai?",
            workflow_state=workflow,
        ).to_dict()
        route["previous_category"] = "property_details"
        updated_workflow = compute_workflow_state(
            build_resolved_field_state(
                existing=field_state,
                extracted_fields={"monthly_salary": "100000"},
            ),
            active_category=route.get("category"),
        )
        action = select_next_action(updated_workflow, route, {})

        self.assertEqual(route["category"], "income_details")
        self.assertEqual(action["category"], "income_details")

    def test_balance_transfer_activates_previous_loan_fields(self):
        workflow = compute_workflow_state(
            resolved_state(loan_type="balance transfer"),
            active_category="loan_requirement",
        )
        state = workflow["category_state"]["loan_requirement"]

        self.assertIn("balance_transfer", state["active_branches"])
        self.assertIn("previous_loan_amount", state["missing_fields"])
        self.assertIn("previous_current_roi", state["missing_fields"])

    def test_home_loan_does_not_ask_balance_transfer_fields(self):
        workflow = compute_workflow_state(
            resolved_state(loan_type="home loan"),
            active_category="loan_requirement",
        )
        state = workflow["category_state"]["loan_requirement"]

        self.assertIn("home_loan", state["active_branches"])
        self.assertNotIn("previous_loan_amount", state["missing_fields"])
        self.assertNotIn("previous_current_roi", state["missing_fields"])


if __name__ == "__main__":
    unittest.main()
