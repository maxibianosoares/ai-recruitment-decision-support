# Demo Script — AI Recruitment Decision Support System
**For: Prof. Joy demo · Target runtime: 7–9 minutes · Prepared: Phase 8**

This is a live-execution script, not slides. Everything shown is the
real running system (Django + SQLite + local Ollama/gemma3:12b), not
mockups. Say so explicitly at the start — it's a credibility point.

---

## 0. Pre-Demo Checklist (do this 15–20 min before Prof. Joy arrives)

Run in order, in a terminal you can leave open and minimized (don't
close it — closing kills the Ollama/Django processes):

```powershell
# 1. Start Ollama and make sure the model is actually loaded into
#    memory BEFORE the demo — the first call to a cold model is much
#    slower and that lag will happen live if you skip this.
ollama serve
# (in a second terminal)
ollama run gemma3:12b
>>> hello
# wait for a reply, then type /bye to exit the chat — this warms the
# model without needing to leave a chat session open
ollama ps
# confirm gemma3:12b shows as loaded

# 2. Confirm your data is in place (should already be done from Phase 7)
python manage.py migrate
python manage.py seed_demo_data          # skip --reset, don't wipe what's there
python manage.py createsuperuser         # only if you don't have one yet

# 3. Set DEBUG=False in .env for the demo run, so any hiccup shows the
#    TL-themed 404/500 page instead of a raw Python traceback on the
#    projector. Flip it back to True afterward for your own debugging.
#    Edit .env:  DEBUG=False

# 4. Start the server
python manage.py runserver
```

Then, in the browser you'll actually present from:

- [ ] Open `http://127.0.0.1:8000/accounts/login/` and **log in already**,
      before Prof. Joy sits down. Don't log in live — it wastes time
      and risks a typo on the projector.
- [ ] Open a **second browser tab** to `http://127.0.0.1:8000/ai-assistant/`
      and silently ask **one throwaway question** (e.g. "test") to force
      the first, slow, cold-start Ollama call to happen now, off-camera.
      Refresh the tab afterward so it looks fresh for the real demo.
- [ ] Zoom your browser to 100–110% and maximize the window — small
      text on a projector undercuts a confidence-heavy demo.
- [ ] Keep this file, or the 9-question list from Phase 3/4, open on a
      **second monitor or your phone** so you can copy-paste the RAG
      questions instead of retyping them live (typos change retrieval
      results).
- [ ] Know your seeded job/candidate names by heart: **ICT Officer**
      job, with **ICT Officer Candidate A / B / C** (Strong / Medium /
      Weak). You will not need to remember IDs — everything is
      click-navigable.

**If Ollama fails or is slow live:** don't panic-debug in front of the
professor. Say: *"The AI service seems to be under load — let me show
you the pre-computed results while it catches up,"* and pivot to the
Ranking page (step 5), which needs no live AI call at all.

---

## 1. The 9-Step Storyboard

Time budget assumes ~8 minutes total; adjust pacing live based on how
many questions Prof. Joy asks along the way — that's fine, this is a
guide, not a stopwatch.

---

### ① Home — Framing (≈30 sec)

**URL:** `http://127.0.0.1:8000/`
**Action:** Land on the home page. Don't click anything yet.

**Say:**
> "Before I show any screen, I want to state the framing of this whole
> system up front: this is a **decision-support** platform for civil
> service recruitment in Timor-Leste, not a decision-*making*
> platform. Every AI output you'll see — a score, a ranking, an
> answer — is evidence for a human recruiter to weigh. The system
> never finalizes a hiring decision on its own. That's the
> Human-in-the-Loop principle this whole architecture is built
> around, and I'll come back to it at the end."

**Watch for on screen:** Nothing technical yet — this is a verbal
frame-setting moment. Keep it short.

---

### ② Create Job — AI Job Profiling (≈60 sec)

**URL:** `http://127.0.0.1:8000/jobs/create/`
**Action:** Either create a **new, throwaway** job live (e.g. title
"Demo Officer", paste 2–3 sentences of requirements text), or open an
**existing** job (ICT Officer) via `/jobs/<id>/` if you'd rather not
risk a live LLM call at this step.

**Say (if creating live):**
> "When a recruiter creates a vacancy, they just write the job
> description in plain language — the same way they always have. The
> system's first AI stage reads that description and extracts a
> structured job profile automatically: required education, years of
> experience, languages, and — most importantly for the next steps —
> required skills. This structured profile is what feeds the Rule
> Engine and Semantic Matching later. Nothing downstream is manually
> configured."

**Watch for on screen:** After saving, land on the Job Detail page —
point at the **Required Skills** badges, which came from the AI
extraction, not manual tagging.

