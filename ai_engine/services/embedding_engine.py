from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-base-en-v1.5"


class EmbeddingEngine:
    """
    Lazy-loading wrapper around the sentence-transformers embedding
    model used by RAG retrieval (rag/retriever.py).

    IMPORTANT (deployment memory fix, 2026-09-13): the model used to
    load in __init__, which ran immediately at import time -- meaning
    it loaded into memory the moment Django started, before serving
    even a single request, for every page (Login, Dashboard, Jobs)
    whether or not that request ever touches RAG. On Render's free
    tier (512MB RAM total), this alone was enough to exceed the
    memory limit and crash the worker (confirmed via Render's own
    "Ran out of memory (used over 512MB)" event log), producing a 502
    Bad Gateway on every request, including ones that never needed
    the embedding model at all.

    Fix: load the model on first actual use (first call to .encode())
    instead of at construction time. The public interface
    (embedding_engine.encode(text)) is unchanged, so no other file
    (rag/retriever.py, etc.) needs to change. Pages that never call
    RAG retrieval (Login, Dashboard, Job list, Apply) now never load
    this model into memory at all.
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    def encode(self, text):
        return self._get_model().encode(
            text,
            normalize_embeddings=True
        )


embedding_engine = EmbeddingEngine()