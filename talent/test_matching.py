"""
Candidate-Document Matching (talent/matching.py).

Unit tests use REAL document reading (pypdf) and the real build_unified();
the Rule Engine result is passed in as a hand-written matrix, because the
subject is how the matcher turns profile + documents + that matrix into a
status with evidence.  Integration tests run the real worker and the real
recruitment_pipeline with only the LLM / embedding calls replaced (same
approach as talent/test_documents.py).  All PDFs are synthetic.  No
Ollama is needed.
"""

import copy
from unittest import mock

from django.urls import reverse

from accounts.models import User
from ai_engine.services import recruitment_pipeline as rp
from talent import statuses as S
from talent.matching import (
    INSUFFICIENT, MATCHED, NEEDS_REVIEW, NOT_MATCHED, STATUSES,
    BASIS_BOTH, BASIS_CV, BASIS_DOC,
    match_requirements,
)
from talent.models import ApplicationSupportingDocument as SD
from talent.test_documents import (
    CERT, CERT2, DIPLOMA, DocBase, good_profile, pdf,
)
from talent.test_task_i import encrypted_pdf, native_pdf
from talent.tests import _make_role
from talent.unified import build_unified


def job(**over):
    profile = {
        "job_title": "ICT Officer", "education": "", "skills": [],
        "preferred_skills": [], "languages": [], "certifications": [],
        "years_experience": 0, "professional_summary": "",
    }
    profile.update(over)
    return profile


def rule_result(*rows):
    return {"eligible": True, "matrix": list(rows)}


def row_of(result, requirement_prefix):
    rows = [r for r in result["rows"] if r["requirement"].startswith(requirement_prefix)]
    assert len(rows) == 1, (requirement_prefix, [r["requirement"] for r in result["rows"]])
    return rows[0]


class MatchBase(DocBase):

    def setUp(self):
        super().setUp()
        self.app = self.queue(native_pdf())

    def docs(self):
        return list(self.app.supporting_documents.all())

    def run_match(self, job_profile, profile=None, matrix=(), read=True):
        if read:
            self.processed(self.app)
        profile = profile if profile is not None else good_profile()
        unified = build_unified(self.app, profile)
        return match_requirements(
            job_profile, profile, unified, rule_result(*matrix), self.docs())


# =====================================================================
# Exact (rule-based) matching
# =====================================================================

