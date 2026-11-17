# HNGV 2026 integration: rules JSON, rule engine, RAG corpus, benchmark

Status date: 2026-11-16. All HNGV values come from OCR of public notices and are
**unverified** until checked against the PDFs. No candidate data is used anywhere.

## What was added

| Path | Purpose |
|---|---|
| `knowledge_base/vacancy_rules/hngv_2026_vacancy_rules.json` | Canonical data: rules R01-R14, 10 vacancies (430 positions), statute conflicts C1-C3 |
| `knowledge_base/vacancy_rules/vacancy_rules.schema.json` | JSON Schema (required keys) |
| `ai_engine/services/vacancy_rules_engine.py` | Deterministic engine, stdlib only. Every check returns a rule ID. `decision_authority` is always `jury` |
| `ai_engine/test_vacancy_rules_engine.py` | 73 unit tests (+ 20 in `rag/evaluation/test_vacancy_flexibility.py`), synthetic candidates, boundary cases |
| `rag/build_hngv_corpus.py` | Generates the corpus Markdown from the JSON (edit JSON, re-run) |
| `knowledge_base/documents_staging/hngv_2026/*.md` | 12 generated corpus files (102 chunks with the repo splitter, every chunk carries its vacancy code) |
| `rag/evaluation/questions_hngv.py` + `benchmark_hngv_questions.json` | 40 new questions (15 direct, 8 partial, 8 unsupported, 5 cross-source, 4 temporal) |
| `rag/evaluation/test_hngv_benchmark_consistency.py` | 11 text-level checks: benchmark labels vs corpus vs JSON |
| `rag/evaluation/run_benchmark.py` (edited) | `BENCHMARK_SET=baseline\|hngv\|combined`; default is unchanged; baseline results file is never overwritten |
| `rag/manual_benchmark_category_breakdown.py` (edited) | same `BENCHMARK_SET` switch |

Nothing else was changed. `recruitment_rules.py` and the live pipeline are untouched.

## Rule engine outcomes

PASS / FAIL / REVIEW / HUMAN / NOT_DUE per rule. Overall: `REJECT_RECOMMENDED`
(any FAIL), `HUMAN_REVIEW`, `AUTOMATED_CHECKS_PASSED`. R05 (language mastery) and
R14 (stage-I criteria) are always HUMAN. Partial rules FAIL only when the
objective part clearly fails (e.g. level below required, fewer than 3 months in
total); anything needing a field mapping or judgement is REVIEW.

Explicit assumptions (reported in every result): age measured on the closing
date (2026-09-18) in completed years, limits inclusive; public holidays not
modelled; stage-I score included in the mean only if supplied.

## Conflicts between notices and statutes (paper material)

* **C1, pass mark boundary.** Decree-Law 34/2008 Art. 35(1): candidates with
  "60 points or less" in an eliminatory phase are disqualified. The notices:
  60 passes. `evaluate_stage_progress(..., statute_strict=True)` applies the statute.
* **C2, age.** Notices 20-55; Law 5/2009 amending Law 8/2004 (policy.pdf) 17-55.
* **C3, language.** Notices Tetum + Portuguese (CPI/4: Tetum + minimum
  Portuguese/English); Decree-Law 34/2008 Art. 23: one official language.
* Accountability gaps: R14 (no stage-I criteria), R07/R08 not in the 9-item
  list, no experience letter, no appeal clause in the notices (statute: 5
  working days, Art. 33).

## How to adopt the corpus (do this in order)

1. Re-run the baseline first and keep the file:
   `python -m rag.evaluation.run_benchmark` (needs faiss + sentence-transformers).
2. Copy `knowledge_base/documents_staging/hngv_2026/*.md` into
   `knowledge_base/documents/`, then `python -m rag.build_index`.
3. `BENCHMARK_SET=combined python -m rag.evaluation.run_benchmark`.
4. Compare the 40 baseline questions before/after. Items likely to change
   because the corpus now contains salaries, jury and age content: OS01
   (civil-servant salary, expected unsupported), PE01, PE04, DE04, TC03.
   A flip is a finding about corpus contamination, not necessarily a bug.

## Tested here, and not tested

Run for real in the sandbox: `python -m unittest ai_engine.test_vacancy_rules_engine`
(54 tests) and `python -m unittest rag.evaluation.test_hngv_benchmark_consistency`
(11 tests, the cross-source check ran against a text dump of the existing PDFs).
Also checked: the splitter produces 102 chunks, all containing their vacancy code.

NOT run (packages missing in the sandbox): index rebuild, retrieval, evidence
gate, groundedness, the benchmark itself, `manage.py test`. So there is **no
accuracy figure** for the new questions. Tetum/Portuguese retrieval is untested
(the corpus is English; originals are Tetum with OCR errors).

## Before using in the paper

Verify every value against the PDFs (esp. CPI/4 education, CPI/22 appointment
field, application period in 4 notices); have a second person label
`expected` (`labeler_2`), resolve the `borderline` items; process the 12
remaining HNGV notices; decide with Prof Jo whether the engine is evaluated on
synthetic candidates only.


## Dynamic benchmark (added 2026-11-17)

`rag/evaluation/dynamic_questions.py` generates questions for **every** vacancy in the
rules JSON (labels come from templates; the strings each answer must contain come from
the same JSON that generates the corpus). Add a vacancy to the JSON, run
`python -m rag.build_hngv_corpus`, and the benchmark grows with no code change.
Codes listed in `known_unprocessed` become "unsupported" probes until they are added.

