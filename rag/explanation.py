def build_evidence(documents):

    evidence = []


    for document in documents:

        evidence.append({

            "document": document.get(
                "source"
            ),

            "chunk_id": document.get(
                "id"
            ),

            "score": document.get(
                "score"
            ),

            "evidence": document.get(
                "text"
            )

        })


    return evidence