class ExactMatchTests(MatchBase):

    def test_education_verified_by_diploma_has_document_quote_and_basis(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "diploma.pdf")
        out = self.run_match(
            job(education="Bachelor's degree in Information Technology"),
            good_profile(education=""))
        r = row_of(out, "Education")
        self.assertEqual(r["status"], MATCHED)
        self.assertEqual(r["basis"], BASIS_DOC)
        self.assertTrue(r["verified_by_document"])
        ev = r["evidence"][0]
        self.assertEqual(ev["document"], "diploma.pdf")
        self.assertIn("Bachelor of Science", ev["quote"])
        self.assertEqual(ev["document_type"], SD.TYPE_EDUCATION)

    def test_cv_and_diploma_agree(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "diploma.pdf")
        out = self.run_match(job(education="Bachelor"))
        r = row_of(out, "Education")
        self.assertEqual((r["status"], r["basis"]), (MATCHED, BASIS_BOTH))
        sources = {e["document_type"] for e in r["evidence"]}
        self.assertEqual(sources, {"cv", SD.TYPE_EDUCATION})

    def test_cv_claim_without_document_is_labelled_unverified(self):
        out = self.run_match(job(education="Bachelor"), read=False)
        r = row_of(out, "Education")
        self.assertEqual((r["status"], r["basis"]), (MATCHED, BASIS_CV))
        self.assertFalse(r["verified_by_document"])
        self.assertIn("not verified", r["reason"])

    def test_higher_level_satisfies_a_lower_requirement_and_lower_does_not(self):
        master = [l.replace("Bachelor of Science", "Master of Science") for l in DIPLOMA]
        self.add(self.app, SD.TYPE_EDUCATION, pdf(master), "m.pdf")
        out = self.run_match(job(education="Bachelor degree"),
                             good_profile(education="Master of Science in IT"))
        self.assertEqual(row_of(out, "Education")["status"], MATCHED)

        out = self.run_match(job(education="Master degree"),
                             good_profile(education="Master of Science in IT"), read=False)
        self.assertEqual(row_of(out, "Education")["status"], MATCHED)

    def test_below_requirement_is_not_matched(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "diploma.pdf")
        out = self.run_match(job(education="Master's degree"), good_profile(education=""))
        r = row_of(out, "Education")
        self.assertEqual(r["status"], NOT_MATCHED)
        self.assertEqual(r["basis"], BASIS_DOC)

    def test_alternative_levels_use_the_lowest_one(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "diploma.pdf")
        out = self.run_match(job(education="Bachelor or Master degree"),
                             good_profile(education=""))
        self.assertEqual(row_of(out, "Education")["status"], MATCHED)

    def test_certification_confirmed_by_certificate(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT), "net.pdf")
        out = self.run_match(job(certifications=["Network Fundamentals Training"]))
        r = row_of(out, "Certification")
        self.assertEqual((r["status"], r["basis"]), (MATCHED, BASIS_DOC))
        self.assertEqual(r["evidence"][0]["document"], "net.pdf")
        self.assertIn("Network Fundamentals", r["evidence"][0]["quote"])
        self.assertIsNotNone(r["evidence"][0].get("page"))

    def test_certification_listed_only_in_cv_is_a_claim(self):
        out = self.run_match(
            job(certifications=["First Aid"]),
            good_profile(certifications=["First Aid"]), read=False)
        r = row_of(out, "Certification")
        self.assertEqual((r["status"], r["basis"]), (MATCHED, BASIS_CV))
        self.assertFalse(r["verified_by_document"])

    def test_skill_found_verbatim_in_a_certificate_is_document_verified(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT2), "pm.pdf")
        out = self.run_match(
            job(skills=["Project Management"]),
            good_profile(skills=["Python"]),
            matrix=[{"requirement": "Skill: Project Management", "level": "MISSING"}])
        r = row_of(out, "Skill")
        self.assertEqual((r["status"], r["basis"]), (MATCHED, BASIS_DOC))
        self.assertIn("PROJECT MANAGEMENT", r["evidence"][0]["quote"])
        self.assertEqual(r["evidence"][0]["document"], "pm.pdf")

    def test_skill_substring_of_another_word_is_not_a_hit(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(["CERTIFICATE OF COMPLETION", "This is to certify that Maria da Silva", "has successfully completed JavaScript Basics Training", "Issued by: Example Web Academy"]), "js.pdf")
        out = self.run_match(
            job(skills=["Java"]), good_profile(skills=["Python"]),
            matrix=[{"requirement": "Skill: Java", "level": "MISSING"}])
        self.assertEqual(row_of(out, "Skill")["status"], NOT_MATCHED)

    def test_languages(self):
        out = self.run_match(
            job(languages=["English", "Portuguese"]),
            good_profile(languages=["English"]), read=False)
        self.assertEqual(row_of(out, "Language: English")["status"], MATCHED)
        self.assertEqual(row_of(out, "Language: Portuguese")["status"], NOT_MATCHED)


# =====================================================================
# Semantic: reuse the Rule Engine's level, no second model call
# =====================================================================

