from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.service import LLMService
from app.services.schema_normalizer import build_high_confidence_local_updates
from app.services.schema_normalizer import normalize_extracted_fields
from app.services.schema_registry import get_schema_registry
from app.services.session_response import normalize_ai_response


DEFAULT_UTTERANCE = (
    "sir mujhe 30 lakh ka loan chahiye, property location greater noida hai, "
    "monthly gross salary 1 lakh hai aur CIBIL 760 hai"
)


@dataclass
class FakeSession:
    state: object = field(default_factory=lambda: type("State", (), {})())

    def __post_init__(self) -> None:
        self.state.extracted_fields = {}
        self.state.last_suggestion = ""

    def build_fallback_summary(self, utterance: str) -> str:
        return utterance[:120]

    def convert_summary_to_hinglish(self, summary: str) -> str:
        return summary

    def build_known_fields_text(self, limit: int = 12) -> str:
        items = list(self.state.extracted_fields.items())[:limit]
        return ", ".join(f"{key}: {value}" for key, value in items)


async def run_live_pipeline(utterance: str) -> None:
    registry = get_schema_registry()
    llm = LLMService()

    print("=== Schema Registry ===")
    print(f"Loaded fields: {len(registry.fields)}")

    print("\n=== High-Confidence Local Updates ===")
    local_updates = build_high_confidence_local_updates(utterance)
    print(json.dumps(local_updates, indent=2, ensure_ascii=False))

    print("\n=== Normalized Fields ===")
    normalized = normalize_extracted_fields(local_updates)
    print(json.dumps(normalized, indent=2, ensure_ascii=False))

    session = FakeSession()
    session.state.extracted_fields.update(normalized)

    print("\n=== Response Formatter ===")
    raw_response = (
        "[SUMMARY]Customer is looking for a 30 lakh home loan in Greater Noida.\n"
        "[INFO]{\"loan_amount\": \"3000000\", \"property_city\": \"greater noida\", "
        "\"gross_monthly_salary\": \"100000\", \"cibil_score\": \"760\"}\n"
        "[SUGGESTION]Sir, kya aap mujhe apna current employment status bata sakte hain?"
    )
    formatted = normalize_ai_response(session, raw_response, utterance)
    print(formatted)

    print("\n=== Live Schema Extraction ===")
    live_extracted = await llm.extract_schema_values(
        utterance=utterance,
        conversation_context=utterance,
        known_fields={},
        schema_fields=registry.fields,
        schema_prompt=registry.format_for_prompt(),
    )
    print(json.dumps(live_extracted, indent=2, ensure_ascii=False))

    print("\n=== Live Stream Reply ===")
    chunks: list[str] = []
    async for chunk in llm.stream_reply(
        utterance=utterance,
        conversation_context=utterance,
        known_entities=live_extracted,
        customer_last_utterance=utterance,
        agent_last_utterance="",
        context_summary=utterance,
    ):
        chunks.append(chunk)
        print(chunk, end="", flush=True)
    print("\n")


def run_local_pipeline(utterance: str) -> None:
    registry = get_schema_registry()
    print("=== Schema Registry ===")
    print(f"Loaded fields: {len(registry.fields)}")

    print("\n=== High-Confidence Local Updates ===")
    local_updates = build_high_confidence_local_updates(utterance)
    print(json.dumps(local_updates, indent=2, ensure_ascii=False))

    print("\n=== Normalized Fields ===")
    normalized = normalize_extracted_fields(local_updates)
    print(json.dumps(normalized, indent=2, ensure_ascii=False))

    session = FakeSession()
    session.state.extracted_fields.update(normalized)

    print("\n=== Response Formatter ===")
    raw_response = (
        "[SUMMARY]Customer is looking for a 30 lakh home loan in Greater Noida.\n"
        "[INFO]{\"loan_amount\": \"3000000\", \"property_city\": \"greater noida\", "
        "\"gross_monthly_salary\": \"100000\", \"cibil_score\": \"760\"}\n"
        "[SUGGESTION]Sir, kya aap mujhe apna current employment status bata sakte hain?"
    )
    formatted = normalize_ai_response(session, raw_response, utterance)
    print(formatted)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test the full customer-info pipeline."
    )
    parser.add_argument(
        "--utterance",
        default=DEFAULT_UTTERANCE,
        help="Customer utterance to run through the pipeline.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the live LLM-backed extraction and reply steps.",
    )
    args = parser.parse_args()

    run_local_pipeline(args.utterance)

    if not args.live:
        print(
            "\nUse --live to exercise the real LLM-backed extraction and reply steps."
        )
        return 0

    try:
        asyncio.run(run_live_pipeline(args.utterance))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Pipeline smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
