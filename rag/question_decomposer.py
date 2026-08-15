from ai_engine.services.local_llm import generate_json


class QuestionDecomposer:

    def decompose(self, question):

        prompt = f"""
You are a question decomposition component
for a Retrieval-Augmented Generation system.

Break the question into the smallest meaningful
independent claims that can be separately verified
against a knowledge base.

IMPORTANT:

1. Each claim must represent one independently
   answerable factual request.

2. If the question contains "and", consider whether
   it contains multiple independent claims.

3. Do NOT answer the question.

4. Do NOT add information that is not present
   in the original question.

5. Preserve the meaning of the original question.

6. Each claim must be independently retrievable.

Return ONLY valid JSON.

Format:

{{
    "claims": [
        {{
            "id": "C1",
            "text": ""
        }},
        {{
            "id": "C2",
            "text": ""
        }}
    ]
}}

Question:
{question}
"""

        result = generate_json(

            prompt,

            default={
                "claims": [
                    {
                        "id": "C1",
                        "text": question
                    }
                ]
            }
        )

        claims = result.get(
            "claims",
            []
        )

        if not claims:

            claims = [
                {
                    "id": "C1",
                    "text": question
                }
            ]

        return claims


question_decomposer = QuestionDecomposer()