import re


class TextSplitter:

    def __init__(

        self,

        chunk_size=700,

        overlap=100

    ):

        self.chunk_size = chunk_size

        self.overlap = overlap

    def split(

        self,

        text

    ):

        sentences = re.split(

            r'(?<=[.!?])\s+',

            text

        )

        chunks = []

        current = ""

        for sentence in sentences:

            if len(current) + len(sentence) < self.chunk_size:

                current += " " + sentence

            else:

                chunks.append(

                    current.strip()

                )

                current = current[-self.overlap:] + " " + sentence

        if current:

            chunks.append(

                current.strip()
            )

        return chunks


text_splitter = TextSplitter()