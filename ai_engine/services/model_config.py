"""
Phase 20 — single source of truth for which local Ollama model this
system uses, and its Ollama connection URL.

Change the model here ONLY. Every LLM-calling module in this
codebase (llm_service.py, ollama_llm.py, llm_semantic_matcher.py,
llm_reasoning.py) imports MODEL_NAME from this file instead of
declaring its own copy.

============================================================
MODEL SELECTION RECORD (Phase 20)
============================================================

BASELINE model (Phase 1-19, all prior benchmark results):
    gemma3:12b

CURRENT PROTOTYPE model (Phase 20 onward):
    gemma3:4b

Why changed:
    Real dry-run measurements on the target hardware (AMD Ryzen 5
    5625U, 6 cores/12 threads, 16GB RAM, AMD Radeon integrated
    graphics 2GB -- Ollama does not use this iGPU for compute on
    this platform, inference runs on CPU) showed single LLM calls
    taking up to ~6 minutes with gemma3:12b, and a full candidate
    screening (3 sequential LLM calls) taking correspondingly
    longer. This is not workable for a live demo.

Why gemma3:4b specifically (not a different family):
    - Same Gemma 3 family as the baseline -> same prompting
      conventions, same multilingual support (the MULTILINGUAL_
      INSTRUCTION used throughout this codebase for
      English/Portuguese/Tetum/Indonesian CVs was written and
      tuned against Gemma 3's documented language coverage), same
      Ollama `format: json` structured-output support, same LoRA
      adapter compatibility if Phase 16 is ever revisited on
      better hardware later.
    - ~1/3 the parameters of the baseline -> roughly proportionally
      less compute per generated token on CPU, without switching to
      an unfamiliar model family whose behavior on this codebase's
      prompts is untested.
    - Still large enough to follow structured-JSON extraction
      instructions reliably (this is a lighter cognitive load than
      open-ended generation).

Hardware constraints considered: RAM (16GB, gemma3:4b's weights are
a fraction of gemma3:12b's, leaving far more headroom for Django +
FAISS + embedding model running concurrently), CPU-only inference
(no viable GPU acceleration path on this AMD iGPU under Ollama on
Windows), and the explicit instruction not to install multiple
models "just to experiment."

Trade-off (state this honestly in the thesis): a 4B model is
expected to reason somewhat less richly than a 12B model on
ambiguous cases. This is a deliberate, documented speed/quality
trade-off for demo viability, not an unexamined downgrade -- the
40-question RAG benchmark and the screening evaluation are re-run
against gemma3:4b (see rag/evaluation/results/ and the Phase 20
report) specifically so this trade-off is measured, not assumed.

To try a different model, change MODEL_NAME below and re-run:
    ollama pull <model>
    python manage.py evaluate_screening
    python manage.py run_benchmark
and compare against both the gemma3:12b baseline and the gemma3:4b
current-prototype results already on file.
"""

import os

import requests

MODEL_NAME = os.getenv(
    "OLLAMA_MODEL",
    "gemma3:4b"
)

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434"
)

OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"

# Shared safety timeout (Phase 20 Task 2). This is a ceiling for how
# long to wait before giving up, NOT a target processing time -- see
# the Phase 20 report for actual measured durations.
OLLAMA_TIMEOUT_SECONDS = 300

# =====================================================================
# EMERGENCY DEPLOYMENT (public demo) -- provider selection
# =====================================================================
# LLM_PROVIDER switches which backend llm_service.py / ollama_llm.py
# actually call. This does NOT change any prompt, any research logic,
# or any downstream field -- both providers return the same JSON
# shape to the rest of the pipeline.
#
#   LLM_PROVIDER=ollama        -> local Ollama (default, unchanged
#                                  Phase 1-20 behavior, used for local
#                                  development)
#   LLM_PROVIDER=online_gemma  -> Google AI Studio's hosted Gemma API
#                                  (generativelanguage.googleapis.com),
#                                  used for the Render deployment where
#                                  Ollama cannot run
#
# Official Google docs for this endpoint: "Run Gemma with the Gemini
# API" -- https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
# This is Google's own hosted access to the SAME Gemma model family
# used locally, not a different model and not a third-party service.
#
# IMPORTANT -- verified 2026-09-13, found during real STEP 3.2 testing
# (not from static docs alone, an actual HTTP 404 surfaced this):
#   1. Google's hosted Gemma endpoint has moved on from Gemma 3 to
#      Gemma 4 -- as of this date it lists gemma-4-31b-it and
#      gemma-4-26b-a4b-it as the supported models, NOT gemma-3-4b-it
#      (which is what's used locally via Ollama). Requesting an
#      unsupported model name returns HTTP 404, not a model-specific
#      error, which is easy to misread as an auth problem.
#   2. Google is also mid-migration to a new API key format ("AQ."
#      auth keys replacing the older "AIzaSy..." standard keys). The
#      new AQ. keys are REJECTED (also as HTTP 404, not 401/403) when
#      sent the old way, as a `?key=...` URL query parameter -- they
#      must be sent as the `x-goog-api-key` HTTP header instead. This
#      code already does that below. If you generated your API key
#      after this migration, it will only work with the header form.
#   3. Net effect: the deployed model is necessarily a different
#      (larger) Gemma generation than the local Ollama baseline. This
#      is an environment constraint on the hosted API, not a project
#      decision -- document it plainly as a deployment-vs-local
#      difference if it comes up in the thesis.

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

