from pathlib import Path

import fitz

from docx import Document


class DocumentLoader:

    def load(self, file_path):

        path = Path(file_path)

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._load_pdf(path)

        elif suffix == ".docx":
            return self._load_docx(path)

        elif suffix == ".txt":
            return path.read_text(
                encoding="utf-8",
                errors="ignore"
            )

        elif suffix == ".md":
            return path.read_text(
                encoding="utf-8",
                errors="ignore"
            )

        raise ValueError(
            f"Unsupported file type : {suffix}"
        )

    def _load_pdf(self, path):

        doc = fitz.open(path)

        text = []

        for page in doc:

            text.append(
                page.get_text()
            )

        doc.close()

        return "\n".join(text)

    def _load_docx(self, path):

        doc = Document(path)

        return "\n".join(

            p.text

            for p in doc.paragraphs
        )


document_loader = DocumentLoader()