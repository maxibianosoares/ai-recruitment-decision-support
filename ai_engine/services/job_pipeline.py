from time import perf_counter
from django.utils import timezone

from .llm_job_parser import analyze_job_description, DEFAULT_JOB_PROFILE
from .rag_screening_context import get_rag_screening_context
from .language_detection import detect_language, TETUM_JOB_EXTRA_WORDS
from .translation import translate_tetum_to_english


def _prepare_job_text(description):
    """
    TASK E -- Tetum job-description handling. Never raises.

    Returns (processing_text, info).
      English / Portuguese / Indonesian / unknown / insignificant Tetum
          -> processing_text is the ORIGINAL description, NO LLM call.
      Significant Tetum
          -> ONE Tetum->English translation call; processing_text is the
             English text. If translation fails, falls back to the
             original text.
    job.description itself is never modified.
    """
    info = {
        "detected_language": "unknown",
        "tetum_word_proportion": 0.0,
        "translation": "not_needed",
        "processing_language": "original",
        "detection_seconds": 0.0,
        "translation_seconds": 0.0,
    }
    text = description or ""

    try:
        t0 = perf_counter()
        detection = detect_language(
            text, extra_words=TETUM_JOB_EXTRA_WORDS
        )
        info["detection_seconds"] = round(perf_counter() - t0, 3)
        info["detected_language"] = detection["detected_language"]
        info["tetum_word_proportion"] = detection["tetum_word_proportion"]
        tetum = bool(detection["tetum_significant"])
    except Exception as e:
        print(f"Job language detection failed: {e} -- using original text")
        return text, info

    print(f"Job language detected: {info['detected_language']}")

    if not tetum:
        return text, info

    try:
        t1 = perf_counter()
        result = translate_tetum_to_english(text, document_type="job")
        info["translation_seconds"] = round(perf_counter() - t1, 3)
    except Exception as e:
        print(f"Tetum translation: failed ({e})\nFallback: original text")
        info["translation"] = "failed"
        return text, info

    if result.get("success"):
        info["translation"] = "success"
        info["processing_language"] = "english"
        print("Tetum translation: success")
        print("Job profiling language: English")
        return result["translated_text"], info

    info["translation"] = "failed"
    print("Tetum translation: failed\nFallback: original text")
    return text, info


def process_job(job):

    start = perf_counter()

    # TASK E: only a significant-Tetum description is translated (one
    # call); everything else is passed through exactly as before.
    # The job form has a separate "requirements" field (education,
    # experience, mandatory skills, languages). It was never read, so
    # those requirements never reached the profile. Include it, so the
    # description AND the requirements are profiled (and, for Tetum,
    # translated) in the same single pass.
    source_text = job.description or ""
    requirements_text = (getattr(job, "requirements", "") or "").strip()
    if requirements_text:
        source_text = f"{source_text}\n\nRequirements:\n{requirements_text}"

    processing_text, language_info = _prepare_job_text(source_text)

    _t = perf_counter()
    profile = analyze_job_description(
        processing_text
    )
    language_info["profiling_seconds"] = round(perf_counter() - _t, 2)

    # Widened 2026-09-26 (same root cause/fix as
    # recruitment_pipeline.py's analogous guard): a bare `if not
    # profile:` treats ANY non-empty list as valid, including a
    # multi-item array shape that analyze_job_description()'s own
    # normalization intentionally leaves unwrapped (no safe single
    # object to pick). Checking for a dict carrying at least one
    # DEFAULT_JOB_PROFILE key (and rejecting the existing "error" key
    # from analyze_job_description()'s own exception path) closes that
    # gap without changing behavior for the normal case.
    if (
        not isinstance(profile, dict)
        or not any(key in profile for key in DEFAULT_JOB_PROFILE)
        or "error" in profile
    ):
        raise ValueError(
            "AI service returned an invalid or empty job profile "
            "(the LLM may be unreachable, or returned an unexpected "
            "response shape)."
        )

    print("\n====================================")
    print("ICT OFFICER JOB PROFILE")
    print("====================================")
    print(profile)
    print("====================================\n")

    job.ai_job_profile = profile

    # Knowledge-Infused Screening: one live RAG query per job,
    # cached here so every applicant to this job reuses the same
    # policy evidence instead of re-querying RAG identically on
    # every single application. Never raises — a RAG/Ollama failure
    # here degrades to an empty context (handled downstream by
    # recruitment_pipeline's fallback to the static placeholder
    # weight), it does not block job creation.
    job.ai_rag_context = get_rag_screening_context(job.title)

    # TASK E: small metadata only (no translated text, no migration),
    # kept inside the existing JSON field; every existing consumer reads
    # specific keys, so an extra key is harmless.
    if isinstance(job.ai_rag_context, dict):
        job.ai_rag_context["job_language"] = language_info

    job.ai_processed = True

    job.ai_processing_time = round(
        perf_counter() - start,
        2
    )

    job.ai_processed_at = timezone.now()

    job.save()

    return job