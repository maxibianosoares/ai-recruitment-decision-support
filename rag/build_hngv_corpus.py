"""Backward-compatible wrapper: `python -m rag.build_hngv_corpus` builds the HNGV staging corpus
with the generic builder (rag/build_vacancy_corpus.py).

`vacancy_doc(v, general)` is kept for callers/tests that build one vacancy's text in memory.
"""
import json
from pathlib import Path

from rag.build_vacancy_corpus import main, vacancy_lines

ROOT = Path(__file__).resolve().parents[1]
HNGV_PACK = ROOT / "knowledge_base" / "vacancy_rules" / "hngv_2026_vacancy_rules.json"


def vacancy_doc(v, general=None, pack=None):
    pack = dict(pack) if pack else json.loads(HNGV_PACK.read_text(encoding="utf-8"))
    if general is not None:
        pack["general_regime_reference"] = general
    return "\n".join(vacancy_lines(v, pack)) + "\n"


if __name__ == "__main__":
    main(["--src", str(HNGV_PACK),
          "--out", str(ROOT / "knowledge_base" / "documents_staging" / "hngv_2026"),
          "--prefix", "hngv_2026", "--all"])
