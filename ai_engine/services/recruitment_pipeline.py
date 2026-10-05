import hashlib
import json
import logging

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from django.core.cache import cache
from .language_detection import detect_language
from .translation import translate_tetum_to_english
from django.utils import timezone

logger = logging.getLogger(__name__)

from .llm_candidate_profile import analyze_cv, DEFAULT_PROFILE
from .llm_reasoning import generate_recruitment_assessment, split_assessment
from .skill_gap_analysis import skill_gap_analysis
from .recruitment_rules import evaluate_recruitment_rules
from .model_config import MODEL_NAME as LLM_MODEL_NAME
from .model_config import NEW_CANDIDATE_RAG
from .candidate_legal_rag import get_candidate_legal_evidence

# APPLY JOB OPTIMIZATION PHASE (2026-10-04) -- candidate-profile cache.
#
# WHY: profiling showed analyze_cv() (STEP 1, one full LLM call with
# up to 3 attempts) costs ~30s+ on a real run. That cost is paid
# again, unchanged, if the SAME candidate applies to a DIFFERENT job
# with the SAME CV text -- the profile (education/skills/experience
# extracted from the CV) is a pure function of `processing_text` and
# does NOT depend on which job is being applied to. This mirrors the
# exact SHA-256-keyed caching pattern already used and documented for
# document extraction (see ai_engine/services/document_extraction/
# router.py) -- same rationale, same mechanism, no new dependency.
#
# SAFETY: a cache hit returns the EXACT SAME dict a fresh analyze_cv()
# call would have returned for byte-identical input text -- this is
# not an approximation or a shortcut that changes what gets computed,
# only *when* it gets (re)computed. Only a profile that already PASSED
# the existing validity guard below is ever cached, so a transient LLM
# failure can never get "stuck" in the cache. The fused-reasoning call
# (STEP 3, the actual per-job recruitment decision) is NEVER cached.
CANDIDATE_PROFILE_CACHE_KEY_PREFIX = "candidate_profile:v1:"
CANDIDATE_PROFILE_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h


def _candidate_profile_cache_key(processing_text):
    digest = hashlib.sha256(processing_text.encode("utf-8")).hexdigest()
    return f"{CANDIDATE_PROFILE_CACHE_KEY_PREFIX}{digest}"


LLM_PROVIDER_NAME = "Ollama (local)"

# Phase 20 (F1): bumped from 1.0.0 -- the live pipeline now makes 2
# sequential LLM calls per application (analyze_cv + one fused
# reasoning call) instead of 3 (analyze_cv + semantic_match +
# generate_explainable_report). Recorded per-application via the
# Audit Trail (Phase 18) so Phase 1-19 baseline runs and Phase 20
# runs are distinguishable in stored data, not just in git history.
AI_PIPELINE_VERSION = "2.0.0-phase20-fused-reasoning"


ALLOWED_DECISIONS = [
    "Highly Recommended",
    "Recommended",
    "Consider",
    "Not Recommended"
]


def normalize_decision(raw_decision):
    """
    The decision label is LLM-generated free text. Map it to the
    canonical whitelist so the UI never has to render an
    unrecognized label; anything unmatched falls back to "Consider"
    so it still surfaces for human review rather than being silently
    dropped.
    """

    text = (raw_decision or "").strip().lower()

    for option in ALLOWED_DECISIONS:
        if option.lower() == text:
            return option

    if "highly" in text:
        return "Highly Recommended"

    if "not" in text:
        return "Not Recommended"

    if "recommend" in text:
        return "Recommended"

    return "Consider"


def clamp_0_100(raw_value):
    """Guarantee an integer 0-100 regardless of what the LLM returns."""

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return 0

    return int(max(0, min(100, round(value))))


RAG_POLICY_SCORE_PLACEHOLDER = 80


