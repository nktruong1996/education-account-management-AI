import os
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

# --- Azure OpenAI Client ---
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = "https://eduopenainew.openai.azure.com/"
AZURE_API_VERSION = "2024-02-01"

client = AzureOpenAI(
    api_key = AZURE_OPENAI_API_KEY,
    azure_endpoint = AZURE_OPENAI_ENDPOINT,
    api_version = AZURE_API_VERSION,
)

# --- Models ---
CHAT_MODEL = "gpt-5-mini"
EMBEDDING_MODEL = "embedding_models/all-MiniLM-L6-v2"

# --- RAG Settings ---
CHUNK_SIZE = 200
CHUNK_OVERLAP = 60
TOP_K_CHUNKS = 4
RECENCY_WEIGHT = 0.15
MIN_SIMILARITY_THRESHOLD = 0.3

# --- Memory ---
MAX_HISTORY_TURNS = 10

# --- Fallback ---
SUPPORT_CONTACT = "support@moe-eservice.gov.sg"

# --- Internal Auth ---
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "dev-secret-key")

# --- Database ---
DB_CONNECTION_STRING = os.getenv("DB_CONNECTION_STRING", (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=DESKTOP-RC0R4GG\\MYSQLSERVER;"
    "DATABASE=AI_assistant;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
))