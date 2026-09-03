from collections import Counter

from rag.retriever import retriever


QUERIES = [

    # ---------------------------------------------------------
    # AI RECRUITMENT POLICY
    # ---------------------------------------------------------

    "Can AI replace human recruiter?",

    "What information should every AI recommendation provide?",

    "Can AI rank candidates?",


    # ---------------------------------------------------------
    # CIVIL SERVICE COMMISSION LAW
    # ---------------------------------------------------------

    "What are the legal powers and responsibilities of the Civil Service Commission?",

    "What is the authority of the Civil Service Commission?",


    # ---------------------------------------------------------
    # COMPETENCY FRAMEWORK
    # ---------------------------------------------------------

    "What competencies are required for civil servants?",

    "What is the competency framework for civil servants?",


    # ---------------------------------------------------------
    # POLICY
    # ---------------------------------------------------------

    "What are the principles of public administration policy?",

    "What does the government policy establish?",


    # ---------------------------------------------------------
    # RECRUITMENT LAW
    # ---------------------------------------------------------

    "What are the legal requirements for civil service recruitment?",

    "What are the recruitment selection requirements?",


    # ---------------------------------------------------------
    # TRAINING / DEVELOPMENT
    # ---------------------------------------------------------

    "What are the rules for training and professional development of civil servants?",

    "How are civil servants trained and developed?"

]


def run_test():

    print()
    print("=" * 80)
    print("RETRIEVAL DISTRIBUTION TEST")
    print("=" * 80)

    source_counter = Counter()

    for query in QUERIES:

        print()
        print("-" * 80)
        print("QUERY:")
        print(query)
        print("-" * 80)

        results = retriever.search(
            query,
            top_k=5
        )

        if not results:

            print("NO RESULTS")
            continue

        for i, result in enumerate(results, start=1):

            source = result.get(
                "source",
                "UNKNOWN"
            )

            score = result.get(
                "score",
                0
            )

            text = result.get(
                "text",
                ""
            )

            source_counter[source] += 1

            print(
                f"{i}. "
                f"{source} "
                f"| score={score:.4f}"
            )

            print(
                f"   {text[:180]}"
                .replace("\n", " ")
            )

    print()
    print("=" * 80)
    print("SOURCE DISTRIBUTION")
    print("=" * 80)

    for source, count in source_counter.most_common():

        print(
            f"{source:<60} {count}"
        )

    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":

    run_test()