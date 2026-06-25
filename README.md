# Education Account Management AI

This project is a prototype AI assistant for an MOE-style e-Service portal. It provides a Streamlit chat interface and a FastAPI backend that can answer FAQ-style questions using uploaded PDF documents as a knowledge base.

The system uses Azure OpenAI for chat responses and a local Sentence Transformers embedding model for document retrieval. Uploaded documents are processed, chunked, embedded, and stored in a SQL Server database.

## Features

- FAQ chatbot for MOE/e-Service related questions
- Intent detection for portal questions, greetings, and off-topic questions
- PDF document upload through the Streamlit UI
- Text extraction from uploaded PDFs
- Document chunking and local embedding generation
- SQL Server storage for documents, chunks, and embeddings
- Retrieval-augmented generation using relevant document chunks
- Basic fallback handling for off-topic or low-confidence answers
- API key protection for internal backend endpoints
- Basic rate limiting on FastAPI routes

## Project Structure

```text
education-account-management-AI/
│
├── app.py
├── main.py
├── config.py
├── models.py
├── prompts.py
├── document_processor.py
├── retrieval_sql.py
├── requirements.txt
├── .env
│
├── assistants/
│   ├── faq.py
│   └── faq_v2.py
│
├── embedding_models/
│   └── all-MiniLM-L6-v2/
│
└── venv/
```

### Important Files

#### `app.py`
Streamlit frontend for the chatbot. It allows users to:

- Chat with the assistant
- Upload PDF documents
- Trigger document ingestion
- View knowledge base statistics
- Clear the chat session

The Streamlit app sends requests to the FastAPI backend at:

```text
http://localhost:8000
```

#### `main.py`
FastAPI backend entry point. It defines the main API routes:

- `GET /health`
- `POST /ai/faq/chat`
- `POST /ai/documents/upload`
- `POST /ai/documents/ingest`
- `GET /ai/documents/stats`
- `GET /ai/documents`
- `DELETE /ai/documents/{document_id}`

It also configures CORS, rate limiting, and API key validation.

#### `config.py`
Central configuration file for:

- Azure OpenAI client setup
- Chat model name
- Local embedding model path
- RAG settings
- SQL Server connection string
- Internal API key

Update this file if your Azure OpenAI endpoint, model deployment name, SQL Server database, or embedding model path changes.

#### `models.py`
Pydantic request and response models used by the FastAPI backend.

Main models include:

- `FAQRequest`
- `FAQResponse`
- `UploadRequest`
- `UploadResponse`
- `HealthResponse`

#### `prompts.py`
Contains prompt templates and fallback responses, including:

- Intent classification prompt
- FAQ assistant system prompt
- Tier 1 off-topic fallback
- Tier 2 low-confidence fallback

#### `document_processor.py`
Handles PDF text extraction using `pdfplumber` and performs basic text cleaning.

#### `retrieval_sql.py`
Handles the RAG knowledge base logic:

- Connects to SQL Server
- Chunks document text
- Generates embeddings using Sentence Transformers
- Stores documents and chunks
- Retrieves relevant chunks using cosine similarity and recency weighting
- Provides document statistics

#### `assistants/faq.py` and `assistants/faq_v2.py`
Contain the FAQ assistant logic.

The backend currently imports `faq_v2.py` in `main.py`:

```python
from assistants.faq_v2 import handle_faq, detect_intent
```

So `faq_v2.py` is the active version used by the API.

#### `embedding_models/all-MiniLM-L6-v2/`
Local embedding model folder used by Sentence Transformers.

This folder is large and usually should not be committed to Git. It is better to download the model during setup or document how to obtain it.

#### `venv/`
Local Python virtual environment.

This should not be committed to Git. Other developers should create their own virtual environment locally.

## Requirements

- Python 3.11+ recommended
- VS Code
- SQL Server / SQL Server Express
- ODBC Driver 18 for SQL Server
- Azure OpenAI access
- Local Sentence Transformers embedding model, or internet access to download it

Python packages are listed in:

```text
requirements.txt
```

## Environment Variables

Create a `.env` file in the project root.

Example:

```env
AZURE_OPENAI_API_KEY="your-azure-openai-api-key"
INTERNAL_API_KEY="dev-secret-key"
```

Do not commit real API keys to GitHub.

## Database Setup

The project expects a SQL Server database named:

```text
AI_assistant
```

The current connection string in `config.py` is:

```python
DB_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=.\\SQLEXPRESS;"
    "DATABASE=AI_assistant;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)
```

Make sure the database exists before running the application.

The code expects two tables: `documents` and `chunks`.

A possible SQL setup script is:

```sql
-- Recreate clean database
CREATE DATABASE AI_assistant;
GO

USE AI_assistant;
GO

-- Documents table
CREATE TABLE documents (
    id INT IDENTITY(1,1) PRIMARY KEY,
    doc_id NVARCHAR(36) NOT NULL,
    file_name NVARCHAR(255) NOT NULL,
    source_label NVARCHAR(255) NULL,
    content_hash NVARCHAR(64) NOT NULL,
    uploaded_at DATETIME2 NOT NULL,
    admin_only BIT NOT NULL DEFAULT 0
);
GO

-- Chunks table
CREATE TABLE chunks (
    id INT IDENTITY(1,1) PRIMARY KEY,
    chunk_id NVARCHAR(36) NOT NULL,
    document_id INT NOT NULL,
    text NVARCHAR(MAX) NOT NULL,
    embedding NVARCHAR(MAX) NOT NULL,
    uploaded_at DATETIME2 NOT NULL,

    CONSTRAINT FK_chunks_documents
        FOREIGN KEY (document_id)
        REFERENCES documents(id)
        ON DELETE CASCADE
);
GO

-- Helpful indexes
CREATE INDEX IX_documents_content_hash
ON documents(content_hash);
GO

CREATE INDEX IX_documents_admin_only
ON documents(admin_only);
GO

CREATE INDEX IX_chunks_document_id
ON chunks(document_id);
GO

-- Verify schema
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE';

SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'documents'
ORDER BY ORDINAL_POSITION;
GO
```

