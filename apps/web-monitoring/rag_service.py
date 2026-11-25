import json
import os
import re
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
env_path = BASE_DIR / ".env" if (BASE_DIR / ".env").exists() else BASE_DIR.parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

CHROMA_DIR = (BASE_DIR / os.getenv("CHROMA_PATH", "../../data/vector_db")).resolve()
LLM_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "0.68"))
MAX_HISTORY_MESSAGES = int(os.getenv("AI_MAX_HISTORY_MESSAGES", "20"))

_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}\.(md|txt)$")
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "untuk", "pada", "dengan", "ini", "itu",
    "atau", "jika", "bila", "apa", "bagaimana", "berapa", "saya", "kami", "anda",
    "tolong", "buat", "buatkan", "beri", "berikan", "ada", "tidak", "bisa", "ya",
    "dong", "gak", "nggak", "nya", "di", "dalam", "oleh", "adalah", "tentang",
}

_client = None
_collection = None


def _get_genai_client():
    global _client
    if _client is not None:
        return _client

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Paket 'google-genai' belum terpasang. Jalankan: pip install -r apps/web-monitoring/requirements.txt"
        ) from exc

    load_dotenv(dotenv_path=env_path)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"GEMINI_API_KEY tidak ditemukan. Pastikan file .env ada di {env_path}"
        )

    _client = genai.Client(api_key=api_key)
    return _client


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError(
            "Paket 'chromadb' belum terpasang. Jalankan: pip install -r apps/web-monitoring/requirements.txt"
        ) from exc

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = chroma.get_or_create_collection(
        name="ferqueue_knowledge",
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


# ==============================================================================
# MANAJEMEN BASIS PENGETAHUAN SOP & RE-INDEX RAG
# ==============================================================================
def normalize_knowledge_filename(raw_name: str) -> str:
    name = Path(str(raw_name or "").strip()).name
    if not name:
        raise ValueError("Nama file SOP tidak boleh kosong.")
    if "." not in name:
        name = f"{name}.md"
    stem, ext = name.rsplit(".", 1)
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    safe_ext = ext.lower()
    if safe_ext not in ("md", "txt"):
        raise ValueError("Ekstensi file SOP hanya mendukung .md atau .txt.")
    candidate = f"{safe_stem}.{safe_ext}"
    if not _SAFE_FILENAME_RE.match(candidate):
        raise ValueError("Nama file SOP hanya boleh huruf, angka, tanda hubung (-), atau garis bawah (_).")
    return candidate


def _resolve_knowledge_path(filename: str) -> Path:
    safe_name = normalize_knowledge_filename(filename)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = (KNOWLEDGE_DIR / safe_name).resolve()
    if resolved.parent != KNOWLEDGE_DIR.resolve():
        raise ValueError("Path file SOP tidak valid.")
    return resolved


def split_chunks(text: str, size: int = 350, overlap: int = 60) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(start + 1, end - overlap)
    return chunks


def list_knowledge_files() -> list[dict]:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        first_heading = next(
            (line.lstrip("# ").strip() for line in content.splitlines() if line.strip()),
            path.stem,
        )
        stat = path.stat()
        items.append({
            "filename": path.name,
            "title": first_heading[:120],
            "size_bytes": stat.st_size,
            "word_count": len(content.split()),
            "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "preview": content[:180].strip(),
        })
    return items


def read_knowledge_file(filename: str) -> dict:
    path = _resolve_knowledge_path(filename)
    if not path.is_file():
        raise FileNotFoundError(f"Dokumen SOP '{path.name}' tidak ditemukan.")
    content = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    return {
        "filename": path.name,
        "content": content,
        "size_bytes": stat.st_size,
        "word_count": len(content.split()),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_knowledge_file(filename: str, content: str) -> dict:
    text = str(content or "").strip()
    if not text:
        raise ValueError("Isi dokumen SOP tidak boleh kosong.")
    if len(text.encode("utf-8")) > 200 * 1024:
        raise ValueError("Ukuran dokumen SOP maksimal 200 KB.")
    path = _resolve_knowledge_path(filename)
    path.write_text(text + "\n", encoding="utf-8")
    return read_knowledge_file(path.name)


def delete_knowledge_file(filename: str) -> str:
    path = _resolve_knowledge_path(filename)
    if not path.is_file():
        raise FileNotFoundError(f"Dokumen SOP '{path.name}' tidak ditemukan.")
    all_files = list_knowledge_files()
    if len(all_files) <= 1:
        raise ValueError("Minimal harus tersisa 1 dokumen SOP di basis pengetahuan.")
    path.unlink()
    return path.name


def get_knowledge_status() -> dict:
    files = list_knowledge_files()
    chunk_count = 0
    vector_ready = False
    try:
        chunk_count = _get_collection().count()
        vector_ready = chunk_count > 0
    except Exception:
        chunk_count = 0
        vector_ready = False
    return {
        "total_files": len(files),
        "vector_chunks": chunk_count,
        "vector_ready": vector_ready,
        "model": LLM_MODEL,
        "max_history_messages": MAX_HISTORY_MESSAGES,
    }


def reindex_knowledge() -> dict:
    """Chunk ulang seluruh dokumen knowledge/*.md|*.txt dan simpan embedding ke ChromaDB."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    documents, metadatas, ids = [], [], []
    file_names = []

    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        file_names.append(path.name)
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, chunk in enumerate(split_chunks(text)):
            documents.append(chunk)
            metadatas.append({"source": path.name, "chunk": idx})
            ids.append(f"{path.stem}_{idx}")

    if not documents:
        return {
            "indexed_files": 0,
            "indexed_chunks": 0,
            "vector_ready": False,
            "warning": "Tidak ada dokumen .md atau .txt di folder knowledge/.",
        }

    try:
        client = _get_genai_client()
        collection = _get_collection()
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=documents,
        )
        embeddings = [item.values for item in response.embeddings]

        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        return {
            "indexed_files": len(file_names),
            "indexed_chunks": len(documents),
            "vector_ready": True,
            "warning": None,
        }
    except Exception as exc:
        return {
            "indexed_files": len(file_names),
            "indexed_chunks": len(documents),
            "vector_ready": False,
            "warning": f"File SOP tersimpan, tetapi embedding ChromaDB belum diperbarui ({exc}). Pencarian hybrid lokal tetap aktif.",
        }


# ==============================================================================
# HYBRID RETRIEVAL (VECTOR CHROMADB + KEYWORD FALLBACK LOKAL)
# ==============================================================================
def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(str(text or "").lower()) if t not in _STOPWORDS}


def _keyword_retrieve_documents(query: str, top_k: int = 4) -> list[dict]:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    q_tokens = _tokenize(query)
    scored = []

    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, chunk in enumerate(split_chunks(text)):
            c_tokens = _tokenize(chunk)
            overlap = len(q_tokens & c_tokens) if q_tokens else 0
            # Beri bobot tambahan jika nama file relevan
            name_overlap = len(q_tokens & _tokenize(path.stem.replace("_", " "))) if q_tokens else 0
            score = overlap + (name_overlap * 2)
            scored.append({
                "content": chunk,
                "source": path.name,
                "distance": round(max(0.05, 1.0 - min(0.95, score / max(1, len(q_tokens) + 1))), 4),
                "score": score,
                "method": "keyword",
                "chunk_id": f"{path.name}#{idx}",
            })

    scored.sort(key=lambda item: (item["score"], -item["distance"]), reverse=True)
    positive = [item for item in scored if item["score"] > 0]
    if positive:
        return positive[:top_k]
    # Jika query sangat umum (mis. audit harian), tetap kembalikan ringkasan SOP inti
    return scored[: min(2, len(scored))]


def retrieve_documents(query: str, top_k: int = 4) -> tuple[list[dict], str]:
    vector_docs = []
    retrieval_mode = "keyword_local"

    try:
        collection = _get_collection()
        if collection.count() > 0:
            client = _get_genai_client()
            emb_res = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=query,
            )
            query_vector = emb_res.embeddings[0].values
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, collection.count()),
                include=["documents", "metadatas", "distances"],
            )
            if results.get("documents") and results["documents"][0]:
                for i, content in enumerate(results["documents"][0]):
                    distance = float(results["distances"][0][i])
                    if distance <= MAX_DISTANCE:
                        meta = results["metadatas"][0][i] or {}
                        vector_docs.append({
                            "content": content,
                            "source": meta.get("source", "sop.md"),
                            "distance": round(distance, 4),
                            "method": "vector",
                        })
            if vector_docs:
                retrieval_mode = "vector_chromadb"
    except Exception:
        vector_docs = []

    # Gabungkan dengan pencarian keyword lokal jika hasil vector masih sedikit (< 2)
    if len(vector_docs) < 2:
        kw_docs = _keyword_retrieve_documents(query, top_k=top_k)
        seen = {(d["source"], d["content"][:80]) for d in vector_docs}
        for d in kw_docs:
            key = (d["source"], d["content"][:80])
            if key not in seen:
                vector_docs.append(d)
                seen.add(key)
            if len(vector_docs) >= top_k:
                break
        if retrieval_mode == "vector_chromadb" and len(vector_docs) > 0:
            retrieval_mode = "hybrid_vector_keyword"

    return vector_docs[:top_k], retrieval_mode


SYSTEM_PROMPT = """
Kamu adalah FERQUEUE AI Assistant untuk petugas operasional gerbang pelabuhan penyeberangan.
Gunakan Bahasa Indonesia yang jelas, terstruktur, praktis, dan langsung membantu petugas mengambil keputusan.

KEMAMPUAN & FOKUS ANALISIS:
1. **Analisis Keputusan Overweight & Saran Pengurangan Muatan:**
   - Jika menganalisis data kendaraan tertentu, sebutkan jenis kendaraan, golongan, berat aktual vs batas maksimal, selisih kelebihan berat (gram & persentase), tingkat pelanggaran (**Overweight Ringan <= 15%** atau **Overweight Berat > 15%**), serta minimal pengurangan muatan (gram).
2. **Ringkasan Audit Harian & Tanya Jawab Data Operasional:**
   - Jika petugas meminta ringkasan audit harian, laporan hari ini, statistik pelanggaran, pelanggar terberat, atau kondisi timbangan saat ini, gunakan **DATA OPERASIONAL & RINGKASAN AUDIT HARIAN** yang diberikan secara akurat (jangan mengarang angka!).
   - Sajikan ringkasan audit harian secara rapi dengan poin-poin: Ringkasan Total & Kepatuhan, Sebaran per Golongan, Sorotan Kasus Overweight, Status Timbangan Aktif, dan Rekomendasi Tindak Lanjut Petugas.
3. **Audit Visual Multimodal (Jika Foto Kendaraan Dilampirkan):**
   - Verifikasi kesesuaian visual antara bentuk kendaraan pada foto (`Mobil` = Golongan A, `Bus` = Golongan B, `Truk` = Golongan C) dengan data golongan yang tercatat.
   - Laporkan jika ada dugaan salah klasifikasi golongan atau catatan fisik/muatan penting yang terlihat di foto (jika foto tidak jelas atau bukan kendaraan, sampaikan secara jujur).
4. **Langkah Penanganan Lapangan, Skrip Komunikasi, & Dasar Regulasi:**
   - Rujuk ketentuan berat pada **Permenhub No. PM 103 Tahun 2017** (Pasal 2, Pasal 4, Pasal 5, Pasal 6).
   - Tiket masuk tidak diterbitkan untuk kendaraan Overweight (Pasal 5) dan palang gerbang dibuka khusus untuk jalur keluar/putar balik (Pasal 6).
5. **Konteks Percakapan Multi-Turn:**
   - Perhatikan riwayat percakapan sebelumnya agar pertanyaan lanjutan (misalnya simulasi penurunan muatan atau revisi skrip komunikasi) tetap nyambung.

ATURAN KETAT (ANTI-HALUSINASI):
- Gunakan HANYA data kendaraan, data operasional, foto yang dilampirkan, riwayat percakapan, dan dokumen SOP FERQUEUE yang disediakan.
- Batas golongan baku: Golongan A (Mobil) = 55 gram (Rp 60.000), Golongan B (Bus) = 85 gram (Rp 120.000), Golongan C (Truk) = 100 gram (Rp 250.000).
- Panjang (cm) dan Tinggi (cm) hanya informasi tampilan monitoring dan tidak menentukan pelanggaran.
- Jangan pernah menyebutkan nama file dokumen sumber (seperti `.md` atau `.txt`) di dalam teks jawaban.
- Jika pertanyaan benar-benar di luar domain FERQUEUE dan tidak tercakup di data maupun SOP, jawab dengan sopan: "Informasi tersebut belum tersedia dalam basis pengetahuan FERQUEUE."
"""


def _format_history_text(chat_history: list[dict] | None) -> str:
    if not chat_history:
        return ""
    lines = []
    for msg in chat_history[-MAX_HISTORY_MESSAGES:]:
        role = "Petugas" if str(msg.get("role", "")).lower() == "user" else "AI Assistant"
        content = str(msg.get("content") or "").strip()
        if content:
            lines.append(f"- {role}: {content[:1200]}")
    return "\n".join(lines)


def _is_daily_audit_query(question: str) -> bool:
    q = str(question or "").lower()
    keywords = (
        "audit harian", "ringkasan", "rekap", "laporan hari ini", "hari ini",
        "statistik", "berapa kendaraan", "berapa truk", "berapa bus", "berapa mobil",
        "pelanggar", "terberat", "timbangan sekarang", "status gate", "operasional",
    )
    return any(k in q for k in keywords)


def _build_fallback_answer(
    question: str,
    vehicle_data: dict | None,
    operational_summary: dict | None,
    relevant_docs: list[dict],
    has_image: bool,
    reason: str,
) -> str:
    """Fallback terstruktur berbasis rule PM 103/2017 + data live jika Gemini API sedang tidak terjangkau."""
    sections = []
    sections.append(
        "### Mode Fallback Lokal (Rule-Based + Data Live)\n"
        f"_Koneksi model Gemini sedang tidak tersedia ({reason}), sehingga jawaban disusun otomatis dari data aktual & basis SOP lokal._"
    )

    if vehicle_data:
        status = vehicle_data.get("status", "Normal")
        gol = vehicle_data.get("golongan", "A")
        jenis = vehicle_data.get("jenis_kendaraan", "Kendaraan")
        berat = vehicle_data.get("berat_aktual_gram", 0)
        batas = vehicle_data.get("batas_maksimum_gram", 55)
        kelebihan = vehicle_data.get("kelebihan_berat_gram", 0)
        pct = vehicle_data.get("persentase_kelebihan", "0%")
        kategori = vehicle_data.get("kategori_overweight", "-")
        sections.append(
            "### Analisis Kendaraan\n"
            f"- **Kendaraan:** {jenis} (Golongan {gol}) — Status **{status}**\n"
            f"- **Berat Aktual vs Batas:** {berat} g / {batas} g\n"
            f"- **Kelebihan Muatan:** +{kelebihan} g ({pct}) — Kategori: **{kategori}**\n"
            f"- **Saran Pengurangan:** Turunkan minimal **{kelebihan} gram** di luar area pelabuhan sebelum timbang ulang.\n"
            "- **Tindakan Regulasi (PM 103/2017):** Tiket masuk tidak diterbitkan (**Pasal 5**), buka palang khusus jalur keluar/putar balik (**Pasal 6**), lakukan pemeriksaan fisik, dan arahkan pengemudi keluar pelabuhan."
        )
        if has_image:
            sections.append(
                "### Catatan Audit Visual\n"
                "- Foto kendaraan terlampir siap diaudit visual; aktifkan kembali koneksi Gemini API untuk verifikasi kesesuaian bentuk kendaraan otomatis."
            )

    if operational_summary and (_is_daily_audit_query(question) or not vehicle_data):
        hari = operational_summary.get("ringkasan_hari_ini", {})
        all_rec = operational_summary.get("ringkasan_keseluruhan", {})
        sensor = operational_summary.get("sensor_timbangan_aktif", {})
        tgl = operational_summary.get("tanggal_hari_ini", "-")
        heaviest = hari.get("pelanggaran_terberat")
        heaviest_txt = (
            f"{heaviest.get('id_pemeriksaan')} ({heaviest.get('jenis_kendaraan')} Gol. {heaviest.get('golongan')}, "
            f"+{heaviest.get('kelebihan_berat_gram')} g / {heaviest.get('persentase_kelebihan')})"
            if heaviest
            else "Belum ada pelanggaran overweight hari ini"
        )
        sections.append(
            f"### Ringkasan Audit Harian ({tgl})\n"
            f"- **Total Pemeriksaan Hari Ini:** {hari.get('total', 0)} unit "
            f"(Normal: {hari.get('normal', 0)}, Overweight: {hari.get('overweight', 0)})\n"
            f"- **Sebaran Golongan Hari Ini:** Mobil (Gol. A): {hari.get('mobil', 0)} | Bus (Gol. B): {hari.get('bus', 0)} | Truk (Gol. C): {hari.get('truk', 0)}\n"
            f"- **Pelanggaran Terberat Hari Ini:** {heaviest_txt}\n"
            f"- **Total Arsip Tercatat:** {all_rec.get('total', 0)} unit (Overweight: {all_rec.get('overweight', 0)})\n"
            f"- **Sensor Timbangan Aktif:** Gol. {sensor.get('golongan', 'A')} — {sensor.get('berat_gram', 0)} g / batas {sensor.get('batas_gram', 55)} g ({sensor.get('status', 'Normal')})"
        )

    if relevant_docs and not vehicle_data:
        snippets = "\n".join(f"- {d['content'][:320].strip()}..." for d in relevant_docs[:2])
        sections.append(f"### Rujukan SOP Terkait\n{snippets}")

    return "\n\n".join(sections)


def generate_answer(
    question: str,
    vehicle_data: dict | None = None,
    chat_history: list[dict] | None = None,
    operational_summary: dict | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
) -> dict:
    search_query = question
    if vehicle_data:
        search_query = (
            f"{question} aturan berat Permenhub PM 103 Tahun 2017 "
            f"klasifikasi tingkat overweight saran pengurangan muatan penanganan petugas"
        )

    relevant_docs, retrieval_mode = retrieve_documents(search_query, top_k=4)
    unique_sources = sorted({d["source"] for d in relevant_docs})
    has_image = bool(image_bytes)

    if not relevant_docs and not vehicle_data and not operational_summary and not has_image:
        return {
            "answer": "Informasi tersebut belum tersedia dalam basis pengetahuan FERQUEUE.",
            "sources": [],
            "used_vision": False,
            "used_fallback": False,
            "retrieval_mode": retrieval_mode,
        }

    context_blocks = []
    if operational_summary:
        context_blocks.append(
            "DATA OPERASIONAL & RINGKASAN AUDIT HARIAN (REAL-TIME):\n"
            + json.dumps(operational_summary, ensure_ascii=False, indent=2)
        )
    if vehicle_data:
        context_blocks.append(
            "DATA KENDARAAN / LOG PEMERIKSAAN TERPILIH:\n"
            + json.dumps(vehicle_data, ensure_ascii=False, indent=2)
        )
    if relevant_docs:
        sop_text = "\n\n".join(d["content"] for d in relevant_docs)
        context_blocks.append(f"DOKUMEN SOP REFERENSI FERQUEUE:\n{sop_text}")
    history_text = _format_history_text(chat_history)
    if history_text:
        context_blocks.append(f"RIWAYAT PERCAKAPAN SEBELUMNYA:\n{history_text}")
    if has_image:
        context_blocks.append(
            "LAMPIRAN VISUAL: Sebuah foto kendaraan dilampirkan. Lakukan audit visual "
            "(verifikasi kecocokan bentuk kendaraan dengan golongan tercatat serta kondisi fisik/muatan)."
        )
    context_blocks.append(f"PERTANYAAN / INSTRUKSI PETUGAS:\n{question}")

    payload_text = "\n\n".join(context_blocks)

    try:
        from google.genai import types

        client = _get_genai_client()
        if has_image:
            contents = [
                types.Part.from_text(text=payload_text),
                types.Part.from_bytes(data=image_bytes, mime_type=image_mime or "image/jpeg"),
            ]
        else:
            contents = payload_text

        response = client.models.generate_content(
            model=LLM_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.35,
            ),
        )
        answer_text = (response.text or "").strip() or "Tidak ada jawaban yang dihasilkan model."
        return {
            "answer": answer_text,
            "sources": unique_sources,
            "used_vision": has_image,
            "used_fallback": False,
            "retrieval_mode": retrieval_mode,
        }
    except Exception as exc:
        fallback_text = _build_fallback_answer(
            question=question,
            vehicle_data=vehicle_data,
            operational_summary=operational_summary,
            relevant_docs=relevant_docs,
            has_image=has_image,
            reason=str(exc),
        )
        return {
            "answer": fallback_text,
            "sources": unique_sources,
            "used_vision": False,
            "used_fallback": True,
            "retrieval_mode": retrieval_mode,
        }


if __name__ == "__main__":
    import sys

    status = get_knowledge_status()
    print("=" * 60)
    print("FERQUEUE RAG Service — Diagnosis & Self-Test")
    print(f"LLM Model      : {LLM_MODEL}")
    print(f"Embedding Model: {EMBEDDING_MODEL}")
    print(f"Chroma DB Path : {CHROMA_DIR}")
    print(f"Dokumen SOP    : {status['total_files']} file | Chroma Chunks: {status['vector_chunks']}")
    print("=" * 60)

    test_q = sys.argv[1] if len(sys.argv) > 1 else "Berapa batas berat maksimum untuk Golongan A, B, dan C?"
    print(f"\n[1/2] Menjalankan query uji: '{test_q}'...")
    hasil = generate_answer(test_q)
    print("\n[2/2] Jawaban:")
    print("-" * 50)
    print(hasil["answer"])
    print("-" * 50)
    print(f"Mode retrieval : {hasil['retrieval_mode']} | Fallback: {hasil['used_fallback']}")
    print(f"Sumber SOP     : {', '.join(hasil['sources'])}")
