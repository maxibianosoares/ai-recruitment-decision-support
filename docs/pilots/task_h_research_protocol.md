# Research Protocol — CSC Pilot (Task H)

## Research position

AI-powered recruitment **decision-support** system. The AI provides
candidate profile, requirement matching, skill matching, rule-based
screening, semantic matching, RAG evidence, and an explainable
recommendation. **The final recruitment decision remains with the
authorized human recruitment officer.** No claim is made in this pilot
that the system is ready for official recruitment decisions.

## Main thesis research question (unchanged — Part Q)

> Does adding authoritative RAG evidence improve the reliability and
> legal/policy grounding of LLM-based candidate document screening?

This remains the primary research question (see `docs/PAPER_FRAMEWORK.md`).
It is not changed by Task H.

## Supporting pilot research questions (Task H, new)

1. How do recruitment users perceive the usefulness of AI-assisted
   candidate screening?
2. Does evidence-grounded AI output help users understand recruitment
   recommendations?
3. What types of AI errors or unsupported recommendations are observed
   during pilot use?
4. How does AI-assisted screening affect screening time?
5. What organizational, technical, and human factors should be considered
   before any potential future adoption?

## Part C — Pilot objectives

1. **Objective 1 — Speed of understanding.** Assess whether AI output
   helps recruiters understand candidate documents faster than manual
   review alone.
2. **Objective 2 — Evidence grounding.** Assess whether evidence-grounded
   RAG output helps recruiters understand the basis of a recommendation.
3. **Objective 3 — Usability.** Assess the usability and perceived
   usefulness of the system.
4. **Objective 4 — Trust.** Assess recruiters' trust/confidence in the AI
   recommendation.
5. **Objective 5 — Risk identification.** Identify risks, errors, missing
   evidence, and improvement needs before any potential future deployment.

This pilot does not attempt to prove production readiness. Any conclusion
beyond these five objectives is out of scope for this pilot.

## Part D — Participants

**Target population:** CSC recruitment officers; HR/recruitment staff;
ICT/technical staff (where relevant to reviewing technical job
postings); supervisors/managers (where relevant).

**No fixed participant count is required.** Use whatever number of
participants is actually available at CSC. If the sample is small (e.g.
fewer than 10), report the pilot explicitly as an **exploratory pilot /
usability and feasibility study**, not a national-scale or statistically
powered validation. Convenience sampling (whoever is available and willing
at CSC) is acceptable and should be stated as such in any write-up.

## Part E — Pilot data

**Default: synthetic/dummy data only.** Do not use real candidate personal
data unless ALL of the following are in place:
- proper authorization from CSC management,
- research/organizational approval,
- a documented data-protection procedure,
- a clear, limited purpose,
- secure storage,
- participant/organizational consent where applicable.

Until all of the above are confirmed, treat this as: **Required — not yet
authorized.** See `task_h_consent_information.md`.

**Preferred pilot dataset:** Dummy Job + Dummy Candidate CV(s) +
Timor-Leste recruitment/legal evidence (already in the system's RAG
corpus). Never include passport numbers, personal ID numbers, phone
numbers, home addresses, private emails, or other sensitive personal
information in pilot data.

## Part F — Pilot scenario

**Reused from the existing project** (per Task H instruction to reuse
existing candidate profiles where they fit) — the
`seed_professor_demo` management command already implements exactly the
spread this pilot needs:

```
Job: ICT Officer (Ministry of Public Administration)

Candidate A — Maria da Costa   -> qualified (5 yrs ICT/government
                                   experience, strong skill match)
Candidate B — Joao Martins     -> borderline/partial (2 yrs private-sector
                                   IT, no government experience, limited
                                   security experience)
Candidate C — Paulo Soares     -> clearly unsuitable (no ICT background,
                                   unrelated degree/experience)
```

All three are synthetic (fictional names, `@example.tl` placeholder
emails, invented CV content) — not real CSC applicants. To (re)seed this
scenario locally:

```
python manage.py seed_professor_demo --reset
```

This runs the **real** pipeline (real extraction, real rule engine, real
skill matching, real RAG, real LLM reasoning via whichever `LLM_PROVIDER`
is configured) — no score is hand-typed. No new scenario-building code was
written for Task H; this existing command is simply the designated pilot
scenario.

## Part G — Comparison conditions

### Condition A — Traditional / human-only review
Recruiter sees: CV + Job Description only, then gives their own
assessment and records the time taken.

### Condition B — AI decision support
Recruiter sees: CV + Job Description + AI Candidate Profile + Skill
Matching + Rule Screening + RAG Evidence + Explainable Recommendation,
then gives their own assessment and records the time taken.

Neither condition is labeled "better" in advance. The pilot only measures
the observed difference; conclusions are drawn after data is analyzed, not
before.

## Part H — Measurements

### Efficiency
- Screening time per candidate (Condition A vs. B).
- Perceived workload (survey item).

### Accuracy / Agreement
Computed **only if** a valid ground truth or expert assessment is actually
collected during the pilot (e.g. a senior recruiter's independent
assessment used as reference). If no valid ground truth exists, do **not**
compute or report accuracy/precision/recall/F1 — state explicitly that
these could not be computed for this pilot round.

### Explainability
- Evidence usefulness, evidence clarity, ability to understand the
  recommendation (survey Section D).

### Usability
- Ease of use, ease of learning, system usefulness (survey Section B/C).

### Trust
- Confidence in AI output, willingness to use it as decision support,
  perceived reliability (survey Section E).

### Human oversight
- Whether the recruiter understood the final decision stayed human
  (survey Section F).
- Whether the recruiter could identify when the AI was uncertain or wrong
  (survey Section F + error log).

## Part J — Pre/post measurement (if practical)

```
Before AI:
  Recruiter reviews candidate (Condition A)
  -> records screening time
  -> records assessment

After AI:
  Recruiter reviews a different but comparable candidate (Condition B)
  -> records screening time
  -> records assessment
```

Use **different candidates** (not the identical CV/job pair) across
Condition A and B for the same participant where practical, to avoid an
obvious learning-bias confound. If showing the same candidate twice is
unavoidable (e.g. very limited candidate pool), document this explicitly
as a limitation of that session's data, not a hidden assumption.

If a proper controlled pre/post design is not practical with the
participants and time available, treat the whole pilot as **exploratory**
and state this limitation plainly in any resulting write-up — do not
imply a controlled experiment took place if it did not.

## Data collection instruments

- Survey: `task_h_survey.md` (Likert 1-5 + open-ended).
- Interview protocol: `task_h_interview_questions.md`.
- Screening-time / assessment template and AI error log:
  `task_h_data_collection_template.md`.
- Consent/participant information: `task_h_consent_information.md`.

## Reporting rules (Part R — do not overclaim)

Any report or thesis chapter drawing on this pilot's data must NOT
conclude: "AI is accurate enough for official recruitment", "AI can
replace recruitment officers", "CSC should deploy this system", or "the
system is legally compliant." Use instead: pilot evaluation, exploratory
evidence, decision-support prototype, preliminary findings, requires
further validation, human oversight remains necessary.
