from __future__ import annotations

import json
from collections.abc import AsyncIterator

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.types import SecretStr

from app.core.config import get_settings


STREAM_SYSTEM_PROMPT = """You are a real-time copilot for a home-loan caller team in India.

TASK: Return EXACTLY 3 sections in this exact format (no extra text, no preamble):

[INFO]{"loan_amount": "4000000", "cibil_score": "760", "gross_monthly_salary": "150000", "property_location": "noida"}
[SUMMARY]Customer needs 40 lakh home loan in Noida, has 780 CIBIL, salary 1.5L per month
[SUGGESTION]Sir, aapke 780 CIBIL score ke hisaab se hum best rate de sakte hain

IMPORTANT:
- [INFO] section MUST be valid JSON - extract any fields the customer mentions: loan_amount, cibil_score, gross_monthly_salary, property_location, property_type, annual_income, existing_loan
- If no info mentioned, use empty JSON: {}
- [SUMMARY] is short context about customer need
- [SUGGESTION] is what agent should say next (in Hinglish)
- Use Roman script only (no Devanagari/Hindi)
- Never add any text before [INFO] or after [SUGGESTION]
"""


class SummaryResponse(BaseModel):
    summary: str = Field(
        description=(
            "A short paragraph in Hinglish written only in Roman script. "
            "Mention the main discussion, customer concern, current status, and next likely action."
        )
    )

    model_config = ConfigDict(extra="forbid")


def build_extraction_schema(fields: dict[str, str]) -> type[BaseModel]:
    annotations: dict[str, tuple[type[str | None], object]] = {}
    for field_name, meaning in fields.items():
        annotations[field_name] = (
            str | None,
            Field(default=None, description=meaning),
        )

    return create_model(  # type: ignore[misc]
        "CustomerFieldExtraction",
        __config__=ConfigDict(extra="forbid"),
        **annotations,
    )


def build_stream_reply_prompt(
    utterance: str,
    conversation_context: str,
    customer_last_utterance: str,
    agent_last_utterance: str,
    context_summary: str,
    known_entities: dict | None,
) -> str:
    return (
        f"{STREAM_SYSTEM_PROMPT}\n\n"
        f"customer_last_utterance: {customer_last_utterance}\n"
        f"agent_last_utterance: {agent_last_utterance}\n"
        f"context_summary: {context_summary}\n"
        f"known_entities: {json.dumps(known_entities or {})}\n\n"
        f"Recent conversation history:\n{conversation_context}\n\n"
        f"Current customer utterance:\n{utterance}"
    )


def build_summary_prompt(conversation: str) -> str:
    return f"""You are summarizing a home-loan call for an internal caller team.

Return strict JSON only in this format:
{{
  "summary": "A short paragraph in Hinglish written only in Roman script. Mention the main discussion, customer concern, current status, and next likely action."
}}

Rules:
- Use only Roman script. Never use Devanagari.
- Do not return extractedData.
- Do not return insights.
- Keep it concise and operational.

Conversation:
{conversation}
"""


def build_schema_extraction_prompt(
    utterance: str,
    conversation_context: str,
    known_fields: dict[str, str],
    schema_prompt: str,
) -> str:
    return f"""You extract customer information from a home-loan call.

Return strict JSON only.
Use only exact variable names from the provided schema.
Extract only fields that are explicitly mentioned or strongly implied from the current utterance with nearby context.
Do not invent values.
If nothing is found, return {{}}

Known extracted fields so far:
{json.dumps(known_fields, ensure_ascii=True)}

Recent conversation:
{conversation_context}

Current utterance:
{utterance}

Available schema fields:
{schema_prompt}
"""


def build_question_prompt(missing_fields: list[str], conversation_context: str) -> str:
    return f"""You are an AI assistant helping an agent in a home loan call.

Based on the conversation context, generate the next question the agent should ask the customer to gather missing information.

Missing fields: {", ".join(missing_fields)}

Conversation:
{conversation_context}

Return only the question in natural Hinglish, without quotes.
"""


