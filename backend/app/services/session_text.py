import re
import time
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
    filler_only = {
        "hmm",
        "hmmm",
        "uh",
        "umm",
        "um",
        "ji",
        "haan",
        "han",
        "hello",
        "helo",
        "hi",
        "ok",
        "okay",
        "acha",
        "achha",
        "accha",
        "bolo",
        "boliye",
    }
    tokens = normalized.split()
    if not tokens:
        return True
    if normalized in filler_only:
        return True
    if len(tokens) >= 4 and len(set(tokens)) == 1:
        return True
    return False


def should_capture_final_segment(transcript: str, confidence: float | None) -> bool:
    normalized = normalize_text(transcript)
    if not normalized or len(normalized) <= 2:
        return False
    if looks_like_noise_or_filler(normalized):
        return False
    if confidence is not None and normalize_confidence(confidence) < 0.45:
        return False
    return True


def should_extract_schema_fields(utterance: str, average_confidence: float) -> bool:
    normalized = normalize_text(utterance)
    if not normalized or average_confidence < 0.6:
        return False
    return len(normalized.split()) >= 4 or any(char.isdigit() for char in utterance)


def should_run_llm_extraction(
    utterance: str,
    average_confidence: float,
    speaker: str | None,
) -> bool:
    if speaker == "1":
        return False

    normalized = normalize_text(utterance)
    if not normalized or len(normalized) < 2:
        return False
    if looks_like_noise_or_filler(normalized):
        return False
    if average_confidence < 0.45:
        return False
    return True


def should_invoke_llm(
    utterance: str, average_confidence: float, last_llm_invoked_at: float, cooldown: float
) -> bool:
    if not utterance or len(utterance.strip()) < 2:
        return False

    normalized = normalize_text(utterance)
    if not normalized or len(normalized) < 2:
        return False

    now = time.monotonic()
    if now - last_llm_invoked_at < cooldown:
        return False

    tokens = normalized.split()
    if len(tokens) < 2:
        return False

    if len(tokens) == 1 and normalized in {
        "hello",
        "hi",
        "namaste",
        "sir",
        "ok",
        "hmm",
    }:
        return False

    return True


def decide_turn_action(
    utterance: str,
    average_confidence: float,
    speaker: str | None,
    last_llm_invoked_at: float,
    cooldown: float,
) -> TurnActionDecision:
    normalized = normalize_text(utterance)
    if not normalized or len(normalized) < 2:
        return TurnActionDecision(False, False, "empty_or_too_short")
    if looks_like_noise_or_filler(normalized):
        return TurnActionDecision(False, False, "noise_or_filler")

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


def build_fallback_summary(utterance: str) -> str:
    cleaned = re.sub(r"\s+", " ", utterance).strip()
    if len(cleaned) > 120:
        cleaned = f"{cleaned[:117].rstrip()}..."
    return cleaned or "Current customer discussion"


def convert_summary_to_hinglish(summary: str) -> str:
    replacements = [
        ("customer is concerned about", "customer ko concern hai about"),
        ("customer confirms", "customer confirm kar raha hai"),
        ("customer is asking about", "customer pooch raha hai about"),
        ("customer is discussing", "customer discuss kar raha hai"),
        ("customer wants", "customer chah raha hai"),
        ("customer requested", "customer ne request ki hai"),
        ("customer mentioned", "customer ne mention kiya hai"),
        ("loan sanction", "loan sanction"),
        ("upfront fee", "upfront fee"),
        ("property paper check", "property paper check"),
        ("property papers", "property papers"),
        ("rate of interest", "rate of interest"),
        ("fee waiver", "fee waiver"),
        ("current status", "current status"),
        ("next action", "next action"),
        ("and is concerned about", "aur concern hai about"),
        ("and wants", "aur chah raha hai"),
    ]

    updated = summary
    for source, target in replacements:
        updated = re.sub(source, target, updated, flags=re.IGNORECASE)

    if updated == summary:
        updated = re.sub(r"^\s*customer\s+", "", updated, flags=re.IGNORECASE).strip()
        updated = re.sub(r"^\s*customer\b", "", updated, flags=re.IGNORECASE).strip(
            " :-"
        )

    return updated


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