## Running the Project in VS Code

### 1. Open the project folder

Open VS Code, then choose:

```text
File > Open Folder
```

Select the project folder:

```text
education-account-management-AI
```

### 2. Open the VS Code terminal

Use:

```text
Terminal > New Terminal
```

Make sure the terminal is opened at the project root.

### 3. Create a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try activating the virtual environment again.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Create the `.env` file

In the project root, create a `.env` file:

```env
AZURE_OPENAI_API_KEY="your-azure-openai-api-key"
INTERNAL_API_KEY="dev-secret-key"
```

The `INTERNAL_API_KEY` must match the value used by both `app.py` and `main.py`.

### 6. Check SQL Server settings

Confirm that SQL Server Express is running and that the database exists:

```text
AI_assistant
```

If your SQL Server instance name is different from `.\SQLEXPRESS`, update the connection string in `config.py`.

### 7. Start the FastAPI backend

In the VS Code terminal:

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The backend should run at:

```text
http://localhost:8000
```

You can test the API docs at:

```text
http://localhost:8000/docs
```

### 8. Start the Streamlit frontend

Open a second VS Code terminal, activate the same virtual environment, then run:

```powershell
streamlit run app.py
```

Streamlit will usually open the app at:

```text
http://localhost:8501
```

## Basic Usage

1. Start the FastAPI backend.
2. Start the Streamlit frontend.
3. Upload a PDF from the sidebar.
4. Click `Ingest Document`.
5. Ask questions related to the uploaded document or MOE e-Service portal.

## Recommended Git Ignore Rules

The project should not commit virtual environments, cache files, API keys, or large local model files.

Recommended `.gitignore` entries:

```gitignore
# Python
.venv/
venv/
__pycache__/
*.pyc

# Environment variables
.env
.env.*

# Local models
embedding_models/
models/
*.safetensors

# VS Code
.vscode/

# Logs
*.log
```

## Notes / Known Issues

A few parts of the current code may need cleanup or verification:

- `.env` should not contain real API keys when pushed to GitHub.
- `venv/` should not be included in the repository.
- `embedding_models/` contains large files and should usually be excluded from Git.
- `main.py` currently uses `faq_v2.py` as the active FAQ assistant.
- Some document management routes may need testing and minor fixes before production use.
- The SQL table creation script is not currently included as a separate migration file.

## Common Commands

Run backend:

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Run frontend:

```powershell
streamlit run app.py
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Check Git status:

```powershell
git status
```

Commit changes:

```powershell
git add .
git commit -m "Update README"
git push
```

## Hướng Dẫn Chạy Project Rút Gọn

- **Tạo & kích hoạt môi trường ảo:**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```

- **Cài thư viện:**
  ```powershell
  pip install -r requirements.txt
  ```

- **Tạo file `.env` (thư mục gốc):**
  ```env
  AZURE_OPENAI_API_KEY="your-key"
  INTERNAL_API_KEY="dev-secret-key"
  ```

- **Cấu hình Database (`config.py`):**
  Chuỗi kết nối (Connection String) đã được cập nhật tài khoản: `UID=sa; PWD=12345`. (Bạn chỉ cần sửa `SERVER=.\SQLEXPRESS` thành tên server của bạn nếu cần).

- **Chạy script tạo Database (SSMS -> Kết nối tới Server -> New Query):**
  ```sql
  -- Recreate clean database
  CREATE DATABASE AI_assistant;
  GO
  
  USE AI_assistant;
  GO
  
  -- Documents table
  CREATE TABLE documents (
      id INT IDENTITY(1,1) PRIMARY KEY,
      doc_id NVARCHAR(36) NOT NULL,
      file_name NVARCHAR(255) NOT NULL,
      source_label NVARCHAR(255) NULL,
      content_hash NVARCHAR(64) NOT NULL,
      uploaded_at DATETIME2 NOT NULL,
      admin_only BIT NOT NULL DEFAULT 0
  );
  GO
  
  -- Chunks table
  CREATE TABLE chunks (
      id INT IDENTITY(1,1) PRIMARY KEY,
      chunk_id NVARCHAR(36) NOT NULL,
      document_id INT NOT NULL,
      text NVARCHAR(MAX) NOT NULL,
      embedding NVARCHAR(MAX) NOT NULL,
      uploaded_at DATETIME2 NOT NULL,
  
      CONSTRAINT FK_chunks_documents
          FOREIGN KEY (document_id)
          REFERENCES documents(id)
          ON DELETE CASCADE
  );
  GO
  
  -- Helpful indexes
  CREATE INDEX IX_documents_content_hash
  ON documents(content_hash);
  GO
  
  CREATE INDEX IX_documents_admin_only
  ON documents(admin_only);
  GO
  
  CREATE INDEX IX_chunks_document_id
  ON chunks(document_id);
  GO
  
  -- Verify schema
  SELECT TABLE_NAME
  FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_TYPE = 'BASE TABLE';
  
  SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_NAME = 'documents'
  ORDER BY ORDINAL_POSITION;
  GO
  ```

- **Chạy Backend (ở Terminal 1):**
  ```powershell
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
  ```

- **Chạy Frontend (mở Terminal 2, kích hoạt .venv trước):**
  ```powershell
  streamlit run app.py
  ```