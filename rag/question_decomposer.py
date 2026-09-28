from ai_engine.services.local_llm import generate_json


class QuestionDecomposer:

    def decompose(self, question):

        prompt = f"""
You are a question decomposition component
for a Retrieval-Augmented Generation system.

Break the user's question into the smallest
meaningful answerable claims.

STRICT RULES:

1. Preserve the original meaning of the question.

2. Do NOT introduce new facts.

3. Do NOT create claims that are not explicitly
   requested by the user.

4. Do NOT infer background information.

5. Do NOT transform a location mentioned in the
   question into a separate question unless the
   user explicitly asks about that location.

6. Every generated claim must be answerable as
   a direct component of the original question.

7. If the question contains only one meaningful
   request, return exactly ONE claim.

8. For questions containing multiple independent
   requests, create one claim for each request.

9. NEVER drop a qualifier that restricts or specifies
   the claim. This includes (but is not limited to):
   current, currently, right now, today, as of [date],
   presently, latest, existing, exact, specific,
   precise, minimum, maximum, at least, at most, named
   persons, dates, locations, and numeric constraints.
   Dropping these words changes what the claim is
   actually asking and can cause a claim about the
   CURRENT state of a fact to be silently answered with
   HISTORICAL or general evidence instead.

10. If the question follows the pattern
    "[general/established statement] - but
    [specific question]", or joins a general statement
    and a specific question with "but", "however", or a
    similar contrast marker, you MUST generate ONE claim
    for the general statement AND a SEPARATE claim for
    the specific question -- even when the general
    statement is not itself phrased as a question. Do
    NOT collapse this pattern into a single claim that
    only captures the specific question.

Examples:

Question:
"What is the monthly salary of a civil servant
in Timor-Leste?"

Correct:
C1: What is the monthly salary of a civil servant
in Timor-Leste?

Incorrect:
C1: What is the salary of a civil servant?
C2: What is the location of Timor-Leste?

---

Question:
"Can AI rank candidates and determine their
monthly salary?"

Correct:
C1: Can AI rank candidates?
C2: Can AI determine a candidate's monthly salary?

---

Question:
"What does the AI recruitment system do and what
salary should the selected candidate receive?"

Correct:
C1: What does the AI recruitment system do?
C2: What salary should the selected candidate receive?

---

Question:
"The Chairperson can assign functions to commissioners
- but who specifically holds that position right now?"

Correct:
C1: The Chairperson can assign functions to commissioners
C2: Who specifically holds that position right now?

Incorrect:
C1: Who specifically holds the position of Chairperson?

The incorrect version above is wrong for two reasons:
it drops the general statement entirely, AND it drops
the qualifier "right now", turning a question about the
CURRENT office holder into a generic question that old,
historical evidence could wrongly appear to answer.

---

Question:
"Public servants are entitled to several types of paid
leave - but how many days of annual leave is a new
recruit entitled to in their first year?"

Correct:
C1: Public servants are entitled to several types of
paid leave
C2: How many days of annual leave is a new recruit
entitled to in their first year?

Incorrect:
C1: How many days of annual leave is a new recruit
entitled to in their first year?

Return ONLY valid JSON.

Format:

{{
    "claims": [
        {{
            "id": "C1",
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

        # ------------------------------------------
        # Safety fallback
        # ------------------------------------------

        if not claims:
            claims = [
                {
                    "id": "C1",
                    "text": question
                }
            ]

        # ------------------------------------------
        # Validate decomposition
        # ------------------------------------------

        valid_claims = []

        for index, claim in enumerate(
            claims,
            start=1
        ):

            text = claim.get(
                "text",
                ""
            ).strip()

            if not text:
                continue

            valid_claims.append({

                "id":
                    f"C{index}",

                "text":
                    text

            })

        if not valid_claims:

            valid_claims = [
                {
                    "id": "C1",
                    "text": question
                }
            ]

        return valid_claims


question_decomposer = QuestionDecomposer()