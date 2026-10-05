import os
from src.data_loader import load_all_documents
from src.vectorstore import FaissVectorStore
from src.search import RAGSearch

# Example usage
if __name__ == "__main__":
    
    docs = load_all_documents("data")
    store = FaissVectorStore("faiss_store")
    faiss_path = os.path.join("faiss_store", "faiss.index")
    if os.path.exists(faiss_path):
        store.load()
    else:
        store.build_from_documents(docs)
    #print(store.query("What is attention mechanism?", top_k=3))
    rag_search = RAGSearch()
    query = "What is octal permissions?"
    result = rag_search.search_and_summarize(query, top_k=3)
    print("Answer:", result["answer"])
    print("Sources:", result["sources"])