import os
import sys
import unittest

from langchain_core.documents import Document

# Add backend root to sys.path
sys.path.append(os.path.join(os.getcwd(), "backend"))

import scripts.ingest as ingest


class IngestPreviewTest(unittest.TestCase):
    def test_build_preview_chunks_splits_without_embeddings(self):
        docs = [
            Document(page_content="A" * 700, metadata={"source": "/tmp/a.txt", "page": 1}),
        ]

        chunks = ingest.build_preview_chunks(docs)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunk.page_content for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
