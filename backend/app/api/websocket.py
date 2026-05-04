import logging
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from fastapi import WebSocket, WebSocketDisconnect

from app.llm.service import LLMService
from app.services.session_manager import SessionManager
from app.services.schema_registry import get_schema_registry
from app.services.schema_normalizer import normalize_extracted_fields
from app.services.lead_detail_context import build_lead_context
from app.services.lead_detail_context import normalize_lead_detail_payload

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
    lead_document_status: Any = None
    leadDocumentStatus: Any = None
    lead_dre_documents: Any = None
    leadDreDocuments: Any = None
    lead_dre_document_error: Any = None
    leadDreDocumentError: Any = None
    lead_context: Any = None
    leadContext: Any = None


class LeadContextRequest(BaseModel):
    lead_id: Any = None
    leadId: Any = None
    lead_detail: Any = None
    leadDetail: Any = None
    lead_dre_documents: Any = None
    leadDreDocuments: Any = None
    lead_dre_document_error: Any = None
    leadDreDocumentError: Any = None
    lead_document_status: Any = None
    leadDocumentStatus: Any = None
    lead_facts: Any = None
    leadFacts: Any = None


def _normalize_optional_error(value: Any) -> str | None:
    if value not in (None, ""):
        return str(value)
    return None


def _has_document_rows(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    uploaded = value.get("uploaded_documents") or value.get("uploadedDocuments") or value.get("uploaded")
    missing = value.get("missing_documents") or value.get("missingDocuments") or value.get("missing")
    return bool(uploaded or missing)


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


@router.post("/api/lead/context")
async def lead_context(request: LeadContextRequest) -> dict:
    return build_lead_context(
        lead_id=request.lead_id or request.leadId,
        lead_detail=request.lead_detail or request.leadDetail,
        lead_dre_documents=request.lead_dre_documents or request.leadDreDocuments,
        lead_dre_document_error=_normalize_optional_error(
            request.lead_dre_document_error or request.leadDreDocumentError
        ),
        lead_document_status=request.lead_document_status or request.leadDocumentStatus,
        lead_facts=request.lead_facts or request.leadFacts,
    )


@router.post("/api/chat")
async def chat_reply(request: ChatRequest) -> dict:
    lead_id = request.lead_id or request.leadId
    lead_context_payload = request.lead_context or request.leadContext
    if not isinstance(lead_context_payload, dict):
        lead_context_payload = None
    lead_detail = normalize_lead_detail_payload(request.lead_detail or request.leadDetail)
    lead_facts = request.lead_facts or request.leadFacts
    lead_missing_fields = request.lead_missing_fields or request.leadMissingFields
    if not isinstance(lead_facts, dict):
        lead_facts = None
    if not isinstance(lead_missing_fields, list):
        lead_missing_fields = None
    lead_document_status = request.lead_document_status or request.leadDocumentStatus
    lead_dre_documents = request.lead_dre_documents or request.leadDreDocuments
    lead_dre_document_error = _normalize_optional_error(
        request.lead_dre_document_error or request.leadDreDocumentError
    )
    built_lead_context = build_lead_context(
        lead_id=lead_id,
        lead_detail=lead_detail,
        lead_dre_documents=lead_dre_documents,
        lead_dre_document_error=lead_dre_document_error,
        lead_document_status=lead_document_status,
        lead_facts=lead_facts,
    )
    canonical_lead_context = built_lead_context
    if lead_context_payload:
        canonical_lead_context = {**built_lead_context, **lead_context_payload}
        if not _has_document_rows(lead_context_payload.get("document_status")) and _has_document_rows(
            built_lead_context.get("document_status")
        ):
            canonical_lead_context["document_status"] = built_lead_context["document_status"]
        if not lead_context_payload.get("document_error") and built_lead_context.get("document_error"):
            canonical_lead_context["document_error"] = built_lead_context["document_error"]

    lead_detail_keys = list(lead_detail.keys())[:30] if isinstance(lead_detail, dict) else []
    lead_fact_keys = list(lead_facts.keys())[:30] if isinstance(lead_facts, dict) else []
    lead_missing_sample = lead_missing_fields[:10] if isinstance(lead_missing_fields, list) else []
    logger.info(
        "[LeadDebug][backend] chat request: lead_id=%s has_context=%s has_detail=%s detail_keys=%s facts_count=%d fact_keys=%s missing_fields=%d missing_sample=%s has_document_status=%s has_dre_documents=%s history_turns=%d",
        lead_id,
        bool(canonical_lead_context),
        bool(lead_detail),
        lead_detail_keys,
        len(lead_facts or {}),
        lead_fact_keys,
        len(lead_missing_fields or []),
        lead_missing_sample,
        bool(lead_document_status),
        bool(lead_dre_documents),
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
        lead_dre_documents=lead_dre_documents,
        lead_document_status=lead_document_status,
        lead_dre_document_error=lead_dre_document_error,
        lead_context=canonical_lead_context,
    )
    return {
        **result,
        "lead_id": lead_id or canonical_lead_context.get("lead_id"),
        "lead_context": canonical_lead_context,
        "lead_context_used": bool(
            canonical_lead_context
            or lead_detail
            or lead_facts
            or lead_document_status
            or lead_dre_documents
            or lead_dre_document_error
        ),
    }
