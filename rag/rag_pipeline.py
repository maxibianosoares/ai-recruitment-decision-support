from rag.retriever import retriever
from rag.context_builder import build_context

from ai_engine.services.local_llm import generate_json


DEFAULT_RESULT = {

    "answer": "",

    "sources": [],

    "confidence": 0

}


class RAGPipeline:

    def ask(

        self,

        query,

        top_k=5

    ):

        # =====================================
        # Retrieve Documents
        # =====================================

        documents = retriever.search(

            query,

            top_k

        )

        context = build_context(

            documents

        )

        # =====================================
        # Prompt
        # =====================================

        prompt = f"""

You are an expert Recruitment AI Assistant.

Answer ONLY using the Knowledge Base below.

If the answer is not contained inside the knowledge base,

reply

"I don't have enough evidence."

============================

Knowledge Base

{context}

============================

Question

{query}

============================

Return ONLY JSON

{{
    "answer":"",
    "sources":[],
    "confidence":0
}}

"""

        result = generate_json(

            prompt,

            default=DEFAULT_RESULT

        )

        return result


rag_pipeline = RAGPipeline()