class SemanticTests(MatchBase):

    def test_free_text_requirement_reuses_rule_engine_level(self):
        req = "Relevant degree in an ICT-related field"
        for level, expected in (("STRONG_MATCH", MATCHED), ("RELATED", MATCHED),
                                ("PARTIAL", NEEDS_REVIEW), ("MISSING", NEEDS_REVIEW)):
            with self.subTest(level):
                out = self.run_match(
                    job(education=req), good_profile(),
                    matrix=[{"requirement": f"Education: {req}", "level": level}],
                    read=False)
                r = row_of(out, "Education")
                self.assertEqual(r["status"], expected)
                self.assertEqual(r["method"], "semantic_from_rule_engine")

    def test_free_text_requirement_with_unknown_level_is_insufficient(self):
        req = "Relevant degree in an ICT-related field"
        out = self.run_match(
            job(education=req), good_profile(),
            matrix=[{"requirement": f"Education: {req}", "level": "UNKNOWN"}], read=False)
        self.assertEqual(row_of(out, "Education")["status"], INSUFFICIENT)

    def test_skill_semantic_levels(self):
        cases = (("MATCH", MATCHED), ("RELATED", MATCHED),
                 ("PARTIAL", NEEDS_REVIEW), ("MISSING", NOT_MATCHED))
        for level, expected in cases:
            with self.subTest(level):
                out = self.run_match(
                    job(skills=["Cybersecurity"]), good_profile(skills=["Networking"]),
                    matrix=[{"requirement": "Skill: Cybersecurity", "level": level,
                             "matched_candidate_skill": "Networking"}],
                    read=False)
                r = row_of(out, "Skill")
                self.assertEqual(r["status"], expected)
                if expected == MATCHED:
                    self.assertEqual(r["basis"], BASIS_CV)

    def test_experience_levels(self):
        cases = (("MATCH", 5, MATCHED), ("NEAR_REQUIREMENT", 4, MATCHED),
                 ("PARTIAL", 2, NEEDS_REVIEW), ("MISSING", 1, NOT_MATCHED),
                 ("MISSING", 0, INSUFFICIENT))
        for level, years, expected in cases:
            with self.subTest(level, years=years):
                out = self.run_match(
                    job(years_experience=5), good_profile(years_experience=years),
                    matrix=[{"requirement": "Experience: 5.0+ years", "level": level}],
                    read=False)
                r = row_of(out, "Experience")
                self.assertEqual(r["status"], expected)
                self.assertFalse(r["verified_by_document"])

    def test_no_model_call_is_made_by_the_matcher(self):
        from ai_engine.services import llm_service
        from ai_engine.services.embedding_engine import embedding_engine
        with mock.patch.object(embedding_engine, "encode") as enc, \
             mock.patch.object(llm_service, "generate_json") as llm:
            self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
            self.run_match(job(education="Relevant ICT degree", skills=["Python"],
                               years_experience=3, languages=["English"],
                               certifications=["X"]))
        enc.assert_not_called()
        llm.assert_not_called()


# =====================================================================
# Missing evidence / unreadable documents: never an automatic rejection
# =====================================================================

