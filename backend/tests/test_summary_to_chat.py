import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))


class SummaryToChatRouteTest(unittest.IsolatedAsyncioTestCase):
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
            service.generate_text = AsyncMock(return_value="Should not be called")

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
            service.generate_text = AsyncMock(return_value="Should not be called")

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
            service.generate_text = AsyncMock(return_value="Should not be called")

            reply = await service.generate_chat_reply(
                "what is customer name?",
                lead_id=667,
                lead_facts={"customer.first_name": "Gautam", "customer.last_name": "Gambhir"},
            )

            self.assertEqual(reply, "Customer name: Gautam Gambhir")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()

    async def test_chat_answers_followup_data_in_structured_format(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            service.generate_text = AsyncMock(return_value="Should not be called")

            reply = await service.generate_chat_reply(
                "what is followup data?",
                lead_id=667,
                lead_facts={"followup_date": "28 April 2026", "followup_type": "call"},
            )

            self.assertEqual(reply, "Followup date: 28 April 2026\nFollowup type: call")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
