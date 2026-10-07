"""
TASK G (2026-10-03) -- tests for the Azure Document Intelligence /
smart-routing / caching layer added on top of the existing Tesseract
OCR pipeline.

Two kinds of tests, deliberately kept separate:

  1. Mocked unit tests (AzureExtractorTests, RouterTests,
     UtilsAzureIntegrationTests) -- zero network access, zero Azure
     cost, test the LOGIC (routing priority, fallback, caching, error
     classification, warning surfacing) regardless of real OCR
     accuracy.

  2. Real end-to-end tests (RealTesseractIntegrationTests) -- Azure is
     NOT configured in these (no env vars set), so they exercise the
     actual, unchanged Tesseract fallback with synthetic PDFs built in
     this file (fpdf2 + Pillow, both already pinned in
     requirements.txt -- no extra dependency), proving the new routing
     code didn't break the pre-existing OCR path for real, not just in
     theory.
     Requires the tesseract/poppler system binaries -- already a
     requirement of the existing OCR feature, not a new one.

Run with:
    python manage.py test ai_engine.test_document_extraction -v 2
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

from django.core.cache import cache
from django.test import TestCase

from ai_engine.services.ocr_fallback import assess_text_quality, OCRQuality
from ai_engine.services.document_extraction import azure_extractor
from ai_engine.services.document_extraction.router import (
    extract_scanned_document,
)
from ai_engine.services.document_extraction.result import (
    DocumentExtractionResult,
)
from talent.utils import extract_text_from_pdf, CVExtractionError


# ---------------------------------------------------------------------
# Synthetic fixture builders -- no real/confidential CV data anywhere.
# ---------------------------------------------------------------------

def _make_digital_pdf(path, lines):
    """
    A real digitally-generated PDF -- has an actual text layer.

    Uses fpdf2, which is ALREADY a pinned dependency in requirements.txt
    (used elsewhere in the project) -- not reportlab, which would have
    been an extra, test-only dependency never declared anywhere.
    """
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="letter")
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in lines:
        pdf.cell(text=line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(path)


def _make_scanned_pdf(path, pages_lines):
    """
    An image-only PDF (no text layer at all) -- simulates a scanned
    document. One page per item in pages_lines (each a list of text
    lines rendered into that page's image). Built with fpdf2 + Pillow
    (both already pinned dependencies) -- no reportlab.
    """
    from fpdf import FPDF
    from PIL import Image, ImageDraw

    pdf = FPDF(unit="pt", format="letter")

    with tempfile.TemporaryDirectory() as tmp_dir:
        for page_num, lines in enumerate(pages_lines):
            img = Image.new("RGB", (1700, 2200), "white")
            draw = ImageDraw.Draw(img)
            y = 100
            for line in lines:
                draw.text((100, y), line, fill="black")
                y += 60

            img_path = os.path.join(tmp_dir, f"page_{page_num}.png")
            img.save(img_path)

            pdf.add_page()
            pdf.image(img_path, x=0, y=0, w=612, h=792)

        pdf.output(path)


def _make_empty_pdf(path):
    from pypdf import PdfWriter
    writer = PdfWriter()
    with open(path, "wb") as f:
        writer.write(f)


def _make_corrupted_pdf(path):
    with open(path, "wb") as f:
        f.write(b"this is not a real PDF file at all, just garbage bytes")


def _fake_analyze_result(content, page_count=1, tables=None):
    """Mimics the shape of azure.ai.documentintelligence.models.AnalyzeResult
    closely enough for _normalize_result() -- not the real SDK class,
    but matching attribute names, which is all that function touches."""
    page = MagicMock()
    page.page_number = 1
    page.width = 8.5
    page.height = 11
    page.lines = [MagicMock()] * 5

    result = MagicMock()
    result.content = content
    result.pages = [page] * page_count
    result.tables = tables or []
    return result


class _ClearCacheMixin:
    def setUp(self):
        super().setUp()
        cache.clear()


# ---------------------------------------------------------------------
# 1. Quality heuristic (shared by both providers) -- pure unit tests.
# ---------------------------------------------------------------------

class QualityHeuristicTests(TestCase):

    def test_ok_for_clean_readable_text(self):
        text = "John Doe. Bachelor of Information Technology. Python, Django, SQL."
        self.assertEqual(assess_text_quality(text), OCRQuality.OK)

    def test_failed_for_too_short(self):
        self.assertEqual(assess_text_quality("hi"), OCRQuality.FAILED)

    def test_failed_for_empty(self):
        self.assertEqual(assess_text_quality("   "), OCRQuality.FAILED)

    def test_low_for_mostly_symbol_noise(self):
        # Long enough to pass the length bar, but mostly punctuation/
        # symbol noise -- the realistic failure mode of a bad scan.
        noisy = "#$%^&*()_+-={}[]|\\:;\"'<>,.?/~`" * 3
        self.assertEqual(assess_text_quality(noisy), OCRQuality.LOW)


# ---------------------------------------------------------------------
# 2. Azure extractor -- mocked SDK, no network/cost.
# ---------------------------------------------------------------------

class AzureExtractorTests(TestCase):

    def setUp(self):
        # Start every test with Azure NOT configured; individual tests
        # opt in via their own patch.dict.
        patcher = patch.dict(os.environ, {
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "",
            "AZURE_DOCUMENT_INTELLIGENCE_KEY": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_not_configured_is_configured_false(self):
        self.assertFalse(azure_extractor.is_configured())

    def test_not_configured_raises_permanent_error(self):
        with self.assertRaises(azure_extractor.AzureExtractionError) as ctx:
            azure_extractor.extract_with_azure("/tmp/does-not-matter.pdf")
        self.assertFalse(ctx.exception.is_transient)

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "fake-key-for-tests-only",
    })
    def test_is_configured_true_when_both_set(self):
        self.assertTrue(azure_extractor.is_configured())

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "fake-key-for-tests-only",
    })
    def test_file_over_f0_limit_raises_without_calling_sdk(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x" * (azure_extractor.AZURE_MAX_FILE_SIZE_BYTES + 1))
            path = f.name
        self.addCleanup(os.remove, path)

        with patch.object(azure_extractor, "_build_client") as mock_build:
            with self.assertRaises(azure_extractor.AzureExtractionError) as ctx:
                azure_extractor.extract_with_azure(path)
            mock_build.assert_not_called()
            self.assertFalse(ctx.exception.is_transient)

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "fake-key-for-tests-only",
    })
    @patch.object(azure_extractor, "_build_client")
    def test_successful_analysis_normalizes_text_and_pages(self, mock_build):
        mock_client = MagicMock()
        mock_poller = MagicMock()
        mock_poller.result.return_value = _fake_analyze_result(
            "John Doe\nBachelor of IT", page_count=1
        )
        mock_client.begin_analyze_document.return_value = mock_poller
        mock_build.return_value = mock_client

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake but small")
            path = f.name
        self.addCleanup(os.remove, path)

        result = azure_extractor.extract_with_azure(path, total_pages=1)

        self.assertEqual(result.provider, "azure_document_intelligence")
        self.assertIn("John Doe", result.text)
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(result.warnings, [])

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "fake-key-for-tests-only",
    })
    @patch.object(azure_extractor, "_build_client")
    def test_warns_when_document_exceeds_f0_page_limit(self, mock_build):
        mock_client = MagicMock()
        mock_poller = MagicMock()
        mock_poller.result.return_value = _fake_analyze_result(
            "partial text", page_count=2
        )
        mock_client.begin_analyze_document.return_value = mock_poller
        mock_build.return_value = mock_client

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake but small")
            path = f.name
        self.addCleanup(os.remove, path)

        result = azure_extractor.extract_with_azure(path, total_pages=5)

        self.assertEqual(len(result.warnings), 1)
        self.assertIn("first 2 page", result.warnings[0])
        self.assertIn("5 page", result.warnings[0])

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "fake-key-for-tests-only",
    })
    @patch.object(azure_extractor, "_build_client")
    def test_http_error_with_500_is_transient(self, mock_build):
        error = Exception("Internal server error")
        error.status_code = 500
        mock_build.side_effect = error

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake but small")
            path = f.name
        self.addCleanup(os.remove, path)

        with self.assertRaises(azure_extractor.AzureExtractionError) as ctx:
            azure_extractor.extract_with_azure(path)
        self.assertTrue(ctx.exception.is_transient)
        self.assertEqual(ctx.exception.status_code, 500)

    @patch.dict(os.environ, {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://fake.cognitiveservices.azure.com/",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY": "super-secret-fake-key",
    })
    @patch.object(azure_extractor, "_build_client")
    def test_error_never_leaks_api_key(self, mock_build):
        error = Exception("auth failed")
        error.status_code = 401
        mock_build.side_effect = error

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake but small")
            path = f.name
        self.addCleanup(os.remove, path)

        with self.assertRaises(azure_extractor.AzureExtractionError) as ctx:
            azure_extractor.extract_with_azure(path)
        self.assertNotIn("super-secret-fake-key", str(ctx.exception))
        self.assertFalse(ctx.exception.is_transient)


# ---------------------------------------------------------------------
# 3. Router -- smart routing + caching, Azure and Tesseract both mocked.
# ---------------------------------------------------------------------

class RouterTests(_ClearCacheMixin, TestCase):

    def _tmp_pdf(self, content=b"%PDF-1.4 unique-per-test-content"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            path = f.name
        self.addCleanup(os.remove, path)
        return path

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "extract_with_azure")
    @patch.object(azure_extractor, "is_configured", return_value=True)
    def test_azure_success_skips_tesseract(
        self, mock_configured, mock_azure, mock_tesseract
    ):
        mock_azure.return_value = DocumentExtractionResult(
            provider="azure_document_intelligence",
            text="Bachelor of Information Technology. Skills: Python, Django, PostgreSQL.",
            quality=None,
        )
        path = self._tmp_pdf()

        result = extract_scanned_document(path, total_pages=1)

        self.assertEqual(result.provider, "azure_document_intelligence")
        self.assertEqual(result.quality, OCRQuality.OK)
        mock_tesseract.assert_not_called()

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "is_configured", return_value=False)
    def test_azure_not_configured_uses_tesseract(
        self, mock_configured, mock_tesseract
    ):
        mock_tesseract.return_value = ("Bachelor of IT", OCRQuality.OK, 1)
        path = self._tmp_pdf()

        result = extract_scanned_document(path, total_pages=1)

        self.assertEqual(result.provider, "tesseract")
        mock_tesseract.assert_called_once()

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "extract_with_azure")
    @patch.object(azure_extractor, "is_configured", return_value=True)
    def test_azure_failure_falls_back_to_tesseract(
        self, mock_configured, mock_azure, mock_tesseract
    ):
        mock_azure.side_effect = azure_extractor.AzureExtractionError(
            "HTTP 500", status_code=500, is_transient=True
        )
        mock_tesseract.return_value = ("rescued by tesseract", OCRQuality.OK, 1)
        path = self._tmp_pdf()

        result = extract_scanned_document(path, total_pages=1)

        self.assertEqual(result.provider, "tesseract")
        self.assertEqual(result.text, "rescued by tesseract")

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "extract_with_azure")
    @patch.object(azure_extractor, "is_configured", return_value=True)
    def test_azure_failed_quality_falls_back_to_tesseract(
        self, mock_configured, mock_azure, mock_tesseract
    ):
        # Azure "succeeds" technically but returns near-nothing usable.
        mock_azure.return_value = DocumentExtractionResult(
            provider="azure_document_intelligence", text="x", quality=None
        )
        mock_tesseract.return_value = ("real content here, readable", OCRQuality.OK, 1)
        path = self._tmp_pdf()

        result = extract_scanned_document(path, total_pages=1)

        self.assertEqual(result.provider, "tesseract")

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "is_configured", return_value=False)
    def test_successful_result_is_cached_on_second_call(
        self, mock_configured, mock_tesseract
    ):
        mock_tesseract.return_value = ("cached content", OCRQuality.OK, 1)
        path = self._tmp_pdf(b"%PDF-1.4 same-content-both-calls")

        extract_scanned_document(path, total_pages=1)
        extract_scanned_document(path, total_pages=1)

        mock_tesseract.assert_called_once()

    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    @patch.object(azure_extractor, "is_configured", return_value=False)
    def test_failed_result_is_not_cached(self, mock_configured, mock_tesseract):
        mock_tesseract.return_value = ("", OCRQuality.FAILED, 1)
        path = self._tmp_pdf(b"%PDF-1.4 failing-content")

        extract_scanned_document(path, total_pages=1)
        extract_scanned_document(path, total_pages=1)

        self.assertEqual(mock_tesseract.call_count, 2)


# ---------------------------------------------------------------------
# 4. talent/utils.py integration -- Azure mocked (fast, deterministic).
# ---------------------------------------------------------------------

class UtilsAzureIntegrationTests(_ClearCacheMixin, TestCase):

    def _tmp_pdf(self, content):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            path = f.name
        self.addCleanup(os.remove, path)
        return path

    def test_digital_pdf_never_calls_scanned_path(self):
        path = self._tmp_pdf(b"irrelevant -- patched below")
        with patch(
            "ai_engine.services.document_extraction.router.extract_scanned_document"
        ) as mock_scanned:
            with patch("talent.utils.PdfReader") as mock_reader_cls:
                mock_page = MagicMock()
                mock_page.extract_text.return_value = (
                    "A" * 200  # well over MIN_NATIVE_TEXT_CHARS
                )
                mock_reader = MagicMock()
                mock_reader.pages = [mock_page]
                mock_reader_cls.return_value = mock_reader

                text = extract_text_from_pdf(path)

        self.assertEqual(text, "A" * 200)
        mock_scanned.assert_not_called()

    @patch.object(azure_extractor, "is_configured", return_value=True)
    @patch.object(azure_extractor, "extract_with_azure")
    def test_azure_warning_surfaces_as_extraction_notice(
        self, mock_azure, mock_configured
    ):
        # A provider warning must still reach the text as a notice.
        # The document is within Azure's page limit (2), so Azure is
        # the provider; the warning text itself is the provider's.
        mock_azure.return_value = DocumentExtractionResult(
            provider="azure_document_intelligence",
            text="Bachelor of IT and relevant experience in software.",
            quality=OCRQuality.OK,
            warnings=["Azure reported a provider warning for this file."],
        )
        path = self._tmp_pdf(b"%PDF-1.4 scanned-like, short native text")

        with patch("talent.utils.PdfReader") as mock_reader_cls:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""  # forces scanned path
            mock_reader = MagicMock()
            mock_reader.pages = [mock_page] * 2
            mock_reader_cls.return_value = mock_reader

            text = extract_text_from_pdf(path)

        self.assertTrue(text.startswith("[EXTRACTION NOTICE:"))
        self.assertIn("provider warning", text)

    @patch.object(azure_extractor, "is_configured", return_value=True)
    @patch.object(azure_extractor, "extract_with_azure")
    @patch("ai_engine.services.document_extraction.router.extract_text_via_ocr")
    def test_document_longer_than_azure_limit_skips_azure(
        self, mock_ocr, mock_azure, mock_configured
    ):
        # TASK I (expected behavior change): previously a 5-page scan
        # was sent to Azure F0, which read only 2 pages and still
        # counted as success, silently dropping pages 3-5. Now Azure is
        # skipped when it cannot read the whole document, and Tesseract
        # (no page cap) reads all of it.
        mock_ocr.return_value = (
            "Full five page CV text. " * 10, OCRQuality.OK, 5
        )
        path = self._tmp_pdf(b"%PDF-1.4 scanned-like, short native text")

        with patch("talent.utils.PdfReader") as mock_reader_cls:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_reader = MagicMock()
            mock_reader.pages = [mock_page] * 5
            mock_reader_cls.return_value = mock_reader

            text = extract_text_from_pdf(path)

        mock_azure.assert_not_called()
        mock_ocr.assert_called_once()
        self.assertIn("Full five page CV text.", text)

    @patch.object(azure_extractor, "is_configured", return_value=True)
    @patch.object(azure_extractor, "extract_with_azure")
    def test_low_quality_azure_result_produces_ocr_notice(
        self, mock_azure, mock_configured
    ):
        mock_azure.return_value = DocumentExtractionResult(
            provider="azure_document_intelligence",
            text="#$%^&*()" * 10,
            quality=None,
        )
        path = self._tmp_pdf(b"%PDF-1.4 noisy scan")

        with patch("talent.utils.PdfReader") as mock_reader_cls:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = ""
            mock_reader = MagicMock()
            mock_reader.pages = [mock_page]
            mock_reader_cls.return_value = mock_reader

            text = extract_text_from_pdf(path)

        self.assertTrue(text.startswith("[OCR NOTICE:"))


# ---------------------------------------------------------------------
# 5. Real end-to-end tests -- Azure NOT configured, real Tesseract.
#    Proves the pre-existing OCR path genuinely still works after
#    routing through the new router.py instead of calling
#    ocr_fallback directly.
# ---------------------------------------------------------------------

class RealTesseractIntegrationTests(_ClearCacheMixin, TestCase):

    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, {
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "",
            "AZURE_DOCUMENT_INTELLIGENCE_KEY": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tmp_path(self, suffix=".pdf"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self.addCleanup(os.remove, path)
        return path

    def test_digital_pdf_fast_path(self):
        path = self._tmp_path()
        _make_digital_pdf(path, [
            "John Doe", "Bachelor of Information Technology", "Skills: Python, Django"
        ])
        text = extract_text_from_pdf(path)
        self.assertIn("John Doe", text)
        self.assertFalse(text.startswith("[OCR NOTICE:"))

    def test_scanned_pdf_real_tesseract_fallback(self):
        path = self._tmp_path()
        _make_scanned_pdf(path, [[
            "John Doe", "EDUCATION", "Bachelor of Information Technology"
        ]])
        text = extract_text_from_pdf(path)
        self.assertIn("John Doe", text)
        self.assertIn("Information Technology", text)

    def test_multi_page_scanned_pdf(self):
        path = self._tmp_path()
        _make_scanned_pdf(path, [
            ["John Doe", "PERSONAL INFORMATION"],
            ["EDUCATION", "Bachelor of Information Technology"],
        ])
        text = extract_text_from_pdf(path)
        self.assertIn("John Doe", text)
        self.assertIn("Bachelor", text)

    def test_corrupted_pdf_raises_cv_extraction_error(self):
        path = self._tmp_path()
        _make_corrupted_pdf(path)
        with self.assertRaises(CVExtractionError):
            extract_text_from_pdf(path)

    def test_empty_pdf_raises_cv_extraction_error(self):
        path = self._tmp_path()
        _make_empty_pdf(path)
        with self.assertRaises(CVExtractionError) as ctx:
            extract_text_from_pdf(path)
        self.assertIn("OCR processing failed", str(ctx.exception))