def build_parse_response_prompt(utterance: str, question: str) -> str:
    return f"""Parse the customer's response to extract the requested information.

Question asked: {question}

Customer response: {utterance}

Return JSON with extracted fields, e.g., {{"loan_amount": "1800000"}} if applicable, else {{}}
"""


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _resolve_model_name(self, model_name: str | None, default: str) -> str:
        resolved = model_name or default
        if ":" in resolved:
            return resolved
        return f"google_genai:{resolved}"

    def _resolve_provider(self, model_name: str | None = None) -> str:
        resolved = model_name or self.settings.llm_model
        if ":" in resolved:
            return resolved.split(":", 1)[0].strip()
        return "google_genai"

    def _build_model(self, model_name: str | None = None):
        provider = self._resolve_provider(model_name)
        kwargs: dict[str, object] = {
            "temperature": 0.2,
            "timeout": self.settings.request_timeout_seconds,
            "max_retries": 3,
        }
        if provider == "google_genai" and self.settings.llm_api_key:
            kwargs["api_key"] = SecretStr(self.settings.llm_api_key)
        return init_chat_model(
            self._resolve_model_name(model_name, self.settings.llm_model),
            **kwargs,
        )

    @staticmethod
    def _message_text(message) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return str(content)

    async def stream_text(
        self, prompt: str, *, model_name: str | None = None
    ) -> AsyncIterator[str]:
        model = self._build_model(model_name)
        async for chunk in model.astream(prompt):
            text = self._message_text(chunk)
            if text:
                yield text

    async def stream_reply(
        self,
        utterance: str,
        conversation_context: str,
        model_name: str | None = None,
        customer_last_utterance: str = "",
        agent_last_utterance: str = "",
        context_summary: str = "",
        known_entities: dict | None = None,
    ) -> AsyncIterator[str]:
        prompt = build_stream_reply_prompt(
            utterance=utterance,
            conversation_context=conversation_context,
            customer_last_utterance=customer_last_utterance,
            agent_last_utterance=agent_last_utterance,
            context_summary=context_summary,
            known_entities=known_entities,
        )
        async for chunk in self.stream_text(prompt, model_name=model_name):
            yield chunk

    async def generate_text(
        self, prompt: str, *, model_name: str | None = None
    ) -> str:
        model = self._build_model(model_name)
        response = await model.ainvoke(prompt)
        return self._message_text(response).strip()

    async def generate_json(
        self, prompt: str, *, model_name: str | None = None
    ) -> dict:
        raw_text = await self.generate_text(prompt, model_name=model_name)
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1:
            return {}

        try:
            parsed = json.loads(raw_text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def generate_summary(
        self, conversation: str, *, model_name: str | None = None
    ) -> dict:
        prompt = build_summary_prompt(conversation)
        model = self._build_model(model_name or self.settings.llm_summary_model)
        structured_model = model.with_structured_output(SummaryResponse)
        result = await structured_model.ainvoke(prompt)
        if isinstance(result, BaseModel):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        return {"summary": str(result)}

    async def extract_schema_values(
        self,
        utterance: str,
        conversation_context: str,
        known_fields: dict[str, str],
        schema_fields: dict[str, str],
        schema_prompt: str,
        *,
        model_name: str | None = None,
    ) -> dict[str, str]:
        prompt = build_schema_extraction_prompt(
            utterance=utterance,
            conversation_context=conversation_context,
            known_fields=known_fields,
            schema_prompt=schema_prompt,
        )
        schema = build_extraction_schema(schema_fields)
        model = self._build_model(model_name or self.settings.llm_extract_model)
        structured_model = model.with_structured_output(schema)
        result = await structured_model.ainvoke(prompt)

        if isinstance(result, BaseModel):
            raw = result.model_dump()
        elif isinstance(result, dict):
            raw = result
        else:
            raw = {}

        return {
            str(key): str(value)
            for key, value in raw.items()
            if value is not None and str(value).strip()
        }

    async def generate_question(
        self, missing_fields: list[str], conversation_context: str
    ) -> str:
        return await self.generate_text(
            build_question_prompt(missing_fields, conversation_context),
            model_name=self.settings.llm_summary_model,
        )

    async def parse_response(self, utterance: str, question: str) -> dict[str, str]:
        return await self.generate_json(
            build_parse_response_prompt(utterance, question),
            model_name=self.settings.llm_summary_model,
        )
