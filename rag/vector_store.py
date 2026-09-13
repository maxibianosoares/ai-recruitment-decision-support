import os
import faiss
import pickle


VECTOR_PATH = "knowledge_base/vector_store/index.faiss"

METADATA_PATH = "knowledge_base/vector_store/metadata.pkl"



def save_vector_store(
        index,
        metadata
):

    os.makedirs(
        "knowledge_base/vector_store",
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