import os
from typing import Optional
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from src.vectorstore import FaissVectorStore
from langchain_groq import ChatGroq

load_dotenv(override=True)

class RAGSearch:
    def __init__(self, persist_dir: str = "faiss_store", embedding_model: str = "all-MiniLM-L6-v2",
                 llm_model: str = None, shared_model: Optional[SentenceTransformer] = None):
        self.vectorstore = FaissVectorStore(persist_dir, embedding_model, shared_model=shared_model)
        # Load or build vectorstore
        faiss_path = os.path.join(persist_dir, "faiss.index")
        meta_path = os.path.join(persist_dir, "metadata.pkl")
        if not (os.path.exists(faiss_path) and os.path.exists(meta_path)):
            from src.data_loader import load_all_documents
            docs = load_all_documents("data")
            self.vectorstore.build_from_documents(docs)
        else:
            self.vectorstore.load()

        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file or environment variables."
            )

        if not llm_model:
            llm_model = os.getenv("GROQ_MODEL_NAME")
        if not llm_model:
            raise RuntimeError(
                "GROQ_MODEL_NAME is not set. Set it to a Groq model you have access to, "
                "for example GEMMA 2 or any available model in your account."
            )

        self.llm = ChatGroq(groq_api_key=groq_api_key, model_name=llm_model)
        print(f"[INFO] Groq LLM initialized: {llm_model}")

    def search_and_summarize(self, query: str, top_k: int = 5) -> dict:
        """Return {"answer": str, "sources": list[str]}."""
        results = self.vectorstore.query(query, top_k=top_k)
        texts = [r["metadata"].get("text", "") for r in results if r["metadata"]]

        # Deduplicated source filenames
        seen = set()
        sources = []
        for r in results:
            if r["metadata"] and r["metadata"].get("source"):
                name = os.path.basename(r["metadata"]["source"])
                if name not in seen:
                    sources.append(name)
                    seen.add(name)

        context = "\n\n".join(texts)
        if not context:
            return {"answer": "No relevant documents found.", "sources": []}

        prompt = (
            f"You are a knowledgeable and clear AI assistant. Based on the provided context, "
            f"answer the user's question in a clear, well-structured, and easily understandable format.\n\n"
            f"Guidelines for your response:\n"
            f"- Structure your explanation logically with clear headings (## or ###) and short paragraphs.\n"
            f"- Use bullet points and bold text for key concepts to improve readability.\n"
            f"- When explaining numbers, permissions, comparisons, or parameters, use clean Markdown tables.\n"
            f"- Format code, commands, or technical syntax inside fenced code blocks with language tags (e.g. ```bash, ```python).\n"
            f"- Include a brief summary or key takeaway section at the end if the topic is complex.\n"
            f"- Base your answer strictly on the context provided. If the context does not contain enough information to fully answer, state clearly what is known and what is missing.\n\n"
            f"Question:\n{query}\n\n"
            f"Context:\n{context}\n\n"
            f"Answer:"
        )
        response = self.llm.invoke([prompt])
        return {"answer": response.content, "sources": sources}

# Example usage
if __name__ == "__main__":
    rag_search = RAGSearch()
    query = "What is attention mechanism?"
    result = rag_search.search_and_summarize(query, top_k=3)
    print("Answer:", result["answer"])
    print("Sources:", result["sources"])