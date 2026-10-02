"""
Language Detection -- TASK D (2026-09-30)

Two layers, because no off-the-shelf language-ID library covers
Tetum (audited: langdetect's supported languages -- see
https://github.com/Mimino666/langdetect -- do not include Tetum,
ISO 639-3 "tet". Tetum has very little digitized training text, so
this is expected, not a langdetect bug).

Layer 1 -- langdetect (new dependency: pure-Python, tiny, works
fully offline, no model download over the network, MIT-licensed):
identifies the GENERAL language (english/portuguese/indonesian/...)
for reporting/research-value purposes only. Cannot recognize Tetum.

Layer 2 -- a small, hand-curated list of highly distinctive Tetum
function words (pronouns, prepositions, particles -- NOT skill or
domain vocabulary, so this is a different thing from the "no large
synonym dictionary" rule from TASK B/C; it's a standard
language-identification technique for under-resourced languages with
no statistical model available). Computes what fraction of the
document's word tokens are these words. THIS is the only signal that
decides whether translation happens -- langdetect's own label is
never used for that decision, only for the reported
"detected_language" value on non-Tetum documents.

THRESHOLD IS A STARTING POINT, NOT FINAL: this sandbox has no real
Tetum CV to calibrate against (same network limitation as TASK B/C's
embedding model). Run

    python manage.py test_language_detection

on your own machine with real Tetum text to see the actual
proportion it produces, and adjust TETUM_SIGNIFICANCE_THRESHOLD below
if that shows a real problem.
"""

import re

try:
    from langdetect import detect_langs, DetectorFactory
    DetectorFactory.seed = 0  # deterministic results across runs
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False


_LANGDETECT_CODE_MAP = {
    "en": "english",
    "pt": "portuguese",
    "id": "indonesian",
}

# Highly distinctive Tetum function words -- pronouns, prepositions,
# conjunctions, particles, a few very common recruitment-adjacent
# words. Chosen to essentially never appear in English, Portuguese
# or Indonesian text. NOT skill/domain vocabulary.
TETUM_STOPWORDS = {
    "husi", "iha", "atu", "nia", "sira", "ita", "ami", "imi",
    "wainhira", "tanba", "maibe", "hodi", "bele", "labele", "tuir",
    "hela", "hotu", "nebe", "ne'ebe", "rasik",
    "ba", "mos", "katak", "hori", "kedas", "agora", "ohin",
    "aban", "horisehik", "sae", "tama", "sai", "hau",
    "governu", "estadu", "serbisu", "knaar", "eskola", "aprende",
}

# Proportion of word tokens that must be Tetum stopwords before
# translation triggers. See module docstring re: calibration.
TETUM_SIGNIFICANCE_THRESHOLD = 0.08

# Per TASK D: text too short for reliable detection -> skip
# detection entirely, use existing fallback (no forced translation).
MIN_WORDS_FOR_DETECTION = 5


# TASK E (job descriptions only): Tetum job ads are mostly requirement
# vocabulary ("tenke", "tinan", "esperiensia", "kualifikasaun"), which the
# CV-oriented list above misses -- a realistic Tetum job ad measured below
# the 8% threshold with that list alone. These extra words are used ONLY
# when a caller passes extra_words=TETUM_JOB_EXTRA_WORDS (job_pipeline.py);
# the default (CV) behaviour is unchanged. All are distinctive Tetum words
# that are not English/Portuguese/Indonesian words.
TETUM_JOB_EXTRA_WORDS = {
    "tenke", "tinan", "ka", "ho", "liu", "kona", "ne'e", "ne'ebé",
    "mós", "mos", "seluk", "presiza", "kandidatu", "pozisaun",
    "kualifikasaun", "esperiénsia", "esperiensia", "konhesimentu",
    "aplikasaun", "dezenvolve", "mantein", "rezolve", "lian",
    "ko'alia", "ofisiál", "ofisial", "hakerek", "diak", "tuun",
}


def _tetum_word_proportion(text, extra_words=None):
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", text.lower())
    if not words:
        return 0.0, 0
    vocabulary = (
        TETUM_STOPWORDS | extra_words if extra_words else TETUM_STOPWORDS
    )
    tetum_hits = sum(1 for w in words if w in vocabulary)
    return tetum_hits / len(words), len(words)


def detect_language(text, extra_words=None):
    """
    Never raises -- worst case returns "unknown" /
    tetum_significant=False, so the pipeline always has something
    safe to continue with.

    Returns:
        {
            "detected_language": "english" | "portuguese" | "indonesian" | "tetum" | "unknown",
            "langdetect_confidence": float or None,
            "tetum_word_proportion": float,
            "tetum_significant": bool,
            "note": str or None,
        }
    """

    text = (text or "").strip()

    tetum_proportion, word_count = _tetum_word_proportion(
        text, extra_words
    )

    if word_count < MIN_WORDS_FOR_DETECTION:
        return {
            "detected_language": "unknown",
            "langdetect_confidence": None,
            "tetum_word_proportion": round(tetum_proportion, 3),
            "tetum_significant": False,
            "note": "Text too short for reliable language detection.",
        }

    detected_language = "unknown"
    langdetect_confidence = None

    if _LANGDETECT_AVAILABLE:
        try:
            candidates = detect_langs(text)
            if candidates:
                top = candidates[0]
                detected_language = _LANGDETECT_CODE_MAP.get(top.lang, top.lang)
                langdetect_confidence = round(float(top.prob), 3)
        except Exception:
            # langdetect raises LangDetectException on some inputs
            # (e.g. no textual features) -- fall through to "unknown"
            # rather than crashing the pipeline.
            pass

    tetum_significant = tetum_proportion >= TETUM_SIGNIFICANCE_THRESHOLD

    return {
        "detected_language": "tetum" if tetum_significant else detected_language,
        "langdetect_confidence": langdetect_confidence,
        "tetum_word_proportion": round(tetum_proportion, 3),
        "tetum_significant": tetum_significant,
        "note": None,
    }