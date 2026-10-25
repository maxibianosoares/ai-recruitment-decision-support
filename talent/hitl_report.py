"""
Weekly Human-in-the-Loop (HITL) report.

Answers, with numbers computed by code (never by a language model):
for the AI recommendations the committee actually decided on each
week, how many did the humans APPROVE as the AI leaned (agreed), and
how many did they OVERRIDE (decided the opposite direction)?  Also how
many AI-screened applications are still waiting for a human decision.

Privacy by construction
-----------------------
The result contains ONLY counts, rates and hours.  It never contains a
candidate or reviewer name, email, username, id, job title, decision
reason or document text, and it has no per-reviewer or per-job
breakdown (small groups could identify a person).  A week with very
few decisions is flagged ``low_volume`` so a reader does not over-read
it.

Definitions (they follow the existing application, nothing new):
  * decision direction : HumanDecision.decision  (approved / rejected)
  * agreed / overridden: HumanDecision.agreed_with_ai, exactly as the
    candidate_detail view stored it at decision time
  * AI leaned positive : Application.ai_decision in {"highly
    recommended", "recommended", "consider"} (same rule as the view)
  * decisions are locked once recorded, so a week's decisions are those
    CREATED in that week

Read-only: no writes, no network, no model call.
"""

from datetime import datetime, time, timedelta
from statistics import median

from django.utils import timezone

from . import statuses as S
from .models import Application, HumanDecision

SCHEMA_VERSION = 1

POSITIVE_AI_DECISIONS = ("highly recommended", "recommended", "consider")

CATEGORIES = (
    "highly recommended", "recommended", "consider", "not recommended",
)
OTHER = "other / none"

LOW_VOLUME_THRESHOLD = 5

PENDING_BUCKETS = (
    ("up_to_7_days", 0, 7),
    ("8_to_14_days", 8, 14),
    ("over_14_days", 15, None),
)


def ai_leans_positive(ai_decision):
    return (ai_decision or "").strip().lower() in POSITIVE_AI_DECISIONS


def _category(ai_decision):
    value = (ai_decision or "").strip().lower()
    return value if value in CATEGORIES else OTHER


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def _week_start(day):
    return day - timedelta(days=day.weekday())


