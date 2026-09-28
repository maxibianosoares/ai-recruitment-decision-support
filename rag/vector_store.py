import os
import re
import faiss
import pickle

from ai_engine.services.embedding_engine import (
    MODEL_NAME,
    DEFAULT_MODEL_NAME,
)


# =====================================================================
# CROSS-LINGUAL RETRIEVAL FIX (2026-09-23) -- index path now depends on
# which embedding model built it. When EMBEDDING_MODEL is unset (the
# default), the path is IDENTICAL to before this change -- the existing
# production index at knowledge_base/vector_store/ is never touched,
# moved, or overwritten. Only when EMBEDDING_MODEL is explicitly set to
# something else does a new, separate directory get used, so an old
# index and a new (e.g. multilingual) index can coexist side by side
# for benchmarking and rollback (switch the env var back = rollback).
# =====================================================================

def _slugify_model_name(name):
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()


if MODEL_NAME == DEFAULT_MODEL_NAME:
    _VECTOR_STORE_DIR = "knowledge_base/vector_store"
else:
    _VECTOR_STORE_DIR = (
        f"knowledge_base/vector_store_{_slugify_model_name(MODEL_NAME)}"
    )

VECTOR_PATH = f"{_VECTOR_STORE_DIR}/index.faiss"

METADATA_PATH = f"{_VECTOR_STORE_DIR}/metadata.pkl"



def save_vector_store(
        index,
        metadata
):

    os.makedirs(
        _VECTOR_STORE_DIR,
        exist_ok=True
    )


    faiss.write_index(
        index,
        VECTOR_PATH
    )


    with open(
        METADATA_PATH,
        "wb"
    ) as f:

        pickle.dump(
            metadata,
            f
        )



def load_vector_store():

    index = faiss.read_index(
        VECTOR_PATH
    )


    with open(
        METADATA_PATH,
        "rb"
    ) as f:

        metadata = pickle.load(f)


    return index, metadata