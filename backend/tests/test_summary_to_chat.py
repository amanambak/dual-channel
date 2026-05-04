import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))


class SummaryToChatRouteTest(unittest.IsolatedAsyncioTestCase):
    def mock_lead_plan(self, service, plan):
        service.generate_json = AsyncMock(return_value=plan)
        service.generate_text = AsyncMock(return_value="Should not be called")

    async def test_summary_to_chat_returns_llm_question_with_schema_context(self):
        os.environ.setdefault("GOOGLE_API_KEY", "test-key")
        os.environ.setdefault("GEMINI_API_KEY", "test-key")

        payload = {
            "customer_info": {
                "loan_amount": "20L",
                "cibil_score": "760",
            }
        }

        with patch("app.services.rag_service.RAGService", autospec=True):
            from app.api.websocket import SummaryChatRequest, summary_chat

        with patch(
            "app.api.websocket.llm_service.generate_db_insert_question",
            new=AsyncMock(return_value="Insert loan_amount first, then cibil_score."),
        ) as mock_generate:
            response = await summary_chat(SummaryChatRequest(**payload))

            self.assertEqual(
                response["reply"],
                "Insert loan_amount first, then cibil_score.",
            )
            self.assertEqual(
                response["customer_info"],
                {"loan_amount": "2000000", "cibil_score": "760"},
            )

            mock_generate.assert_awaited_once()
            _, kwargs = mock_generate.await_args
            self.assertEqual(
                kwargs["customer_info"],
                {"loan_amount": "2000000", "cibil_score": "760"},
            )
            self.assertIn("loan_amount", kwargs["schema_prompt"])
            self.assertIn("cibil_score", kwargs["schema_prompt"])

    def test_db_insert_prompt_asks_for_an_answer(self):
        from app.llm.service import build_db_insert_question_prompt

        prompt = build_db_insert_question_prompt(
            {"loan_amount": "3000000", "cibil_score": "760"},
            "Known fields: loan_amount: 3000000",
            "schema reference",
        )

        self.assertIn("Answer which extracted canonical field(s) should be inserted into the database now.", prompt)
        self.assertIn("Do not ask a question.", prompt)
        self.assertNotIn("Ask exactly one concise question", prompt)

    def test_lead_query_plan_prompt_prefers_only_requested_fields(self):
        from app.llm.service import build_lead_query_plan_prompt

        prompt = build_lead_query_plan_prompt(
            "bank name?",
            "\n".join(
                [
                    "- lead_details.bank.id | Id | available",
                    "- lead_details.bank.dsa_code | Dsa code | available",
                    "- lead_details.bank.banklang.bank_name | Bank name | available",
                ]
            ),
        )

        self.assertIn("Return only the data explicitly asked for", prompt)
        self.assertIn("bank name? -> {\"action\":\"fields\",\"fields\":[\"lead_details.bank.banklang.bank_name\"]", prompt)
        self.assertIn("Only return fields when highly confident", prompt)
        self.assertIn("rm mobile -> {\"action\":\"fields\"", prompt)
        self.assertIn(
            "which priority property details are missing? -> {\"action\":\"missing_fields\",\"fields\":[],\"confidence\":0.8,\"scope_hint\":\"property\",\"priority_only\":true}",
            prompt,
        )
        self.assertIn(
            "priority details konsi missing hai? -> {\"action\":\"missing_fields\",\"fields\":[],\"confidence\":0.2,\"scope_hint\":null,\"priority_only\":true}",
            prompt,
        )
        self.assertNotIn("query_terms", prompt)

    def test_sanitize_lead_query_plan_drops_query_terms_and_low_confidence_fields(self):
        from app.services.lead_detail_context import sanitize_lead_query_plan

        plan = sanitize_lead_query_plan(
            {
                "action": "missing_fields",
                "fields": ["lead_details.cibil_score", "fake.path"],
                "query_terms": ["konsi", "details"],
                "confidence": 0.2,
                "scope_hint": "property",
            },
            {"lead_details.cibil_score", "property_details.builder_id"},
        )

        self.assertEqual(plan["action"], "missing_fields")
        self.assertEqual(plan["fields"], [])
        self.assertEqual(plan["confidence"], 0.2)
        self.assertEqual(plan["scope_hint"], None)
        self.assertNotIn("query_terms", plan)

    def test_normalize_extracted_fields_scales_lakh_values(self):
        from app.services.schema_normalizer import normalize_extracted_fields

        normalized = normalize_extracted_fields(
            {
                "loan_amount": "20L",
                "cibil_score": "760",
            }
        )

        self.assertEqual(normalized["loan_amount"], "2000000")
        self.assertEqual(normalized["cibil_score"], "760")

    async def test_chat_prompt_does_not_expose_source_filenames(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(
                return_value=[
                    Document(
                        page_content="Home loan policy says age must be 21 to 65.",
                        metadata={"source": "/tmp/loan_policy.txt"},
                    )
                ]
            )

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Answer only from context."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply("What is the eligibility?")

            self.assertEqual(reply, "Answer only from context.")
            prompt = captured_prompt["prompt"]
            self.assertNotIn("[source_filename]", prompt)
            self.assertNotIn("loan_policy.txt", prompt)
            self.assertNotIn("Document:", prompt)
            self.assertIn("Home loan policy says age must be 21 to 65.", prompt)

    async def test_chat_prompt_includes_loaded_lead_context(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Lead ka loan amount 2500000 hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "Give me a short overview of this loaded profile.",
                lead_id=668,
                lead_detail={
                    "id": 668,
                    "customer": {
                        "first_name": "Rahul",
                        "mobile": "9876543210",
                    },
                    "lead_details": {
                        "lead_id": 668,
                        "loan_amount": 2500000,
                        "cibil_score": 760,
                    },
                },
            )

            self.assertEqual(reply, "Lead ka loan amount 2500000 hai.")
            prompt = captured_prompt["prompt"]
            self.assertIn("Loaded Lead Details", prompt)
            self.assertIn("Lead ID: 668", prompt)
            self.assertIn("lead_details.loan_amount: 2500000", prompt)
            self.assertIn("customer.first_name: Rahul", prompt)

    def test_lead_detail_context_flattens_key_fields(self):
        from app.services.lead_detail_context import build_lead_detail_chat_context

        context = build_lead_detail_chat_context(
            lead_id=668,
            lead_detail={
                "customer": {"first_name": "Rahul", "email": "rahul@example.com"},
                "lead_details": {"loan_amount": 2500000, "property_city": "Noida"},
            },
        )

        self.assertIn("Lead ID: 668", context)
        self.assertIn("customer.email: rahul@example.com", context)
        self.assertIn("lead_details.property_city: Noida", context)

    async def test_chat_answers_loaded_lead_field_without_rag(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["partner_name"]})

            reply = await service.generate_chat_reply(
                "what is partner name?",
                lead_id=667,
                lead_detail={"partner_name": "Ambak Partner"},
            )

            self.assertEqual(reply, "Partner name: Ambak Partner")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_chat_answers_loaded_lead_field_from_flat_facts(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["customer.first_name"]})

            reply = await service.generate_chat_reply(
                "what is customer first name?",
                lead_id=667,
                lead_facts={"customer.first_name": "Aman"},
            )

            self.assertEqual(reply, "First name: Aman")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_chat_answers_grouped_customer_name_in_structured_format(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["customer.first_name", "customer.last_name"]})

            reply = await service.generate_chat_reply(
                "what is customer name?",
                lead_id=667,
                lead_facts={"customer.first_name": "Gautam", "customer.last_name": "Gambhir"},
            )

            self.assertEqual(reply, "First name: Gautam\nLast name: Gambhir")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_customer_name_does_not_use_generic_name_field(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["customer.first_name", "customer.last_name"]})

            reply = await service.generate_chat_reply(
                "what is customer name?",
                lead_id=667,
                lead_detail={
                    "lead_breadcrumb": [{"name": "New"}],
                    "customer": {"first_name": "Gautam", "last_name": "Gambhir"},
                },
            )

            self.assertEqual(reply, "First name: Gautam\nLast name: Gambhir")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_chat_answers_followup_data_in_structured_format(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["followup_date", "followup_type"]})

            reply = await service.generate_chat_reply(
                "what is followup data?",
                lead_id=667,
                lead_facts={"followup_date": "28 April 2026", "followup_type": "call"},
            )

            self.assertEqual(reply, "Followup date: 28 April 2026\nFollowup type: call")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_property_identified_question_uses_boolean_field_not_id(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["lead_details.is_property_identified"]})

            reply = await service.generate_chat_reply(
                "property identified kya hai?",
                lead_id=668,
                lead_facts={"id": "668", "lead_details.is_property_identified": "no"},
            )

            self.assertEqual(reply, "Is property identified: no")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_bank_details_question_returns_bank_section(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "section", "section_path": "lead_details.bank"})

            lead_facts = {
                "lead_details.bank.id": "1",
                "lead_details.bank.dsa_code": "kjhsd8789ds",
                "lead_details.bank.is_gross_code": "0",
                "lead_details.bank.banklang.bank_name": "ICICI Bank",
            }
            reply = await service.generate_chat_reply(
                "lead ki puri bank details batao",
                lead_id=668,
                lead_facts=lead_facts,
            )

            self.assertEqual(
                reply,
                "Bank details:\nId: 1\nDsa code: kjhsd8789ds\nIs gross code: 0\nBank name: ICICI Bank",
            )
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_bank_name_question_still_returns_single_field(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["lead_details.bank.banklang.bank_name"]})

            reply = await service.generate_chat_reply(
                "bank name?",
                lead_id=668,
                lead_facts={
                    "lead_details.bank.dsa_code": "kjhsd8789ds",
                    "lead_details.bank.banklang.bank_name": "ICICI Bank",
                },
            )

            self.assertEqual(reply, "Bank name: ICICI Bank")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_hierarchy_details_are_grouped_by_role(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "section", "section_path": "hierarchy_details"})

            reply = await service.generate_chat_reply(
                "give details of hierarchy_details",
                lead_id=667,
                lead_detail={
                    "hierarchy_details": {
                        "rm_id": {
                            "id": 158,
                            "label": "yoddha Anurag",
                            "mobile": "8853075020",
                            "email": "qa@ambak.com",
                        },
                        "abm_id": {
                            "id": 47,
                            "label": "Malhar",
                            "mobile": "7425840901",
                            "email": "aqib11.siddiqui@ambak.com",
                        },
                    },
                },
            )

            self.assertEqual(
                reply,
                "Hierarchy details:\n"
                "RM:\n"
                "- Id: 158\n"
                "- Label: yoddha Anurag\n"
                "- Mobile: 8853075020\n"
                "- Email: qa@ambak.com\n\n"
                "ABM:\n"
                "- Id: 47\n"
                "- Label: Malhar\n"
                "- Mobile: 7425840901\n"
                "- Email: aqib11.siddiqui@ambak.com",
            )
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_missing_profile_fields_are_deterministic_and_include_marital_status(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["customer", "lead_details"]})

            reply = await service.generate_chat_reply(
                "abhi customer ke profile mei kon kon se field missing hai?",
                lead_id=667,
                lead_facts={
                    "customer.first_name": "Mahendra",
                    "customer.last_name": "Dhoni",
                    "customer.mobile": "7526695567",
                    "customer.email": None,
                    "customer.marital_status": None,
                    "lead_details.loan_amount": "10000000",
                    "lead_details.monthly_salary": "100000",
                    "lead_details.cibil_score": "766",
                },
            )

            self.assertIn("missing fields", reply.lower())
            self.assertIn("- Marital status", reply)
            self.assertIn("- Email", reply)
            self.assertNotIn("KYC status pending", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_missing_fields_with_invalid_profile_scope_falls_back_to_loaded_missing_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["profile"]})

            reply = await service.generate_chat_reply(
                "abhi customer ke profile mei kon kon se field missing hai?",
                lead_id=667,
                lead_facts={
                    "customer.first_name": "Mahendra",
                    "customer.email": None,
                    "customer.marital_status": None,
                    "lead_details.loan_amount": "10000000",
                },
            )

            self.assertIn("missing fields", reply.lower())
            self.assertIn("- Email", reply)
            self.assertIn("- Marital status", reply)
            self.assertNotIn("None found", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_missing_fields_use_precomputed_fetch_snapshot(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["profile"]})

            reply = await service.generate_chat_reply(
                "missing fields batao",
                lead_id=667,
                lead_detail={"customer": {"first_name": "Mahendra"}},
                lead_missing_fields=[
                    {"path": "customer.email", "label": "Email", "reason": "null"},
                    {"path": "lead_details.property_city", "label": "Property city", "reason": "empty_string"},
                ],
            )

            self.assertIn("High priority missing fields:", reply)
            self.assertIn("Other missing fields:", reply)
            self.assertIn("- Email (null)", reply)
            self.assertIn("- Property city (empty string)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_lead_644_priority_missing_query_resolves_indexed_flat_facts(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService
            from app.services.lead_detail_context import load_priority_field_paths

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["lead_details", "customer", "property_details"]})
            stale_missing_snapshot = [
                {"path": f"[0].{path}", "label": path.split(".")[-1].replace("_", " ").capitalize(), "reason": "not_loaded"}
                for path in load_priority_field_paths()
            ]

            reply = await service.generate_chat_reply(
                "what are the priority missing details",
                lead_id=644,
                lead_facts={
                    "[0].id": "644",
                    "[0].loan_type": "2",
                    "[0].lead_details.lead_id": "644",
                    "[0].lead_details.profession": "1",
                    "[0].lead_details.cibil_score": "899",
                    "[0].lead_details.prev_emi_amount": "0",
                    "[0].lead_details.prev_loan_amount": "0",
                    "[0].lead_details.prev_loan_start_date": None,
                    "[0].lead_details.prev_tenure": "0",
                    "[0].lead_details.prev_current_roi": "0",
                    "[0].lead_details.remaining_loan_amount": "0",
                    "[0].lead_details.monthly_salary": "1000000",
                    "[0].lead_details.is_property_decided": "Yes",
                    "[0].lead_details.income_calculation_mode": "",
                    "[0].customer.mobile": "6333949398",
                    "[0].customer.pancard_no": "LYUPS3752G",
                    "[0].customer.dob": "31/01/2001",
                    "[0].property_details.is_property_identified": "yes",
                    "[0].property_details.property_city": "67",
                    "[0].property_details.property_state": "65",
                    "[0].property_details.expected_market_value": "0",
                    "[0].property_details.registration_value": "0",
                    "[0].property_details.property_type": "",
                    "[0].property_details.property_sub_type": "",
                    "[0].property_details.agreement_type": "",
                    "[0].property_details.builder_id": None,
                    "[0].property_details.project_id": None,
                    "[0].property_details.check_oc_cc": "0",
                    "[0].property_details.ready_for_registration": "0",
                    "[0].fulfillment_type": "ambak",
                },
                lead_missing_fields=stale_missing_snapshot,
            )

            self.assertNotIn("Loan type (not loaded)", reply)
            self.assertNotIn("Lead id (not loaded)", reply)
            self.assertNotIn("Profession (not loaded)", reply)
            self.assertNotIn("Cibil score (not loaded)", reply)
            self.assertNotIn("Mobile (not loaded)", reply)
            self.assertIn("Prev loan start date (null)", reply)
            self.assertIn("Income calculation mode (empty string)", reply)
            self.assertIn("Property type (empty string)", reply)
            self.assertIn("Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_lead_644_priority_missing_query_ignores_stale_not_loaded_snapshot(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService
            from app.services.lead_detail_context import load_priority_field_paths

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["lead_details", "customer", "property_details"]})
            stale_missing_snapshot = [
                {"path": path, "label": path.split(".")[-1].replace("_", " ").capitalize(), "reason": "not_loaded"}
                for path in load_priority_field_paths()
            ]

            reply = await service.generate_chat_reply(
                "what are the priority missing details",
                lead_id=644,
                lead_detail={"id": 644},
                lead_facts={
                    "id": "644",
                    "loan_type": "2",
                    "lead_details.lead_id": "644",
                    "lead_details.profession": "1",
                    "lead_details.cibil_score": "899",
                    "lead_details.prev_emi_amount": "0",
                    "lead_details.prev_loan_amount": "0",
                    "lead_details.prev_loan_start_date": None,
                    "lead_details.prev_tenure": "0",
                    "lead_details.prev_current_roi": "0",
                    "lead_details.remaining_loan_amount": "0",
                    "lead_details.monthly_salary": "1000000",
                    "lead_details.is_property_decided": "Yes",
                    "lead_details.income_calculation_mode": "",
                    "customer.mobile": "6333949398",
                    "customer.pancard_no": "LYUPS3752G",
                    "customer.dob": "31/01/2001",
                    "property_details.is_property_identified": "yes",
                    "property_details.property_city": "67",
                    "property_details.property_state": "65",
                    "property_details.expected_market_value": "0",
                    "property_details.registration_value": "0",
                    "property_details.property_type": "",
                    "property_details.property_sub_type": "",
                    "property_details.agreement_type": "",
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.check_oc_cc": "0",
                    "property_details.ready_for_registration": "0",
                    "fulfillment_type": "ambak",
                },
                lead_missing_fields=stale_missing_snapshot,
            )

            self.assertNotIn("Loan type (not loaded)", reply)
            self.assertNotIn("Lead id (not loaded)", reply)
            self.assertNotIn("Profession (not loaded)", reply)
            self.assertNotIn("Cibil score (not loaded)", reply)
            self.assertNotIn("Mobile (not loaded)", reply)
            self.assertIn("Prev loan start date (null)", reply)
            self.assertIn("Income calculation mode (empty string)", reply)
            self.assertIn("Property type (empty string)", reply)
            self.assertIn("Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_property_missing_query_returns_only_property_priority_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "scope_prefixes": ["property_details"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which priority property details are missing?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.is_property_identified": "yes",
                    "property_details.property_city": "67",
                    "property_details.property_state": "65",
                    "property_details.expected_market_value": None,
                    "property_details.registration_value": None,
                    "property_details.property_type": None,
                    "property_details.property_sub_type": None,
                    "property_details.agreement_type": None,
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.check_oc_cc": "0",
                    "property_details.ready_for_registration": "0",
                    "lead_details.remarks": None,
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Expected market value (null)\n"
                "- Registration value (null)\n"
                "- Property type (null)\n"
                "- Property sub type (null)\n"
                "- Agreement type (null)\n"
                "- Builder id (null)\n"
                "- Project id (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Prev emi", reply)
            self.assertNotIn("Other missing fields", reply)
            self.assertNotIn("Remarks", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_property_query_terms_resolve_to_property_scope(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "query_terms": ["property"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "give priority property details are missing",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.is_property_identified": "yes",
                    "property_details.property_city": "67",
                    "property_details.property_state": "65",
                    "property_details.expected_market_value": None,
                    "property_details.registration_value": None,
                    "property_details.property_type": None,
                    "property_details.property_sub_type": None,
                    "property_details.agreement_type": None,
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.check_oc_cc": "0",
                    "property_details.ready_for_registration": "0",
                    "lead_details.income_calculation_mode": "",
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Expected market value (null)\n"
                "- Registration value (null)\n"
                "- Property type (null)\n"
                "- Property sub type (null)\n"
                "- Agreement type (null)\n"
                "- Builder id (null)\n"
                "- Project id (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Prev emi", reply)
            self.assertNotIn("Income calculation", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_property_message_scopes_even_when_plan_omits_terms(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which priority property details are missing?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.is_property_identified": "yes",
                    "property_details.property_city": "67",
                    "property_details.property_state": "65",
                    "property_details.expected_market_value": None,
                    "property_details.registration_value": None,
                    "property_details.property_type": None,
                    "property_details.property_sub_type": None,
                    "property_details.agreement_type": None,
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.check_oc_cc": "0",
                    "property_details.ready_for_registration": "0",
                    "lead_details.income_calculation_mode": "",
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Expected market value (null)\n"
                "- Registration value (null)\n"
                "- Property type (null)\n"
                "- Property sub type (null)\n"
                "- Agreement type (null)\n"
                "- Builder id (null)\n"
                "- Project id (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Prev emi", reply)
            self.assertNotIn("Income calculation", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_builder_query_uses_natural_subject_without_known_scope(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which priority builder details are missing?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.property_type": None,
                },
            )

            self.assertEqual(reply, "High priority missing fields:\n- Builder id (null)")
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Prev emi", reply)
            self.assertNotIn("Project", reply)
            self.assertNotIn("Property type", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_credit_query_uses_natural_subject_without_known_scope(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which priority credit details are missing?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                    "lead_details.income_calculation_mode": "",
                },
            )

            self.assertEqual(reply, "High priority missing fields:\n- Cibil score (empty string)")
            self.assertNotIn("Prev emi", reply)
            self.assertNotIn("Builder", reply)
            self.assertNotIn("Income", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_existing_loan_bt_query_returns_only_bt_priority_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "field_groups": ["existing_loan_bt"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which missing Existing Loan / BT details are pending?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.income_calculation_mode": "",
                    "lead_details.prev_emi_amount": None,
                    "lead_details.prev_loan_amount": None,
                    "lead_details.prev_loan_start_date": None,
                    "lead_details.prev_tenure": None,
                    "lead_details.prev_current_roi": None,
                    "lead_details.remaining_loan_amount": None,
                    "property_details.property_type": None,
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Prev emi amount (null)\n"
                "- Prev loan amount (null)\n"
                "- Prev loan start date (null)\n"
                "- Prev tenure (null)\n"
                "- Prev current roi (null)\n"
                "- Remaining loan amount (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Income calculation", reply)
            self.assertNotIn("Property", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_generic_priority_missing_query_ignores_spurious_bt_group(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "field_groups": ["existing_loan_bt"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "list the priority missing details",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "lead_details.prev_loan_amount": None,
                    "lead_details.prev_loan_start_date": None,
                    "lead_details.prev_tenure": None,
                    "lead_details.prev_current_roi": None,
                    "lead_details.remaining_loan_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_generic_priority_missing_query_ignores_spurious_bt_query_terms(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "query_terms": ["existing loan", "bt"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "list the priority missing details",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "lead_details.prev_loan_amount": None,
                    "lead_details.prev_loan_start_date": None,
                    "lead_details.prev_tenure": None,
                    "lead_details.prev_current_roi": None,
                    "lead_details.remaining_loan_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_highest_priority_missing_query_returns_priority_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "list highest priority missing details",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_hinglish_priority_missing_query_returns_priority_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "priority details konsi missing hai?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_low_confidence_missing_plan_ignores_query_terms_and_runs_broad(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "query_terms": ["konsi", "details"],
                    "fields": ["fake.path"],
                    "confidence": 0.2,
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "priority details konsi missing hai?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_property_scope_hint_filters_missing_fields_without_query_terms(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "fields": [],
                    "confidence": 0.8,
                    "scope_hint": "property",
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "property ke missing details",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.is_property_identified": "yes",
                    "property_details.property_city": "67",
                    "property_details.property_state": "65",
                    "property_details.expected_market_value": "5000000",
                    "property_details.registration_value": "4500000",
                    "property_details.property_type": "1",
                    "property_details.property_sub_type": "2",
                    "property_details.agreement_type": "registered",
                    "property_details.builder_id": None,
                    "property_details.project_id": None,
                    "property_details.check_oc_cc": "1",
                    "property_details.ready_for_registration": "1",
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Builder id (null)\n"
                "- Project id (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Prev emi", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_hinglish_priority_missing_query_does_not_depend_on_llm_plan(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            service.generate_json = AsyncMock(return_value={"action": "fallback"})
            service.generate_text = AsyncMock(return_value="Should not be called")

            reply = await service.generate_chat_reply(
                "priority details konsi missing hai?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            service.generate_json.assert_not_awaited()
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_hinglish_priority_missing_list_request_returns_priority_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            service.generate_json = AsyncMock(return_value={"action": "fallback"})
            service.generate_text = AsyncMock(return_value="Should not be called")

            reply = await service.generate_chat_reply(
                "missing priority details list kar do",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            service.generate_json.assert_not_awaited()
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_generic_priority_missing_query_ignores_unknown_filler_words(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            service.generate_json = AsyncMock(return_value={"action": "fallback"})
            service.generate_text = AsyncMock(return_value="Should not be called")

            reply = await service.generate_chat_reply(
                "missing priority details randomword pleasewala kuch bhi bol do",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.prev_emi_amount": None,
                    "property_details.builder_id": None,
                },
            )

            self.assertIn("- Cibil score (empty string)", reply)
            self.assertIn("- Prev emi amount (null)", reply)
            self.assertIn("- Builder id (null)", reply)
            service.generate_json.assert_not_awaited()
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_missing_query_terms_resolve_to_catalog_field_group(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(
                service,
                {
                    "action": "missing_fields",
                    "query_terms": ["previous loan"],
                    "priority_only": True,
                },
            )

            reply = await service.generate_chat_reply(
                "which previous loan details are missing?",
                lead_id=644,
                lead_facts={
                    "lead_details.cibil_score": "",
                    "lead_details.income_calculation_mode": "",
                    "lead_details.prev_emi_amount": None,
                    "lead_details.prev_loan_amount": None,
                    "lead_details.prev_loan_start_date": None,
                    "lead_details.prev_tenure": None,
                    "lead_details.prev_current_roi": None,
                    "lead_details.remaining_loan_amount": None,
                    "property_details.property_type": None,
                },
            )

            self.assertEqual(
                reply,
                "High priority missing fields:\n"
                "- Prev emi amount (null)\n"
                "- Prev loan amount (null)\n"
                "- Prev loan start date (null)\n"
                "- Prev tenure (null)\n"
                "- Prev current roi (null)\n"
                "- Remaining loan amount (null)",
            )
            self.assertNotIn("Cibil", reply)
            self.assertNotIn("Income calculation", reply)
            self.assertNotIn("Property", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_priority_missing_uses_lead_facts_when_detail_is_partial(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_fields", "scope_prefixes": ["lead_details"]})

            reply = await service.generate_chat_reply(
                "what are the priority missing details",
                lead_id=678,
                lead_detail={"partial": True},
                lead_facts={
                    "id": "678",
                    "loan_type": "2",
                    "lead_details.lead_id": "678",
                    "lead_details.profession": "1",
                    "lead_details.cibil_score": "899",
                    "lead_details.monthly_salary": "1000000",
                    "customer.mobile": "6333949398",
                    "customer.pancard_no": "LYUPS3752G",
                    "customer.dob": "31/01/2001",
                    "fulfillment_type": "ambak",
                },
            )

            self.assertNotIn("Lead id (not loaded)", reply)
            self.assertNotIn("Loan type (not loaded)", reply)
            self.assertNotIn("Profession (not loaded)", reply)
            self.assertNotIn("Cibil score (not loaded)", reply)
            self.assertNotIn("Mobile (not loaded)", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    def test_offer_priority_aliases_do_not_mark_equivalent_loaded_fields_missing(self):
        from app.services.lead_detail_context import build_priority_missing_fields

        missing = build_priority_missing_fields(
            {
                "id": 678,
                "loan_type": 2,
                "lead_details": {
                    "lead_id": 678,
                    "profession": 1,
                    "cibil_score": 899,
                    "monthly_salary": "1000000",
                    "property_city": 67,
                    "property_state": 65,
                    "is_property_identified": "yes",
                },
                "customer": {
                    "mobile": "6333949398",
                    "pancard_no": "LYUPS3752G",
                    "dob": "31/01/2001",
                },
                "fulfillment_type": "ambak",
            },
            [],
        )

        missing_paths = {item["path"] for item in missing}
        self.assertNotIn("lead_details.lead_id", missing_paths)
        self.assertNotIn("property_details.property_city", missing_paths)
        self.assertNotIn("property_details.property_state", missing_paths)
        self.assertNotIn("property_details.is_property_identified", missing_paths)

    async def test_next_step_uses_high_priority_offer_fields(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "next_step"})

            reply = await service.generate_chat_reply(
                "next kya puchna hai?",
                lead_id=667,
                lead_facts={
                    "loan_type": "2",
                    "customer.mobile": "6333949398",
                    "lead_details.cibil_score": "899",
                },
            )

            self.assertIn("Next step:", reply)
            self.assertIn("Lead id", reply)
            self.assertIn("Profession", reply)
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_repeated_next_step_asks_for_refresh_confirmation(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "next_step"})

            result = await service.generate_chat_reply_payload(
                "what is the next step?",
                history=[
                    {"role": "user", "content": "what is the next step?"},
                    {"role": "assistant", "content": "Next step: Customer se Cibil Score confirm karein."},
                ],
                lead_id=667,
                lead_facts={"lead_details.cibil_score": ""},
            )

            self.assertTrue(result["needs_lead_refresh_confirmation"])
            self.assertIn("database/lead details update", result["reply"])
            self.assertEqual(result["previous_next_step"], "Next step: Customer se Cibil Score confirm karein.")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_no_refresh_confirmation_returns_previous_next_step(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "next_step"})

            result = await service.generate_chat_reply_payload(
                "No, same data",
                history=[
                    {"role": "user", "content": "what is the next step?"},
                    {"role": "assistant", "content": "Next step: Customer se Cibil Score confirm karein."},
                    {"role": "user", "content": "what is the next step?"},
                    {"role": "assistant", "content": "Kya database/lead details update hue hain?"},
                ],
                lead_id=667,
                lead_facts={"lead_details.cibil_score": ""},
            )

            self.assertEqual(result["reply"], "Next step: Customer se Cibil Score confirm karein.")
            self.assertTrue(result["used_cached_next_step"])
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_refreshed_next_step_recomputes_without_confirmation(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "next_step"})

            result = await service.generate_chat_reply_payload(
                "what is the next step?",
                history=[
                    {"role": "user", "content": "what is the next step?"},
                    {"role": "assistant", "content": "Next step: Customer se Cibil Score confirm karein."},
                ],
                lead_id=667,
                lead_facts={"loan_type": "2"},
                lead_refreshed=True,
            )

            self.assertFalse(result.get("needs_lead_refresh_confirmation", False))
            self.assertIn("Next step:", result["reply"])
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_marital_status_missing_does_not_match_generic_status(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "fields", "paths": ["customer.marital_status"]})

            reply = await service.generate_chat_reply(
                "marital_status bhi toh missing hai?",
                lead_id=667,
                lead_facts={"status": "active", "customer.marital_status": None},
            )

            self.assertEqual(reply, "Marital status: Missing")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_missing_documents_answer_uses_loaded_docs_not_rag_policy(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            self.mock_lead_plan(service, {"action": "missing_documents"})

            reply = await service.generate_chat_reply(
                "isme kon kon se missing doc hai",
                lead_id=667,
                lead_facts={
                    "customer.recommended_docs[0].doc_id": "11",
                    "customer.recommended_docs[0].is_doc_uploaded": "0",
                    "customer.recommended_docs[1].doc_id": "12",
                    "customer.recommended_docs[1].is_doc_uploaded": "1",
                },
            )

            self.assertEqual(reply, "Missing documents:\n- doc 11")
            self.assertNotIn("salary slips", reply.lower())
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
