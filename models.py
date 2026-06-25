from pydantic import BaseModel
from typing import Literal, Optional

# --- Shared ---
class ChatMessage(BaseModel):
    role: str
    content: str

# --- FAQ ---
class FAQRequest(BaseModel):
    message: str
    history: list[ChatMessage]
    user_id: str
    role: str = "user"

class FAQResponse(BaseModel):
    answer: str
    fallback: bool
    fallback_type: Optional[Literal["tier1", "tier2", "account_info"]] = None
    support_contact: Optional[str] = None

# --- FAS ---
class FormContext(BaseModel):
    outstanding_fields: list[str]
    prefilled_fields: list[str]

class FASRequest(BaseModel):
    message: str
    history: list[ChatMessage]
    user_id: str
    form_context: FormContext

class FASResponse(BaseModel):
    answer: str
    fallback: bool
    outstanding_fields_reminder: Optional[list[str]] = None

# --- Document Upload ---
class UploadResponse(BaseModel):
    doc_id: str
    chunks_stored: int
    message: str

class UploadRequest(BaseModel):
    text: str
    source_label: str = ""

# --- Health ---
class HealthResponse(BaseModel):
    status: str
    openai_connected: bool
    model: str
    total_chunks: int = 0
    total_documents: int = 0