import logging
import os
import re
import time
from typing import Dict, List, Optional

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from typing import List
import asyncio
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self.settings = get_settings()
        self.embeddings = self._init_embeddings()
        self.vector_store = self._init_vector_store()
        self.chunker = self._init_chunker()
        self.recursive_chunker = self._init_recursive_chunker()
        self.bm25: Optional[BM25Okapi] = None
        self.bm25_docs: List[Document] = []
        self._refresh_bm25()

    def _init_embeddings(self) -> GoogleGenerativeAIEmbeddings:
        """Initialize Google Generative AI embeddings."""
        return GoogleGenerativeAIEmbeddings(
            model=self.settings.embedding_model,
            google_api_key=self.settings.llm_api_key,
        )

    def _init_vector_store(self) -> Chroma:
        """Initialize Chroma vector store with persistence."""
        persist_directory = self.settings.chroma_db_path
        if not os.path.isabs(persist_directory):
            persist_directory = os.path.join(os.getcwd(), persist_directory)

        return Chroma(
            collection_name="loan_policies",
            embedding_function=self.embeddings,
            persist_directory=persist_directory,
        )

    def _init_chunker(self) -> SemanticChunker:
        """Initialize Semantic Chunker."""
        return SemanticChunker(
            self.embeddings,
            breakpoint_threshold_type="percentile",
        )

    def _init_recursive_chunker(self) -> RecursiveCharacterTextSplitter:
        """Initialize a deterministic fallback splitter for policy docs."""
        return RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenizer for BM25."""
        return re.findall(r"\w+", text.lower())

    def _refresh_bm25(self):
        """Build/Refresh the BM25 index from current ChromaDB documents."""
        try:
            # Retrieve all documents from Chroma
            data = self.vector_store.get()
            docs = []
            for content, metadata in zip(data["documents"], data["metadatas"]):
                docs.append(Document(page_content=content, metadata=metadata))
            
            if not docs:
                logger.info("No documents found in ChromaDB. BM25 index not initialized.")
                return

            self.bm25_docs = docs
            tokenized_corpus = [self._tokenize(doc.page_content) for doc in docs]
            self.bm25 = BM25Okapi(tokenized_corpus)
            logger.info(f"BM25 index built with {len(docs)} documents.")
        except Exception as e:
            logger.error(f"Failed to refresh BM25 index: {e}")

    def _count_total_chunks(self) -> int:
        """Count all chunks currently stored in the vector store."""
        try:
            collection = getattr(self.vector_store, "_collection", None)
            if collection is not None and hasattr(collection, "count"):
                return int(collection.count())

            data = self.vector_store.get()
            ids = data.get("ids") or []
            if ids:
                return len(ids)
            documents = data.get("documents") or []
            return len(documents)
        except Exception:
            try:
                data = self.vector_store.get()
                ids = data.get("ids") or []
                if ids:
                    return len(ids)
                documents = data.get("documents") or []
                return len(documents)
            except Exception as exc:
                logger.debug("Failed to count total chunks: %s", exc)
                return 0

    def get_vector_store(self) -> Chroma:
        return self.vector_store

    def get_embeddings(self) -> GoogleGenerativeAIEmbeddings:
        return self.embeddings

    def chunk_documents_with_stages(
        self, documents: List[Document]
    ) -> tuple[List[Document], List[Document], List[Document]]:
        """Split documents and return recursive, semantic, and final chunk sets."""
        logger.info("Splitting %d documents into recursive chunks...", len(documents))
        recursive_chunks = self.recursive_chunker.split_documents(documents)
        logger.info(
            "Recursive splitter created %d chunks from %d documents.",
            len(recursive_chunks),
            len(documents),
        )
        self.log_chunk_batch("recursive", recursive_chunks)

        if not recursive_chunks:
            return [], [], []

        semantic_chunks = self.chunker.split_documents(recursive_chunks)
        logger.info(
            "Semantic splitter created %d chunks from %d recursive chunks.",
            len(semantic_chunks),
            len(recursive_chunks),
        )
        self.log_chunk_batch("semantic", semantic_chunks)

        final_chunks = semantic_chunks if len(semantic_chunks) > len(recursive_chunks) else recursive_chunks
        return recursive_chunks, semantic_chunks, final_chunks

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents into smaller search chunks."""
        _, _, final_chunks = self.chunk_documents_with_stages(documents)
        return final_chunks

    async def add_documents(self, documents: List[Document]):
        """Add documents to the vector store and refresh BM25."""
        await self.vector_store.aadd_documents(documents)
        self._refresh_bm25()
        logger.info(f"Added {len(documents)} chunks and refreshed BM25 index.")

    def reset_collection(self) -> None:
        """Delete and recreate the underlying Chroma collection."""
        try:
            self.vector_store.delete_collection()
        except Exception as exc:
            logger.warning("Failed to delete existing Chroma collection: %s", exc)
        self.vector_store = self._init_vector_store()
        self.bm25 = None
        self.bm25_docs = []
        logger.info("Recreated empty RAG vector store and cleared BM25 cache.")

    def reciprocal_rank_fusion(
        self, 
        vector_results: List[Document], 
        bm25_results: List[Document], 
        k: int = 60
    ) -> List[Document]:
        """Combine two ranked lists using Reciprocal Rank Fusion."""
        fused_scores: Dict[str, float] = {}
        doc_map: Dict[str, Document] = {}

        def _process_list(results: List[Document]):
            for rank, doc in enumerate(results):
                # Use page_content as key for simplicity, assuming unique enough for this scope
                doc_id = doc.page_content 
                doc_map[doc_id] = doc
                if doc_id not in fused_scores:
                    fused_scores[doc_id] = 0.0
                fused_scores[doc_id] += 1.0 / (k + rank + 1)

        _process_list(vector_results)
        _process_list(bm25_results)

        # Sort by fused score
        sorted_docs = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_map[doc_id] for doc_id, _ in sorted_docs]

    @staticmethod
    def _doc_preview(doc: Document, limit: int = 160) -> str:
        text = re.sub(r"\s+", " ", doc.page_content or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def log_chunk_batch(self, label: str, docs: List[Document]) -> None:
        """Log every chunk in a batch with its full content."""
        logger_to_use = getattr(self, "logger", logger)
        logger_to_use.info("%s chunks=%d", label, len(docs))
        for index, doc in enumerate(docs, start=1):
            metadata = doc.metadata or {}
            source = os.path.basename(metadata.get("source", "unknown"))
            page = metadata.get("page", "unknown")
            logger_to_use.info(
                "%s chunk %d: source=%s page=%s content=%r",
                label,
                index,
                source,
                page,
                doc.page_content or "",
            )

    def log_retrieved_chunks(self, query: str, docs: List[Document], elapsed_ms: float) -> None:
        """Log the chunks fetched before the LLM call."""
        logger.info(
            "RAG retrieval finished: query=%r chunks=%d elapsed_ms=%.2f",
            query,
            len(docs),
            elapsed_ms,
        )
        for index, doc in enumerate(docs, start=1):
            source = doc.metadata.get("source", "unknown") if doc.metadata else "unknown"
            logger.info(
                "RAG chunk %d: source=%s preview=%r",
                index,
                os.path.basename(source),
                self._doc_preview(doc),
            )

    def log_result_set(
        self,
        label: str,
        query: str,
        docs: List[Document],
        elapsed_ms: float,
        *,
        limit: int = 5,
    ) -> None:
        """Log a ranked result set with a short preview of each document."""
        logger.info(
            "%s results: query=%r count=%d elapsed_ms=%.2f",
            label,
            query,
            len(docs),
            elapsed_ms,
        )
        for index, doc in enumerate(docs[:limit], start=1):
            source = doc.metadata.get("source", "unknown") if doc.metadata else "unknown"
            logger.info(
                "%s result %d: source=%s preview=%r",
                label,
                index,
                os.path.basename(source),
                self._doc_preview(doc),
            )
        if len(docs) > limit:
            logger.info("%s results truncated: showing %d of %d", label, limit, len(docs))

    async def similarity_search(self, query: str, k: int = None) -> List[Document]:
        """Perform a simple semantic similarity search."""
        top_k = k or self.settings.rag_top_k
        start_time = time.perf_counter()
        results = await self.vector_store.asimilarity_search(query, k=top_k)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.log_result_set("SIMILARITY", query, results, elapsed_ms)
        return results

    async def hybrid_search(self, query: str, k: int = None) -> List[Document]:
        """Perform hybrid search combining Semantic and BM25 in parallel."""
        top_k = k or self.settings.rag_top_k
        start_time = time.perf_counter()
        total_chunks = self._count_total_chunks()
        logger.info("RAG corpus size: total_chunks=%d query=%r", total_chunks, query)
        
        # 1. Start Semantic Search as a background task (Network call)
        vector_start = time.perf_counter()
        vector_task = asyncio.create_task(self.vector_store.asimilarity_search(query, k=20))
        
        # 2. Run BM25 Search (CPU-bound, local)
        # We do this while the vector task is running
        bm25_start = time.perf_counter()
        bm25_results = []
        if self.bm25:
            tokenized_query = self._tokenize(query)
            bm25_results = self.bm25.get_top_n(tokenized_query, self.bm25_docs, n=20)
        bm25_elapsed_ms = (time.perf_counter() - bm25_start) * 1000.0
        self.log_result_set("BM25", query, bm25_results, bm25_elapsed_ms)
        
        # 3. Wait for the Semantic Search to complete
        vector_results = await vector_task
        vector_elapsed_ms = (time.perf_counter() - vector_start) * 1000.0
        self.log_result_set("SIMILARITY", query, vector_results, vector_elapsed_ms)
        
        # 4. Fuse Results
        fused_results = self.reciprocal_rank_fusion(vector_results, bm25_results)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "RAG hybrid search completed: query=%r total_chunks=%d vector=%d bm25=%d fused=%d elapsed_ms=%.2f",
            query,
            total_chunks,
            len(vector_results),
            len(bm25_results),
            len(fused_results),
            elapsed_ms,
        )
        
        return fused_results[:top_k]