ONLINE_GEMMA_API_KEY = os.getenv("ONLINE_GEMMA_API_KEY", "")

ONLINE_GEMMA_MODEL = os.getenv("ONLINE_GEMMA_MODEL", "gemma-4-26b-a4b-it")

ONLINE_GEMMA_BASE_URL = os.getenv(
    "ONLINE_GEMMA_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta"
)

ONLINE_GEMMA_TIMEOUT_SECONDS = 45
# Lowered from 60 (2026-09-15, approved fix for recurring worker
# timeout incident in AI Assistant / question_decomposer). Two
# separate production incidents showed the actual hang lasting
# 5-9 MINUTES despite this timeout being set to 60s -- requests'
# read-timeout can be reset by a connection that trickles data
# slowly rather than staying fully silent, so the nominal timeout
# value doesn't reliably bound total wait time. This alone doesn't
# fix that underlying behavior, but widens the safety margin to
# gunicorn's hard 120s worker timeout (see Procfile) -- if this
# call is going to hang, cutting it at 45s leaves more room for the
# rest of the request (RAG retrieval, response building) to still
# finish inside gunicorn's limit, and gives the user a clean error
# instead of a SIGKILLed connection.


def call_online_gemma(prompt, want_json=True):
    """
    Calls Google's hosted Gemma API and returns the raw text of the
    model's reply (same contract as Ollama's /api/generate "response"
    field -- callers already parse that into JSON themselves, so this
    keeps that same responsibility split instead of duplicating JSON
    parsing here).

    Shared by llm_service.py (candidate/job profile extraction, fused
    reasoning, RAG job-context) and ollama_llm.py (RAG Assistant
    pipeline) -- both HTTP-calling implementations branch to this one
    function rather than each having their own copy of the online-
    Gemma request logic.

    Raises on any failure (missing API key, network error, non-2xx
    response, unexpected response shape) -- callers already have
    their own try/except and graceful-degradation logic for when
    Ollama fails, so an online-Gemma failure is handled the exact
    same honest way: a clear error, never a silently faked result.
    """

    if not ONLINE_GEMMA_API_KEY:
        raise RuntimeError(
            "ONLINE_GEMMA_API_KEY is not set, but LLM_PROVIDER=online_gemma."
        )

    url = (
        f"{ONLINE_GEMMA_BASE_URL.rstrip('/')}/models/"
        f"{ONLINE_GEMMA_MODEL}:generateContent"
    )

    generation_config = {
        "temperature": 0.1,
        # Verified 2026-09-13 via real testing against a live
        # GitHub-reported issue for this exact model family
        # (google-gemini/cookbook#1198): lowercase "minimal" is
        # accepted by the API without error but does NOT reliably
        # suppress thinking output for gemma-4-*. Uppercase "MINIMAL"
        # is the confirmed-working value.
        "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        # Explicit generous budget -- thinking tokens (even near-zero
        # ones under MINIMAL) are counted against this, so leave
        # headroom for the actual visible answer.
        "maxOutputTokens": 4096
    }

    if want_json:
        generation_config["responseMimeType"] = "application/json"

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": generation_config
    }

    print(f"[DEBUG-KEY-CHECK] provider=online_gemma model={ONLINE_GEMMA_MODEL} key_len={len(ONLINE_GEMMA_API_KEY)} key_prefix={ONLINE_GEMMA_API_KEY[:6]!r} key_suffix={ONLINE_GEMMA_API_KEY[-4:]!r}")

    try:

        response = requests.post(
            url,
            headers={
                "x-goog-api-key": ONLINE_GEMMA_API_KEY,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=ONLINE_GEMMA_TIMEOUT_SECONDS
        )

        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        # requests' own exception message includes the full request
        # URL, which (since the API key is passed as a query param)
        # would otherwise leak the key in plaintext into any log or
        # print() of this exception. Re-raise with that scrubbed.
        status = getattr(e.response, "status_code", "unknown")
        raise RuntimeError(
            f"Online Gemma request failed (HTTP {status})."
        ) from None

    data = response.json()

    try:
        parts = data["candidates"][0]["content"]["parts"]

        # Gemma 4 (with thinking enabled at any level, including
        # MINIMAL) returns the thinking content as a SEPARATE part
        # marked "thought": true, followed by the actual answer in a
        # later part -- confirmed 2026-09-13 via real API response:
        # parts[0] = {"text": "", "thought": true}, parts[1] =
        # {"text": "OK"}. Blindly reading parts[0] (the old code)
        # returns the thought part, which is empty once MINIMAL
        # actually suppresses thinking content -- not a sign the
        # model failed to answer. Skip any part flagged as a thought
        # and join the rest.
        text = "".join(
            part.get("text", "")
            for part in parts
            if not part.get("thought", False)
        )

        if not text:
            raise RuntimeError(
                f"No non-thought text found in response parts: {parts}"
            )

        return text
    except (KeyError, IndexError) as e:
        raise RuntimeError(
            f"Unexpected online Gemma response shape: {data}"
        ) from e