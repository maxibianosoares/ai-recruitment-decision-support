# AI-Powered Civil Service Recruitment Decision Support Pilot
**Pilot Overview — Task H**

---

## Research Position (read this first)

This system is an **AI-powered recruitment decision-support system**, not an
automated recruitment decision-maker. For every candidate it produces:

- a structured candidate profile,
- requirement matching (rule-based),
- semantic skill matching,
- RAG-grounded legal/policy evidence,
- an explainable recommendation with reasoning and risks.

**The final recruitment decision remains with the authorized human
recruitment officer at all times.** The AI recommendation is evidence
presented to a human reviewer, never a decision recorded on its own — this
is enforced in the software itself (see System Overview below), not only
stated in this document.

This pilot does **not** claim the system is ready for official recruitment
decisions, does not claim it can replace recruitment officers, does not
claim CSC should deploy it, and does not claim legal compliance. It is an
**exploratory pilot / usability and feasibility study** producing
preliminary findings that require further validation.

---

## Background

The Civil Service Commission (CSC) of Timor-Leste processes recruitment
applications that involve reviewing CVs (often scanned, multilingual —
Tetum, Portuguese, Indonesian, English) against job requirements and
national civil-service regulations (e.g. Decreto-Lei 34/2008, Decreto-Lei
22/2011). This is manually intensive and time-consuming for recruitment
staff.

This project (an AI Recruitment Decision Support System, built as an
academic capstone/thesis under the KOICA-Handong MS ICT Convergence
Programme) explores whether document extraction, deterministic rule
screening, semantic skill matching, and RAG-grounded LLM reasoning can
help a human recruiter review candidates faster and with clearer,
evidence-grounded justification — while keeping the human fully in control
of the final decision.

## Problem

Manual CV screening against legal/policy requirements is slow, and written
justification for a recommendation (why this candidate, and on what basis)
is often informal or inconsistent. Scanned/low-quality documents and
multilingual CVs add further friction.

## Objectives

See `task_h_research_protocol.md` for the full list (5 pilot objectives
plus 5 supporting research questions). In summary, this pilot evaluates:
screening-time impact, whether RAG evidence helps recruiters understand
recommendations, usability/perceived usefulness, trust/confidence in AI
output, and risks/errors that must be fixed before any future, larger-scale
evaluation.

## System Overview

```
CV
 |
 v
Document Extraction (native text / Azure Document Intelligence / Tesseract OCR fallback)
 |
 v
Candidate Profile (LLM-extracted: education, skills, experience, languages, certifications)
 |
 v
Rule Screening (deterministic, graded: education/experience/language/certification/skills)
 |
 v
Semantic Skill Matching (embedding-based, deterministic)
 |
 v
RAG Evidence (retrieved from Timor-Leste civil-service regulations corpus)
 |
 v
LLM Reasoning (fused semantic assessment + explainable recommendation)
 |
 v
Explainable Recommendation  <-- shown as "Decision Support", never "Automatic Decision"
 |
 v
Human Review  <-- recruiter records Approve/Reject + mandatory reason
 |
 v
Recruiter Decision (the actual, authoritative outcome)
```

This is the system's existing, already-implemented pipeline (see
`talent/views.py`, `ai_engine/services/recruitment_pipeline.py`,
`talent/models.py: HumanDecision`) — Task H did not rebuild it. The only
Task H software change is a presentational pilot banner (see
`task_h_user_guide.md`), controlled by `PILOT_MODE` and off by default.

## Pilot Workflow

See `task_h_user_guide.md` for the step-by-step recruiter workflow.

## Participants

See `task_h_research_protocol.md` Part D. Target: CSC recruitment
officers, HR/recruitment staff, ICT/technical staff, and
supervisors/managers where relevant — whatever number is actually
available. No minimum/target count is imposed; small samples are reported
honestly as an exploratory pilot, not a national-scale validation.

## Data

Synthetic/dummy data only for this pilot (see `task_h_data_collection_template.md`
and the reused `ICT Officer` + Maria da Costa / Joao Martins / Paulo Soares
scenario in `ai_engine/management/commands/seed_professor_demo.py`). No
real candidate personal data is used unless CSC grants explicit
authorization, a data-protection procedure, and documented consent — see
`task_h_consent_information.md`.

## Evaluation

Survey (`task_h_survey.md`), semi-structured interviews
(`task_h_interview_questions.md`), screening-time observation, and an AI
error/feedback log (`task_h_data_collection_template.md`). See
`task_h_research_protocol.md` for the full methodology, including the
Condition A (human-only) vs. Condition B (AI-assisted) comparison and the
explicit limitations of this exploratory design.

## Risks

- Small/non-random participant sample -> findings are exploratory, not
  generalizable.
- gemma3:4b (local) is a smaller/faster model chosen for demo viability on
  CPU-only hardware, not the strongest available reasoning model — pilot
  results reflect this specific configuration.
- Document extraction (OCR / Azure Document Intelligence) is TASK G's
  domain — accuracy on real-world scanned CVs has not yet been empirically
  compared between providers (Azure live validation is still pending real
  credentials, see TASK G report).
- Candidate-specific legal RAG (`NEW_CANDIDATE_RAG`) is OFF by default and
  was not exercised in this pilot's default configuration.
- Using real CSC candidate data would require formal authorization/consent
  not yet in place (see `task_h_consent_information.md`).

## Limitations

This is a single-organization, small-sample, exploratory pilot using
synthetic data by default. It measures perceived usability, trust, and
explainability, and surfaces errors — it does not establish statistical
accuracy, legal compliance, or production readiness. Any accuracy/agreement
metric (precision/recall/F1) is computed **only if** a valid human expert
ground truth is actually collected during the pilot (see
`task_h_research_protocol.md` Part H) — it is never estimated or assumed in
advance.

---
*Prepared for Task H — do not cite as evidence of production readiness.*
