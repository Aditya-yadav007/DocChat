import os
import sys
import threading

# Ensure project root is on sys.path for module imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(override=True)

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from sentence_transformers import SentenceTransformer
from src.data_loader import load_all_documents
from src.vectorstore import FaissVectorStore
from src.search import RAGSearch

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# ── Directories ───────────────────────────────────────────────
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
FAISS_DIR = os.path.join(PROJECT_ROOT, 'faiss_store')
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'csv', 'xlsx', 'docx', 'json'}

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Shared model (loaded ONCE at startup) ─────────────────────
print("[STARTUP] Loading SentenceTransformer model (one-time)...")
SHARED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
print("[STARTUP] Model loaded.")

# ── Global state ──────────────────────────────────────────────
rag_instance = None
chat_history = []
index_status = {"busy": False, "message": "Ready"}
_lock = threading.Lock()


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _init_rag():
    """Create RAGSearch using shared model. Only loads FAISS index + LLM (fast)."""
    global rag_instance
    load_dotenv(override=True)
    faiss_path = os.path.join(FAISS_DIR, 'faiss.index')
    if os.path.exists(faiss_path):
        try:
            rag_instance = RAGSearch(persist_dir=FAISS_DIR, shared_model=SHARED_MODEL)
            print("[INFO] RAGSearch initialized successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to initialize RAGSearch: {e}")
            rag_instance = None


def _incremental_index(file_paths):
    """Index ONLY the new files — append to existing FAISS index."""
    global rag_instance, index_status
    try:
        index_status = {"busy": True, "message": "Loading new documents..."}

        # Load only the new files
        from pathlib import Path
        from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
        from langchain_community.document_loaders import Docx2txtLoader, JSONLoader
        from langchain_community.document_loaders.excel import UnstructuredExcelLoader

        new_docs = []
        for fp in file_paths:
            ext = fp.rsplit('.', 1)[-1].lower()
            try:
                if ext == 'pdf':
                    new_docs.extend(PyPDFLoader(fp).load())
                elif ext == 'txt':
                    new_docs.extend(TextLoader(fp).load())
                elif ext == 'csv':
                    new_docs.extend(CSVLoader(fp).load())
                elif ext == 'xlsx':
                    new_docs.extend(UnstructuredExcelLoader(fp).load())
                elif ext == 'docx':
                    new_docs.extend(Docx2txtLoader(fp).load())
                elif ext == 'json':
                    new_docs.extend(JSONLoader(fp).load())
            except Exception as e:
                print(f"[ERROR] Failed to load {fp}: {e}")

        if not new_docs:
            index_status = {"busy": False, "message": "No documents could be parsed"}
            return

        index_status["message"] = f"Embedding {len(new_docs)} document(s)..."

        # If we have an existing index, add incrementally
        faiss_path = os.path.join(FAISS_DIR, 'faiss.index')
        store = FaissVectorStore(FAISS_DIR, shared_model=SHARED_MODEL)
        if os.path.exists(faiss_path):
            store.load()
            store.add_documents(new_docs)  # incremental!
        else:
            store.build_from_documents(new_docs)

        # Reload RAGSearch with updated index
        rag_instance = RAGSearch(persist_dir=FAISS_DIR, shared_model=SHARED_MODEL)
        index_status = {"busy": False, "message": "Ready"}
        print(f"[INFO] Incremental index complete. Total vectors: {store.index.ntotal}")

    except Exception as e:
        print(f"[ERROR] Indexing failed: {e}")
        index_status = {"busy": False, "message": f"Error: {e}"}


def _full_rebuild():
    """Full rebuild — used only for delete operations."""
    global rag_instance, index_status
    try:
        index_status = {"busy": True, "message": "Rebuilding index..."}
        docs = load_all_documents(DATA_DIR)
        if not docs:
            # No documents left, clear index
            for f in ['faiss.index', 'metadata.pkl']:
                p = os.path.join(FAISS_DIR, f)
                if os.path.exists(p):
                    os.remove(p)
            rag_instance = None
            index_status = {"busy": False, "message": "Ready (no documents)"}
            return

        store = FaissVectorStore(FAISS_DIR, shared_model=SHARED_MODEL)
        store.build_from_documents(docs)
        rag_instance = RAGSearch(persist_dir=FAISS_DIR, shared_model=SHARED_MODEL)
        index_status = {"busy": False, "message": "Ready"}
    except Exception as e:
        print(f"[ERROR] Rebuild failed: {e}")
        index_status = {"busy": False, "message": f"Error: {e}"}


