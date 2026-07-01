from fastapi import APIRouter
from dynamic_fas.conversation import handle_chat
from dynamic_fas.models import (
    DynamicChatRequest,
    DynamicChatResponse,
    DynamicResetSessionRequest,
)
from dynamic_fas.session_store import reset_session

router = APIRouter(prefix="/dynamic-fas", tags=["Dynamic FAS"])

@router.post("/chat", response_model=DynamicChatResponse)
def chat(request: DynamicChatRequest):
    return handle_chat(request)

@router.post("/reset-session")
def reset(request: DynamicResetSessionRequest):
    reset_session(request.session_id)
    return {
        "session_id": request.session_id,
        "reset": True,
    }
