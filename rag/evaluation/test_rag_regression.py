from rag.rag_pipeline import rag_pipeline


TEST_CASES = [

    {
        "id": "S01",
        "question": "Can AI replace human recruiter?",
        "expected": "supported"
    },

    {
        "id": "S02",
        "question": "What information should every AI recommendation provide?",
        "expected": "supported"
    },

    {
        "id": "S03",
        "question": "What is the purpose of the AI recruitment policy?",
        "expected": "supported"
    },

    {
        "id": "P01",
        "question": (
            "What does the AI recruitment system do "
            "and what salary should the selected candidate receive?"
        ),
        "expected": "partially_supported"
    },

    {
        "id": "P02",
        "question": (
            "Can AI rank candidates "
            "and determine their monthly salary?"
        ),
        "expected": "partially_supported"
    },

    {
        "id": "U01",
        "question": (
            "What is the monthly salary of a civil servant "
            "in Timor-Leste?"
        ),
        "expected": "unsupported"
    },

    {
        "id": "U02",
        "question": "Who is the current President of Timor-Leste?",
        "expected": "unsupported"
    }
]


def print_separator():
    print("\n" + "=" * 70)


def main():

    results = []

    print_separator()
    print("RAG REGRESSION TEST")
    print("7 TEST CASES")
    print_separator()

    for test in TEST_CASES:

        print(f"\nID       : {test['id']}")
        print(f"QUESTION : {test['question']}")
        print(f"EXPECTED : {test['expected']}")

        try:

            result = rag_pipeline.ask(
                test["question"]
            )

            actual = result.get(
                "evidence_status",
                "unknown"
            )

            coverage = result.get(
                "coverage",
                0
            )

            grounded = result.get(
                "grounded",
                False
            )

            confidence = result.get(
                "confidence",
                0
            )

            correct = (
                actual == test["expected"]
            )

            results.append({

                "id":
                    test["id"],

                "expected":
                    test["expected"],

                "actual":
                    actual,

                "coverage":
                    coverage,

                "confidence":
                    confidence,

                "grounded":
                    grounded,

                "correct":
                    correct

            })

            print(
                f"ACTUAL   : {actual}"
            )

            print(
                f"COVERAGE : {coverage:.4f}"
            )

            print(
                f"CONFIDENCE: {confidence:.2f}"
            )

            print(
                f"GROUNDED : {grounded}"
            )

            print(
                f"CORRECT  : {correct}"
            )

            print_separator()

        except Exception as e:

            print(
                f"ERROR    : {e}"
            )

            results.append({

                "id":
                    test["id"],

                "expected":
                    test["expected"],

                "actual":
                    "error",

                "coverage":
                    0,

                "confidence":
                    0,

                "grounded":
                    False,

                "correct":
                    False

            })

            print_separator()

    # ======================================================
    # SUMMARY
    # ======================================================

    total = len(results)

    correct_count = sum(
        1
        for r in results
        if r["correct"]
    )

    grounded_count = sum(
        1
        for r in results
        if r["grounded"]
    )

    accuracy = (
        correct_count / total
        if total
        else 0
    )

    grounded_rate = (
        grounded_count / total
        if total
        else 0
    )

    print("\n")
    print("=" * 70)
    print("FINAL REGRESSION TEST RESULT")
    print("=" * 70)

    print(
        f"Total Tests       : {total}"
    )

    print(
        f"Correct           : {correct_count}"
    )

    print(
        f"Incorrect         : {total - correct_count}"
    )

    print(
        f"Accuracy          : {accuracy:.2%}"
    )

    print(
        f"Grounded          : {grounded_count}"
    )

    print(
        f"Grounded Rate     : {grounded_rate:.2%}"
    )

    print("\nDETAILS")
    print("-" * 70)

    for r in results:

        status = (
            "PASS"
            if r["correct"]
            else "FAIL"
        )

        print(
            f"{r['id']:4} | "
            f"EXPECTED={r['expected']:20} | "
            f"ACTUAL={r['actual']:20} | "
            f"{status}"
        )

    print("-" * 70)

    if correct_count == total:

        print("RESULT: 7/7 PASS")
        print("RAG regression checkpoint PASSED.")

    else:

        print(
            f"RESULT: {correct_count}/{total} PASS"
        )

        print(
            "RAG regression checkpoint FAILED."
        )


if __name__ == "__main__":
    main()