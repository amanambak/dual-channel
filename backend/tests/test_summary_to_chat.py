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

    async def test_chat_route_accepts_dre_documents_and_normalizes_lead_detail_array(self):
        os.environ.setdefault("GOOGLE_API_KEY", "test-key")
        os.environ.setdefault("GEMINI_API_KEY", "test-key")

        payload = {
            "message": "which documents are missing?",
            "lead_id": 674,
            "lead_detail": [
                {
                    "id": 674,
                    "customer": {"customer_id": 21088, "first_name": "Aman"},
                }
            ],
            "lead_dre_documents": {
                "documents": [
                    {"child_name": "PAN Card", "doc_path": "pan.pdf"},
                    {"child_name": "Aadhaar Card", "status": "pending"},
                ]
            },
        }

        with patch(
            "app.api.websocket.llm_service.generate_chat_reply",
            new=AsyncMock(return_value="Uploaded documents: PAN Card\nMissing documents: Aadhaar Card"),
        ) as mock_generate:
            from app.api.websocket import ChatRequest, chat_reply

            response = await chat_reply(ChatRequest(**payload))

        self.assertEqual(
            response["reply"],
            "Uploaded documents: PAN Card\nMissing documents: Aadhaar Card",
        )
        self.assertTrue(response["lead_context_used"])
        _, kwargs = mock_generate.await_args
        self.assertEqual(kwargs["lead_detail"]["id"], 674)
        self.assertEqual(kwargs["lead_detail"]["customer"]["customer_id"], 21088)
        self.assertEqual(kwargs["lead_dre_documents"], payload["lead_dre_documents"])

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

    def test_lead_detail_context_includes_dre_document_summary(self):
        from app.services.lead_detail_context import build_lead_detail_chat_context

        context = build_lead_detail_chat_context(
            lead_id=668,
            lead_detail={"id": 668, "customer": {"first_name": "Rahul"}},
            lead_dre_documents={
                "documents": [
                    {"child_name": "PAN Card", "doc_path": "pan.pdf"},
                    {"child_name": "Bank Statement", "is_doc_uploaded": 0},
                ]
            },
        )

        self.assertIn("DRE document status", context)
        self.assertIn("Uploaded documents: PAN Card", context)
        self.assertIn("Missing documents: Bank Statement", context)

    async def test_chat_sends_loaded_lead_field_to_llm(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Partner name Ambak Partner hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "what is partner name?",
                lead_id=667,
                lead_detail={"partner_name": "Ambak Partner"},
            )

            self.assertEqual(reply, "Partner name Ambak Partner hai.")
            fake_rag.hybrid_search.assert_awaited_once_with("what is partner name?")
            service.generate_text.assert_awaited_once()
            self.assertIn("partner_name: Ambak Partner", captured_prompt["prompt"])

    async def test_chat_sends_flat_facts_to_llm(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Customer first name Aman hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "what is customer first name?",
                lead_id=667,
                lead_facts={"customer.first_name": "Aman"},
            )

            self.assertEqual(reply, "Customer first name Aman hai.")
            fake_rag.hybrid_search.assert_awaited_once_with("what is customer first name?")
            service.generate_text.assert_awaited_once()
            self.assertIn("customer.first_name: Aman", captured_prompt["prompt"])

    async def test_chat_sends_grouped_customer_name_to_llm(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Customer name Gautam Gambhir hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "what is customer name?",
                lead_id=667,
                lead_facts={"customer.first_name": "Gautam", "customer.last_name": "Gambhir"},
            )

            self.assertEqual(reply, "Customer name Gautam Gambhir hai.")
            fake_rag.hybrid_search.assert_awaited_once_with("what is customer name?")
            service.generate_text.assert_awaited_once()
            self.assertIn("customer.first_name: Gautam", captured_prompt["prompt"])
            self.assertIn("customer.last_name: Gambhir", captured_prompt["prompt"])

    async def test_chat_sends_followup_data_to_llm(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Followup 28 April 2026 ko call hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "what is followup data?",
                lead_id=667,
                lead_facts={"followup_date": "28 April 2026", "followup_type": "call"},
            )

            self.assertEqual(reply, "Followup 28 April 2026 ko call hai.")
            fake_rag.hybrid_search.assert_awaited_once_with("what is followup data?")
            service.generate_text.assert_awaited_once()
            self.assertIn("followup_date: 28 April 2026", captured_prompt["prompt"])
            self.assertIn("followup_type: call", captured_prompt["prompt"])

    async def test_chat_sends_dre_document_status_to_llm_without_rag(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "Uploaded PAN Card hai. Missing Aadhaar Card aur Salary Slip hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "Which documents are missing?",
                lead_id=674,
                lead_detail=[
                    {
                        "id": 674,
                        "customer": {
                            "recommended_docs": [
                                {"child_name": "Salary Slip", "is_doc_uploaded": 0},
                            ]
                        },
                    }
                ],
                lead_dre_documents={
                    "documents": [
                        {"child_name": "PAN Card", "doc_path": "pan.pdf"},
                        {"child_name": "Aadhaar Card", "status": "pending"},
                    ]
                },
            )

            self.assertEqual(reply, "Uploaded PAN Card hai. Missing Aadhaar Card aur Salary Slip hai.")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_awaited_once()
            prompt = captured_prompt["prompt"]
            self.assertIn("DRE document status", prompt)
            self.assertIn("Uploaded documents: PAN Card", prompt)
            self.assertIn("Missing documents: Aadhaar Card, Salary Slip", prompt)
            self.assertIn("No relevant policy documents needed for this lead document question.", prompt)

    async def test_chat_sends_dre_document_error_to_llm_without_rag(self):
        with patch("app.llm.service.RAGService", autospec=True) as mock_rag_cls:
            fake_rag = mock_rag_cls.return_value
            fake_rag.hybrid_search = AsyncMock(return_value=[])

            from app.llm.service import LLMService

            service = LLMService()
            captured_prompt = {}

            async def fake_generate_text(prompt: str, *, model_name: str | None = None) -> str:
                captured_prompt["prompt"] = prompt
                return "DRE document status abhi available nahi hai."

            service.generate_text = AsyncMock(side_effect=fake_generate_text)

            reply = await service.generate_chat_reply(
                "Tell me about DRE documents",
                lead_id=674,
                lead_detail={"id": 674},
                lead_dre_document_error="Lead DRE document API failed with HTTP 500.",
            )

            self.assertEqual(reply, "DRE document status abhi available nahi hai.")
            fake_rag.hybrid_search.assert_not_awaited()
            service.generate_text.assert_awaited_once()
            self.assertIn(
                "DRE document status unavailable: Lead DRE document API failed with HTTP 500.",
                captured_prompt["prompt"],
            )


if __name__ == "__main__":
    unittest.main()
