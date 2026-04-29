import asyncio
import os
import sys

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

async def test_hybrid():
    from app.services.rag_service import RAGService
    from app.core.config import get_settings
    
    settings = get_settings()
    print(f"Initializing RAGService for hybrid test...")
    rag = RAGService()
    
    query = "What are the eligibility criteria for home loan?"
    print(f"\nTesting Query: '{query}'")
    
    print("\n--- Semantic Search Results ---")
    semantic_docs = await rag.similarity_search(query, k=3)
    for i, doc in enumerate(semantic_docs):
        print(f"{i+1}. {doc.page_content[:100]}...")

    print("\n--- Hybrid Search Results ---")
    hybrid_docs = await rag.hybrid_search(query, k=3)
    for i, doc in enumerate(hybrid_docs):
        print(f"{i+1}. {doc.page_content[:100]}...")

    # Test keyword boosting
    keyword_query = "PAN Card Aadhaar"
    print(f"\nTesting Keyword Query: '{keyword_query}'")
    hybrid_docs_kw = await rag.hybrid_search(keyword_query, k=2)
    for i, doc in enumerate(hybrid_docs_kw):
        print(f"{i+1}. {doc.page_content[:100]}...")

if __name__ == "__main__":
    asyncio.run(test_hybrid())
