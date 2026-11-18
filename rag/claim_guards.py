"""Deterministic guards used before/alongside the LLM claim verifier.

Pure Python (no faiss / LLM imports) so they are unit-testable anywhere and apply to every
document set, not to any one notice.

Three guards:
  * temporal   - is the claim asking for a CURRENT fact? (whole-word match; "presented" or
                 "snow" must not count as "present" / "now")
  * identifier - a vacancy code such as CPI/3/2026 named in the claim must appear in the
                 evidence, otherwise the evidence is about something else
  * rank       - a seniority qualifier (senior, junior, chief ...) named in the claim must
                 appear in the evidence, otherwise the evidence is about a different grade
"""
import re
import unicodedata

CURRENT_PATTERNS = [
    r"currently", r"current", r"today", r"now", r"latest", r"existing",
    r"at present", r"presently", r"the present", r"right now", r"still",
    r"serving", r"incumbent",
]

HISTORICAL_MARKERS = [
    "promulgated", "promulgada", "promulgado", "published", "publique-se",
    "jornal da república", "decreto-lei", "lei no.", "lei n.º", "law no.",
] + [f"in {y}" for y in range(2008, 2026)]

RANK_QUALIFIERS = ["senior", "junior", "chief", "deputy", "principal", "trainee", "intern",
                   "sénior", "júnior", "chefe"]

# Vacancy/notice codes only (CPI/3/2026). Bare law numbers (34/2008) are NOT checked: a chunk
# of a statute rarely repeats its own number, so requiring it would reject valid evidence.
_ID_RE = re.compile(r"\b[A-Za-z]{2,}/\d{1,4}/\d{4}\b")


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def _has_word(pattern, text):
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", _norm(text)) is not None


def is_current_claim(claim):
    return any(_has_word(p, claim) for p in CURRENT_PATTERNS)


def has_historical_evidence(evidence):
    low = (evidence or "").lower()
    return any(m in low for m in HISTORICAL_MARKERS)


def temporal_guard(claim, evidence):
    if is_current_claim(claim) and has_historical_evidence(evidence):
        return {"blocked": True, "reason": (
            "The claim asks for a current or present fact, but the retrieved evidence "
            "contains historical or dated information and does not establish current validity.")}
    return {"blocked": False, "reason": ""}


def identifiers(text):
    return {m.group(0).upper() for m in _ID_RE.finditer(text or "")}


def identifier_guard(claim, evidence):
    """Every code named in the claim must occur in the evidence."""
    ev = _norm(evidence).upper()
    missing = sorted(i for i in identifiers(claim) if i not in ev)
    if missing:
        return {"blocked": True, "reason": (
            "The claim names " + ", ".join(missing) + ", which does not appear in the "
            "retrieved evidence; the evidence is about something else.")}
    return {"blocked": False, "reason": ""}


def rank_guard(claim, evidence):
    """A seniority qualifier in the claim must occur in the evidence."""
    asked = [q for q in RANK_QUALIFIERS if _has_word(re.escape(_norm(q)), claim)]
    missing = [q for q in asked if not _has_word(re.escape(_norm(q)), evidence)]
    if missing:
        return {"blocked": True, "reason": (
            "The claim names the grade/rank '" + "', '".join(missing) + "', which does not "
            "appear in the retrieved evidence; the evidence covers a different grade.")}
    return {"blocked": False, "reason": ""}


def run_guards(claim, evidence):
    """First blocking guard wins. Returns {"blocked": bool, "reason": str, "guard": str}."""
    for name, fn in (("temporal", temporal_guard), ("identifier", identifier_guard),
                     ("rank", rank_guard)):
        r = fn(claim, evidence)
        if r["blocked"]:
            return {**r, "guard": name}
    return {"blocked": False, "reason": "", "guard": ""}


def scope_results(claim, results):
    """Keep only retrieved chunks that mention every vacancy code named in the claim.

    Notices built from one template have near-identical sentences across vacancies; without this
    the verifier is shown other vacancies' text and gets confused. If the claim names no code, or
    no chunk mentions it, the results are returned unchanged (identifier_guard then decides).
    """
    codes = identifiers(claim)
    if not codes:
        return results
    kept = [r for r in results
            if all(c in _norm(r.get("text", "")).upper() for c in codes)]
    return kept or results


def retrieve_scoped(claim, search, top_k=3, wide_k=10):
    """search(query, top_k=n) -> list of {"text","score","source"}; returns top_k scoped results."""
    if not identifiers(claim):
        return search(claim, top_k=top_k)
    return scope_results(claim, search(claim, top_k=wide_k))[:top_k]


# ---------------------------------------------------------------------------
# Decomposition clean-up
# ---------------------------------------------------------------------------
# The LLM decomposer sometimes emits a bare phrase as its own "claim" ("at HNGV",
# "for public administration staff in the general rules?"). Such a fragment is trivially
# "supported" by retrieval and lifts the question's status, hiding an unsupported main claim.
_FRAGMENT_RE = re.compile(
    r"^(?:at|in|on|for|to|of|by|with|from|under|within|during|according to|regarding|about|"
    r"per|as|and|or|than|against|between|among)\b", re.IGNORECASE)


_WH_RE = re.compile(r"\b(what|which|who|whom|whose|when|where|why|how)\b", re.IGNORECASE)


def is_fragment(text):
    """A bare phrase, not a question/statement. "At which stage ...?" is NOT a fragment."""
    t = (text or "").strip()
    if len(t.split()) < 3:
        return True
    if _FRAGMENT_RE.match(t):
        return not _WH_RE.search(" ".join(t.split()[:4]))
    return False


def clean_claims(claims, question):
    """Merge fragment claims into the preceding claim, then restore identity qualifiers.

    * a fragment is appended to the previous claim, so its words (e.g. a vacancy code) are kept
    * a vacancy code or rank qualifier present in the question but in NO claim is appended to
      the first claim, so identifier_guard / rank_guard can still see it
    Returns claims re-numbered C1..Cn. Never returns an empty list.
    """
    merged = []
    for c in claims:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        if merged and is_fragment(text):
            prev = merged[-1]["text"].rstrip(" ?.")
            frag = text.rstrip(" ?.")
            frag = frag[:1].lower() + frag[1:]
            merged[-1]["text"] = f"{prev}, {frag}?"
        else:
            merged.append({"text": text})
    if not merged:
        merged = [{"text": question}]

    joined = _norm(" ".join(m["text"] for m in merged))
    lost = []
    for q in RANK_QUALIFIERS:
        nq = _norm(q)
        if nq in lost:
            continue
        if _has_word(re.escape(nq), question) and not _has_word(re.escape(nq), joined):
            lost.append(nq)
    lost += sorted(i for i in identifiers(question) if i.lower() not in joined)
    if lost:
        merged[0]["text"] = merged[0]["text"].rstrip(" ?.") + " (" + ", ".join(lost) + ")?"
    return [{"id": f"C{i}", "text": m["text"]} for i, m in enumerate(merged, 1)]


# ---------------------------------------------------------------------------
# Aggregation (supports an optional per-claim "partial" verdict)
# ---------------------------------------------------------------------------
def aggregate_status(evaluated):
    total = len(evaluated)
    full = sum(1 for c in evaluated if c.get("supported"))
    part = sum(1 for c in evaluated if not c.get("supported") and c.get("partial"))
    coverage = (full + 0.5 * part) / total if total else 0
    if full == 0 and part == 0:
        status = "unsupported"
    elif full == total:
        status = "supported"
    else:
        status = "partially_supported"
    return {"status": status, "coverage": coverage, "supported_claims": full,
            "partial_claims": part, "total_claims": total}
