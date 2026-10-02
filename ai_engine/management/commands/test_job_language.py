"""
TASK E test: Tetum job-description handling in job_pipeline.process_job.

Usage:
    python manage.py test_job_language

Uses a fake Job object and mocks the LLM / RAG calls, so it needs no
database, no Ollama and no API key. It checks WHEN translation is
triggered and that fallback is safe. Real translation quality must be
checked separately with reprocess_job on a real Tetum job.
"""
from unittest import mock

from django.core.management.base import BaseCommand

from ai_engine.services import job_pipeline

ENGLISH = (
    "Junior Web Developer. Requirements: Bachelor's degree in Computer "
    "Science, Information Technology or a related field. Minimum 1 year of "
    "relevant web development experience. Skills: HTML, CSS, JavaScript, "
    "PHP or Python, MySQL or PostgreSQL, Git, REST API, troubleshooting. "
    "At least one official language of Timor-Leste."
)
PORTUGUESE = (
    "Programador Web Júnior. Requisitos: Licenciatura em Ciências da "
    "Computação, Tecnologias de Informação ou área relacionada. Experiência "
    "mínima de 1 ano em desenvolvimento web. Competências: HTML, CSS, "
    "JavaScript, PHP ou Python, MySQL ou PostgreSQL, Git, REST API. "
    "Pelo menos uma língua oficial de Timor-Leste."
)
INDONESIAN = (
    "Pengembang Web Junior. Persyaratan: Sarjana Ilmu Komputer, Teknologi "
    "Informasi atau bidang terkait. Pengalaman minimal 1 tahun dalam "
    "pengembangan web. Keterampilan: HTML, CSS, JavaScript, PHP atau "
    "Python, MySQL atau PostgreSQL, Git, REST API. Menguasai minimal satu "
    "bahasa resmi Timor-Leste."
)
TETUM = (
    "Pozisaun: Dezenvolvedór Web Junior. Kandidatu tenke iha diploma "
    "Bachelor iha Siénsia Komputadór, Teknolojia Informasaun, Sistema "
    "Informasaun, Engenharia Software ka área seluk ne'ebé relevante. "
    "Esperiénsia mínimu tinan 1 iha dezenvolvimentu web ka software. "
    "Konhesimentu ne'ebé presiza: HTML, CSS, JavaScript, PHP ka Python, "
    "MySQL ka PostgreSQL, Git, REST API, rezolve problema. Kandidatu "
    "tenke bele ko'alia lian ofisiál Timor-Leste ida."
)
MIXED_MOSTLY_ENGLISH = (
    "Responsabilidade: Develop and maintain web applications for the "
    "ministry. Experiénsia mínimo tinan 2. Required skills: Python, "
    "Django, PostgreSQL, Git, REST API, troubleshooting. Bachelor's "
    "degree in Computer Science or a related field is required."
)

FAKE_PROFILE = {
    "job_title": "Junior Web Developer", "education": "Bachelor",
    "skills": ["HTML"], "languages": [], "certifications": [],
    "years_experience": 1, "professional_summary": "x",
}


class FakeJob:
    def __init__(self, description):
        self.title = "Junior Web Developer"
        self.description = description
        self.requirements = ""
        self.ai_job_profile = None
        self.ai_rag_context = None
        self.saved = False

    def save(self):
        self.saved = True


class Command(BaseCommand):
    help = "Task E: Tetum job-description handling tests (mocked LLM)."

    def _run(self, description, translate_result):
        job = FakeJob(description)
        seen = {}
        translate = mock.Mock(return_value=translate_result)

        def fake_parser(text):
            seen["text"] = text
            return dict(FAKE_PROFILE)

        with mock.patch.object(job_pipeline, "translate_tetum_to_english", translate), \
             mock.patch.object(job_pipeline, "analyze_job_description", fake_parser), \
             mock.patch.object(job_pipeline, "get_rag_screening_context", lambda t: {"evidence": []}):
            job_pipeline.process_job(job)
        return job, translate, seen

    def handle(self, *args, **options):
        ok = {"success": True, "translated_text": "ENGLISH VERSION", "error": None}
        bad = {"success": False, "translated_text": "", "error": "x"}
        results = []

        def check(name, cond):
            results.append(cond)
            self.stdout.write(f"{'PASS' if cond else 'FAIL'}  {name}")

        for name, text in (("1 English", ENGLISH), ("2 Portuguese", PORTUGUESE), ("3 Indonesian", INDONESIAN)):
            job, tr, seen = self._run(text, ok)
            check(f"{name}: no translation call", tr.call_count == 0)
            check(f"{name}: original text profiled + profile saved",
                  seen["text"] == text and isinstance(job.ai_job_profile, dict))

        job, tr, seen = self._run(TETUM, ok)
        info = job.ai_rag_context["job_language"]
        check("4 Tetum: detected as Tetum", info["detected_language"] == "tetum")
        check("4 Tetum: exactly ONE translation call", tr.call_count == 1)
        check("4 Tetum: English text sent to profiling", seen["text"] == "ENGLISH VERSION")
        check("4 Tetum: original description kept", job.description == TETUM)
        check("4 Tetum: translation=success, language=english",
              info["translation"] == "success" and info["processing_language"] == "english")

        job, tr, seen = self._run(MIXED_MOSTLY_ENGLISH, ok)
        check("5 Mixed (little Tetum): NOT translated", tr.call_count == 0 and seen["text"] == MIXED_MOSTLY_ENGLISH)

        job, tr, seen = self._run(TETUM, bad)
        info = job.ai_rag_context["job_language"]
        check("6 Tetum + translation failure: falls back to original",
              seen["text"] == TETUM and info["translation"] == "failed" and job.saved)

        raising = mock.Mock(side_effect=RuntimeError("boom"))
        job = FakeJob(TETUM)
        with mock.patch.object(job_pipeline, "translate_tetum_to_english", raising), \
             mock.patch.object(job_pipeline, "analyze_job_description", lambda t: dict(FAKE_PROFILE)), \
             mock.patch.object(job_pipeline, "get_rag_screening_context", lambda t: {"evidence": []}):
            job_pipeline.process_job(job)
        check("6b Tetum + translation exception: no crash", job.saved)

        # 7: the separate "requirements" field must reach the parser
        job = FakeJob("We need a Database Administrator.")
        job.requirements = "Bachelor in Computer Science. Minimum 2 years."
        seen = {}
        with mock.patch.object(job_pipeline, "translate_tetum_to_english", mock.Mock(return_value=ok)), \
             mock.patch.object(job_pipeline, "analyze_job_description", lambda t: (seen.update(text=t) or dict(FAKE_PROFILE))), \
             mock.patch.object(job_pipeline, "get_rag_screening_context", lambda t: {"evidence": []}):
            job_pipeline.process_job(job)
        check("7 requirements field is included in the profiled text",
              "Minimum 2 years" in seen["text"] and "Database Administrator" in seen["text"])

        self.stdout.write(f"\n{sum(results)}/{len(results)} passed")