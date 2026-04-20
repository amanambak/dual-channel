import json
import asyncio
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

SYSTEM_PROMPT = """You are a real-time copilot for a home-loan caller team in India.

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

Conversation context: {conversation_context}
Current utterance: {utterance}
known_entities: {known_entities}
"""

SUMMARY_PROMPT = """You are summarizing a home-loan call for an internal caller team.

Return strict JSON only in this format:
{{
  "summary": "A short paragraph in Hinglish written only in Roman script. Mention the main discussion, customer concern, current status, and next likely action."
}}

Rules:
- Use only Roman script. Never use Devanagari.
- Do not return extractedData.
- Do not return insights.
- Keep it concise and operational.
- If known customer information is provided, include those exact variable names and values inside the summary text.

Conversation:
{conversation}
"""


class GeminiClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.retry_delays = (0.6, 1.2, 2.5)

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {429, 500, 502, 503, 504}
        return isinstance(
            exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
        )

    async def stream_reply(
        self,
        utterance: str,
        conversation_context: str,
        model_override: str | None = None,
        customer_last_utterance: str = "",
        agent_last_utterance: str = "",
        context_summary: str = "",
        known_entities: dict | None = None,
    ) -> AsyncIterator[str]:
        model = model_override or self.settings.gemini_model
        url = f"{self.settings.gemini_base_url}/{model}:streamGenerateContent"
        params = {
            "alt": "sse",
            "key": self.settings.gemini_api_key,
        }
        known_entities = known_entities or {}
        payload = {
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 500,
                "topP": 0.8,
                "topK": 20,
                "stopSequences": ["```", "\n\n\n"],
            },
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"{SYSTEM_PROMPT}\n\n"
                                f"customer_last_utterance: {customer_last_utterance}\n"
                                f"agent_last_utterance: {agent_last_utterance}\n"
                                f"context_summary: {context_summary}\n"
                                f"known_entities: {json.dumps(known_entities)}\n\n"
                                f"Recent conversation history:\n{conversation_context}\n\n"
                                f"Current customer utterance:\n{utterance}"
                            )
                        }
                    ]
                }
            ],
        }

        attempts = len(self.retry_delays) + 1
        current_model = model
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.request_timeout_seconds
                ) as client:
                    async with client.stream(
                        "POST", url, params=params, json=payload
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data = json.loads(line[6:])
                            text = (
                                data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                            )
                            if text:
                                yield text
                return
            except Exception as exc:
                # If 503 and we haven't tried fallback yet, retry with fallback model
                if (
                    attempt == 0
                    and "503" in str(exc)
                    and current_model != self.settings.fallback_model
                ):
                    model = self.settings.fallback_model
                    url = (
                        f"{self.settings.gemini_base_url}/{model}:streamGenerateContent"
                    )
                    continue
                if attempt >= len(self.retry_delays) or not self._should_retry(exc):
                    raise
                await asyncio.sleep(self.retry_delays[attempt])

    async def generate_summary(self, conversation: str) -> dict:
        url = f"{self.settings.gemini_base_url}/{self.settings.summary_model}:generateContent"
        params = {"key": self.settings.gemini_api_key}
        payload = {
            "contents": [
                {"parts": [{"text": SUMMARY_PROMPT.format(conversation=conversation)}]}
            ]
        }

        data = await self._post_json_with_retry(url, params, payload)

        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {
                "summary": "Summary response could not be parsed.",
            }

        return json.loads(text[start : end + 1])

    async def extract_schema_values(
        self,
        utterance: str,
        conversation_context: str,
        known_fields: dict[str, str],
        schema_prompt: str,
    ) -> dict[str, str]:
        prompt = f"""You extract customer information from a home-loan call.

Return strict JSON only.
Use only exact variable names from the provided schema.
Extract only fields that are explicitly mentioned or strongly implied from the current utterance with nearby context.
Do not invent values.
If nothing is found, return {{}}.

Known extracted fields so far:
{json.dumps(known_fields, ensure_ascii=True)}

Recent conversation:
{conversation_context}

Current utterance:
{utterance}

Available schema fields:
{schema_prompt}
"""

        url = f"{self.settings.gemini_base_url}/{self.settings.summary_model}:generateContent"
        params = {"key": self.settings.gemini_api_key}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        data = await self._post_json_with_retry(url, params, payload)

        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {}

        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            return {}

        return {
            str(key): str(value)
            for key, value in parsed.items()
            if value is not None and str(value).strip()
        }

    async def _post_json_with_retry(
        self, url: str, params: dict, payload: dict
    ) -> dict:
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.request_timeout_seconds
                ) as client:
                    response = await client.post(url, params=params, json=payload)
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                if attempt >= len(self.retry_delays) or not self._should_retry(exc):
                    raise
                await asyncio.sleep(self.retry_delays[attempt])

        raise RuntimeError("unreachable")

    async def generate_question(
        self, missing_fields: list[str], conversation_context: str
    ) -> str:
        prompt = f"""You are an AI assistant helping an agent in a home loan call.

Based on the conversation context, generate the next question the agent should ask the customer to gather missing information.

Missing fields: {", ".join(missing_fields)}

Conversation:
{conversation_context}

Return only the question in natural Hinglish, without quotes.
"""

        url = f"{self.settings.gemini_base_url}/{self.settings.summary_model}:generateContent"
        params = {"key": self.settings.gemini_api_key}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        data = await self._post_json_with_retry(url, params, payload)
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        return text.strip()

    async def parse_response(self, utterance: str, question: str) -> dict[str, str]:
        prompt = f"""Parse the customer's response to extract the requested information.

Question asked: {question}

Customer response: {utterance}

Return JSON with extracted fields, e.g., {{"loan_amount": "1800000"}} if applicable, else {{}}.
"""

        url = f"{self.settings.gemini_base_url}/{self.settings.summary_model}:generateContent"
        params = {"key": self.settings.gemini_api_key}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        data = await self._post_json_with_retry(url, params, payload)
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {}

        return json.loads(text[start : end + 1])
