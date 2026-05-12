from dataclasses import dataclass

from app.models.session import SessionState
from app.services.text_utils import normalize_text


@dataclass(frozen=True)
class TurnActionDecision:
    run_extraction: bool
    run_reply: bool
    reason: str


def normalize_confidence(confidence: float | None) -> float:
    if confidence is None:
        return 0.75
    return max(0.0, min(float(confidence), 1.0))


def get_average_confidence(values: list[float]) -> float:
    if not values:
        return 0.75
    return sum(values) / len(values)


def looks_like_noise_or_filler(normalized: str) -> bool:
    return False


def looks_like_transcription_instruction_leak(text: str) -> bool:
    return False


def should_capture_final_segment(transcript: str, confidence: float | None) -> bool:
    return bool(str(transcript or "").strip())


def should_run_llm_extraction(
    utterance: str,
    average_confidence: float,
    speaker: str | None,
) -> bool:
    if speaker == "1":
        return False

    return bool(str(utterance or "").strip())


def should_invoke_llm(
    utterance: str, average_confidence: float, last_llm_invoked_at: float, cooldown: float
) -> bool:
    return bool(str(utterance or "").strip())


def decide_turn_action(
    utterance: str,
    average_confidence: float,
    speaker: str | None,
    last_llm_invoked_at: float,
    cooldown: float,
) -> TurnActionDecision:
    if not str(utterance or "").strip():
        return TurnActionDecision(False, False, "empty_or_too_short")

    if speaker == "1":
        return TurnActionDecision(False, False, "agent_context_only")

    run_extraction = should_run_llm_extraction(utterance, average_confidence, speaker)
    run_reply = should_invoke_llm(
        utterance,
        average_confidence,
        last_llm_invoked_at,
        cooldown,
    )

    if run_extraction and run_reply:
        reason = "customer_extract_and_reply"
    elif run_extraction:
        reason = "customer_extract_only"
    elif run_reply:
        reason = "customer_reply_only"
    else:
        reason = "customer_no_action"

    return TurnActionDecision(run_extraction, run_reply, reason)


def build_turn_dedupe_key(utterance: str, speaker: str | None) -> str:
    normalized = normalize_text(utterance)
    speaker_key = speaker or ""
    return f"{speaker_key}|{normalized}"


def build_known_fields_text(fields: dict[str, str], limit: int = 8) -> str:
    items = list(fields.items())
    if not items:
        return ""
    return ", ".join(f"{key}: {value}" for key, value in items[:limit])


def build_recent_conversation_context(
    state: SessionState, limit: int = 8
) -> str:
    recent_messages = state.messages[-limit:]
    lines: list[str] = []

    known_fields_text = build_known_fields_text(state.extracted_fields, limit=12)
    if known_fields_text:
        lines.append(f"Known customer fields: {known_fields_text}")

    for msg in recent_messages:
        role = "Customer" if msg.type == "user" else "Caller Assist"
        if msg.speaker:
            if msg.speaker == "0":
                role = "Customer"
            elif msg.speaker == "1":
                role = "Agent"
        lines.append(f"{role}: {msg.text}")
    return "\n".join(lines) if lines else "No prior conversation context available."


def detect_call_stage(utterance: str, state: SessionState) -> str:
    normalized = normalize_text(utterance)
    tokens = set(normalized.split())

    discovery_keywords = {
        "ki",
        "kya",
        "kaise",
        "konsa",
        "kaun",
        "kitna",
        "inform",
        "about",
        "query",
        "pooch",
        "pucha",
    }
    negotiation_keywords = {
        "rate",
        "roi",
        "interest",
        "fee",
        "charges",
        "waive",
        "discount",
        "reduce",
        "lower",
        "emi",
        "installment",
    }
    closing_keywords = {
        "okay",
        "thik",
        "achha",
        "good",
        "fine",
        "process",
        "apply",
        "submit",
        "documents",
        "disburse",
        "sanction",
        "approval",
    }

    has_discovery = bool(tokens & discovery_keywords)
    has_negotiation = bool(tokens & negotiation_keywords)
    has_closing = bool(tokens & closing_keywords)

    if has_closing and state.extracted_fields.get("loan_amount"):
        return "closing"
    if has_negotiation:
        return "negotiation"
    if has_discovery or not state.extracted_fields:
        return "discovery"
    return state.call_stage
