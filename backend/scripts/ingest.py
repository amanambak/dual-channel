import asyncio
import logging
import os
import sys
from pathlib import Path

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader, UnstructuredMarkdownLoader
from app.services.rag_service import RAGService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main(data_dir: str):
    rag_service = RAGService()
    
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
    args = parser.parse_args()
    
    # Adjust path if running from backend/scripts
    data_path = args.dir
    if not os.path.isabs(data_path):
        data_path = os.path.abspath(os.path.join(os.getcwd(), data_path))
    
    asyncio.run(main(data_path))
