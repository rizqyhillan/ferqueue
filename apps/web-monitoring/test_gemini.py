import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 1. Tes LLM Generation
chat_res = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    contents="Tes koneksi FERQUEUE AI. Jawab singkat: Siap!"
)
print("Respon LLM:", chat_res.text)

# 2. Tes Embedding untuk RAG
emb_res = client.models.embed_content(
    model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
    contents="Tes vektor SOP FERQUEUE"
)
print("Panjang Vektor Embedding:", len(emb_res.embeddings[0].values))