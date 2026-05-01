import logging
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi import WebSocket, WebSocketDisconnect

from app.llm.service import LLMService
from app.services.session_manager import SessionManager
from app.services.schema_registry import get_schema_registry
from app.services.schema_normalizer import normalize_extracted_fields

router = APIRouter()
session_manager = SessionManager()
llm_service = LLMService()
schema_registry = get_schema_registry()
logger = logging.getLogger(__name__)


class SummaryRequest(BaseModel):
    conversation: str


class SummaryChatRequest(BaseModel):
    customer_info: dict[str, str] = Field(default_factory=dict)
    conversation: str = ""


class ChatRequest(BaseModel):
    message: Any = ""
    history: list[dict[str, Any]] = Field(default_factory=list)
    lead_id: Any = None
    leadId: Any = None
    lead_detail: Any = None
    leadDetail: Any = None
    lead_facts: Any = None
    leadFacts: Any = None
    lead_missing_fields: Any = None
    leadMissingFields: Any = None
    lead_refreshed: Any = False
    leadRefreshed: Any = False


def _normalize_chat_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


@router.websocket("/ws/session")
async def session_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session = await session_manager.create_session(websocket)

    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        await session_manager.close_session(session.session_id)


@router.get("/api/sessions/{session_id}/summary")
async def session_summary(session_id: str) -> dict:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return await session.generate_summary()


@router.post("/api/summary")
async def ad_hoc_summary(request: SummaryRequest) -> dict:
    customer_info = await llm_service.extract_schema_values(
        utterance=request.conversation,
        conversation_context=request.conversation,
        known_fields={},
        schema_fields=schema_registry.fields,
        schema_prompt=schema_registry.format_for_prompt(),
    )
    filtered = {
        key: value for key, value in customer_info.items()
        if key in schema_registry.fields
    }
    return {"customer_info": filtered}


@router.post("/api/summary/chat")
async def summary_chat(request: SummaryChatRequest) -> dict:
    normalized_customer_info = normalize_extracted_fields(request.customer_info)
    reply = await llm_service.generate_db_insert_question(
        customer_info=normalized_customer_info,
        conversation_context=request.conversation,
        schema_prompt=schema_registry.format_for_prompt(),
    )
    return {"reply": reply, "customer_info": normalized_customer_info}


@router.post("/api/chat")
async def chat_reply(request: ChatRequest) -> dict:
    lead_id = request.lead_id or request.leadId
    lead_detail = request.lead_detail or request.leadDetail
    lead_facts = request.lead_facts or request.leadFacts
    lead_missing_fields = request.lead_missing_fields or request.leadMissingFields
    if not isinstance(lead_detail, dict):
        lead_detail = None
    if not isinstance(lead_facts, dict):
        lead_facts = None
    if not isinstance(lead_missing_fields, list):
        lead_missing_fields = None

    lead_detail_keys = list(lead_detail.keys())[:30] if isinstance(lead_detail, dict) else []
    lead_fact_keys = list(lead_facts.keys())[:30] if isinstance(lead_facts, dict) else []
    lead_missing_sample = lead_missing_fields[:10] if isinstance(lead_missing_fields, list) else []
    logger.info(
        "[LeadDebug][backend] chat request: lead_id=%s has_detail=%s detail_keys=%s facts_count=%d fact_keys=%s missing_fields=%d missing_sample=%s history_turns=%d",
        lead_id,
        bool(lead_detail),
        lead_detail_keys,
        len(lead_facts or {}),
        lead_fact_keys,
        len(lead_missing_fields or []),
        lead_missing_sample,
        len(request.history),
    )

    lead_refreshed = bool(request.lead_refreshed or request.leadRefreshed)

    result = await llm_service.generate_chat_reply_payload(
        message=str(request.message or ""),
        history=_normalize_chat_history(request.history),
        lead_id=lead_id,
        lead_detail=lead_detail,
        lead_facts=lead_facts,
        lead_missing_fields=lead_missing_fields,
        lead_refreshed=lead_refreshed,
    )
    return {
        **result,
        "lead_id": lead_id,
        "lead_context_used": bool(lead_detail or lead_facts),
    }
