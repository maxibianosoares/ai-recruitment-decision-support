"""
Anonymous health check of the screening pipeline (counts only).

Everything here is plain database counting -- no model is called, and the
result contains NO names, emails, ids, job titles or document text.

What is checked
  queue            applications waiting (QUEUED) and how long the oldest waits
  in flight        applications being read / screened, and any that look stuck
  failures         AI screening failures (FAILED) in the last 24 hours
  retryable        unreadable CVs (DOCUMENT_INVALID / EXTRACTION_FAILED) in the
                   last 24 hours -- the candidate can fix these, so they are
                   information, not an alert
  awaiting review  AI-finished applications with no human decision yet

Alerts (things an administrator should look at):
  queue_stalled    the oldest QUEUED application has waited too long
                   (usually: the worker is not running)
  stuck            an application has been EXTRACTING / EXTRACTED / PROCESSING
                   for too long
  ai_failures      one or more FAILED in the last 24 hours

Timing note: the worker updates ai_status with save(update_fields=...), which
does not refresh updated_at, so "waiting/in-flight time" is measured from the
last full save of the application (when it was queued or re-queued).
"""

from datetime import timedelta

from django.db.models import Min
from django.utils import timezone

from . import statuses as S
from .hitl_report import _pending
from .models import Application

DEFAULT_QUEUE_MINUTES = 30
DEFAULT_STUCK_MINUTES = 30
LOOKBACK_HOURS = 24
LONG_WAIT_DAYS = 14


def _minutes(now, then):
    if then is None:
        return None
    return max(int((now - then).total_seconds() // 60), 0)


def collect(now=None, queue_minutes=DEFAULT_QUEUE_MINUTES,
            stuck_minutes=DEFAULT_STUCK_MINUTES):
    now = now or timezone.now()
    since = now - timedelta(hours=LOOKBACK_HOURS)

    apps = Application.objects

    queued = apps.filter(ai_status=S.QUEUED)
    oldest_queued = queued.aggregate(m=Min("updated_at"))["m"]
    in_flight = apps.filter(ai_status__in=S.IN_FLIGHT_STATUSES)
    oldest_flight = in_flight.aggregate(m=Min("updated_at"))["m"]

    queued_wait = _minutes(now, oldest_queued)
    flight_wait = _minutes(now, oldest_flight)
    stuck_cutoff = now - timedelta(minutes=stuck_minutes)

    data = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "queue": {
            "queued": queued.count(),
            "oldest_waiting_minutes": queued_wait,
        },
        "in_flight": {
            "count": in_flight.count(),
            "oldest_minutes": flight_wait,
            "stuck": in_flight.filter(updated_at__lt=stuck_cutoff).count(),
        },
        "last_24h": {
            "completed": apps.filter(ai_status=S.SUCCESS,
                                     ai_processed_at__gte=since).count(),
            "ai_failures": apps.filter(ai_status=S.FAILED,
                                       ai_processed_at__gte=since).count(),
            "unreadable_cv": apps.filter(
                ai_status__in=S.RETRYABLE_DOCUMENT_STATUSES,
                ai_processed_at__gte=since).count(),
        },
        "awaiting_human_decision": _pending(now),
        "thresholds": {"queue_minutes": queue_minutes,
                       "stuck_minutes": stuck_minutes},
    }

    alerts = []
    if queued_wait is not None and queued_wait >= queue_minutes:
        alerts.append("queue_stalled")
    if data["in_flight"]["stuck"]:
        alerts.append("stuck")
    if data["last_24h"]["ai_failures"]:
        alerts.append("ai_failures")
    data["alerts"] = alerts

    data["notes"] = []
    if data["awaiting_human_decision"]["age"].get("over_14_days"):
        data["notes"].append("long_wait")

    return data


def alert_subject(data):
    parts = []
    if "queue_stalled" in data["alerts"]:
        parts.append(f"{data['queue']['queued']} queued and waiting")
    if "stuck" in data["alerts"]:
        parts.append(f"{data['in_flight']['stuck']} stuck")
    if "ai_failures" in data["alerts"]:
        parts.append(f"{data['last_24h']['ai_failures']} AI failure(s) in 24h")
    return "[Pipeline Alert] " + ", ".join(parts)


def _na(value, unit=""):
    return "n/a" if value is None else f"{value}{unit}"


def render_text(data, title="Screening pipeline status"):
    q, f, d = data["queue"], data["in_flight"], data["last_24h"]
    p = data["awaiting_human_decision"]
    lines = [
        title,
        f"Generated at: {data['generated_at']}",
        "",
        "QUEUE AND WORKER",
        f"- Waiting in queue: {q['queued']} "
        f"(oldest waiting: {_na(q['oldest_waiting_minutes'], ' min')})",
        f"- Being processed: {f['count']} "
        f"(oldest: {_na(f['oldest_minutes'], ' min')}; "
        f"looking stuck: {f['stuck']})",
        "",
        "LAST 24 HOURS",
        f"- AI screening completed: {d['completed']}",
        f"- AI screening failures: {d['ai_failures']}",
        f"- CVs the candidate must re-upload (unreadable): {d['unreadable_cv']}",
        "",
        "WAITING FOR A HUMAN DECISION",
        f"- Applications: {p['awaiting_human_decision']}",
        f"- Up to 7 days: {p['age']['up_to_7_days']}",
        f"- 8 to 14 days: {p['age']['8_to_14_days']}",
        f"- Over 14 days: {p['age']['over_14_days']}",
        "",
    ]
    if data["alerts"]:
        lines.append("NEEDS ATTENTION")
        if "queue_stalled" in data["alerts"]:
            lines.append(
                f"- The oldest queued application has waited "
                f"{_na(q['oldest_waiting_minutes'], ' min')} (limit "
                f"{data['thresholds']['queue_minutes']} min). Check that the "
                "worker service is running.")
        if "stuck" in data["alerts"]:
            lines.append(
                f"- {f['stuck']} application(s) have been in processing for "
                f"over {data['thresholds']['stuck_minutes']} min.")
        if "ai_failures" in data["alerts"]:
            lines.append(
                f"- {d['ai_failures']} AI screening failure(s) in the last "
                "24 hours. See the worker logs for the reason.")
        lines.append("")
    if "long_wait" in data["notes"]:
        lines.append(
            f"Note: {p['age']['over_14_days']} application(s) have waited "
            f"more than {LONG_WAIT_DAYS} days for a human decision.")
        lines.append("")
    lines.append("Counts only: no names, emails, ids or document text.")
    return "\n".join(lines)
