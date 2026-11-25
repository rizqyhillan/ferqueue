import rag_service


def ingest_documents():
    files = rag_service.list_knowledge_files()
    print(f"Memproses {len(files)} dokumen SOP dari {rag_service.KNOWLEDGE_DIR}...")
    result = rag_service.reindex_knowledge()
    if result.get("warning"):
        print(f"[WARNING] {result['warning']}")
    else:
        print(
            f"Sukses menyimpan {result['indexed_chunks']} chunks dari "
            f"{result['indexed_files']} dokumen ke {rag_service.CHROMA_DIR}"
        )


if __name__ == "__main__":
    ingest_documents()
