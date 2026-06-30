from fastapi import FastAPI, HTTPException, Depends, Request
# from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi import UploadFile, File, Form

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import client, CHAT_MODEL, INTERNAL_API_KEY
from models import FAQRequest, FAQResponse, HealthResponse, UploadRequest, UploadResponse, ChatRequest, ChatResponse, ResetSessionRequest
from assistants.faq_v2 import handle_faq, detect_intent
from dynamic_fas.router import router as dynamic_fas_router
from services.conversation import handle_chat, reset_session
# from assistants.faq_v2 import stream_faq
from retrieval_sql import ingest_document, get_store_stats, get_connection, list_documents, delete_document
from document_processor import extract_text_from_pdf

app = FastAPI(
    title="SFS e-Service AI Prototype",
    version="0.1.0",
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dynamic_fas_router)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

async def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

# --- Health check ---
@app.get("/health", response_model=HealthResponse)
@limiter.limit("60/minute")
async def health_check(request: Request):
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": "Reply with the word OK only."}],
            max_completion_tokens=30,
        )
        reply = response.choices[0].message.content.strip()

        print(f"[health] Raw reply: {reply}")

        connected = "ok" in reply.lower()

    except Exception as e:
        print(f"[health] OpenAI connection failed: {type(e).__name__}: {e}")
        connected = False

    try:
        stats = get_store_stats()
        db_connected = True
    except Exception as e:
        db_connected = False
        print(f"[health] Database connection failed: {type(e).__name__}: {e}")

        stats = {
            "total_chunks": 0,
            "total_documents": 0,
        }

    return HealthResponse(
        status = "ok" if connected and db_connected else "degraded",
        openai_connected=connected,
        model=CHAT_MODEL,
        total_chunks=stats["total_chunks"],
        total_documents=stats["total_documents"],
    )

# --- Document ingestion ---
@app.post("/ai/documents/ingest", response_model=UploadResponse)
@limiter.limit("100/minute")
async def ingest_doc(request: Request, req: UploadRequest, api_key: str = Depends(verify_api_key)):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty document text")
    
    result = ingest_document(
        text=req.text,
        source_label=req.source_label,
        file_name=req.source_label or "unnamed document",
    )

    if result.get("skipped"):
        return UploadResponse(
            doc_id="duplicate",
            chunks_stored=0,
            message=f"'{req.source_label or 'unnamed document'}' already exists in the knowledge base - skipped.",
        )
    
    return UploadResponse(
        doc_id=result["doc_id"],
        chunks_stored=result["chunks_stored"],
        message=f"Ingested {result['chunks_stored']} chunks from '{req.source_label or 'unnamed document'}'",
    )

# --- Document management ---
@app.get("/ai/documents")
@limiter.limit("100/minute")
async def get_documents(request: Request, api_key: str = Depends(verify_api_key)):
    return list_documents()

@app.delete("/ai/documents/{document_id}")
@limiter.limit("50/minute")
async def remove_document(
    request: Request,
    document_id: int,
    api_key: str = Depends(verify_api_key)
):
    deleted = delete_document(document_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "document_id": document_id,
        "deleted": True,
        "message": f"Deleted document {document_id} and its associated chunks."
    }

# --- Chunk inspection ---
@app.get("/ai/documents/chunks")
@limiter.limit("100/minute")
async def get_chunks(request: Request, api_key: str = Depends(verify_api_key)):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                c.chunk_id,
                d.doc_id,
                d.file_name,
                d.source_label,
                CAST(c.uploaded_at as DATETIME2) AS uploaded_at,
                c.text
            FROM chunks c
            INNER JOIN documents d on c.document_id = d.id
            ORDER BY c.uploaded_at DESC
            """
        )

        rows = cursor.fetchall()

        return [
            {
                "chunk_id": row.chunk_id,
                "doc_id": row.doc_id,
                "file_name": row.file_name,
                "source_label": row.source_label,
                "uploaded_at": row.uploaded_at.isoformat(),
                "text": row.text,
            }
            for row in rows
        ]

    finally:
        conn.close()

# --- Chunk stats ---
@app.get("/ai/documents/stats")
@limiter.limit("100/minute")
async def get_stats(request: Request, api_key: str = Depends(verify_api_key)):
    return get_store_stats()

# --- FAQ Assistant ---
@app.post("/ai/faq/chat", response_model=FAQResponse)
@limiter.limit("100/minute")
async def faq_chat(request: Request, req: FAQRequest, api_key: str = Depends(verify_api_key)):
    try:
        return handle_faq(req)
    except Exception as e:
        print(f"[faq] Error for user {req.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal AI error")
    
# # --- FAQ Assistant Stream ---
# @app.post("/ai/faq/chat_stream")
# @limiter.limit("100/minute")
# def faq_chat_stream(request: Request, req: FAQRequest, api_key: str = Depends(verify_api_key)):
#     try:
#         return StreamingResponse(stream_faq(req), media_type="application/x-ndjson")
#     except Exception as e:
#         print(f"[faq_stream] Error for user {req.user_id}: {e}")
#         raise HTTPException(status_code=500, detail="Internal AI error")
    
# --- Document processor ---
@app.post("/ai/documents/upload", response_model=UploadResponse)
@limiter.limit("50/minute")
async def upload_doc(
    request: Request,
    file: UploadFile = File(...),
    admin_only: bool = Form(False),
    api_key: str = Depends(verify_api_key)
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for now")
    
    contents = await file.read()
    text = extract_text_from_pdf(contents)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")
    
    result = ingest_document(
        text=text,
        source_label=file.filename,
        file_name=file.filename,
        admin_only=admin_only
    )

    if result.get("skipped"):
        return UploadResponse(
            doc_id="duplicate",
            chunks_stored=0,
            message=f"'{file.filename}' already exists in the knowledge base - skipped.",
        )
    
    return UploadResponse(
        doc_id=result["doc_id"],
        chunks_stored=result["chunks_stored"],
        message=f"Ingested {result['chunks_stored']} chunks from '{file.filename}'",
    )

# --- Normal Chat (Form Cố Định) ---
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return handle_chat(request)

@app.post("/reset-session")
def reset(request: ResetSessionRequest):
    reset_session(request.session_id)
    return {
        "message": "Session reset successfully",
        "session_id": request.session_id,
    }

# --- Dev runner ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_access:app", host="0.0.0.0", port=8001, reload=True)