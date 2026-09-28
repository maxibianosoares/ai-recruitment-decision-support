import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.retriever import retriever

QUERIES = [
    ("ELIGIBILITY (EN)", "What are the eligibility requirements to become a civil servant?"),
    ("ELIGIBILITY (PT)", "Quais sao os requisitos de elegibilidade para ingressar na funcao publica?"),
    ("QUALIFICATIONS (EN)", "What academic qualifications are required for civil service positions?"),
    ("QUALIFICATIONS (PT)", "Que qualificacoes academicas sao exigidas para os cargos da funcao publica?"),
    ("RECRUITMENT/SELECTION (EN)", "How are candidates selected and recruited into the civil service?"),
    ("RECRUITMENT/SELECTION (PT)", "Como sao selecionados e recrutados os candidatos para a funcao publica?"),
    ("PROFESSIONAL EXPERIENCE (EN)", "What professional experience is required for promotion in the civil service?"),
    ("MERIT (EN)", "How is merit evaluated in civil service recruitment?"),
    ("MEDICAL EXAMINATION (EN)", "Is a medical examination required for civil service appointment?"),
    ("CSC ROLE (EN)", "What is the role of the Civil Service Commission?"),
    ("DELIBERATELY UNSUPPORTED (EN)", "What is the minimum wage for private sector workers in Timor-Leste?"),
]

for label, query in QUERIES:
    print()
    print("=" * 70)
    print(f"[{label}]")
    print(f"QUERY: {query}")
    print("-" * 70)

    results = retriever.search(query, top_k=5)

    for rank, item in enumerate(results, start=1):
        source = Path(item["source"]).name
        score = item["score"]
        excerpt = item["text"][:160].replace("\n", " ")
        print(f"  #{rank} score={score:.4f} source={source}")
        print(f"      excerpt: {excerpt}...")

print()
print("=" * 70)
print("DONE")
print("=" * 70)