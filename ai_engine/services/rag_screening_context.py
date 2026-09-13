"""
Knowledge-Infused Screening -- RAG query for legal/policy context
relevant to evaluating candidates for a given job.

IMPORTANT (read before citing this in the thesis): this is a
PER-JOB signal, not a per-candidate one. The query below references
only the job title, not anything from a specific candidate's CV, so
retrieval -- and therefore the resulting evidence and score -- is
effectively constant across every candidate who applies to the same
job. That is by design (see recruitment_pipeline.py for why this is
computed once per job and cached, not once per application), but it
means this module answers "what does policy say about this type of
role", not "how well does this specific person comply with policy".
Describe it that way if asked.

PHASE 20 (F2) NOTE -- simplified from the Phase 1-19 baseline:
    Baseline: rag_pipeline.ask() -- the full conversational pipeline
    (question decomposition -> per-claim retrieval+verification ->
    generation -> a separate LLM groundedness re-check). That is
    4-6 sequential LLM calls, appropriate for a free-form question
    typed by a human in the AI Assistant, where hallucination risk
    on an open-ended query is high and must be checked from several
    angles.

    This module's query is different in kind: it is a single,
    system-generated, single-intent question ("what does policy
    require for job title X"), not an open-ended human question.
    Decomposing it into sub-claims and re-verifying each one buys
    little extra safety here, at a large latency cost (measured at
    up to several minutes per job creation on this hardware).

    Simplified pipeline used here instead:
        retriever.search()   -- direct FAISS retrieval, no LLM
        EvidenceGate.evaluate() -- deterministic scoring, no LLM
        ONE generate_json() call -- grounded answer + citation,
            explicitly instructed not to use outside knowledge
    That is 1 LLM call instead of 4-6.

    The AI Assistant's conversational pipeline (rag/rag_pipeline.py,
    rag/question_decomposer.py, rag/evidence_coverage.py,
    rag/groundedness.py) is completely untouched by this change --
    those are Phase 19's temporal guard / hallucination-resistance
    mechanisms for free-form user questions and remain on the full
    pipeline.

    Honest trade-off: this path's "grounded" flag reflects retrieval
    relevance clearing the same threshold used elsewhere
    (EvidenceGate), not an independent post-hoc re-check of the
    generated text against the evidence the way groundedness.py
    does for the AI Assistant. State this distinction if asked --
    it is a deliberate, documented difference for a lower-stakes,
    single-intent, system-generated query, not an oversight.
"""

from rag.retriever import retriever
from rag.evidence_gate import EvidenceGate
from rag.rag_pipeline import humanize_source
from ai_engine.services.llm_service import generate_json


DEFAULT_RAG_CONTEXT = {
    "query": "",
    "answer": "",
    "evidence": [],
    "best_evidence_score": 0,
    "grounded": False,
    "error": None
}

TOP_K = 3


def get_rag_screening_context(job_title):
    """
    Runs one simplified RAG query for the given job title and
    returns a plain dict -- never raises, so a RAG/Ollama failure
    degrades gracefully instead of blocking job creation.

    Returns the same shape as the Phase 1-19 baseline (see
    DEFAULT_RAG_CONTEXT), so recruitment_pipeline.py and every
    template that reads application.ai_rag_context / job.ai_rag_context
    need no changes.
    """

    job_title = (job_title or "this position").strip()

    query = (
        f"What are the official legal requirements and evaluation "
        f"criteria for civil service recruitment for a {job_title} "
        f"position?"
    )

    context = dict(DEFAULT_RAG_CONTEXT)
    context["query"] = query

    try:
        documents = retriever.search(query, top_k=TOP_K)
    except Exception as e:
        context["error"] = f"Retrieval failed: {e}"
        return context

    if not documents:
        context["answer"] = "I don't have enough evidence."
        return context

    gate_result = EvidenceGate.evaluate(documents)

    evidence = [
        {
            "document": humanize_source(doc.get("source")),
            "chunk_id": doc.get("id"),
            "score": round(float(doc.get("score", 0)), 4),
            "excerpt": (doc.get("text") or "")[:280]
        }
        for doc in documents
    ]

    context["evidence"] = evidence
    context["best_evidence_score"] = gate_result.get("score", 0)
    context["grounded"] = gate_result.get("status") != "unsupported"

    if gate_result.get("status") == "unsupported":
        context["answer"] = "I don't have enough evidence."
        return context

    evidence_text = "\n".join(
        f"- ({item['document']}) {item['excerpt']}"
        for item in evidence
    )

    prompt = f"""You are a civil service recruitment policy assistant.

The retrieved evidence below may be written in Portuguese, English,
Tetum, or Indonesian. Read it in its original language and understand
its meaning -- do not skip or misread evidence just because it is not in
English, and do not silently mistranslate legal/policy meaning.

Evidence takes priority over anything you already "know" about Timor-Leste
law -- rely only on the retrieved evidence below, not on general or prior
knowledge, even if you believe you know the answer.

Answer the question below using ONLY the retrieved evidence provided.
Do not use outside knowledge. If the evidence does not fully answer
the question, say so explicitly rather than filling the gap yourself.

Question
{query}

Retrieved Evidence
{evidence_text}

Return ONLY valid JSON:

{{
    "answer": ""
}}
"""

    try:

        result = generate_json(
            prompt,
            default={"answer": "I don't have enough evidence."}
        )

        context["answer"] = result.get(
            "answer", "I don't have enough evidence."
        )

    except Exception as e:
        context["error"] = f"Generation failed: {e}"
        context["answer"] = "I don't have enough evidence."

    return context
