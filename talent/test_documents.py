"""
Multi-document upload and unified candidate object.

Follows talent/test_task_i.py: REAL document extraction (pypdf, Poppler,
Tesseract) and the real worker command run in these tests; only the LLM /
embedding calls inside the AI pipeline and the Notification #1 sender are
replaced, because the subject here is WHAT the documents contribute and
WHEN, not model quality.  All PDFs are synthetic.  No Ollama is needed.
"""

import copy
import io
import logging
import shutil
from io import StringIO
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from accounts.models import User
from ai_engine.services import recruitment_pipeline as rp
from ai_engine.services.document_extraction import orchestrator
from ai_engine.test_document_extraction import (
    _make_digital_pdf,
    _make_scanned_pdf,
)
from talent import statuses as S
from talent.documents import (
    MAX_CERTIFICATES,
    process_pending_supporting_documents,
    store_supporting_documents,
    validate_uploads,
)
from talent.models import (
    Application,
    ApplicationDocument,
    ApplicationSupportingDocument as SD,
)
from talent.test_task_i import (
    TaskIBase,
    WORKER,
    _bytes_of,
    encrypted_pdf,
    native_pdf,
)
from talent.tests import _make_role
from talent.unified import build_unified, enrich_profile, names_match

DIPLOMA = [
    "Universidade Nacional de Timor Lorosae",
    "DIPLOMA",
    "This is to certify that",
    "Maria da Silva",
    "has been awarded the degree of",
    "Bachelor of Science in Information Technology",
    "Date of graduation: 15 July 2018",
]

CERT = [
    "CERTIFICATE OF COMPLETION",
    "This is to certify that Maria da Silva",
    "has successfully completed Network Fundamentals Training",
    "Issued by: Example Networking Academy",
    "Date of issue: 12 March 2022",
    "Valid until: 12 March 2025",
]

CERT2 = [
    "PROJECT MANAGEMENT CERTIFICATION",
    "Awarded to Maria da Silva",
    "Issued by: Example Institute of Management",
    "Date of issue: 3 June 2021",
]


def pdf(lines):
    return _bytes_of(_make_digital_pdf, lines)


def good_profile(**over):
    profile = {
        "education": "Bachelor of Science in Information Technology",
        "skills": ["Networking", "Python"],
        "languages": ["English"],
        "certifications": [],
        "years_experience": 5,
        "professional_summary": "ICT officer",
    }
    profile.update(over)
    return profile


class DocBase(TaskIBase):

    def add(self, app, doc_type, data, name="doc.pdf"):
        return SD.objects.create(
            application=app, doc_type=doc_type, pdf_bytes=data,
            original_name=name, sha256=name,
        )

    def processed(self, app):
        process_pending_supporting_documents(app)
        return list(app.supporting_documents.all())

    def run_real_pipeline(self, profile=None):
        """Run the real worker and the REAL recruitment_pipeline; only the
        LLM / embedding calls inside it are replaced."""
        seen = {"rule_profile": None, "cv_prompts": []}

        def fake_cv(text, *a, **k):
            seen["cv_prompts"].append(text)
            return copy.deepcopy(profile or good_profile(education=""))

        def fake_rules(prof, job_prof):
            seen["rule_profile"] = copy.deepcopy(prof)
            return {"eligible": True, "passed_rules": [], "failed_rules": [],
                    "warnings": [], "matrix": []}

        assessment = {
            "overall_score": 70, "dimension_scores": {"skills": 70},
            "decision": "Recommended", "confidence": 80,
            "reasoning": ["ok"], "risks": [], "recommendation": "Proceed"}

        with mock.patch.object(rp, "analyze_cv", side_effect=fake_cv), \
             mock.patch.object(rp, "evaluate_recruitment_rules", side_effect=fake_rules), \
             mock.patch.object(rp, "skill_gap_analysis", return_value={"match_score": 60}), \
             mock.patch.object(rp, "generate_recruitment_assessment", return_value=assessment), \
             mock.patch.object(rp, "NEW_CANDIDATE_RAG", False), \
             mock.patch(f"{WORKER}.send_ai_screening_completed_email"):
            out = StringIO()
            call_command("process_pending_applications", stdout=out)
        return seen, out.getvalue()


# =====================================================================
# Reading + merging (real extraction)
# =====================================================================

