def build_context(documents):

    context_parts = []


    for document in documents:

        source = document.get(
            "source",
            "Unknown"
        )

        text = document.get(
            "text",
            ""
        )


        context_parts.append(

            f"""
Source:
{source}

Evidence:
{text}
"""

        )


    return "\n\n".join(
        context_parts
    )