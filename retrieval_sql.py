import uuid
import json
import math
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass

import pyodbc
from sentence_transformers import SentenceTransformer

from config import (
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K_CHUNKS,
    RECENCY_WEIGHT,
    DB_CONNECTION_STRING,
    MIN_SIMILARITY_THRESHOLD,
)

# --- Local Embedding Model ---
_embedding_model = SentenceTransformer(EMBEDDING_MODEL)

# --- Data structures ---
@dataclass
class Chunk:
    chunk_id: str
    document_id: int
    text: str
    embedding: list[float]
    uploaded_at: datetime

# --- DB connection ---
def get_connection():
    return pyodbc.connect(DB_CONNECTION_STRING)

# --- Chunking ---
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words): break

        start += chunk_size - overlap
    
    return chunks

# --- Embedding ---
def embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings = _embedding_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False
    )
    return embeddings.tolist()

def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]

# --- Document helpers ---
def calculate_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def get_document_by_hash(content_hash: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, doc_id, file_name, source_label, content_hash, uploaded_at
            FROM documents
            WHERE content_hash = ?
            """,
            content_hash,
        )

        return cursor.fetchone()

    finally:
        conn.close()

def insert_document(
        doc_id: str,
        file_name: str,
        source_label: str,
        content_hash: str,
        uploaded_at: datetime,
) -> int:
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO documents (
                doc_id,
                file_name,
                source_label,
                content_hash,
                uploaded_at
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
            """,
            doc_id,
            file_name,
            source_label,
            content_hash,
            uploaded_at,
        )

        document_id = cursor.fetchone()[0]

        conn.commit()

        return document_id

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

# --- Storage ---
def ingest_document(
        text: str,
        doc_id: str | None = None,
        source_label: str = "",
        file_name: str | None = None
) -> dict:
    content_hash = calculate_content_hash(text)

    existing_doc = get_document_by_hash(content_hash)
    if existing_doc:
        return {
            "doc_id": existing_doc.doc_id,
            "document_id": existing_doc.id,
            "chunks_stored": 0,
            "skipped": True,
            "reason": "Duplicate document already exists",
        }
    
    if doc_id is None:
        doc_id = str(uuid.uuid4())

    if file_name is None:
        file_name = source_label or doc_id
    
    chunks_text = chunk_text(text)

    if not chunks_text:
        return {
            "doc_id": doc_id,
            "document_id": None,
            "chunks_stored": 0,
            "skipped": True,
            "reason": "No text chunks generated",
        }
    
    uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    embeddings = embed_texts(chunks_text)

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO documents (
                doc_id,
                file_name,
                source_label,
                content_hash,
                uploaded_at
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
            """,
            doc_id,
            file_name,
            source_label,
            content_hash,
            uploaded_at,
        )

        document_id = cursor.fetchone()[0]

        for text_chunk, embedding in zip(chunks_text, embeddings):
            cursor.execute(
                """
                INSERT INTO chunks (
                    chunk_id,
                    document_id,
                    text,
                    embedding,
                    uploaded_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                str(uuid.uuid4()),
                document_id,
                text_chunk,
                json.dumps(embedding),
                uploaded_at,
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "doc_id": doc_id,
        "document_id": document_id,
        "chunks_stored": len(chunks_text),
        "skipped": False,
        "reason": None,
    }

# --- Retrieval ---
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x,y in zip(a,b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(x*x for x in b))

    if norm_a == 0 or norm_b == 0: return 0.0
    return dot / (norm_a * norm_b)

def recency_boost(uploaded_at: datetime, all_dates: list[datetime]) -> float:
    if not all_dates or len(set(all_dates)) == 1:
        return 0.0
    min_ts = min(all_dates).timestamp()
    max_ts = max(all_dates).timestamp()
    span = max_ts - min_ts

    if span == 0: return 0.0

    return (uploaded_at.timestamp() - min_ts) / span

def retrieve(query: str, top_k: int = TOP_K_CHUNKS) -> list[str]:
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                c.chunk_id,
                c.text,
                c.embedding,
                CAST(c.uploaded_at AS DATETIME2) AS uploaded_at,
                d.file_name,
                d.source_label
            FROM chunks c
            INNER JOIN documents d on c.document_id = d.id
            """
        )

        rows = cursor.fetchall()

    finally:
        conn.close()

    if not rows:
        return []

    query_embedding = embed_query(query)
    all_dates = [row.uploaded_at for row in rows]

    scored = []

    for row in rows:
        embedding = json.loads(row.embedding)
        similarity = cosine_similarity(query_embedding, embedding)
        
        if similarity < MIN_SIMILARITY_THRESHOLD:
            continue

        freshness = recency_boost(row.uploaded_at, all_dates)
        score = (1 - RECENCY_WEIGHT) * similarity + RECENCY_WEIGHT * freshness

        scored.append((score, row.text))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [text for _, text in scored[:top_k]]

# --- Document management ---
def list_documents() -> list[dict]:
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                d.id,
                d.doc_id,
                d.file_name,
                d.source_label,
                d.content_hash,
                d.uploaded_at,
                COUNT(c.chunk_id) AS chunk_count
            FROM documents d
            LEFT JOIN chunks c ON d.id = c.document_id
            GROUP BY
                d.id,
                d.doc_id,
                d.file_name,
                d.source_label,
                d.content_hash,
                d.uploaded_at
            ORDER BY d.uploaded_at DESC
            """
        )

        rows = cursor.fetchall()

    finally:
        conn.close()

    return [
        {
            "id": row.id,
            "doc_id": row.doc_id,
            "file_name": row.file_name,
            "source_label": row.source_label,
            "content_hash": row.content_hash,
            "uploaded_at": row.uploaded_at,
            "chunk_count": row.chunk_count,
        }
        for row in rows
    ]

def delete_document(document_id: int) -> bool:
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM documents
            WHERE id = ?
            """,
            document_id,
        )

        affected = cursor.rowcount

        conn.commit()

        return affected > 0

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

# --- Stats ---

def get_store_stats() -> dict:
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM chunks")
        total_chunks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM documents")
        total_documents = cursor.fetchone()[0]

        return {
            "total_chunks": total_chunks,
            "total_documents": total_documents,
        }

    finally:
        conn.close()