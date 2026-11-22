import os
from pathlib import Path
import chromadb
from dotenv import load_dotenv
from google import genai

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CHROMA_DIR = (BASE_DIR / os.getenv("CHROMA_PATH", "../../data/vector_db")).resolve()
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError(f"GEMINI_API_KEY tidak ditemukan. Pastikan file .env ada di {env_path}")

client = genai.Client(api_key=api_key)
chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = chroma.get_or_create_collection(
    name="ferqueue_knowledge",
    metadata={"hnsw:space": "cosine"},
)


def split_chunks(text: str, size: int = 500, overlap: int = 80) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return chunks


def ingest_documents():
    if not KNOWLEDGE_DIR.exists():
        print(f"Folder tidak ditemukan: {KNOWLEDGE_DIR}")
        return

    documents, metadatas, ids = [], [], []

    for path in sorted(KNOWLEDGE_DIR.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        for idx, chunk in enumerate(split_chunks(text)):
            documents.append(chunk)
            metadatas.append({"source": path.name, "chunk": idx})
            ids.append(f"{path.stem}_{idx}")

    if not documents:
        print("Tidak ada file .md atau .txt di dalam folder knowledge/.")
        return

    print(f"Memproses embedding untuk {len(documents)} potongan dokumen...")
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=documents,
    )
    embeddings = [item.values for item in response.embeddings]

    # Hapus data lama agar tidak duplikat jika ingest dijalankan ulang
    existing = collection.get()
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    print(f"Sukses menyimpan {len(documents)} chunks ke {CHROMA_DIR}")


if __name__ == "__main__":
    ingest_documents()