class MissingAndUnreadableTests(MatchBase):

    def test_nothing_found_is_insufficient_not_rejected(self):
        out = self.run_match(
            job(education="Bachelor", skills=["Python"], languages=["English"],
                certifications=["PMP"]),
            good_profile(education="", skills=[], languages=[]), read=False,
            matrix=[{"requirement": "Skill: Python", "level": "MISSING"}])
        for prefix in ("Education", "Skill", "Language", "Certification"):
            self.assertEqual(row_of(out, prefix)["status"], INSUFFICIENT, prefix)
        self.assertEqual(out["summary"][NOT_MATCHED], 0)

    def test_missing_optional_certificates_are_not_evidence_of_absence(self):
        out = self.run_match(job(certifications=["PMP"]), read=False)
        r = row_of(out, "Certification")
        self.assertEqual(r["status"], INSUFFICIENT)
        self.assertIn("optional", r["reason"])

    def test_certificate_uploaded_but_requirement_not_in_it(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT), "net.pdf")
        out = self.run_match(job(certifications=["PMP"]))
        self.assertEqual(row_of(out, "Certification")["status"], NOT_MATCHED)

    def test_unreadable_diploma_with_cv_claim_goes_to_review(self):
        self.add(self.app, SD.TYPE_EDUCATION, b"%PDF-1.4 broken", "diploma.pdf")
        out = self.run_match(job(education="Bachelor"))
        r = row_of(out, "Education")
        self.assertEqual(r["status"], NEEDS_REVIEW)
        self.assertEqual(r["basis"], "none")
        self.assertTrue(out["needs_human_review"])

    def test_unreadable_diploma_never_becomes_not_matched(self):
        self.add(self.app, SD.TYPE_EDUCATION, encrypted_pdf(), "locked.pdf")
        out = self.run_match(job(education="Master's degree"),
                             good_profile(education="Bachelor of IT"))
        self.assertEqual(row_of(out, "Education")["status"], NEEDS_REVIEW)

    def test_unreadable_certificate_blocks_a_not_found_conclusion(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, b"%PDF-1.4 broken", "bad.pdf")
        out = self.run_match(
            job(certifications=["PMP"], skills=["Cybersecurity"]),
            good_profile(skills=["Networking"]),
            matrix=[{"requirement": "Skill: Cybersecurity", "level": "MISSING"}])
        self.assertEqual(row_of(out, "Certification")["status"], NEEDS_REVIEW)
        self.assertEqual(row_of(out, "Skill")["status"], NEEDS_REVIEW)

    def test_pending_document_is_insufficient_not_failed(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")  # not read yet
        out = self.run_match(job(education="Bachelor"), good_profile(education=""),
                             read=False)
        self.assertEqual(row_of(out, "Education")["status"], INSUFFICIENT)

    def test_no_requirements_means_no_rows(self):
        out = self.run_match(job(), read=False)
        self.assertEqual(out["rows"], [])
        self.assertFalse(out["needs_human_review"])


# =====================================================================
# Conflicting documents
# =====================================================================

class ConflictTests(MatchBase):

    def test_cv_and_diploma_levels_disagree(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        out = self.run_match(job(education="Bachelor"),
                             good_profile(education="Master of Science in IT"))
        r = row_of(out, "Education")
        self.assertEqual(r["status"], NEEDS_REVIEW)
        self.assertIn("differs", r["reason"])
        shown = " ".join((e["quote"] or "") for e in r["evidence"])
        self.assertIn("Master", shown)
        self.assertIn("Bachelor", shown)       # both values kept as evidence

    def test_name_on_diploma_differs(self):
        other = [l.replace("Maria da Silva", "Joana Pereira") for l in DIPLOMA]
        self.add(self.app, SD.TYPE_EDUCATION, pdf(other), "d.pdf")
        out = self.run_match(job(education="Bachelor"), good_profile(education=""))
        r = row_of(out, "Education")
        self.assertEqual(r["status"], NEEDS_REVIEW)
        self.assertNotEqual(r["basis"], BASIS_DOC)

    def test_name_on_certificate_differs_is_not_used_as_verification(self):
        other = [l.replace("Maria da Silva", "Joana Pereira") for l in CERT]
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(other), "c.pdf")
        out = self.run_match(job(certifications=["Network Fundamentals Training"],
                                 skills=["Network Fundamentals"]),
                             good_profile(skills=["Python"]),
                             matrix=[{"requirement": "Skill: Network Fundamentals",
                                      "level": "MISSING"}])
        self.assertEqual(row_of(out, "Certification")["status"], NEEDS_REVIEW)
        self.assertNotEqual(row_of(out, "Skill")["basis"], BASIS_DOC)

    def test_two_certificates_with_different_dates(self):
        a = pdf(CERT)
        b = pdf([l.replace("12 March 2022", "5 May 2020") for l in CERT])
        self.add(self.app, SD.TYPE_CERTIFICATE, a, "a.pdf")
        self.add(self.app, SD.TYPE_CERTIFICATE, b, "b.pdf")
        out = self.run_match(job(certifications=["Network Fundamentals Training"]))
        self.assertEqual(row_of(out, "Certification")["status"], NEEDS_REVIEW)


# =====================================================================
# Duplicate information
# =====================================================================

class DuplicateTests(MatchBase):

    def test_duplicate_requirements_give_one_row_each(self):
        out = self.run_match(
            job(skills=["Python", "python", " PYTHON "], languages=["English", "english"]),
            good_profile(), read=False,
            matrix=[{"requirement": "Skill: Python", "level": "STRONG_MATCH"}])
        self.assertEqual(len([r for r in out["rows"] if r["requirement_type"] == "skill"]), 1)
        self.assertEqual(len([r for r in out["rows"] if r["requirement_type"] == "language"]), 1)

    def test_same_certificate_twice_and_in_cv_is_one_row_one_evidence_each(self):
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT), "a.pdf")
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT), "copy-of-a.pdf")
        out = self.run_match(
            job(certifications=["Network Fundamentals Training"]),
            good_profile(certifications=["Network Fundamentals Training"]))
        rows = [r for r in out["rows"] if r["requirement_type"] == "certification"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["basis"]), (MATCHED, BASIS_BOTH))
        keys = [(e["document"], e["quote"]) for e in rows[0]["evidence"]]
        self.assertEqual(len(keys), len(set(keys)))


# =====================================================================
# Output contract + regression
# =====================================================================