def compute_final_score(
    rule_eligible,
    skill_match_score,
    semantic_score,
    rag_score=RAG_POLICY_SCORE_PLACEHOLDER
):
    """
    Decision Fusion Formula — single source of truth for the final
    ai_score, shared by the live pipeline and the demo-data seeder
    so seeded scores can never drift from what the real pipeline
    would compute for the same inputs.

    Weighting per thesis methodology:
      Rule Match (skill %)   40%
      LLM Semantic Match     40%
      RAG Engine Policy      20%

    UPDATED (thesis honesty): rag_score is now populated from a real
    RAG query against the CSC legal/policy corpus (see
    rag_screening_context.py + job_pipeline.py) whenever that query
    succeeded at job-creation time. The `RAG_POLICY_SCORE_PLACEHOLDER`
    default below is used ONLY as a fallback when the RAG/Ollama call
    failed or returned no evidence — never as the normal case.

    Known remaining limitation, state this honestly if asked: the
    RAG query is keyed on job title only, computed once per job and
    cached (see recruitment_pipeline.py), not re-run per candidate.
    It answers "what does policy require for this type of role",
    not "how well does this specific person's CV comply" — so this
    term is currently identical for every applicant to the same job,
    not yet a per-candidate compliance signal.

    If the rule engine's hard gate fails (eligible=False), the score
    is capped below the pass threshold regardless of how well
    semantic/skill matching went, so a candidate disqualified by
    hard requirements can never surface as a high score.
    """

    skill_match_score = clamp_0_100(skill_match_score)
    semantic_score = clamp_0_100(semantic_score)
    rag_score = clamp_0_100(rag_score)

    if not rule_eligible:

        final_score = int(
            (skill_match_score * 0.4)
            + (semantic_score * 0.4)
        )

        final_score = min(final_score, 49)

    else:

        final_score = int(
            (skill_match_score * 0.4)
            + (semantic_score * 0.4)
            + (rag_score * 0.2)
        )

    return max(0, min(100, final_score))