def _scan_documents():
    """Return list of all documents found under data/."""
    docs = []
    for root, _dirs, files in os.walk(DATA_DIR):
        for f in files:
            ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
            if ext in ALLOWED_EXTENSIONS:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, DATA_DIR)
                docs.append({
                    "name": f,
                    "path": rel,
                    "size": os.path.getsize(full),
                    "type": ext.upper(),
                })
    return docs


# ── Routes ────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/index-status', methods=['GET'])
def get_index_status():
    return jsonify(index_status)


@app.route('/documents', methods=['GET'])
def list_documents():
    return jsonify({"status": "ok", "documents": _scan_documents()})


@app.route('/upload', methods=['POST'])
def upload():
    if index_status["busy"]:
        return jsonify({"status": "error", "message": "Indexing in progress, please wait."}), 409

    if 'files' not in request.files:
        return jsonify({"status": "error", "message": "No files provided"}), 400

    files = request.files.getlist('files')
    saved_paths = []
    uploaded_names = []
    for f in files:
        if f.filename and _allowed(f.filename):
            name = secure_filename(f.filename)
            path = os.path.join(UPLOAD_DIR, name)
            f.save(path)
            saved_paths.append(path)
            uploaded_names.append(name)

    if not saved_paths:
        return jsonify({"status": "error", "message": "No valid files uploaded"}), 400

    # Start incremental indexing in background thread
    thread = threading.Thread(target=_incremental_index, args=(saved_paths,), daemon=True)
    thread.start()

    return jsonify({
        "status": "ok",
        "files": uploaded_names,
        "message": f"Uploaded {len(uploaded_names)} file(s). Indexing in background..."
    })


@app.route('/delete-document', methods=['POST'])
def delete_document():
    if index_status["busy"]:
        return jsonify({"status": "error", "message": "Indexing in progress, please wait."}), 409

    data = request.get_json()
    rel_path = data.get('path', '')
    full_path = os.path.normpath(os.path.join(DATA_DIR, rel_path))
    if not full_path.startswith(os.path.normpath(DATA_DIR)):
        return jsonify({"status": "error", "message": "Invalid path"}), 400
    if not os.path.isfile(full_path):
        return jsonify({"status": "error", "message": "File not found"}), 404

    os.remove(full_path)

    # Full rebuild in background (FAISS doesn't support deletion)
    thread = threading.Thread(target=_full_rebuild, daemon=True)
    thread.start()

    return jsonify({"status": "ok", "message": "File deleted. Rebuilding index..."})


@app.route('/query', methods=['POST'])
def query():
    if index_status["busy"]:
        return jsonify({"status": "error", "message": "Index is being built. Please wait a moment."}), 503

    data = request.get_json()
    user_query = data.get('query', '').strip()
    if not user_query:
        return jsonify({"status": "error", "message": "Missing query"}), 400

    if rag_instance is None:
        _init_rag()
        if rag_instance is None:
            return jsonify({"status": "error", "message": "No documents indexed yet or LLM initialization failed. Please check your .env settings."}), 400

    try:
        result = rag_instance.search_and_summarize(user_query, top_k=3)
        chat_history.append({"role": "user", "content": user_query, "sources": []})
        chat_history.append({"role": "assistant", "content": result["answer"], "sources": result["sources"]})
        return jsonify({"status": "ok", "answer": result["answer"], "sources": result["sources"]})
    except Exception as e:
        print(f"[ERROR] Query processing failed: {e}")
        return jsonify({"status": "error", "message": f"AI response failed: {str(e)}"}), 500


@app.route('/history', methods=['GET'])
def get_history():
    return jsonify({"status": "ok", "history": chat_history})


@app.route('/clear-history', methods=['POST'])
def clear_history():
    chat_history.clear()
    return jsonify({"status": "ok"})


# ── Startup ───────────────────────────────────────────────────
if __name__ == '__main__':
    _init_rag()
    app.run(host='0.0.0.0', port=5000, debug=True)
