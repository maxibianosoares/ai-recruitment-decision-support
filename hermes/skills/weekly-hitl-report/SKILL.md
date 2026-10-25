---
name: weekly-hitl-report
description: Turn the anonymous weekly Human-in-the-Loop JSON from the recruitment system into a short weekly report (how many AI recommendations the committee agreed with or overrode). Use only on the JSON file provided; never on personal data.
---

# Weekly Human-in-the-Loop report

## Input
One JSON file produced by `python manage.py weekly_hitl_report --format json`.
It contains counts only (schema_version 1). The numbers in it are the ONLY
numbers you may use. Do not compute new statistics, estimate, or round
differently from the file.

## Steps
1. Read the JSON file given to you. If it is missing, not valid JSON, or has a
   different `schema_version`, stop and report exactly that. Do not guess.
2. Write `reports/hitl-<period.end>.md` with these sections, in this order:
   1. **Key numbers** — copy from `period`: decisions, approved, rejected,
      agreed_with_ai, overridden, agreement_rate and override_rate as
      percentages, overridden_breakdown, median_hours_ai_to_decision.
   2. **Week by week** — a table from `weekly`. Mark any week with
      `low_volume: true` as "low volume" and do not describe a trend from it.
   3. **By AI recommendation** — a table from `period.by_ai_recommendation`.
   4. **Waiting for a human decision** — from `pending_now`.
   5. **Data check** — from `data_integrity`. If
      `agreement_flag_inconsistencies` is above 0, say so plainly and tell the
      reader the figures need checking before they are quoted.
   6. **Reading the numbers** — at most five short sentences. Each sentence
      must quote a number from the file. Say what the numbers show about
      human oversight (for example, the share of AI recommendations the
      committee overrode, and in which direction). Say what they do NOT show
      (they do not show whether the AI or the committee was right).
3. Copy the `definitions` and `privacy` text from the file at the end.
4. Re-read your finished report once and check every number against the JSON.
   If any number differs, fix it.

## Rules
- Never write or ask for a name, email, id, job title or decision reason.
  If such a thing appears in the file, stop and report it as a privacy fault.
- Never judge an individual reviewer or candidate. Never recommend changing a
  decision. The report describes; it does not advise on hiring.
- Do not say a trend exists unless at least two non-low-volume weeks support it.
- If total decisions in the period are below 5, say the period is too small to
  draw conclusions.
- Do not call the recruitment system, its database, or any external service.
  Work only from the file.
