import os
import threading

from sentence_transformers import SentenceTransformer

# =====================================================================
# CROSS-LINGUAL RETRIEVAL FIX (2026-09-23) -- evidence-based root cause:
# knowledge base is predominantly Portuguese legal/policy text, but
# queries are frequently English. The English-only default below
# (BAAI/bge-base-en-v1.5) was confirmed via live audit to rank the
# correct Portuguese evidence chunk (policy.pdf, "Artigo 14.o --
# Requisitos") at #22 out of the full corpus for a representative
# English query, well outside any retrieval top_k in use -- so the
# claim-level evidence check never saw it.
#
# EMBEDDING_MODEL lets this be swapped to a multilingual model without
# touching any calling code (rag/retriever.py, rag/build_index.py) --
# same pattern already used for ONLINE_GEMMA_MODEL in model_config.py.
# Default is UNCHANGED so production behavior does not shift until a
# new index is built and benchmarked and EMBEDDING_MODEL is
# deliberately set.
# =====================================================================

DEFAULT_MODEL_NAME = "BAAI/bge-base-en-v1.5"

MODEL_NAME = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)


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
        self._model_name = MODEL_NAME
        # Task B/C fix: Skill Matching and the Rule Engine now call
        # encode() from two parallel threads (recruitment_pipeline STEP 2).
        # Without a lock both threads can load the model at the same time
        # on the first request, which makes one of them fail or cache a
        # broken model. The lock makes only one thread load it.
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode(self, text):
        return self._get_model().encode(
            text,
            normalize_embeddings=True
        )


embedding_engine = EmbeddingEngine()