class ReadAndMergeTests(DocBase):

    # 1. CV only
    def test_cv_only_object_and_profile_unchanged(self):
        app = self.queue(native_pdf())
        profile = good_profile(certifications=["First Aid"])
        unified = build_unified(app, profile)
        self.assertFalse(unified["needs_human_review"])
        self.assertEqual([e["sources"] for e in unified["education"]], [["cv"]])
        self.assertEqual([c["name"] for c in unified["certifications"]], ["First Aid"])
        self.assertEqual(enrich_profile(profile, unified), profile)

    # 2. CV + diploma
    def test_cv_plus_diploma_merges_education(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "diploma.pdf")
        (doc,) = self.processed(app)
        self.assertEqual(doc.status, SD.STATUS_PROCESSED)
        self.assertEqual(doc.extraction_method, "native")
        self.assertIsNone(doc.pdf_bytes)            # bytes released
        unified = build_unified(app, good_profile())
        self.assertEqual(len(unified["education"]), 1)
        e = unified["education"][0]
        self.assertEqual(e["sources"], ["cv", "education_certificate"])
        self.assertEqual(e["level"], "bachelor")
        self.assertEqual(e["field"], "Information Technology")
        self.assertIn("Universidade Nacional", e["institution"])
        self.assertEqual(e["year"], 2018)
        self.assertEqual(unified["conflicts"], [])

    # 3. CV + certificate
    def test_cv_plus_certificate(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "cert.pdf")
        self.processed(app)
        unified = build_unified(app, good_profile())
        (cert,) = unified["certifications"]
        self.assertIn("Network Fundamentals", cert["name"])
        self.assertIn("Example Networking Academy", cert["issuer"])
        self.assertIn("12 March 2022", cert["issued_date"])
        self.assertIn("12 March 2025", cert["expiry_date"])
        enriched = enrich_profile(good_profile(), unified)
        self.assertEqual(len(enriched["certifications"]), 1)

    # 4. everything together, no needless duplicates
    def test_full_set_is_one_object_without_duplicates(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c1.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT2), "c2.pdf")
        self.processed(app)
        profile = good_profile(certifications=["Network Fundamentals Training"])
        unified = build_unified(app, profile)
        self.assertEqual(len(unified["certifications"]), 2,
                         [c["name"] for c in unified["certifications"]])
        net = next(c for c in unified["certifications"] if "Network" in c["name"])
        self.assertEqual(sorted(net["sources"]), ["certificate", "cv"])
        self.assertEqual(len(unified["education"]), 1)
        self.assertFalse(unified["needs_human_review"])

    # 5. nothing optional uploaded
    def test_no_optional_documents(self):
        app = self.queue(native_pdf())
        unified = build_unified(app, good_profile())
        status = unified["document_processing_status"]
        self.assertEqual(status["documents"], [])
        self.assertEqual(len(status["optional_not_uploaded"]), 3)
        self.assertIn("not treated as evidence", status["note"])
        self.assertFalse(unified["needs_human_review"])

    # 6. unreadable documents
    def test_unreadable_documents_are_recorded_not_fatal(self):
        app = self.queue(native_pdf())
        bad = self.add(app, SD.TYPE_CERTIFICATE, b"%PDF-1.4 not a real pdf", "broken.pdf")
        enc = self.add(app, SD.TYPE_SUPPORTING, encrypted_pdf(), "locked.pdf")
        ok = self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "ok.pdf")
        self.processed(app)
        for doc in (bad, enc, ok):
            doc.refresh_from_db()
        self.assertEqual(bad.status, SD.STATUS_FAILED)
        self.assertEqual(enc.status, SD.STATUS_FAILED)
        self.assertTrue(bad.error_message)
        self.assertEqual(ok.status, SD.STATUS_PROCESSED)
        unified = build_unified(app, good_profile())
        self.assertEqual(len(unified["certifications"]), 1)
        self.assertTrue(unified["needs_human_review"])
        reasons = " ".join(unified["review_reasons"])
        self.assertIn("document_unreadable: broken.pdf", reasons)
        self.assertIn("document_unreadable: locked.pdf", reasons)

    # 7. conflicts are kept and flagged, never resolved silently
    def test_education_level_conflict(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.processed(app)
        profile = good_profile(education="Master of Science in Information Technology")
        unified = build_unified(app, profile)
        conflict = next(c for c in unified["conflicts"]
                        if c["type"] == "education_level_mismatch")
        self.assertEqual({v["source"] for v in conflict["values"]},
                         {"cv", "education_certificate"})
        self.assertEqual(len(unified["education"]), 2)       # both kept
        self.assertTrue(unified["needs_human_review"])
        self.assertEqual(enrich_profile(profile, unified)["education"],
                         profile["education"])               # CV value not replaced

    def test_name_on_document_differs_from_applicant(self):
        app = self.queue(native_pdf())
        other = [line.replace("Maria da Silva", "Joana Pereira") for line in CERT]
        self.add(app, SD.TYPE_CERTIFICATE, pdf(other), "c.pdf")
        self.processed(app)
        unified = build_unified(app, good_profile())
        self.assertIn("holder_name_mismatch", [c["type"] for c in unified["conflicts"]])
        self.assertTrue(unified["needs_human_review"])
        self.assertTrue(names_match("María da Silva", "Maria Silva"))
        self.assertFalse(names_match("Joana Pereira", "Maria da Silva"))

    def test_conflicting_dates_for_the_same_certificate(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c1.pdf")
        changed = [x.replace("12 March 2022", "1 January 2019") for x in CERT]
        self.add(app, SD.TYPE_CERTIFICATE, pdf(changed), "c2.pdf")
        self.processed(app)
        unified = build_unified(app, good_profile())
        self.assertEqual(len(unified["certifications"]), 1)
        self.assertIn("certification_detail_mismatch",
                      [c["type"] for c in unified["conflicts"]])

    # 8. provenance
    def test_evidence_names_document_page_and_quote(self):
        app = self.queue(native_pdf())
        doc = self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "cert.pdf")
        self.processed(app)
        unified = build_unified(app, good_profile())
        ev = [e for e in unified["evidence"] if e["document_type"] == "certificate"]
        self.assertTrue(ev)
        self.assertTrue(all(e["document"] == "cert.pdf" for e in ev))
        self.assertTrue(all(e["document_id"] == doc.pk for e in ev))
        self.assertTrue(all(e["page"] == 1 for e in ev))
        self.assertTrue(any("Issued by" in (e["quote"] or "") for e in ev))

    def test_unrecognised_certificate_claims_nothing(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE,
                 pdf(["Random invoice 0001", "Total due 25 USD", "Thank you for your order"]), "x.pdf")
        self.processed(app)
        self.assertEqual(build_unified(app, good_profile())["certifications"], [])

    def test_supporting_document_adds_no_qualification(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_SUPPORTING,
                 pdf(["Letter of reference", "Bachelor of Law and Master of Arts mentioned here"]), "ref.pdf")
        self.processed(app)
        unified = build_unified(app, good_profile())
        self.assertEqual(len(unified["supporting_information"]), 1)
        self.assertEqual(len(unified["education"]), 1)
        self.assertEqual(unified["certifications"], [])

    @skipUnless(shutil.which("tesseract") and shutil.which("pdftoppm"),
                "Tesseract / Poppler not installed")
    def test_scanned_certificate_uses_the_existing_ocr_path(self):
        app = self.queue(native_pdf())
        scan = _bytes_of(_make_scanned_pdf, [[
            "CERTIFICATE OF COMPLETION",
            "This is to certify that Maria da Silva",
            "has successfully completed Network Fundamentals Training",
            "Issued by: Example Networking Academy",
            "Date of issue: 12 March 2022",
        ]])
        doc = self.add(app, SD.TYPE_CERTIFICATE, scan, "scan.pdf")
        self.processed(app)
        doc.refresh_from_db()
        self.assertIn(doc.status, (SD.STATUS_PROCESSED, SD.STATUS_LOW_QUALITY))
        self.assertIn("ocr", doc.extraction_method)
        self.assertTrue(doc.parsed["certifications"])


# =====================================================================
# Web request
# =====================================================================

class ApplyWebTests(DocBase):

    def setUp(self):
        super().setUp()
        self.client.login(email="ti@x.com", password="pass12345")
        self.url = reverse("apply_job", kwargs={"job_id": self.job.id})

    def post(self, **files):
        data = {"cv_file": SimpleUploadedFile("cv.pdf", native_pdf(),
                                              content_type="application/pdf")}
        data["education_file"] = SimpleUploadedFile(
            "diploma.pdf", pdf(DIPLOMA), content_type="application/pdf")
        data.update(files)
        if data.get("education_file") is None:
            data.pop("education_file")
        return self.client.post(self.url, data, follow=True)

    @staticmethod
    def up(name, data):
        return SimpleUploadedFile(name, data, content_type="application/pdf")

    def test_form_shows_three_inputs_and_no_other_supporting_documents(self):
        html = self.client.get(self.url).content.decode()
        for name in ("cv_file", "education_file", "certificate_files"):
            self.assertIn(f'name="{name}"', html)
        self.assertNotIn("supporting_files", html)
        self.assertNotIn("Other Supporting Documents", html)
        import re
        tag = {n: re.search(r'<input[^>]*name="%s"[^>]*>' % n, html).group(0)
               for n in ("cv_file", "education_file", "certificate_files")}
        self.assertIn("required", tag["cv_file"])
        self.assertIn("required", tag["education_file"])
        self.assertNotIn("required", tag["certificate_files"])

    # 10. valid set is queued; nothing is read in the request
    def test_valid_documents_are_stored_and_nothing_is_extracted_in_the_request(self):
        with mock.patch.object(orchestrator, "extract_document") as extract:
            resp = self.post(
                education_file=self.up("diploma.pdf", pdf(DIPLOMA)),
                certificate_files=[self.up("c1.pdf", pdf(CERT)),
                                   self.up("c2.pdf", pdf(CERT2))])
        extract.assert_not_called()
        app = Application.objects.get(job=self.job)
        self.assertEqual(app.ai_status, S.QUEUED)
        docs = app.supporting_documents.all()
        self.assertEqual(docs.count(), 3)
        self.assertTrue(all(d.pdf_bytes and d.status == SD.STATUS_PENDING for d in docs))
        text = " ".join(str(m) for m in resp.context["messages"])
        self.assertIn("diploma.pdf", text)
        self.assertIn("c2.pdf", text)

    def test_certificates_are_optional(self):
        self.post()  # CV + diploma only
        app = Application.objects.get(job=self.job)
        self.assertEqual(
            list(app.supporting_documents.values_list("doc_type", flat=True)),
            [SD.TYPE_EDUCATION])
        self.assertEqual(app.ai_status, S.QUEUED)

    def test_diploma_is_required(self):
        resp = self.post(education_file=None)
        self.assertFalse(Application.objects.filter(job=self.job).exists())
        text = " ".join(str(m) for m in resp.context["messages"])
        self.assertIn("diploma", text.lower())

    def test_invalid_diploma_rejects_the_submission(self):
        self.post(education_file=self.up("d.pdf", b"hello world"))
        self.assertFalse(Application.objects.filter(job=self.job).exists())

    def test_invalid_file_rejects_the_whole_submission(self):
        bad_inputs = {
            "not a pdf extension": self.up("notes.txt", b"hello"),
            "pdf extension, wrong content": self.up("x.pdf", b"hello world"),
            "empty": self.up("e.pdf", b""),
            "encrypted": self.up("lock.pdf", encrypted_pdf()),
            "oversized": self.up("big.pdf", b"%PDF-" + b"0" * (5 * 1024 * 1024 + 1)),
        }
        for label, upload in bad_inputs.items():
            with self.subTest(label):
                self.post(certificate_files=[upload])
                self.assertFalse(Application.objects.filter(job=self.job).exists(), label)

    def test_certificate_cap(self):
        files = [self.up(f"{i}.pdf", pdf([f"Certificate number {i}", "Training course"]))
                 for i in range(MAX_CERTIFICATES + 1)]
        self.post(certificate_files=files)
        self.assertFalse(Application.objects.filter(job=self.job).exists())

    def test_identical_files_are_stored_once(self):
        data = pdf(CERT)
        items, error = validate_uploads(
            self.up("d.pdf", pdf(DIPLOMA)),
            [self.up("a.pdf", data), self.up("b.pdf", data)])
        self.assertIsNone(error)
        self.assertEqual(len(items), 2)  # diploma + one certificate

    def test_reupload_after_cv_failure_replaces_that_document_type(self):
        self.post(education_file=self.up("old.pdf", pdf(DIPLOMA)))
        app = Application.objects.get(job=self.job)
        app.ai_status = S.DOCUMENT_INVALID
        app.save()
        newer = DIPLOMA[:-1] + ["Date of graduation: 1 July 2020"]
        self.post(education_file=self.up("new.pdf", pdf(newer)))
        names = list(app.supporting_documents.values_list("original_name", flat=True))
        self.assertEqual(names, ["new.pdf"])


# =====================================================================
# Worker + pipeline (real worker, real pipeline, stubbed LLM calls)
# =====================================================================

class WorkerAndPipelineTests(DocBase):

    # 9. screening integration -- CV only keeps the old behaviour
    def test_cv_only_screening_is_unchanged(self):
        app = self.queue(native_pdf())
        profile = good_profile(education="Bachelor of IT", certifications=["First Aid"])
        seen, _ = self.run_real_pipeline(profile)
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        self.assertEqual(seen["rule_profile"], profile)
        self.assertNotIn("document_review", app.ai_rag_context)
        self.assertEqual(len(seen["cv_prompts"]), 1)
        self.assertEqual(app.unified_candidate["schema_version"], 1)

    def test_documents_flow_from_upload_to_unified_object(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_EDUCATION, pdf(DIPLOMA), "d.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, b"%PDF-1.4 broken", "bad.pdf")
        seen, _ = self.run_real_pipeline()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        # the LLM profile call ran once, on the CV text only
        self.assertEqual(len(seen["cv_prompts"]), 1)
        self.assertNotIn("Date of graduation", seen["cv_prompts"][0])
        self.assertNotIn("Network Fundamentals", seen["cv_prompts"][0])
        # the rule engine received the education from the diploma + the certificate
        self.assertIn("Bachelor", seen["rule_profile"]["education"])
        self.assertTrue(any("Network Fundamentals" in c
                            for c in seen["rule_profile"]["certifications"]))
        # unified object stored, review flag set for the unreadable document
        review = app.ai_rag_context["document_review"]
        self.assertTrue(review["needs_human_review"])
        self.assertTrue(any("bad.pdf" in r for r in review["review_reasons"]))
        self.assertEqual(len(app.unified_candidate["certifications"]), 1)
        # all old output fields are still filled
        for field in ("ai_profile", "ai_rule_result", "ai_semantic_result",
                      "ai_skill_gap", "ai_explainable_report"):
            self.assertTrue(getattr(app, field), field)
        # bytes of every supporting document were released
        self.assertFalse(app.supporting_documents.exclude(pdf_bytes=None).exists())
        self.assertFalse(ApplicationDocument.objects.filter(application=app).exists())

    def test_supporting_document_crash_never_blocks_screening(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c.pdf")
        with mock.patch(f"{WORKER}.process_pending_supporting_documents",
                        side_effect=RuntimeError("boom")):
            self.run_real_pipeline()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)

    def test_merge_failure_never_blocks_screening(self):
        app = self.queue(native_pdf())
        with mock.patch("talent.unified.build_unified", side_effect=RuntimeError("boom")):
            seen, _ = self.run_real_pipeline(good_profile())
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)
        self.assertEqual(seen["rule_profile"], good_profile())

    def test_failed_cv_leaves_documents_waiting_for_the_reupload(self):
        app = self.queue(b"%PDF-1.4 corrupt cv")
        doc = self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT), "c.pdf")
        self.run_real_pipeline()
        app.refresh_from_db(); doc.refresh_from_db()
        self.assertEqual(app.ai_status, S.DOCUMENT_INVALID)
        self.assertEqual(doc.status, SD.STATUS_PENDING)      # not read yet
        self.assertTrue(doc.pdf_bytes)

    def test_document_text_is_not_written_to_logs_or_worker_output(self):
        secret = "ZZ-UNIQUE-SECRET-TOKEN-4711"
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE, pdf(CERT + [secret]), "c.pdf")
        self.add(app, SD.TYPE_CERTIFICATE, b"%PDF-1.4 broken", "bad.pdf")
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("talent.documents").info("sentinel")
            _, output = self.run_real_pipeline()
        self.assertNotIn(secret, "\n".join(logs.output))
        self.assertNotIn(secret, output)


# =====================================================================
# Candidate detail page
# =====================================================================

class DetailPageTests(DocBase):

    def test_documents_are_listed_and_review_flag_is_staff_only(self):
        app = self.queue(native_pdf())
        self.add(app, SD.TYPE_CERTIFICATE, b"%PDF-1.4 broken", "bad.pdf")
        self.run_real_pipeline()
        app.refresh_from_db()
        self.assertEqual(app.ai_status, S.SUCCESS)

        self.client.login(email="ti@x.com", password="pass12345")       # the candidate
        page = self.client.get(reverse("candidate_detail", args=[app.id])).content.decode()
        self.assertIn("Supporting Documents", page)
        self.assertIn("bad.pdf", page)
        self.assertNotIn("Flagged for human review", page)
        self.client.logout()

        hr = User.objects.create_user(
            username="hr", password="pass12345", email="hr@x.com",
            role=_make_role("HR Officer", ["recruitment_manage"]), is_verified=True)
        self.client.login(email="hr@x.com", password="pass12345")
        page = self.client.get(reverse("candidate_detail", args=[app.id])).content.decode()
        self.assertIn("Flagged for human review", page)
        self.assertIn("document_unreadable: bad.pdf", page)