def week_bounds(week_start_date):
    """Aware [Monday 00:00, next Monday 00:00) in the current time zone."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(week_start_date, time.min), tz)
    end = timezone.make_aware(
        datetime.combine(week_start_date + timedelta(days=7), time.min), tz)
    return start, end


def last_completed_week_start(now=None):
    now = timezone.localtime(now or timezone.now())
    return _week_start(now.date()) - timedelta(days=7)


def _summarise(decisions):
    """decisions: iterable of HumanDecision with .application loaded."""
    decisions = list(decisions)

    total = len(decisions)
    approved = sum(1 for d in decisions if d.decision == "approved")
    rejected = sum(1 for d in decisions if d.decision == "rejected")
    agreed = sum(1 for d in decisions if d.agreed_with_ai)
    overridden = total - agreed

    ai_negative_human_approved = sum(
        1 for d in decisions
        if not d.agreed_with_ai and d.decision == "approved")
    ai_positive_human_rejected = sum(
        1 for d in decisions
        if not d.agreed_with_ai and d.decision == "rejected")

    by_category = {c: {"decisions": 0, "agreed": 0, "overridden": 0}
                   for c in CATEGORIES + (OTHER,)}
    for d in decisions:
        cell = by_category[_category(d.application.ai_decision)]
        cell["decisions"] += 1
        cell["agreed" if d.agreed_with_ai else "overridden"] += 1

    hours = []
    for d in decisions:
        done = d.application.ai_processed_at
        if done and d.created_at >= done:
            hours.append((d.created_at - done).total_seconds() / 3600)

    return {
        "decisions": total,
        "approved": approved,
        "rejected": rejected,
        "agreed_with_ai": agreed,
        "overridden": overridden,
        "agreement_rate": _rate(agreed, total),
        "override_rate": _rate(overridden, total),
        "overridden_breakdown": {
            "ai_negative_human_approved": ai_negative_human_approved,
            "ai_positive_human_rejected": ai_positive_human_rejected,
        },
        "by_ai_recommendation": by_category,
        "median_hours_ai_to_decision": (
            round(median(hours), 1) if hours else None),
        "low_volume": total < LOW_VOLUME_THRESHOLD,
    }


def _pending(now):
    """AI-finished applications that have no human decision yet (as of now)."""
    waiting = Application.objects.filter(
        ai_status=S.SUCCESS, human_decision__isnull=True)

    buckets = {name: 0 for name, _, _ in PENDING_BUCKETS}
    total = 0
    for app in waiting.only("ai_processed_at", "applied_at"):
        since = app.ai_processed_at or app.applied_at
        days = max((now - since).days, 0) if since else 0
        total += 1
        for name, low, high in PENDING_BUCKETS:
            if days >= low and (high is None or days <= high):
                buckets[name] += 1
                break

    return {"awaiting_human_decision": total, "age": buckets}


def _flag_inconsistencies(decisions):
    """
    Data-integrity check: the stored agreed_with_ai must equal what the
    decision rule gives for the application's CURRENT AI recommendation.
    A non-zero count means a stored flag and the data disagree and the
    numbers above should be read with care.
    """
    bad = 0
    for d in decisions:
        positive = ai_leans_positive(d.application.ai_decision)
        expected = ((d.decision == "approved" and positive)
                    or (d.decision == "rejected" and not positive))
        if bool(d.agreed_with_ai) != expected:
            bad += 1
    return bad


def build_report(week_ending=None, weeks=4, now=None):
    """
    week_ending: any date inside the LAST week to report (default: the
                 most recent completed Monday-Sunday week)
    weeks:       how many consecutive weeks to include (1..52)
    """
    if not 1 <= int(weeks) <= 52:
        raise ValueError("weeks must be between 1 and 52")
    weeks = int(weeks)

    now = now or timezone.now()
    last_start = (_week_start(week_ending) if week_ending
                  else last_completed_week_start(now))

    starts = [last_start - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]
    period_start, _ = week_bounds(starts[0])
    _, period_end = week_bounds(starts[-1])

    base = HumanDecision.objects.select_related("application")

    weekly = []
    for start in starts:
        lo, hi = week_bounds(start)
        row = _summarise(base.filter(created_at__gte=lo, created_at__lt=hi))
        row["week_start"] = start.isoformat()
        row["week_end"] = (start + timedelta(days=6)).isoformat()
        weekly.append(row)

    in_period = list(base.filter(created_at__gte=period_start,
                                 created_at__lt=period_end))
    period = _summarise(in_period)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timezone.localtime(now).isoformat(timespec="seconds"),
        "time_zone": str(timezone.get_current_timezone()),
        "period": {
            "start": starts[0].isoformat(),
            "end": (starts[-1] + timedelta(days=6)).isoformat(),
            "weeks": weeks,
            **period,
        },
        "weekly": weekly,
        "pending_now": _pending(now),
        "data_integrity": {
            "agreement_flag_inconsistencies": _flag_inconsistencies(in_period),
        },
        "definitions": {
            "agreed_with_ai": "The committee's decision points the same way "
                              "as the AI recommendation (AI positive and "
                              "approved, or AI negative and rejected).",
            "overridden": "The committee decided the opposite direction to "
                          "the AI. Decisions are final once recorded, so "
                          "'changed' is counted as an override.",
            "ai_negative_human_approved": "AI said Not Recommended; the "
                                          "committee approved.",
            "ai_positive_human_rejected": "AI said Highly Recommended / "
                                          "Recommended / Consider; the "
                                          "committee rejected.",
            "low_volume": f"Fewer than {LOW_VOLUME_THRESHOLD} decisions; "
                          "do not read trends into it.",
        },
        "privacy": "Counts only: no names, emails, ids, job titles, "
                   "reasons or document text; no per-reviewer or per-job "
                   "breakdown.",
    }


# ---------------------------------------------------------------------
# Markdown (deterministic -- the report works without any AI agent)
# ---------------------------------------------------------------------

LABELS = {
    "en": {
        "title": "Human-in-the-Loop weekly report",
        "period": "Period",
        "summary": "Summary of the period",
        "decisions": "Committee decisions",
        "approved": "Approved",
        "rejected": "Rejected",
        "agreed": "Agreed with the AI recommendation",
        "overridden": "Overrode the AI recommendation",
        "ai_neg_app": "AI negative, committee approved",
        "ai_pos_rej": "AI positive, committee rejected",
        "median": "Median hours from AI result to decision",
        "weekly": "Week by week",
        "week": "Week",
        "agree_rate": "Agreement",
        "low": "low volume",
        "by_ai": "By AI recommendation (period)",
        "ai_rec": "AI recommendation",
        "pending": "Waiting for a human decision now",
        "pending_total": "Applications waiting",
        "integrity": "Data check",
        "integrity_ok": "Stored agreement flags match the decision rule.",
        "integrity_bad": "Stored agreement flags that do not match the "
                         "decision rule",
        "none": "n/a",
        "privacy": "Privacy",
    },
    "id": {
        "title": "Laporan mingguan Human-in-the-Loop",
        "period": "Periode",
        "summary": "Ringkasan periode",
        "decisions": "Keputusan panitia",
        "approved": "Disetujui",
        "rejected": "Ditolak",
        "agreed": "Sesuai rekomendasi AI",
        "overridden": "Mengubah (berlawanan dengan) rekomendasi AI",
        "ai_neg_app": "AI negatif, panitia menyetujui",
        "ai_pos_rej": "AI positif, panitia menolak",
        "median": "Median jam dari hasil AI sampai keputusan",
        "weekly": "Per minggu",
        "week": "Minggu",
        "agree_rate": "Kesesuaian",
        "low": "volume rendah",
        "by_ai": "Menurut rekomendasi AI (periode)",
        "ai_rec": "Rekomendasi AI",
        "pending": "Menunggu keputusan manusia saat ini",
        "pending_total": "Lamaran menunggu",
        "integrity": "Pemeriksaan data",
        "integrity_ok": "Penanda kesesuaian yang tersimpan cocok dengan aturan keputusan.",
        "integrity_bad": "Penanda kesesuaian yang tidak cocok dengan aturan keputusan",
        "none": "n/a",
        "privacy": "Privasi",
    },
}


def _pct(rate, na):
    return na if rate is None else f"{rate * 100:.1f}%"


def render_markdown(report, lang="en"):
    L = LABELS[lang]
    p = report["period"]
    na = L["none"]
    out = [f"# {L['title']}", "",
           f"{L['period']}: {p['start']} – {p['end']} ({p['weeks']})", "",
           f"## {L['summary']}", "",
           f"- {L['decisions']}: {p['decisions']} "
           f"({L['approved']}: {p['approved']}, {L['rejected']}: {p['rejected']})",
           f"- {L['agreed']}: {p['agreed_with_ai']} "
           f"({_pct(p['agreement_rate'], na)})",
           f"- {L['overridden']}: {p['overridden']} "
           f"({_pct(p['override_rate'], na)})",
           f"  - {L['ai_neg_app']}: {p['overridden_breakdown']['ai_negative_human_approved']}",
           f"  - {L['ai_pos_rej']}: {p['overridden_breakdown']['ai_positive_human_rejected']}",
           f"- {L['median']}: "
           f"{na if p['median_hours_ai_to_decision'] is None else p['median_hours_ai_to_decision']}",
           "", f"## {L['weekly']}", "",
           f"| {L['week']} | {L['decisions']} | {L['approved']} | {L['rejected']} "
           f"| {L['agreed']} | {L['overridden']} | {L['agree_rate']} |",
           "|---|---|---|---|---|---|---|"]
    for w in report["weekly"]:
        flag = f" ({L['low']})" if w["low_volume"] and w["decisions"] else ""
        out.append(
            f"| {w['week_start']}{flag} | {w['decisions']} | {w['approved']} "
            f"| {w['rejected']} | {w['agreed_with_ai']} | {w['overridden']} "
            f"| {_pct(w['agreement_rate'], na)} |")

    out += ["", f"## {L['by_ai']}", "",
            f"| {L['ai_rec']} | {L['decisions']} | {L['agreed']} | {L['overridden']} |",
            "|---|---|---|---|"]
    for name, cell in p["by_ai_recommendation"].items():
        out.append(f"| {name} | {cell['decisions']} | {cell['agreed']} "
                   f"| {cell['overridden']} |")

    pend = report["pending_now"]
    out += ["", f"## {L['pending']}", "",
            f"- {L['pending_total']}: {pend['awaiting_human_decision']}"]
    for name, count in pend["age"].items():
        out.append(f"  - {name}: {count}")

    bad = report["data_integrity"]["agreement_flag_inconsistencies"]
    out += ["", f"## {L['integrity']}", "",
            f"- {L['integrity_ok']}" if bad == 0
            else f"- {L['integrity_bad']}: {bad}",
            "", f"_{L['privacy']}: {report['privacy']}_", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------
# Plain text (the email backend sends text only)
# ---------------------------------------------------------------------

def _num(value, na):
    return na if value is None else value


def render_text(report, lang="en"):
    """Readable without a monospace font or Markdown: label: value lines."""
    L = LABELS[lang]
    na = L["none"]
    p = report["period"]
    lines = [
        L["title"],
        f"{L['period']}: {p['start']} - {p['end']}",
        "",
        L["summary"].upper(),
        f"{L['decisions']}: {p['decisions']}"
        f" ({L['approved']}: {p['approved']}, {L['rejected']}: {p['rejected']})",
        f"{L['agreed']}: {p['agreed_with_ai']} ({_pct(p['agreement_rate'], na)})",
        f"{L['overridden']}: {p['overridden']} ({_pct(p['override_rate'], na)})",
        f"   {L['ai_neg_app']}: {p['overridden_breakdown']['ai_negative_human_approved']}",
        f"   {L['ai_pos_rej']}: {p['overridden_breakdown']['ai_positive_human_rejected']}",
        f"{L['median']}: {_num(p['median_hours_ai_to_decision'], na)}",
        "",
        L["weekly"].upper(),
    ]
    for w in report["weekly"]:
        flag = f" [{L['low']}]" if w["low_volume"] and w["decisions"] else ""
        lines.append(
            f"{w['week_start']}{flag}: {w['decisions']} / "
            f"{L['approved']} {w['approved']} / {L['rejected']} {w['rejected']} / "
            f"{L['agreed']} {w['agreed_with_ai']} / "
            f"{L['overridden']} {w['overridden']} / "
            f"{L['agree_rate']} {_pct(w['agreement_rate'], na)}")
    lines += ["", L["by_ai"].upper()]
    for name, cell in p["by_ai_recommendation"].items():
        lines.append(f"{name}: {cell['decisions']} / {L['agreed']} "
                     f"{cell['agreed']} / {L['overridden']} {cell['overridden']}")
    pend = report["pending_now"]
    lines += ["", L["pending"].upper(),
              f"{L['pending_total']}: {pend['awaiting_human_decision']}"]
    for name, count in pend["age"].items():
        lines.append(f"   {name}: {count}")
    bad = report["data_integrity"]["agreement_flag_inconsistencies"]
    lines += ["", L["integrity"].upper(),
              L["integrity_ok"] if bad == 0
              else f"{L['integrity_bad']}: {bad}",
              "", f"{L['privacy']}: {report['privacy']}"]
    return "\n".join(lines) + "\n"
