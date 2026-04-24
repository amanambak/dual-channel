import asyncio
import os
import sys

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

async def test_init():
    try:
        from app.services.rag_service import RAGService
        from app.core.config import get_settings
        
        settings = get_settings()
        if not settings.llm_api_key:
            print("WARNING: GEMINI_API_KEY / GOOGLE_API_KEY not set. Embedding test will likely fail.")
        
        print(f"Initializing RAGService with model: {settings.embedding_model}")
        rag = RAGService()
        print("RAGService initialized successfully.")
        
        # Simple embedding test if key is present
        if settings.llm_api_key:
            print("Testing embeddings...")
            embedding = rag.get_embeddings().embed_query("This is a test.")
            print(f"Embedding successful. Dimension: {len(embedding)}")
        
    except Exception as e:
        print(f"Initialization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_init())
