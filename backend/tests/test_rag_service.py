import logging
import os
import sys
import unittest

from langchain_core.documents import Document

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.services.rag_service import RAGService


class RagServiceChunkLoggingTest(unittest.TestCase):
    def test_log_chunk_batch_logs_each_chunk_content(self):
        service = RAGService.__new__(RAGService)
        service.logger = logging.getLogger("app.services.rag_service.test")

        docs = [
            Document(page_content="First chunk body", metadata={"source": "/tmp/a.txt", "page": 1}),
            Document(page_content="Second chunk body", metadata={"source": "/tmp/b.txt", "page": 2}),
        ]

        with self.assertLogs("app.services.rag_service.test", level="INFO") as captured:
            service.log_chunk_batch("final", docs)

        output = "\n".join(captured.output)
        self.assertIn("final chunk 1", output)
        self.assertIn("final chunk 2", output)
        self.assertIn("First chunk body", output)
        self.assertIn("Second chunk body", output)

    def test_chunk_documents_with_stages_returns_all_chunk_sets(self):
        class DummySplitter:
            def __init__(self, output):
                self.output = output

            def split_documents(self, documents):
                return self.output

        service = RAGService.__new__(RAGService)
        service.logger = logging.getLogger("app.services.rag_service.test")

        source_docs = [
            Document(page_content="source doc", metadata={"source": "/tmp/source.txt", "page": 1}),
        ]
        recursive_docs = [
            Document(page_content="recursive one", metadata={"source": "/tmp/source.txt", "page": 1}),
            Document(page_content="recursive two", metadata={"source": "/tmp/source.txt", "page": 1}),
        ]
        semantic_docs = [
            Document(page_content="semantic one", metadata={"source": "/tmp/source.txt", "page": 1}),
        ]
        service.recursive_chunker = DummySplitter(recursive_docs)
        service.chunker = DummySplitter(semantic_docs)

        recursive, semantic, final = service.chunk_documents_with_stages(source_docs)

        self.assertEqual(recursive, recursive_docs)
        self.assertEqual(semantic, semantic_docs)
        self.assertEqual(final, recursive_docs)


if __name__ == "__main__":
    unittest.main()
