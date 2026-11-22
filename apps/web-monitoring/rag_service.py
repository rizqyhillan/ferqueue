import json
import os
from pathlib import Path
import chromadb
from dotenv import load_dotenv
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

CHROMA_DIR = (BASE_DIR / os.getenv("CHROMA_PATH", "../../data/vector_db")).resolve()
LLM_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.50"))

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError(f"GEMINI_API_KEY tidak ditemukan. Pastikan file .env ada di {env_path}")

client = genai.Client(api_key=api_key)
chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = chroma.get_or_create_collection(
    name="ferqueue_knowledge",
    metadata={"hnsw:space": "cosine"},
)

SYSTEM_PROMPT = """
Kamu adalah FERQUEUE AI Assistant untuk petugas operasional gerbang pelabuhan penyeberangan.
Gunakan Bahasa Indonesia yang jelas, praktis, komunikatif, dan langsung membantu petugas mengambil keputusan.

FOKUS ANALISIS & JAWABAN:
1. **Analisis Status & Klasifikasi Tingkat Overweight:**
   - Jika menganalisis data kendaraan tertentu, sebutkan jenis kendaraan, golongan, berat aktual vs batas maksimal, selisih kelebihan berat (gram), serta tingkat pelanggarannya (**Overweight Ringan <= 15%** atau **Overweight Berat > 15%**).
2. **Saran Pengurangan Muatan:**
   - Hitung dan sebutkan secara konkret minimal berapa gram muatan yang harus diturunkan di luar area pelabuhan agar kendaraan memenuhi batas golongan.
3. **Langkah Penanganan Lapangan & Dasar Regulasi:**
   - Jelaskan langkah petugas di lapangan: tiket masuk tidak diterbitkan (Pasal 5 Permenhub PM 103 Tahun 2017), palang gerbang dibuka khusus untuk jalur keluar pelabuhan (Pasal 6 Permenhub PM 103 Tahun 2017), pemeriksaan fisik oleh petugas, dan pengarahan putar balik keluar pelabuhan.
4. **Mode Chat Bebas:**
   - Jika petugas bertanya tanpa memilih data kendaraan spesifik (misalnya menanyakan aturan berat, pasal rujukan, atau SOP), jawab langsung secara jelas berdasarkan dokumen referensi.

ATURAN KETAT (ANTI-HALUSINASI):
- Gunakan HANYA data kendaraan yang diberikan dan dokumen referensi FERQUEUE.
- Rujukan regulasi HANYA merujuk pada ketentuan berat di **Permenhub No. PM 103 Tahun 2017** (Pasal 2, Pasal 4, Pasal 5, Pasal 6). Jangan membahas ketentuan dimensi/tinggi portal dari peraturan tersebut karena sistem FERQUEUE hanya menilai berat.
- Batas golongan: Golongan A (Mobil) = 55 gram, Golongan B (Bus) = 85 gram, Golongan C (Truk) = 100 gram.
- Panjang (cm) dan Tinggi (cm) hanya informasi tampilan dan tidak memengaruhi pelanggaran.
- Jika pertanyaan berada di luar pengetahuan FERQUEUE, jawab persis: "Informasi tersebut belum tersedia dalam basis pengetahuan FERQUEUE."
- Jangan pernah menampilkan nama file dokumen sumber (seperti .md atau .txt) atau frasa "Referensi Dokumen" di dalam teks jawaban kepada pengguna.
"""


def retrieve_documents(query: str, top_k: int = 3) -> list[dict]:
    emb_res = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
    )
    query_vector = emb_res.embeddings[0].values

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    docs = []
    if not results["documents"] or not results["documents"][0]:
        return docs

    for i, content in enumerate(results["documents"][0]):
        distance = results["distances"][0][i]
        if distance <= MAX_DISTANCE:
            docs.append({
                "content": content,
                "source": results["metadatas"][0][i]["source"],
                "distance": round(float(distance), 4),
            })
    return docs


def generate_answer(question: str, vehicle_data: dict | None = None) -> dict:
    search_query = question
    if vehicle_data:
        search_query = (
            f"{question} aturan berat Permenhub PM 103 Tahun 2017 "
            f"klasifikasi tingkat overweight saran pengurangan muatan penanganan petugas"
        )

    relevant_docs = retrieve_documents(search_query, top_k=3)

    if not relevant_docs:
        return {
            "answer": "Informasi tersebut belum tersedia dalam basis pengetahuan FERQUEUE.",
            "sources": [],
        }

    context_text = "\n\n".join(
        f"[Sumber: {d['source']}]\n{d['content']}" for d in relevant_docs
    )

    if vehicle_data:
        payload = (
            f"DATA KENDARAAN / LOG PEMERIKSAAN TERPILIH:\n"
            f"{json.dumps(vehicle_data, ensure_ascii=False, indent=2)}\n\n"
            f"DOKUMEN REFERENSI FERQUEUE:\n{context_text}\n\n"
            f"PERTANYAAN / INSTRUKSI PETUGAS:\n{question}"
        )
    else:
        payload = (
            f"MODE CHAT UMUM (TIDAK ADA LOG KENDARAAN SPESIFIK YANG DIPILIH)\n\n"
            f"DOKUMEN REFERENSI FERQUEUE:\n{context_text}\n\n"
            f"PERTANYAAN PETUGAS:\n{question}"
        )

    response = client.models.generate_content(
        model=LLM_MODEL,
        contents=payload,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.45,
        ),
    )

    unique_sources = sorted({d["source"] for d in relevant_docs})
    return {
        "answer": response.text,
        "sources": unique_sources,
    }


if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("FERQUEUE RAG Service — Diagnosis & Self-Test")
    print(f"LLM Model      : {LLM_MODEL}")
    print(f"Embedding Model: {EMBEDDING_MODEL}")
    print(f"Chroma DB Path : {CHROMA_DIR}")
    print(f"Chroma Total   : {collection.count()} chunks tersimpan")
    print("=" * 60)

    test_q = sys.argv[1] if len(sys.argv) > 1 else "Berapa batas berat maksimum untuk Golongan A, B, dan C?"
    print(f"\n[1/2] Menjalankan query uji: '{test_q}'...")
    try:
        hasil = generate_answer(test_q)
        print("\n[2/2] Jawaban Sukses Diterima dari Gemini:")
        print("-" * 50)
        print(hasil["answer"])
        print("-" * 50)
        print(f"Sumber dokumen referensi: {', '.join(hasil['sources'])}")
        print("\n[STATUS: OK] RAG Service berfungsi normal tanpa kendala.")
    except Exception as e:
        print(f"\n[STATUS: ERROR] Gagal menjalankan RAG: {e}")
