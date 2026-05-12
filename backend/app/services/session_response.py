import json
import re

from app.services.agent_question_context import current_spoken_expected_field
from app.services.contextual_extraction import normalize_contextual_extracted_fields
from app.services.field_resolver import build_resolved_field_state
from app.services.field_resolver import merge_field_values
from app.services.field_resolver import resolve_extracted_fields
from app.services.schema_normalizer import derive_extracted_fields


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
                normalized = normalize_contextual_extracted_fields(
                    info_json,
                    expected_field=_current_expected_field(session),
                    utterance=utterance,
                    agent_utterance=session.state.agent_last_utterance,
                )
                session.state.extracted_fields.update(normalized)
                session.state.resolved_field_state = build_resolved_field_state(
                    existing=session.state.resolved_field_state,
                    lead_detail=session.state.lead_detail,
                    lead_facts=session.state.lead_facts,
                    extracted_fields=session.state.extracted_fields,
                )
                session.state.resolved_field_state = merge_field_values(
                    session.state.resolved_field_state,
                    resolve_extracted_fields(normalized),
                )
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
        return ""
    if not suggestion:
        suggestion = "Sir/ma'am, main aapki current concern ko clear karke next step confirm kar deta hoon."

    customer_info = session.build_known_fields_text(limit=12)

    response = f"[SUMMARY] {summary}\n"
    if customer_info:
        response += f"[INFO] {customer_info}\n"
    response += f"[SUGGESTION] {suggestion}"

    # Persist last suggestion so the NEXT turn can instruct the LLM not to repeat it
    session.state.last_suggestion = suggestion

    return response


def _current_expected_field(session) -> str | None:
    return current_spoken_expected_field(session.state)
