from ai_engine.services.embedding_engine import embedding_engine

class RAGEmbedding:

    def encode(

        self,

        texts

    ):

        if isinstance(

            texts,

            str

        ):

            texts = [texts]

        return embedding_engine.encode(

            texts,

            normalize_embeddings=True
        )


embedding = RAGEmbedding()