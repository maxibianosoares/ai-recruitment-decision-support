from pathlib import Path

from .document_loader import document_loader
from .text_splitter import text_splitter
from .embedding import embedding_engine
from .vector_store import save_vector_store

import numpy as np
import faiss


DOCUMENTS_PATH = Path(
    "knowledge_base/documents"
)


def build_index():

    # =====================================
    # 1. Find all supported documents
    # =====================================

    files = sorted(

        [

            path

            for path in DOCUMENTS_PATH.iterdir()

            if path.is_file()
            and path.suffix.lower()
            in [".pdf", ".docx", ".txt", ".md"]

        ]

    )

    if not files:

        raise ValueError(
            "No supported documents found."
        )

    print()
    print("=" * 60)
    print("BUILDING RAG VECTOR INDEX")
    print("=" * 60)
    print(
        f"Documents found: {len(files)}"
    )
    print()

    # =====================================
    # 2. Load and split ALL documents
    # =====================================

    all_chunks = []

    metadata = []

    chunk_id = 0

    for path in files:

        print(
            f"Loading: {path.name}"
        )

        text = document_loader.load(
            path
        )

        if not text.strip():

            print(
                f"WARNING: No text extracted from {path.name}"
            )

            continue

        chunks = text_splitter.split(
            text
        )

        print(
            f"  Chunks: {len(chunks)}"
        )

        for chunk in chunks:

            all_chunks.append(
                chunk
            )

            metadata.append({

                "id": chunk_id,

                "text": chunk,

                "source": str(path)

            })

            chunk_id += 1

    # =====================================
    # 3. Validate chunks
    # =====================================

    if not all_chunks:

        raise ValueError(
            "No chunks generated."
        )

    print()
    print(
        f"Total chunks: {len(all_chunks)}"
    )

    # =====================================
    # 4. Generate embeddings
    # =====================================

    embeddings = []

    for i, chunk in enumerate(
        all_chunks
    ):

        vector = embedding_engine.encode(
            chunk
        )

        embeddings.append(
            vector
        )

        if (i + 1) % 10 == 0:

            print(
                f"Embedded: {i + 1}/{len(all_chunks)}"
            )

    # =====================================
    # 5. Convert to NumPy
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
    # 6. Normalize embeddings
    #
    # Cosine similarity:
    # normalized vectors + Inner Product
    # =====================================

    faiss.normalize_L2(
        embeddings
    )

    # =====================================
    # 7. Create FAISS index
    # =====================================

    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(
        dimension
    )

    # =====================================
    # 8. Add ALL embeddings
    # =====================================

    index.add(
        embeddings
    )

    # =====================================
    # 9. Save vector store
    # =====================================

    save_vector_store(
        index,
        metadata
    )

    # =====================================
    # 10. Summary
    # =====================================

    print()
    print("=" * 60)
    print("VECTOR DATABASE CREATED")
    print("=" * 60)

    print(
        f"Documents : {len(files)}"
    )

    print(
        f"Chunks    : {len(all_chunks)}"
    )

    print(
        f"Vectors   : {index.ntotal}"
    )

    print(
        f"Dimension : {dimension}"
    )

    print("=" * 60)

    # =====================================
    # 11. Document distribution
    # =====================================

    print()
    print("DOCUMENT DISTRIBUTION")
    print("-" * 60)

    for path in files:

        count = sum(

            1

            for item in metadata

            if item["source"]
            == str(path)

        )

        print(
            f"{path.name:<45} {count} chunks"
        )

    print()


if __name__ == "__main__":

    build_index()