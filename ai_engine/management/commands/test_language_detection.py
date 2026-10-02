"""
TASK D validation command (2026-09-30).

Run this on YOUR OWN machine (langdetect itself has no network
dependency and already works in the sandbox, but real Tetum
translation needs the real LLM provider -- online_gemma/Ollama --
which this sandbox has no credentials for):

    python manage.py test_language_detection

What it does:
  1. Runs detect_language() against English / Portuguese / Indonesian
     / pure Tetum / mixed Tetum+English samples and a too-short
     sample -- prints detected language, confidence, Tetum word
     proportion, and whether translation would trigger.
  2. If a real Tetum example is available (edit REAL_TETUM_SAMPLE
     below with an actual Tetum CV excerpt), also runs the real
     translate_tetum_to_english() end to end and prints the result +
     timing -- this DOES call the real LLM provider.

Nothing here touches the database, apply_job, or any production data.
"""

import time

from django.core.management.base import BaseCommand

from ai_engine.services.language_detection import detect_language
from ai_engine.services.translation import translate_tetum_to_english


SAMPLES = {
    "English": (
        "I have five years of experience as a network administrator, "
        "working with Cisco routers and Python automation scripts for "
        "the Ministry of Finance.",
        "english / not significant",
    ),
    "Portuguese": (
        "Tenho cinco anos de experiencia como administrador de redes, "
        "trabalhando com routers Cisco e scripts de automacao em "
        "Python para o Ministerio das Financas.",
        "portuguese / not significant",
    ),
    "Indonesian": (
        "Saya memiliki lima tahun pengalaman sebagai administrator "
        "jaringan, bekerja dengan router Cisco dan skrip otomatisasi "
        "Python untuk Kementerian Keuangan.",
        "indonesian / not significant",
    ),
    "Tetum (pure)": (
        "Hau iha tinan lima esperiensia hanesan administradór redes, "
        "hau serbisu ho router Cisco no script automasaun Python ba "
        "Ministeriu Finansas. Hau mos bele halo knaar hotu-hotu iha "
        "eskola.",
        "tetum / SIGNIFICANT (should translate)",
    ),
    "Mixed Tetum+English (real content in Tetum)": (
        "Name: Maria da Costa. Education: Bachelor of Computer "
        "Science. Experience: 5 years as Network Administrator. "
        "Skills: Python, Cisco, PostgreSQL. Hau moras ohin.",
        "tetum / SIGNIFICANT (should translate -- has a real Tetum sentence, not just noise)",
    ),
    "Mixed Tetum+English (minor noise only)": (
        "I have five years of experience as a network administrator, "
        "working with Cisco routers and Python automation scripts "
        "for the Ministry of Finance. I led a team of three "
        "engineers and delivered the national network upgrade "
        "project on time and under budget, hotu, coordinating "
        "closely with regional offices across the country.",
        "english / NOT significant (only 1 stray Tetum word -- must not translate)",
    ),
    "Too short": (
        "Python dev",
        "unknown / not significant (too short to detect)",
    ),
}

