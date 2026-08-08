from sentence_transformers import SentenceTransformer

class EmbeddingEngine:

    def __init__(self):

        self.model = SentenceTransformer(
            "BAAI/bge-base-en-v1.5"
        )

    def encode(self, text):

        return self.model.encode(
            text,
            normalize_embeddings=True
        )


embedding_engine = EmbeddingEngine()