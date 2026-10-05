import os
import sys

# Configure UTF-8 encoding for Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.data_loader import load_all_documents
from src.vectorstore import FaissVectorStore
from src.search import RAGSearch

# Example usage
if __name__ == "__main__":
    faiss_path = os.path.join("faiss_store", "faiss.index")
    if not os.path.exists(faiss_path):
        docs = load_all_documents("data")
        store = FaissVectorStore("faiss_store")
        store.build_from_documents(docs)

    rag_search = RAGSearch()
    query = "What is octal permissions?"
    result = rag_search.search_and_summarize(query, top_k=3)
    print("Answer:", result["answer"])
    print("Sources:", result["sources"])