# EDIT THIS if you have a real Tetum CV excerpt (candidate-provided,
# not invented) -- set it to test the real end-to-end translation
# call. Left empty by default so this command never calls the LLM
# with fabricated Tetum content.
REAL_TETUM_SAMPLE = """CURRICULUM VITAE
DADOS PESOÁL
•	Naran Kompletu: João Soares
•	Hela-fatin: Bairo da Paz, Terra-Santa, Díli, Timor-Leste
•	Nu. Telemóvel: +670 75123456
•	Enderesu Email: koko@gmail.com
•	LinkedIn: koko
•	GitHub / Portofóliu: koko

REZUMU PROFISIONÁL
Web Developer ne’ebé motivadu no iha esperiénsia tinan 5 iha dezenvolvimentu website no aplikasaun web. Matenek iha dezenvolvimentu Front-End no Back-End, liuliu uza teknolojia hanesan HTML, CSS, JavaScript, PHP, no Frameworks Laravel / React. Prontu atu kontribui ba kbiit tékniku hodi kria solusaun web ne'ebé lalais, seguru, no fasil ba uza-na’in (user-friendly).

KBIIT TÉKNIKU (SKILLS)
•	Lian Programasaun: HTML5, CSS3, JavaScript, PHP, SQL
•	Frameworks & Libraries: Bootstrap, Tailwind CSS, Laravel, React.js (hili de'it ne'ebé ita hatene)
•	Baza de Dadus (Database): MySQL, PostgreSQL
•	Ferramentas (Tools): Git, GitHub, VS Code, Figma
•	Kbiit Seluk: Responsive Web Design, SEO básiku, no Rezolve Problema (Troubleshooting)

ESPERIÉNSIA SERVISU
Web Developer
Daya Marketing – Dili, Timor-Leste
02-02-2021- Sei serbisu
•	Kria no dezenvolve website instituionál uza WordPress / Laravel.
•	Asegura website funsiona ho di'ak iha telemóvel no komputadór (Responsive Design).
•	Hadi'a no halo manutensaun ba sistema baza de dadus (database) hodi nune'e aplikasaun la'o lalais.
•	Servisu hamutuk ho ekipa UI/UX dizainer hodi transforma dezenho ba kódigu ne'ebé loos.
Junior Programmer (Estájiu)
Uiabau – Dili, Timor-Leste
[02/2017] – [12/2020]
•	Ajuda dezenvolve no teste kódigu ba aplikasaun web interna.
•	Identifika no hadi'a error (bugs) iha kódigu laran.
•	Dokumenta kódigu no tutorial ba uza-na'in sira.

EDUKASAUN
Lisensiatura iha Enjeñaria Informátika / Siénsia Komputadór
Universidade Nasionál Timór Lorosa'e - UNTL 
Tinan Graduasaun:2021

SERTIFIKADU NO KURSU
•	Sertifikadu Full-Stack Web Development Kursu online Udemy)
•	Kursu Avansadu JavaScript & PHP – Fundasaun Dezenvolvimentu Software Livre 2021)

LIAN (LANGUAGES)
•	Tetum: Lian Inan (Fluente)
•	Portugués: Di'ak (Intermédio / Avansadu)
•	Inglés: Di'ak ba Profisionál (Professional Working Proficiency)
•	Indonéziu: Di'ak (Fluente)

REFERÉNSIA
(Disponível se lori kbiit hodi husu / Available upon request)

Ita hakarak ha'u ajuda edit rezumu profisionál ka aumenta esperiénsia tékniku ne'ebé espesífiku liután (hanesan fokus liu ba Front-End ka Back-End) tuir ita-nia skill lenda nian?

"""


class Command(BaseCommand):
    help = "TASK D: print real language-detection results, and optionally a real translation."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("TASK D -- Language Detection validation"))
        self.stdout.write("")

        for label, (text, expected) in SAMPLES.items():
            result = detect_language(text)
            self.stdout.write(f"  [{label}]  (expected: {expected})")
            self.stdout.write(f"      {result}")
        self.stdout.write("")

        if REAL_TETUM_SAMPLE.strip():
            self.stdout.write(self.style.MIGRATE_HEADING("Real end-to-end translation (calls the LLM)"))
            detection = detect_language(REAL_TETUM_SAMPLE)
            self.stdout.write(f"  Detection: {detection}")
            if detection["tetum_significant"]:
                t0 = time.perf_counter()
                translation = translate_tetum_to_english(REAL_TETUM_SAMPLE)
                elapsed = time.perf_counter() - t0
                self.stdout.write(f"  Translation ({elapsed:.2f}s): success={translation['success']}")
                self.stdout.write(f"  Translated text: {translation['translated_text']}")
            else:
                self.stdout.write("  REAL_TETUM_SAMPLE was not detected as significant Tetum -- no translation run.")
        else:
            self.stdout.write(
                "No REAL_TETUM_SAMPLE set -- skipping real end-to-end translation call. "
                "Edit this file to add a real Tetum CV excerpt if you want to test that part."
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done. Paste this whole output back to Claude."))