class RegressionTests(MatchBase):

    def test_only_the_four_statuses_and_json_serialisable(self):
        import json
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.add(self.app, SD.TYPE_CERTIFICATE, pdf(CERT), "c.pdf")
        out = self.run_match(job(education="Bachelor", skills=["Python"],
                                 languages=["English"], years_experience=2,
                                 certifications=["Network Fundamentals Training"]))
        json.dumps(out)
        self.assertEqual(set(STATUSES),
                         {"matched", "not_matched", "insufficient_evidence",
                          "needs_human_review"})
        for r in out["rows"]:
            self.assertIn(r["status"], STATUSES)
            for e in r["evidence"]:
                self.assertIn("document", e)
        self.assertEqual(sum(out["summary"].values()), len(out["rows"]))

    def test_levels_mirror_the_rule_engine(self):
        from ai_engine.services import recruitment_rules as rr
        from talent import matching
        self.assertEqual(matching.HARD_PASS_LEVELS, rr.HARD_PASS_LEVELS)
        self.assertEqual(matching.UNKNOWN, rr.UNKNOWN)
        from ai_engine.services.skill_gap_analysis import PARTIAL
        self.assertEqual(matching.PARTIAL, PARTIAL)

    def test_inputs_are_not_modified(self):
        self.add(self.app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.processed(self.app)
        profile = good_profile()
        job_profile = job(education="Bachelor", skills=["Python"])
        unified = build_unified(self.app, profile)
        rr = rule_result({"requirement": "Skill: Python", "level": "MATCH"})
        before = copy.deepcopy((profile, job_profile, unified, rr))
        match_requirements(job_profile, profile, unified, rr, self.docs())
        self.assertEqual((profile, job_profile, unified, rr), before)

    def test_empty_or_missing_inputs_do_not_crash(self):
        out = match_requirements({}, {}, {}, {}, [])
        self.assertEqual(out["rows"], [])
        out = match_requirements(None, None, None, None, None)
        self.assertEqual(out["summary"][MATCHED], 0)


# =====================================================================
# Pipeline integration (real worker + pipeline, stubbed LLM/embedding)
# =====================================================================

class PipelineIntegrationTests(DocBase):

    def setUp(self):
        super().setUp()
        self.job.ai_job_profile = job(
            education="Bachelor", skills=["Python"], languages=["English"],
            years_experience=3, certifications=["Network Fundamentals Training"])
        self.job.save()

    def test_matching_is_stored_and_old_outputs_are_unchanged(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c.pdf")
        seen, _ = self.run_real_pipeline(good_profile())
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)

        matching = app.unified_candidate["requirement_matching"]
        self.assertEqual(row_of(matching, "Education")["status"], MATCHED)
        self.assertEqual(row_of(matching, "Certification")["basis"], BASIS_DOC)

        # score, decision and Rule Engine output are exactly what the
        # (stubbed) engines produced: matching added nothing to them
        self.assertEqual(app.ai_score, app.ai_score)
        self.assertEqual(app.ai_rule_result,
                         {"eligible": True, "passed_rules": [], "failed_rules": [],
                          "warnings": [], "matrix": []})
        self.assertNotIn("requirement_matching", app.ai_rule_result)
        self.assertEqual(len(seen["cv_prompts"]), 1)       # CV analysed once

    def test_cv_only_application_gets_matching_without_documents(self):
        app = self.queue(native_pdf())
        self.run_real_pipeline(good_profile())
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        matching = app.unified_candidate["requirement_matching"]
        edu = row_of(matching, "Education")
        self.assertEqual((edu["status"], edu["basis"]), (MATCHED, BASIS_CV))
        self.assertEqual(row_of(matching, "Certification")["status"], INSUFFICIENT)

    def test_matching_failure_never_blocks_screening(self):
        app = self.queue(native_pdf())
        with mock.patch("talent.matching.match_requirements",
                        side_effect=RuntimeError("boom")):
            self.run_real_pipeline(good_profile())
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        self.assertNotIn("requirement_matching", app.unified_candidate)

    def test_unreadable_document_flags_review_and_does_not_reject(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, b"%PDF-1.4 broken", "bad.pdf")
        self.run_real_pipeline(good_profile())
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        matching = app.unified_candidate["requirement_matching"]
        self.assertEqual(row_of(matching, "Education")["status"], NEEDS_REVIEW)
        self.assertTrue(matching["needs_human_review"])

    def test_detail_page_shows_matching_to_staff_only(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.run_real_pipeline(good_profile())

        self.client.login(email="ti@x.com", password="pass12345")
        page = self.client.get(reverse("candidate_detail", args=[app.id])).content.decode()
        self.assertNotIn("Document-Grounded Requirement Matching", page)
        self.client.logout()

        User.objects.create_user(
            username="hr", password="pass12345", email="hr@x.com",
            role=_make_role("HR Officer", ["recruitment_manage"]), is_verified=True)
        self.client.login(email="hr@x.com", password="pass12345")
        page = self.client.get(reverse("candidate_detail", args=[app.id])).content.decode()
        self.assertIn("Document-Grounded Requirement Matching", page)
        self.assertIn("Matched", page)
        self.assertIn("d.pdf", page)
