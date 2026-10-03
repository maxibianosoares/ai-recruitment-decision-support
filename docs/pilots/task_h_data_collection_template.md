# Pilot Data Collection Templates (Task H)

**Important (Part N):** these are **file-based templates** (CSV/
spreadsheet layouts), not new production database tables. The existing
database (`Job`, `Candidate`, `Application`, `HumanDecision`) already
stores every AI pipeline output and the human decision for each
application — that data does not need to be duplicated here. These
templates exist only to capture the things the production schema was
never meant to hold: **participant survey/interview responses,
screening-time stopwatch readings, and qualitative AI error reports.**
No production database schema change was made or is required for this
pilot — if a future, larger-scale study genuinely needs structured
storage for this data, that is a separate, explicit decision to make
later (see `task_h_pilot_overview.md` "Risks").

Each section below is a flat table you can paste directly into a
spreadsheet (Excel/Google Sheets/CSV). Use a `participant_id` like `P01`,
`P02`, ... instead of any name, to keep responses de-identifiable in
analysis, per the consent information.

---

## 1. pilot_participants

| participant_id | role | years_experience_band | digital_system_experience | ai_tool_experience | consent_given (Y/N) | session_date |
|---|---|---|---|---|---|---|
| P01 | | | | | | |

## 2. pilot_sessions

| session_id | participant_id | job_used | condition (A=human-only / B=AI-assisted) | start_time | end_time | notes |
|---|---|---|---|---|---|---|
| S01 | P01 | ICT Officer | B | | | |

## 3. candidate_cases

Reference only — points at the real `Application` record, does not
duplicate its content.

| candidate_case_id | candidate_name (synthetic) | application_id (DB) | intended_fit (qualified / borderline / unsuitable) |
|---|---|---|---|---|
| C01 | Maria da Costa | | qualified |
| C02 | Joao Martins | | borderline |
| C03 | Paulo Soares | | unsuitable |

## 4. screening_time (Part H Efficiency / Part J pre-post)

| session_id | participant_id | candidate_case_id | condition (A/B) | screening_time_seconds | perceived_workload (1-5) |
|---|---|---|---|---|---|
| | | | | | |

## 5. human_assessments

The recruiter's own judgment recorded for research purposes, **separate**
from the official `HumanDecision` they record inside the system itself.

| session_id | participant_id | candidate_case_id | condition (A/B) | recruiter_assessment (qualified/borderline/unsuitable) | confidence (1-5) | notes |
|---|---|---|---|---|---|---|
| | | | | | | |

## 6. ai_assessments

Reference only — pulled from the `Application` record (`ai_score`,
`ai_decision`, `ai_confidence`), not re-entered by hand.

| application_id | candidate_case_id | ai_score | ai_decision | ai_confidence |
|---|---|---|---|---|
| | | | | |

## 7. survey_responses

One row per participant per survey; columns A1-F2 match `task_h_survey.md`
item codes (B1-B4, C1-C4, D1-D4, E1-E3, F1-F2 = 1-5; G1-G6 = free text).

| participant_id | B1 | B2 | B3 | B4 | C1 | C2 | C3 | C4 | D1 | D2 | D3 | D4 | E1 | E2 | E3 | F1 | F2 | G1 | G2 | G3 | G4 | G5 | G6 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | | | | | | | | | | | | |

## 8. qualitative_feedback

Open-ended interview notes (see `task_h_interview_questions.md`).

| participant_id | question_no | response_summary |
|---|---|---|
| | | |

## 9. ai_errors (Part K)

| participant_id | scenario | candidate_case_id | observed_ai_result | expected_or_participant_interpretation | error_type | evidence_available (Y/N) | recommendation_understandable (Y/N) | severity (Low/Medium/High) | comments |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

**Error type — pick one:**
1. Extraction error
2. Candidate profile error
3. Job profile error
4. Skill matching error
5. Rule screening error
6. RAG evidence error
7. Unsupported claim
8. Incorrect recommendation
9. Translation/language issue
10. Usability issue
11. Performance issue
12. Other

Do not record private candidate information beyond what is already
synthetic/dummy in the pilot scenario. If a real-data session is ever
authorized (see `task_h_consent_information.md`), describe errors in
general terms (e.g. "missing experience field") rather than quoting
identifying personal details.

---

*These templates are designed to be copy-pasted into a spreadsheet tool
for actual data entry during/after the pilot — they are documentation,
not live database tables.*
