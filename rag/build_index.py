from .document_loader import document_loader
from .text_splitter import text_splitter
from .embedding import embedding_engine
from .vector_store import save_vector_store

import numpy as np
import faiss


def build_index(path):

    # =====================================
    # Load Document
    # =====================================

    text = document_loader.load(path)

    if not text:
        raise ValueError(
            "Document contains no text."
        )

    # =====================================
    # Split Document
    # =====================================

    chunks = text_splitter.split(text)

    if not chunks:
        raise ValueError(
            "No text chunks generated."
        )

    # =====================================
    # Generate Embeddings
    # =====================================

    embeddings = []

    for chunk in chunks:

        vector = embedding_engine.encode(
            chunk
        )

        embeddings.append(vector)

    # =====================================
    # Convert to NumPy
    # =====================================

    embeddings = np.array(
        embeddings,
        dtype="float32"
    )

    if embeddings.shape[0] == 0:
        raise ValueError(
            "No embeddings generated."
        )

    # =====================================
    # Normalize Embeddings
    #
    # Required for Cosine Similarity
    # =====================================

    faiss.normalize_L2(
        embeddings
    )

    # =====================================
    # Get Embedding Dimension
    # =====================================

    dimension = embeddings.shape[1]

    # =====================================
    # Create FAISS Index
    #
    # Inner Product + normalized vectors
    # = Cosine Similarity
    # =====================================

    index = faiss.IndexFlatIP(
        dimension
    )

    # =====================================
    # Add Embeddings
    # =====================================

    index.add(
        embeddings
    )

    # =====================================
    # Metadata
    # =====================================

    metadata = []

    for i, chunk in enumerate(chunks):

        metadata.append({

            "id": i,

            "text": chunk,

            "source": path

        })

    # =====================================
    # Save Vector Store
    # =====================================

    save_vector_store(
        index,
        metadata
    )

    print(
        "Vector database created successfully."
    )

    print(
        f"Documents: {len(chunks)}"
    )

    print(
        f"Embedding dimension: {dimension}"
    )

    print(
        f"FAISS vectors: {index.ntotal}"
    )