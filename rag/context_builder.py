def build_context(results):

    contexts = []

    for item in results:

        contexts.append(

            f"""
Source:
{item["source"]}

Content:
{item["text"]}
"""
        )

    return "\n\n".join(contexts)