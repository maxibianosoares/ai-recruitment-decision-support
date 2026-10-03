# Pilot User Guide
**AI-Powered Civil Service Recruitment Decision Support — CSC Pilot**

This is a short, practical guide for CSC recruitment officers participating
in the pilot. No technical background is required.

> Throughout the pilot session, you will see a banner at the top of every
> page: **"Pilot / Research Demonstration — AI output is for decision
> support and evaluation only. Final recruitment decisions remain with
> authorized human recruitment officers."** This is shown automatically
> whenever the system runs in pilot mode.

## Workflow

```
Login
  -> Select Job
  -> Select Candidate
  -> View AI Screening
  -> Review Evidence
  -> Review Recommendation
  -> Make Human Decision
  -> Submit Feedback (survey / error log, outside the system)
```

## Step by step

1. **Login** — go to the login page and sign in with the account provided
   for the pilot.
2. **Select a Job** — open "Jobs" from the navigation menu and choose the
   pilot vacancy (default scenario: **ICT Officer**).
3. **Select a Candidate Application** — open "Ranking" (or "Ranking by
   Job") to see the applications for that job, ordered by AI score.
4. **View AI Screening** — click a candidate's row to open their
   application detail page. You will see, in order:
   - **Candidate Profile** — education, experience, skills, languages,
     certifications, as extracted by the AI from the CV.
   - **Job Requirement** — the position's requirements for comparison.
   - **Rule Engine** — pass/fail per requirement (deterministic, not an
     LLM guess).
   - **Semantic Matching** — an overall match score and a per-dimension
     breakdown.
   - **Skill Gap Analysis** — matched vs. missing skills.
   - **Requirement <-> Evidence Matrix** — every requirement next to the
     candidate's actual extracted evidence, in one table.
   - **Legal Reference Evidence** — regulation excerpts retrieved for this
     job (RAG).
   - **Explainable AI** — reasoning, risks, and a recommendation (labeled
     **Decision Support**, not an automatic decision).
5. **Review the Evidence** — read the Requirement/Evidence Matrix and the
   Legal Reference Evidence before forming your own judgment. Check
   whether the evidence actually supports the recommendation shown.
6. **Review the Recommendation** — the AI's recommendation (e.g.
   "Recommended", confidence %) is shown as a badge. This is **not** the
   final decision.
7. **Make the Human Decision** — in the "Human Review" section, record
   **Approve** or **Reject** and write a short reason. This is the only
   field that becomes the application's actual recorded outcome. (Only
   accounts with the "record final decision" permission can submit this —
   ask your pilot coordinator if your account cannot.)
8. **Submit Feedback** — after reviewing one or more candidates, please
   fill in:
   - the survey (`task_h_survey.md`), and/or
   - the AI error/feedback log (`task_h_data_collection_template.md`) if
     you noticed anything wrong, confusing, or missing.

## What to pay attention to while reviewing

- Does the **Candidate Profile** correctly reflect what is actually in the
  CV?
- Does the **Requirement/Evidence Matrix** correctly show why a
  requirement is marked met/not met?
- Does the **Legal Reference Evidence** actually relate to the
  recommendation, or does it look irrelevant/missing?
- Does the **Explainable AI** reasoning make sense, and would you be able
  to defend the human decision using it?
- Would you have reached the same conclusion without the AI output? How
  long did it take you, roughly?

## What NOT to do during the pilot

- Do not upload real candidates' personal documents unless your pilot
  coordinator has confirmed this specific session is authorized for real
  data (see `task_h_consent_information.md`).
- Do not treat the AI recommendation as the final decision — always record
  your own Approve/Reject with a reason.
- Do not share your login credentials with anyone outside the pilot.

## If something goes wrong

Note the candidate name/ID, what you expected, what the system showed
instead, and record it in `task_h_data_collection_template.md`. This is
valuable pilot data, not a sign you did something wrong.
