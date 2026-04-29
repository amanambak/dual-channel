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


class SummaryRequest(BaseModel):
    conversation: str


class SummaryChatRequest(BaseModel):
    customer_info: dict[str, str] = Field(default_factory=dict)
    conversation: str = ""


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


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
    reply = await llm_service.generate_chat_reply(
        message=request.message,
        history=[turn.model_dump() for turn in request.history],
    )
    return {"reply": reply}