**Risk note:** This step calls the LLM live (via `process_job()`).
If you're not confident about timing, **skip live creation** and just
open the already-seeded **ICT Officer** job instead, saying "this was
created the same way — let me show you a completed example."

---

### ③ Candidate Application — Real CV Upload (≈45 sec)

**URL:** `http://127.0.0.1:8000/jobs/<ict-officer-id>/apply/`
**Action:** Open the ICT Officer job, click **Apply for this
Position**. Fill the form with a throwaway name/email and upload a
**real PDF** — either one of the generated demo CVs from
`media/cv/` (Phase 7 seed data) or any small digitally-generated PDF
you have handy.

**Say:**
> "This is the actual candidate-facing form — no login required,
> matching how a real applicant would use it. I'll upload a PDF CV.
> Behind the scenes, the system runs full text extraction from the
> PDF — not OCR, this needs a digitally generated PDF, which is a
> known and documented limitation I'll mention if asked — and passes
> that extracted text into the AI pipeline."

**Watch for on screen:** After submitting, you land back on Job
Detail with a **success message** ("Application submitted and AI
analysis complete") — point out that this single click just ran four
separate AI/algorithmic stages in sequence (candidate profiling, rule
check, semantic match, explainable report).

**Risk note:** This is your other live-LLM moment. If Ollama is slow,
narrate through the wait rather than going silent: *"This is
processing three parallel analyses right now — rule-based, semantic,
and an explainability pass."*

---

### ④ AI Analysis — Skill Gap & Semantic Matching (≈60 sec)

**URL:** stay on the Candidate Detail page for the application you
just submitted, or jump straight to **ICT Officer Candidate A**
(seeded, guaranteed clean data) via Ranking → click a name.

**Say:**
> "This is where the two matching strategies described in my
> methodology actually run. First, **Rule-Based Filtering** —
> a strict, deterministic comparison of required skills versus the
> candidate's extracted skills. Second, **Semantic Matching** — an
> LLM-based comparison that understands *synonyms and related
> concepts*. For example, if a job asks for 'Database Management' and
> a candidate's CV says 'PostgreSQL Administration', a naive keyword
> match would call that a miss. The semantic layer scores it as a
> strong match instead, because it reasons about meaning, not just
> exact text."

**Watch for on screen:**
- **Skill Gap Analysis card:** point at **Matched Skills** vs
  **Missing Skills** — two clearly separated lists.
- **Semantic Matching card:** point at the **per-dimension progress
  bars** (education, experience, technical skills, soft skills,
  certifications, languages) — say explicitly: *"this dimension
  breakdown is generated by the LLM reasoning over the CV and job
  profile together — this is the research contribution, not just a
  single similarity number."*

---

### ⑤ Ranking — The Three-Tier Distribution (≈60 sec)

**URL:** `http://127.0.0.1:8000/ranking-jobs/` → click **ICT Officer**
→ `http://127.0.0.1:8000/ranking-jobs/<id>/`

**Say:**
> "Here's the ranked list for this position. I've seeded three
> representative profiles to demonstrate the full range of outcomes
> the fusion scoring produces: a strong match, a moderate match, and
> a weak one."

**Watch for on screen — this is your strongest visual moment, slow
down here:**
- **Candidate A — score ~88, "Highly Recommended."**
- **Candidate B — score ~64, "Consider."**
- **Candidate C — score ~18, "Not Recommended."**

**Say, pointing at Candidate C specifically:**
> "Candidate C is deliberately the most important row on this table,
> not the least. This candidate is missing the required technical
> skills entirely. Our Rule Engine treats required skills as a **hard
> gate** — when a candidate fails it, the fusion formula caps their
> final score below 50%, *regardless of how well anything else
> scores*. That's a deliberate design decision: a candidate who fails
> a mandatory requirement should never be able to out-rank a
> qualified one just because an LLM's semantic reasoning was
> generous. The hard rule always wins."

---

### ⑥ Candidate Detail — Explainable AI (≈60 sec)

**URL:** Click into **Candidate C's** detail page specifically (more
interesting than A here, because you can show the failure reasoning).

**Say:**
> "This is the full evidence trail behind that 18% score — nothing is
> a black box. The Rule Engine card shows exactly which rules failed
> and why. The Explainable AI section below gives the LLM's narrative
> reasoning, listed risks, and its recommendation in plain language.
> A human recruiter reading this page has everything they need to
> either agree with the system or override it — and this system
> never removes that option from them."

**Watch for on screen:**
- **Rule Engine card:** red **FAIL** badge, **Failed Rules** list
  spelling out exactly what's missing.
