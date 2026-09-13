from .vector_store import load_vector_store
from .embedding import embedding_engine


class Retriever:

    def __init__(self):

        self.index, self.metadata = load_vector_store()


    def search(
        self,
        query,
        top_k=5
    ):

        query_vector = embedding_engine.encode(query)

        query_vector = query_vector.reshape(
            1,
            -1
        )


        distances, indices = self.index.search(
            query_vector,
            top_k
        )


        results = []


        for distance, idx in zip(
            distances[0],
            indices[0]
        ):

            if idx == -1:
                continue


            item = self.metadata[idx].copy()


            item["score"] = float(distance)


            results.append(item)


        return results


retriever = Retriever()