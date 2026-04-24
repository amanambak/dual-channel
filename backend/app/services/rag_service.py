import logging
import os
import re
from typing import Dict, List, Optional

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from rank_bm25 import BM25Okapi

from app.core.config import get_settings

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self.settings = get_settings()
        self.embeddings = self._init_embeddings()
        self.vector_store = self._init_vector_store()
        self.chunker = self._init_chunker()
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

    def get_vector_store(self) -> Chroma:
        return self.vector_store

    def get_embeddings(self) -> GoogleGenerativeAIEmbeddings:
        return self.embeddings

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents into semantic chunks."""
        logger.info(f"Splitting {len(documents)} documents into semantic chunks...")
        return self.chunker.split_documents(documents)

    async def add_documents(self, documents: List[Document]):
        """Add documents to the vector store and refresh BM25."""
        await self.vector_store.aadd_documents(documents)
        self._refresh_bm25()
        logger.info(f"Added {len(documents)} chunks and refreshed BM25 index.")

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

    async def similarity_search(self, query: str, k: int = None) -> List[Document]:
        """Perform a simple semantic similarity search."""
        top_k = k or self.settings.rag_top_k
        return await self.vector_store.asimilarity_search(query, k=top_k)

    async def hybrid_search(self, query: str, k: int = None) -> List[Document]:
        """Perform hybrid search combining Semantic and BM25."""
        top_k = k or self.settings.rag_top_k
        
        # 1. Semantic Search
        vector_results = await self.vector_store.asimilarity_search(query, k=20)
        
        # 2. BM25 Search
        bm25_results = []
        if self.bm25:
            tokenized_query = self._tokenize(query)
            # get_top_n returns the actual documents if we pass them
            bm25_results = self.bm25.get_top_n(tokenized_query, self.bm25_docs, n=20)
        
        # 3. Fuse Results
        fused_results = self.reciprocal_rank_fusion(vector_results, bm25_results)
        
        return fused_results[:top_k]