* `python -m rag.evaluation.dynamic_questions --export` writes `benchmark_dynamic_questions.json`.
* `BENCHMARK_SET` (see `rag/evaluation/benchmark_sets.py`): `baseline` | `hngv` (40 gold,
  hand-written) | `dynamic` (98 now) | `combined` (80) | `all` (178). Each set has its own
  results file; the baseline file is never overwritten.
* Defaults: 4 direct + 2 partial + 2 unsupported topics per vacancy, rotated by a stable hash;
  `build_dynamic_questions(per_vacancy=None, other_per_vacancy=None)` gives every topic.
* Generated labels have no second labeller. Use them as a scalable regression set and keep
  the 40 hand-written questions as the gold set.
* `python -m unittest rag.evaluation.test_dynamic_questions` (15 tests) checks that every generated
  direct answer string occurs in the generated corpus text for every vacancy, that a
  synthetic extra vacancy adds consistent questions, and that sets/IDs/result files are sane.
  It does not measure retrieval accuracy.

## Flexible use for other jobs (opt-in)

Nothing is created automatically for new jobs. To make the engine, corpus and
benchmark follow the rules of another job, add an entry to a rule pack
(`knowledge_base/vacancy_rules/*.json`, see `vacancy_rules.schema.json`):

1. **Rules.** Declare only the rules the job has under `requirements`
   (R01..R14). A rule that is not declared is reported `NOT_APPLICABLE` and does
   not change the overall result. Thresholds (age limits, months, pass mark,
   weights, period) are read from the entry. A new pack file in the same folder
   is found automatically; the same vacancy code in two packs is an error.
   `eng.list_vacancies()` shows what is available.
2. **Corpus.** `python -m rag.build_vacancy_corpus --src <pack.json> --out
   knowledge_base/documents_staging/<name> --vacancy CODE` (or `--all`). Sections
   are written only for declared rules. Institution-specific wording goes in
   `corpus_notes` (`{code}` and `{field}` placeholders). `python -m
   rag.build_hngv_corpus` still works.
3. **Benchmark.** `python -m rag.evaluation.generate_vacancy_questions --src
   <pack.json> --vacancy CODE --out rag/evaluation/benchmark_generated.json`.
   It makes direct questions from the rules the job declares, a "criteria not
   stated" question when R14 says so, and one "no candidate data" question.
   Cross-source and temporal questions still need a person (see
   `questions_hngv.py`). Run with `BENCHMARK_SET=generated` (file path via
   `BENCHMARK_QUESTIONS_FILE`).
4. **Check agreement without any model:** `python -m unittest
   rag.evaluation.test_vacancy_flexibility` (fictional pack, all three tools).

Limits: the rule checks are still the R01-R14 families (identity documents,
age, level and field, months of experience, documents, window, stages, pass
mark, weights). A job whose notice needs a different kind of rule needs a new
check function in `vacancy_rules_engine.py`; the pack alone cannot add one.
Generated labels come from the pack's data; a second person must still label.


## v2 (2026-11-17): the reference law stays authoritative

A vacancy notice is a **secondary source**. The statutes already in the RAG corpus are
transcribed in `knowledge_base/vacancy_rules/reference_law_baseline.json` (each constraint has a
citation and the PDF it comes from). The engine evaluates age and pass-mark checks twice, once
per the notice and once per the law:

| Situation | Result |
|---|---|
| notice and law agree | PASS or FAIL as usual |
| they disagree (e.g. age 17-19, or a score of exactly 60) | **REVIEW**, with both readings and the citation in `law_conflicts` |

`conflict_policy="review"` is the default. `"notice"` and `"law"` exist only for what-if runs
(`statute_strict=True` is an alias of `"law"`). A job profile without a law constraint runs
without conflicts (`law={}`). `audit_vacancy_against_law(vacancy)` lists the static differences
(age range, pass-mark boundary, official languages, missing appeal clause) for the paper.

**Behaviour change from v1:** a 19-year-old on a notice with minimum 20 is now REVIEW (law
allows 17), not FAIL; a written score of exactly 60 is REVIEW, not PASS. Ages 16 and below, scores
of 59.99 and below stay FAIL, because both sources agree.

The generated corpus follows the same principle: every vacancy document carries an authority
note ("the statute is the reference"), and the rule catalogue lists each notice-vs-statute
difference. The law PDFs themselves are not touched.

`BENCHMARK_SET=generated` with `BENCHMARK_QUESTIONS_FILE=<file>` runs questions made by
`generate_vacancy_questions.py` for any pack; it is never part of `combined` or `all`.

Generic profiles: every rule block R01-R14 is optional; `list_vacancies()` and
`find_vacancy(code)` search all pack files in `knowledge_base/vacancy_rules/`; duplicate codes raise
`ValueError`; `weighted_written_score` refuses to assume 25/75 for a named job without R13.

Tests run for real in the sandbox (no model needed): engine 73, flexibility 20, dynamic 15,
consistency 13. Still not run: retrieval, evidence gate, the benchmark itself.

### Rule scope (added after review): law for every job, extras for one job

* The reference law (`reference_law_baseline.json`) applies to **every** civil-service vacancy,
  including a job whose profile declares no age or pass-mark rule: age 17-55 and the
  "60 or less is disqualified" rule are then checked from the law alone (`evidence.source` says so).
* A profile's own rules are **additions for that vacancy only**. They never change another job,
  and where they differ from the law the result is REVIEW with the citation, not a silent override.
* Switching the law off needs `allow_no_law=True`; such a result has `law_applied=false`, a
  WARNING in `assumptions`, and can never be `AUTOMATED_CHECKS_PASSED`.
* Generated corpus documents say the same in every vacancy file.
* The law is applied to written/eliminatory scores. The final-classification threshold stays the
  notice's own (the statute only fixes the eliminatory-method rule and the averaging method).
