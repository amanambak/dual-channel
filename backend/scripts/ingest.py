import asyncio
import logging
import os
import sys
from pathlib import Path

# Add backend root to sys.path relative to this script, not cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from app.core.config import get_settings
from app.services.rag_service import RAGService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_chunk_batch(label: str, docs: list[Document]) -> None:
    """Log a chunk batch without requiring RAGService initialization."""
    logger.info("%s chunks=%d", label, len(docs))
    for index, doc in enumerate(docs, start=1):
        metadata = doc.metadata or {}
        source = os.path.basename(metadata.get("source", "unknown"))
        page = metadata.get("page", "unknown")
        logger.info(
            "%s chunk %d: source=%s page=%s content=%r",
            label,
            index,
            source,
            page,
            doc.page_content or "",
        )


def build_preview_chunks(documents: list[Document]) -> list[Document]:
    """Build deterministic chunks without embeddings for local preview mode."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_documents(documents)


async def main(data_dir: str, show_chunks: bool = False, show_all_chunks: bool = False):
    # Define loaders for different file types
    loaders = {
        ".pdf": PyPDFLoader,
        ".txt": TextLoader,
        ".md": UnstructuredMarkdownLoader,
    }
    
    documents = []
    for ext, loader_cls in loaders.items():
        loader = DirectoryLoader(
            data_dir,
            glob=f"**/*{ext}",
            loader_cls=loader_cls,
            show_progress=True
        )
        try:
            loaded_docs = loader.load()
            documents.extend(loaded_docs)
            logger.info(f"Loaded {len(loaded_docs)} documents with extension {ext}")
        except Exception as e:
            logger.warning(f"Failed to load documents with extension {ext}: {e}")

    if not documents:
        logger.error("No documents found to ingest.")
        return

    if show_all_chunks:
        settings = get_settings()
        if not settings.llm_api_key:
            logger.error(
                "Semantic and BM25 chunk views require GEMINI_API_KEY or GOOGLE_API_KEY."
            )
            return

        rag_service = RAGService()
        recursive_chunks, semantic_chunks, final_chunks = rag_service.chunk_documents_with_stages(documents)
        log_chunk_batch("final", final_chunks)
        await rag_service.add_documents(final_chunks)
        log_chunk_batch("bm25", rag_service.bm25_docs)
        return

    if show_chunks:
        chunks = build_preview_chunks(documents)
        logger.info(
            "Created %d preview chunks from %d documents without requiring embeddings.",
            len(chunks),
            len(documents),
        )
        log_chunk_batch("final", chunks)
        return

    rag_service = RAGService()

    # Semantic Chunking
    chunks = rag_service.chunk_documents(documents)
    logger.info(f"Created {len(chunks)} semantic chunks from {len(documents)} documents.")

    # Ingest into Vector DB
    await rag_service.add_documents(chunks)
    logger.info("Ingestion complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest documents into the RAG system.")
    parser.add_argument("--dir", type=str, default="../data/raw", help="Directory containing documents to ingest.")
    parser.add_argument("--reset", action="store_true", help="Delete the existing Chroma collection before ingesting.")
    parser.add_argument(
        "--show-chunks",
        action="store_true",
        help="Log every final chunk created during ingestion.",
    )
    parser.add_argument(
        "--show-all-chunks",
        action="store_true",
        help="Log recursive, semantic, final, and BM25 chunks. Requires Gemini credentials.",
    )
    args = parser.parse_args()
    
    data_path = args.dir
    if not os.path.isabs(data_path):
        data_path = os.path.abspath(os.path.join(BACKEND_ROOT, data_path))

    if args.reset:
        service = RAGService()
        service.reset_collection()

    asyncio.run(
        main(
            data_path,
            show_chunks=args.show_chunks,
            show_all_chunks=args.show_all_chunks,
        )
    )