def recruitment_pipeline(application):

    start = perf_counter()

    try:

        # =====================================
        # Load Data
        # =====================================

        cv_text = application.candidate.extracted_text

        if not cv_text:

            raise ValueError(
                "Candidate CV text is empty."
            )

        job_profile = application.job.ai_job_profile

        if not job_profile:

            raise ValueError(
                "Job AI Profile has not been generated."
            )

        # Knowledge-Infused Screening: reuse the RAG policy context
        # cached on the job at creation time (see job_pipeline.py).
        # This is a per-job snapshot, not a per-candidate query --
        # copied onto the Application so the evidence a given
        # decision relied on stays fixed even if the job's cached
        # context were ever recomputed later.
        rag_context = application.job.ai_rag_context or {}

        # =====================================
        # STEP 0 (TASK D, 2026-09-30)
        # Language Detection + Conditional Tetum Translation
        # =====================================
        # Runs BEFORE the candidate profile is built -- translating
        # after profile extraction would mean the profile itself was
        # already built from text the pipeline doesn't understand
        # well. `cv_text` (original, saved on the Candidate at upload
        # time) is NEVER overwritten here or anywhere below --
        # `processing_text` is what every downstream step actually
        # uses. No LLM call at all for English/Portuguese/Indonesian
        # documents (translate_tetum_to_english only runs when
        # tetum_significant is True).
        # =====================================

        language_result = detect_language(cv_text)

        if language_result["tetum_significant"]:
            translation_result = translate_tetum_to_english(cv_text)
            processing_text = translation_result["translated_text"]
        else:
            translation_result = None
            processing_text = cv_text

        t_lang = perf_counter()

        # =====================================
        # STEP 1
        # Candidate Intelligence Profile
        # =====================================

        profile_cache_key = _candidate_profile_cache_key(processing_text)

        cached_profile = cache.get(profile_cache_key)

        profile_cache_hit = cached_profile is not None

        if profile_cache_hit:

            profile = cached_profile

            logger.info(
                "[APPLY-JOB-TIMING] candidate profile cache hit "
                "(key=%s...) -- skipping analyze_cv() LLM call.",
                profile_cache_key[-12:]
            )

        else:

            profile = analyze_cv(
                processing_text
            )
        # Bug fix (2026-09-25): analyze_cv() can legitimately exhaust
        # MAX_ATTEMPTS and return a plain {} when the LLM's JSON-mode
        # decoding stalls (see llm_candidate_profile.py comment) -- this
        # is a TECHNICAL PARSING FAILURE, not a candidate with an empty
        # CV. A real (even weak) profile always carries the schema's
        # keys, just with empty/zero values, per DEFAULT_PROFILE and the
        # prompt's own "Missing information should be empty" rule. A
        # dict missing every one of those keys is only reachable via the
        # {} failure path, so it is a safe, narrow signal -- it can't
        # misclassify a genuinely sparse but successfully-parsed CV.
        #
        # Routed through the SAME existing failure mechanism this
        # pipeline already uses for every other precondition failure
        # above (empty CV text, missing job profile): raise, and the
        # existing except block below records ai_status="FAILED" with
        # the reason in ai_feedback, saves the application, and
        # re-raises -- talent/views.py already catches that and tells
        # the candidate/recruiter the AI analysis could not complete,
        # instead of this silently becoming a false "Not Recommended
        # 0%" screening decision. No new decision logic, no Rule Engine
        # change, no scoring change.
        #
        # Second bug (audited 2026-09-25, confirmed via mocked
        # simulation -- see scratchpad/simulate_cv_parse_failure.py,
        # no real candidate data used): the FIRST branch above only
        # catches the "all 3 attempts returned a literal {}" case. A
        # separate failure shape exists -- generate_json() raising an
        # EXCEPTION on all 3 attempts -- for which analyze_cv()'s own
        # except-block (llm_candidate_profile.py) returns
        # DEFAULT_PROFILE.copy() plus an "error" key. That dict DOES
        # carry every DEFAULT_PROFILE key, so it silently passed the
        # first check and would have been fed to the Rule Engine as if
        # it were a real (if empty) candidate profile -- simulation
        # confirmed this produces a normal-looking eligible=False
        # rule result instead of a detected technical failure.
        # "error" is not a field in DEFAULT_PROFILE / the CV-parsing
        # schema, so its presence at the top level of `profile` is
        # only ever produced by that one except-block -- a safe,
        # narrow signal that adds no new decision logic, just widens
        # the existing failure guard to this second proven shape.
        if not any(key in profile for key in DEFAULT_PROFILE) or "error" in profile:

            raise ValueError(
                "CV parsing failed after multiple attempts: the AI "
                "service returned no structured profile data. This is "
                "a technical failure, not a candidate qualification "
                "assessment."
            )

        if not profile_cache_hit:
            # Only a profile that already passed the validity guard
            # above is ever cached -- a technical-failure profile is
            # never cached, so it can never get "stuck"; the next
            # application for this exact CV text simply retries
            # analyze_cv() for real.
            cache.set(
                profile_cache_key,
                profile,
                timeout=CANDIDATE_PROFILE_CACHE_TTL_SECONDS
            )

        t_profile = perf_counter()

        # =====================================
        # STEP 2
        # Deterministic Parallel Analysis
        # (Phase 20: no LLM call here anymore -- both of these are
        # pure Python, evaluated against the already-extracted
        # profile/job_profile. Semantic matching moved into STEP 3,
        # fused with the explainable reasoning call.)
        # =====================================

        with ThreadPoolExecutor(max_workers=2) as executor:

            future_rule = executor.submit(
                evaluate_recruitment_rules,
                profile,
                job_profile
            )

            future_gap = executor.submit(
                skill_gap_analysis,
                profile.get("skills", []),
                job_profile.get("skills", [])
            )

            rule_result = future_rule.result()

            gap_result = future_gap.result()
            t_rule_skill = perf_counter()

        # =====================================
        # STEP 2.5 (Phase 21, research, gated by NEW_CANDIDATE_RAG)
        # Candidate-Specific Legal RAG
        #
        # Runs AFTER the rule engine so it can use rule_result["matrix"]
        # to target only the dimensions that actually have a gap
        # (see candidate_legal_rag.py). Runs BEFORE the fused
        # reasoning call so the evidence can be included in its
        # prompt. Never raises -- degrades to {} on any failure so
        # application submission is never blocked by this step
        # (design report Section E / instruction #18).
        # =====================================

        candidate_legal_evidence = {}

        candidate_rag_stats = None

        if NEW_CANDIDATE_RAG:

            try:

                candidate_legal_evidence, candidate_rag_stats = (
                    get_candidate_legal_evidence(
                        profile=profile,
                        job_profile=job_profile,
                        rule_result=rule_result
                    )
                )

                print("\n===== CANDIDATE LEGAL RAG =====")
                print(json.dumps(candidate_rag_stats, indent=2))
                print("================================\n")

            except Exception as e:

                # Belt-and-braces -- get_candidate_legal_evidence()
                # already catches internally and should never raise,
                # but this step must be unconditionally non-fatal.
                print("Candidate Legal RAG Error:", str(e))

                candidate_legal_evidence = {}

        t_legal_rag = perf_counter()

        # =====================================
        # STEP 3
        # Fused Semantic Matching + Explainable AI
        # (Phase 20 / F1: ONE LLM call producing both the
        # per-dimension semantic assessment and the explainable
        # decision, instead of two separate sequential calls. See
        # llm_reasoning.py for the baseline-vs-fused rationale.)
        # =====================================

        assessment = generate_recruitment_assessment(
            profile=profile,
            job_profile=job_profile,
            rule_result=rule_result,
            gap_result=gap_result,
            rag_context=rag_context,
            candidate_legal_evidence=candidate_legal_evidence
        )

        t_fused = perf_counter()

        semantic_result, report = split_assessment(assessment)

        rule_eligible = rule_result.get("eligible", False)

        skill_match_score = gap_result.get("match_score", 0)

        semantic_score = semantic_result.get("overall_score", 0)

        # Dynamic RAG score: best_evidence_score is a 0-1 float from
        # the RAG evidence gate, scaled to the same 0-100 range as
        # the other two components. If the cached job context is
        # missing, empty, or recorded an error (RAG/Ollama was
        # unreachable when the job was created), fall back to the
        # static placeholder rather than silently scoring every
        # candidate for that job as 0 through no fault of their own.
        if rag_context.get("error") or not rag_context.get("evidence"):

            rag_score = RAG_POLICY_SCORE_PLACEHOLDER

        else:

            rag_score = rag_context.get("best_evidence_score", 0) * 100

        final_score = compute_final_score(
            rule_eligible=rule_eligible,
            skill_match_score=skill_match_score,
            semantic_score=semantic_score,
            rag_score=rag_score
        )

        # =====================================
        # Save Result
        # =====================================

        application.ai_profile = profile

        application.ai_job_profile = job_profile

        application.ai_rule_result = rule_result

        application.ai_semantic_result = semantic_result

        application.ai_skill_gap = gap_result

        # Backward-compatible storage (instruction #17): every
        # existing job-level key (query/answer/evidence/
        # best_evidence_score/grounded/error) stays flat at the top
        # level exactly as Phase 1-20 wrote it, so compute_final_score()
        # above and every existing template/consumer that reads
        # application.ai_rag_context.get("best_evidence_score") etc.
        # needs no change. "candidate_legal_evidence" is added as one
        # extra key, present only when NEW_CANDIDATE_RAG actually ran;
        # absent (not an error) otherwise -- so `.get(
        # "candidate_legal_evidence", {})` is always safe downstream.
        #
        # (Deliberate deviation from the literal {"job_context": {},
        # "candidate_legal_evidence": {}} nested shape suggested in
        # the design brief: that would require updating every
        # existing flat-key consumer of ai_rag_context -- exactly the
        # kind of broad, riskier change instruction #2/#27 asks to
        # avoid for this first pass. Flagged here explicitly rather
        # than silently diverging.)
        application.ai_rag_context = {
            **rag_context,
            **(
                {"candidate_legal_evidence": candidate_legal_evidence}
                if candidate_legal_evidence else {}
            ),
            "language_detection": language_result,
            **(
                {
                    "translation": {
                        "translated": translation_result["success"],
                        "error": translation_result["error"],
                    }
                }
                if translation_result else {}
            )
        }

        application.ai_explainable_report = report

        application.ai_score = final_score

        application.ai_decision = normalize_decision(
            report.get("decision", "")
        )

        application.ai_confidence = clamp_0_100(
            report.get("confidence", 0)
        )

        application.ai_feedback = report.get(
            "recommendation",
            ""
        )

        # Audit Trail (Phase 18): record which model/provider/version
        # actually produced this decision, rather than relying on the
        # field's static default -- so the value here is genuinely
        # traceable even if the model or version changes later.
        application.ai_model = LLM_MODEL_NAME

        application.ai_provider = LLM_PROVIDER_NAME

        application.ai_version = AI_PIPELINE_VERSION

        application.ai_processing_time = round(
            perf_counter() - start,
            2
        )

        application.ai_processed_at = timezone.now()

        application.ai_status = "SUCCESS"

        application.save()

        t_save = perf_counter()

        # APPLY JOB OPTIMIZATION (2026-10-04): per-stage timing
        # breakdown -- additive observability only, changes no
        # behavior/decision/score.
        print(
            "[APPLY-JOB-TIMING] "
            f"lang_detect_translate={t_lang - start:.2f}s "
            f"candidate_profile={t_profile - t_lang:.2f}s"
            f"(cache_hit={profile_cache_hit}) "
            f"rule_engine_skill_match={t_rule_skill - t_profile:.2f}s "
            f"candidate_legal_rag={t_legal_rag - t_rule_skill:.2f}s"
            f"(enabled={NEW_CANDIDATE_RAG}) "
            f"fused_reasoning={t_fused - t_legal_rag:.2f}s "
            f"db_save={t_save - t_fused:.2f}s "
            f"TOTAL={t_save - start:.2f}s"
        )

        return application

    except Exception as e:

        application.ai_status = "FAILED"

        application.ai_feedback = str(e)

        application.ai_processing_time = round(
            perf_counter() - start,
            2
        )

        application.ai_processed_at = timezone.now()

        application.save()

        raise