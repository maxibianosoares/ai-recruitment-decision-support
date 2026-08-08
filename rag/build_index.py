from .document_loader import document_loader
from .text_splitter import text_splitter
from .embedding import embedding_engine
from .vector_store import save_vector_store
import numpy as np

import faiss



def build_index(path):


    text = document_loader.load(
        path
    )


    chunks = text_splitter.split(
        text
    )

    if not chunks:
        raise ValueError("No text chunks generated.")


    embeddings = []

    for chunk in chunks:

        vector = embedding_engine.encode(chunk)

        embeddings.append(vector)

    # Convert ke NumPy Array
    embeddings = np.array(
        embeddings,
        dtype="float32"
    )

    # Ambil dimensi embedding
    dimension = embeddings.shape[1]

    # Buat index
    index = faiss.IndexFlatL2(
        dimension
    )

    # Tambahkan seluruh embedding ke FAISS
    index.add(
        embeddings
    )

    if embeddings.shape[0] == 0:
        raise ValueError("No embeddings generated.")

    index = faiss.IndexFlatL2(
        dimension
    )

    print(type(embeddings))
    print(embeddings.shape)

    index.add(
        embeddings
    )


    metadata=[]


    for i,chunk in enumerate(chunks):

        metadata.append({

            "id":i,

            "text":chunk,

            "source":path

        })


    save_vector_store(
        index,
        metadata
    )


    print(
        "Vector database created"
    )