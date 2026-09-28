import hashlib
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


def _content_hash(path):
    """MD5 of the raw file bytes -- used only to detect two files on
    disk that are byte-identical copies of each other under different
    filenames (confirmed case, 2026-09-23: a Unicode filename-encoding
    artifact produced a second copy of Regime-Formacao-Desenvolvimento
    .pdf under a mangled name, e.g. 'Regime-Formac#U0327a#U0303o-...').
    This does NOT delete or modify the source PDF on disk -- it only
    decides which files feed the index build, so a duplicate document
    does not silently double its own weight in retrieval.
    """

    return hashlib.md5(path.read_bytes()).hexdigest()


def build_index():

    # =====================================
    # 1. Find all supported documents
    # =====================================

    all_candidate_files = sorted(

        [

            path

            for path in DOCUMENTS_PATH.iterdir()

            if path.is_file()
            and path.suffix.lower()
            in [".pdf", ".docx", ".txt", ".md"]

        ]

    )

    if not all_candidate_files:

        raise ValueError(
            "No supported documents found."
        )

    # =====================================
    # 1a. Tie-break preference for byte-identical duplicates -- purely
    #     a citation-display preference (which filename gets kept as
    #     the indexed/cited copy), does NOT affect which content gets
    #     indexed or delete/modify any source file on disk.
    #
    #     Two rules, in order:
    #       (i)  a cleanly-encoded filename beats a mangled one
    #            (e.g. "Formac#U0327a..." is a Unicode-normalization
    #            artifact of "Formação...").
    #       (ii) a filename that was already part of the production
    #            knowledge base beats a newly-added one, so adding new
    #            documents can never silently change which filename is
    #            shown as the citation source for pre-existing content.
    #            Confirmed case (2026-09-23): the newly-uploaded
    #            "Law_7_2009.pdf" is byte-identical to the pre-existing
    #            "civil_service_commission_law.pdf.pdf" -- without this
    #            rule, plain alphabetical sort ("L" < "c") would have
    #            made the new file win the tie-break and silently
    #            renamed the citation source for existing content.
    # =====================================

    def _looks_mangled(name):
        return "#U0" in name

    _PRE_EXISTING_FILENAMES = {
        "Regime-Formação-Desenvolvimento.pdf",
        "Regime-Formac#U0327a#U0303o-Desenvolvimento.pdf",
        "ai_recruitment_policy.pdf",
        "civil_service_commission_law.pdf.pdf",
        "competency_framework.pdf",
        "policy.pdf",
        "recruitment_law.pdf.pdf",
    }

    def _is_new_addition(name):
        return name not in _PRE_EXISTING_FILENAMES

    all_candidate_files = sorted(
        all_candidate_files,
        key=lambda p: (
            _looks_mangled(p.name),
            _is_new_addition(p.name),
            p.name,
        ),
    )

    # =====================================
    # 1b. Skip byte-identical duplicate files
    #     (same content, different filename) -- source files are
    #     never touched, only excluded from THIS build's input.
    # =====================================

    files = []

    seen_hashes = {}

    duplicates_skipped = []

    for path in all_candidate_files:

        file_hash = _content_hash(path)

        if file_hash in seen_hashes:

            duplicates_skipped.append(
                (path.name, seen_hashes[file_hash])
            )

            continue

        seen_hashes[file_hash] = path.name

        files.append(path)

    print()
    print("=" * 60)
    print("BUILDING RAG VECTOR INDEX")
    print("=" * 60)
    print(
        f"Documents found on disk : {len(all_candidate_files)}"
    )
    print(
        f"Duplicate files skipped : {len(duplicates_skipped)}"
    )

    for dup_name, original_name in duplicates_skipped:

        print(
            f"  SKIPPED '{dup_name}' "
            f"(byte-identical to '{original_name}')"
        )

    print(
        f"Documents to index       : {len(files)}"
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