import json
import re


def normalize_ai_response(session, raw_text: str, utterance: str) -> str:
    text = re.sub(r"\s+", " ", raw_text).strip()
    info_match = re.search(r"\[INFO\]({.*?})", text, re.IGNORECASE)
    if info_match:
        try:
            info_json = json.loads(info_match.group(1))
            for key, value in info_json.items():
                if value:
                    session.state.extracted_fields[key] = str(value)
        except Exception:
            pass

    summary_match = re.search(r"\[SUMMARY\](.*?)(?=\[SUGGESTION\]|$)", text, re.IGNORECASE)
    suggestion_match = re.search(r"\[SUGGESTION\](.*)$", text, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""
    suggestion = suggestion_match.group(1).strip() if suggestion_match else ""

    summary = re.sub(
        r"\[/?SUMMARY\]|\[/?SUGGESTION\]|\[/?INFO\]",
        "",
        summary,
        flags=re.IGNORECASE,
    ).strip()
    suggestion = re.sub(
        r"\[/?SUMMARY\]|\[/?SUGGESTION\]|\[/?INFO\]",
        "",
        suggestion,
        flags=re.IGNORECASE,
    ).strip()

    if not summary:
        summary = session.build_fallback_summary(utterance)
    if not suggestion:
        suggestion = (
            "Sir/ma'am, main aapki current concern ko clear karke next step confirm kar deta hoon."
        )

    suggestion = re.sub(r"[\u0900-\u097F]+", "", suggestion).strip()
    summary = re.sub(r"[\u0900-\u097F]+", "", summary).strip()
    summary = session.convert_summary_to_hinglish(summary)
    customer_info = session.build_known_fields_text(limit=6)

    response = f"[SUMMARY] {summary}\n"
    if customer_info:
        response += f"[INFO] {customer_info}\n"
    response += f"[SUGGESTION] {suggestion}"
    return response