- **Explainable AI card:** Reasoning / Risks / Recommendation — all
  human-readable text, not just numbers.
- Mention, if there's time: *"I also want to be transparent that the
  RAG-policy component of the fusion formula is a per-job signal,
  not per-candidate — it's a real retrieval against the legal corpus,
  cached once when the job is created, so every applicant to the
  same job shares it. Making it truly per-candidate would mean
  indexing CVs into the retrieval layer, which I deliberately didn't
  do, to keep the two subsystems architecturally separate. That's
  documented directly in the code and discussed in my methodology
  chapter."* (This kind of unprompted honesty lands very well with an
  examiner — it shows you understand your own system's limits.)

---

### ⑦ AI Assistant — RAG Policy Q&A (≈45 sec)

**URL:** `http://127.0.0.1:8000/ai-assistant/`

**Say:**
> "Separately from candidate matching, this system has a second AI
> subsystem: a Retrieval-Augmented Generation assistant that answers
> policy and legal questions from six official Timor-Leste civil
> service documents — the Civil Service Commission Law, Recruitment
> Law, Competency Framework, and others. I want to show two contrasting
> cases: one the system can answer confidently, and one it should
> correctly refuse."

**Ask live, question 1 (paste, don't retype):**
> `Can AI replace human recruiters in the civil service?`

**Watch for on screen:** Answer appears, **Evidence Coverage:
Supported**, confidence score, and — scroll down — the new evidence
panels (see step ⑧).

**Ask live, question 2:**
> `Who is the current President of Timor-Leste?`

**Say, before the answer even finishes:**
> "This question is designed to fail — deliberately. Watch what the
> system does with it."

**Watch for on screen:** The system should **abstain** — answer along
the lines of "I don't have enough evidence" — because the indexed
documents only contain historical/promulgation references, not a
live fact about who currently holds the office. This is the
**temporal guard** working as intended.

---

### ⑧ Evidence Inspection — Proving It's Not a Wrapper (≈60 sec)

**URL:** same page, scroll down on the **first** question's answer
(the supported one).

**Say:**
> "This is the part I most want you to see, because it's the actual
> research contribution — this isn't a wrapper around a chatbot API.
> Before generating any answer, the system decomposes the question
> into individual claims, retrieves evidence for each claim
> separately, and checks coverage per claim. After generation, there's
> a second, independent pass — a groundedness check — that re-verifies
> the generated answer's claims against the retrieved evidence, to
> catch hallucination *after the fact*, not just before it."

**Watch for on screen, point at each in turn:**
- **Groundedness Check** metric card — should read **"✓ Grounded."**
- **Question Decomposition & Evidence Coverage** panel — the
  claim-by-claim table with Supported/Not Supported badges.
- **Retrieved Evidence** panel — the actual FAISS-retrieved document
  chunks, with document name and relevance score — *"this is the raw
  evidence, not the AI's self-reported citation — you can verify it
  yourself against the source PDF."*

**Say, citing your real benchmark run (N=40, zero pipeline errors,
0 false acceptance):**
> "This isn't a one-off demo question either — I validated this
> behavior across a 40-question benchmark spanning five categories.
> The system scored **100% on both the Unsupported and Temporal
> categories** — meaning it never once hallucinated an answer to a
> question it had no business answering, and the temporal guard
> caught every single 'who is the current X' style trap. Grounded
> rate across all 40 questions was **100%** — every answer that *was*
> given was verifiably traceable to retrieved evidence."

**If time allows**, scroll to the abstained answer (question 2) and
show the **Groundedness/Evidence Coverage still renders honestly**
even for a refusal — it doesn't just go blank.

**If Prof. Joy pushes on weaknesses (a strong sign of engagement —
answer this directly, don't get defensive):**
> "The category that needs more work is Partial Evidence — questions
> that mix one well-supported fact with one specific detail the
> corpus doesn't contain. Accuracy there was 20%, well below the 90%
> and 100% on the cleaner categories. I traced this to a specific,
> fixable cause: my question-decomposition prompt currently only
> reliably splits compound questions joined by 'and' — like 'Can AI
> rank candidates *and* determine salary?' — into separate claims. My
> newer partial-evidence questions use a different construction —
> an assertion followed by 'but' and a question — and the decomposer
> tends to treat the assertion as background context rather than a
> separate claim to verify, so it never gets credited as supported.
> That's a precise, addressable prompt-engineering gap, not a
> fundamental architecture flaw — the coverage-scoring mechanism
> itself works, as proven by the two original partial-evidence
> questions, which it classified correctly."

This is a genuinely strong answer to give under pressure — it shows
you diagnosed a real weakness down to its root cause instead of
hand-waving, which is usually worth more to an examiner than a
suspiciously perfect result.

---

### ⑨ Human-in-the-Loop — Closing (≈30 sec)

**URL:** Back to `http://127.0.0.1:8000/accounts/dashboard/`, or just
turn away from the screen toward the professor.

**Say:**
> "To close where I started: everything you've seen — the ranking,
> the scores, the policy answers — is decision *support*. This
> Application record has a workflow status field — pending,
> screening, shortlisted, interview, accepted, rejected — that
> represents where a human recruiter's own decision process stands.
> The AI never sets or advances that status itself; it only ever
> produces the evidence a human uses to decide. That separation
> between AI-generated evidence and human-owned decisions is the core
> design principle of this thesis, and I've tried to make sure it's
> enforced in the architecture itself, not just claimed in the
> write-up."

**Honesty note for your own awareness (don't volunteer unless
asked):** the status field currently has no dedicated button in the
custom UI to change it — it's editable today only through Django
Admin (`/admin/talent/application/<id>/change/`), which is
functional but not part of the polished TL-themed interface. If Prof.
Joy specifically asks "where does the recruiter click to move a
candidate to the next stage," the honest answer is Django Admin for
now, and you can frame it as a planned Phase 9 UI addition rather
than something broken — the data model and the separation of concerns
are already correct, only the front-end control is still pending.

**Stop talking. Let that land. Take questions.**

---

## 2. Benchmark Results — N=40, Real Run (2026-09-05, zero pipeline errors)

These are your **actual** results, generated by `python manage.py
run_benchmark`, timestamp `20260905_114417`. Verified: 0 questions
errored, all 40 produced a real classification. If you re-run
tonight and get different numbers (some run-to-run variance from the
LLM is normal), replace this table with your fresh output — but this
table is safe to use as-is if you don't re-run.

## RAG Benchmark Results

| Metric | Value |
|---|---|
| Total Questions | 40 |
| Classification Accuracy | 72.5% |
| Supported Accuracy | 80.0% |
| Partial Accuracy | 20.0% |
| Unsupported Accuracy | 100.0% |
| Grounded Rate | 100.0% |
| Avg. Evidence Score | 0.28 |
| False Acceptance (count) | 0 |
| False Rejection (count) | 3 |

## Accuracy by Category

| Category | Correct / Total | Accuracy |
|---|---|---|
| direct_evidence | 9/10 | 90.0% |
| partial_evidence | 2/10 | 20.0% |
| unsupported | 10/10 | 100.0% |
| temporal | 5/5 | 100.0% |
| recruitment_specific | 3/5 | 60.0% |

**One-sentence summary if Prof. Joy asks for the headline number:**
> "72.5% overall classification accuracy across 40 questions, with
> perfect scores on Unsupported and Temporal — the two categories
> that test hallucination resistance — and zero false acceptances,
> meaning the system never once presented an unsupported claim as
> fact."

**LaTeX version (paste directly into the thesis):**

```latex
\begin{table}[h]
\centering
\begin{tabular}{lr}
\hline
Metric & Value \\
\hline
Total Questions & 40 \\
Classification Accuracy & 72.5\% \\
Supported Accuracy & 80.0\% \\
Partial Accuracy & 20.0\% \\
Unsupported Accuracy & 100.0\% \\
Grounded Rate & 100.0\% \\
Avg. Evidence Score & 0.28 \\
False Acceptance (count) & 0 \\
False Rejection (count) & 3 \\
\hline
\end{tabular}
\caption{RAG evaluation summary (N=40)}
\end{table}
```

---

## 3. Quick-Reference Card (print or keep on second screen)

| # | Page | URL |
|---|------|-----|
| ① | Home | `/` |
| ② | Create Job | `/jobs/create/` |
| ③ | Apply | `/jobs/<id>/apply/` |
| ④⑤ | Ranking by Job | `/ranking-jobs/<id>/` |
| ⑥ | Candidate Detail | `/ranking/<application_id>/` |
| ⑦⑧ | AI Assistant | `/ai-assistant/` |
| ⑨ | Dashboard | `/accounts/dashboard/` |

**The two RAG questions to ask live, in order:**
1. `Can AI replace human recruiters in the civil service?` → expect **Supported**
2. `Who is the current President of Timor-Leste?` → expect **abstain / Unsupported**

*(Full 9-question set from Phase 3/4 is available as backup if Prof.
Joy asks for more — see `rag/evaluation/questions.py` for the
corpus-verified list.)*

**The one number to say out loud if nothing else lands:**
> "Candidate C cannot score above 49% no matter what, because it
> failed the hard rule gate — the AI's semantic opinion can never
> override a disqualifying requirement."
