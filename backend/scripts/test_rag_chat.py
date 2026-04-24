import asyncio
import os
import sys

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

async def test_rag_chat():
    from app.llm.service import LLMService
    from app.core.config import get_settings
    
    settings = get_settings()
    print("Initializing LLMService (with RAG)...")
    llm = LLMService()
    
    queries = [
        "What is the minimum CIBIL score required for a home loan?",
        "What documents do I need for income proof?",
        "Tell me about the application process step by step."
    ]
    
    for query in queries:
        print(f"\nUser Query: {query}")
        print("Assistant Reply:")
        reply = await llm.generate_chat_reply(query)
        print(reply)
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(test_rag_chat())
