import json
import re

from app.services.schema_normalizer import derive_extracted_fields
from app.services.schema_normalizer import normalize_extracted_fields


def normalize_ai_response(session, raw_text: str, utterance: str) -> str:
    """Parse the raw LLM output and update session state.

    Returns the cleaned response string, or an empty string if the model
    returned [SKIP] (i.e., nothing useful to show the agent).

    Security: schema normalization filters unknown fields and coerces raw
    values into the shapes defined by the registry and JSON schema.
    """
    text = re.sub(r"\s+", " ", raw_text).strip()

    # --- handle [SKIP] ---
    if re.match(r"\[SKIP\]", text, re.IGNORECASE):
        return ""

    # --- [INFO] block: extract and validate keys ---
    info_match = re.search(r"\[INFO\]({.*?})", text, re.IGNORECASE)
    if info_match:
        try:
            info_json = json.loads(info_match.group(1))
            if isinstance(info_json, dict):
                normalized = normalize_extracted_fields(info_json)
                session.state.extracted_fields.update(normalized)
        except (json.JSONDecodeError, TypeError):
            pass

    # --- parse [SUMMARY] and [SUGGESTION] ---
    summary_match = re.search(
        r"\[SUMMARY\](.*?)(?=\[(?:SUGGESTION|INFO|SKIP)\]|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    suggestion_match = re.search(
        r"\[SUGGESTION\](.*?)(?=\[INFO\]|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    summary = summary_match.group(1).strip() if summary_match else ""
    suggestion = suggestion_match.group(1).strip() if suggestion_match else ""

    # Strip any stray section tags that leaked into the text
    _tag_re = re.compile(
        r"\[/?(?:SUMMARY|SUGGESTION|INFO|SKIP)\]", re.IGNORECASE
    )
    summary = _tag_re.sub("", summary).strip()
    suggestion = _tag_re.sub("", suggestion).strip()

    derive_extracted_fields(session.state.extracted_fields)

    if not summary:
        summary = session.build_fallback_summary(utterance)
    if not suggestion:
        suggestion = "Sir/ma'am, main aapki current concern ko clear karke next step confirm kar deta hoon."

    # Remove Devanagari from agent-facing fields (agent reads Roman script)
    suggestion = re.sub(r"[\u0900-\u097F]+", "", suggestion).strip()
    summary = re.sub(r"[\u0900-\u097F]+", "", summary).strip()

    summary = session.convert_summary_to_hinglish(summary)

    customer_info = session.build_known_fields_text(limit=12)

    response = f"[SUMMARY] {summary}\n"
    if customer_info:
        response += f"[INFO] {customer_info}\n"
    response += f"[SUGGESTION] {suggestion}"

    # Persist last suggestion so the NEXT turn can instruct the LLM not to repeat it
    session.state.last_suggestion = suggestion

    return response
