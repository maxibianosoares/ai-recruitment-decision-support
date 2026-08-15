BENCHMARK_QUESTIONS = [

    # =========================================================
    # SUPPORTED
    # =========================================================

    {
        "id": "S01",
        "question": "Can AI replace human recruiter?",
        "expected": "supported",
        "reference_answer":
            "AI shall assist HR officers but shall never replace final human decisions."
    },

    {
        "id": "S02",
        "question":
            "What information should every AI recommendation provide?",
        "expected": "supported",
        "reference_answer":
            "Overall Score, Matching Reason, Strengths, Weaknesses, Skill Gap Analysis, and Confidence Score."
    },

    {
        "id": "S03",
        "question":
            "What is the purpose of the AI recruitment policy?",
        "expected": "supported",
        "reference_answer":
            "To ensure AI-assisted recruitment is fair, transparent, accountable, explainable, and merit-based."
    },


    # =========================================================
    # PARTIALLY SUPPORTED
    # =========================================================

    {
        "id": "P01",
        "question":
            "What does the AI recruitment system do and what salary should the selected candidate receive?",
        "expected": "partially_supported",

        "supported_parts": [
            "The AI recruitment system assists with resume screening, candidate ranking, skill matching, interview recommendation, and recruitment analytics."
        ],

        "unsupported_parts": [
            "The salary of the selected candidate is not specified in the knowledge base."
        ]
    },


    {
        "id": "P02",
        "question":
            "Can AI rank candidates and determine their monthly salary?",
        "expected": "partially_supported",

        "supported_parts": [
            "AI can assist with candidate ranking."
        ],

        "unsupported_parts": [
            "The policy does not specify that AI determines monthly salary."
        ]
    },


    # =========================================================
    # UNSUPPORTED
    # =========================================================

    {
        "id": "U01",
        "question":
            "What is the monthly salary of a civil servant in Timor-Leste?",
        "expected": "unsupported",

        "reference_answer":
            "The knowledge base does not provide information about civil servant salaries."
    },

    {
        "id": "U02",
        "question":
            "Who is the current President of Timor-Leste?",
        "expected": "unsupported",

        "reference_answer":
            "The knowledge base does not provide information about the current President of Timor-Leste."
    }

]