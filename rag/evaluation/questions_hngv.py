# -*- coding: utf-8 -*-
"""
HNGV 2026 benchmark extension (40 questions).

These questions are written against the corpus built by
`python -m rag.build_hngv_corpus` PLUS the existing 11 PDFs
(knowledge_base/documents). They are only meaningful once the staged
files in knowledge_base/documents_staging/hngv_2026/ have been copied to
knowledge_base/documents/ and the index has been rebuilt.

STATUS: labels are the author's (first labeller) judgement, checked against
the vacancy-rules JSON and, for cross-source items, the PDF text of
Decree-Law 34/2008 (Art. 23, 33, 35, 43) and policy.pdf (age 17-55).
No benchmark result has been produced for them. Before use in a paper:
  1. a second person labels `expected` independently (fill `labeler_2`);
  2. items with label_confidence == "borderline" are discussed and fixed;
  3. every HNGV value is checked against the original PDF.

Categories (new):
  hngv_direct        answer stated in one HNGV notice            -> supported
  hngv_partial       part stated, part missing / not in notice    -> partially_supported
  hngv_unsupported   not in corpus (not processed / no data)      -> unsupported
  hngv_cross_source  needs HNGV notice AND a statute in corpus    -> supported / partially_supported
  hngv_temporal      depends on "today" or later events           -> unsupported / partially_supported
"""

HNGV_QUESTIONS = [

    # ------------------------------------------------------------------ direct
    {"id": "HD01", "category": "hngv_direct", "expected": "supported",
     "question": "What are the minimum and maximum ages for applicants to vacancy CPI/1/2026 (General Doctor) at HNGV?",
     "reference_note": "CPI/1/2026 mandatory requirement 1: age 20 to 55."},
    {"id": "HD02", "category": "hngv_direct", "expected": "supported",
     "question": "How many positions does vacancy CPI/2/2026 for nurses offer?",
     "reference_note": "CPI/2/2026: 236 positions."},
    {"id": "HD03", "category": "hngv_direct", "expected": "supported",
     "question": "What is the monthly salary for the Nursing Assistant vacancy CPI/4/2026?",
     "reference_note": "CPI/4/2026: USD 250."},
    {"id": "HD04", "category": "hngv_direct", "expected": "supported",
     "question": "What is the monthly salary offered in vacancy CPI/18/2026 for the refractionist (ophthalmology) position?",
     "reference_note": "CPI/18/2026: USD 405, category TDTSP Geral Junior B/1."},
    {"id": "HD05", "category": "hngv_direct", "expected": "supported",
     "question": "Which qualification is required for the Midwife vacancy CPI/5/2026?",
     "reference_note": "CPI/5/2026: Licenciatura in Midwifery, legalised by MESCC."},
    {"id": "HD06", "category": "hngv_direct", "expected": "supported",
     "question": "How much work experience is required for the Radiology Technician vacancy CPI/7/2026?",
     "reference_note": "CPI/7/2026: at least 3 months in radiology in a health facility."},
    {"id": "HD07", "category": "hngv_direct", "expected": "supported",
     "question": "During which dates could applicants submit documents for the HNGV 2026 vacancies?",
     "reference_note": "7 to 18 September 2026, 10 working days."},
    {"id": "HD08", "category": "hngv_direct", "expected": "supported",
     "question": "What are the daily submission hours for application documents in vacancy CPI/1/2026?",
     "reference_note": "08:00-12:00 and 13:30-17:30 on working days."},
    {"id": "HD09", "category": "hngv_direct", "expected": "supported",
     "question": "How is the written test content weighted between general and specific subjects in vacancy CPI/14/2026?",
     "reference_note": "General subjects 25%, specific subjects 75%."},
    {"id": "HD10", "category": "hngv_direct", "expected": "supported",
     "question": "In what order are the selection stages of vacancy CPI/13/2026 carried out?",
     "reference_note": "Document assessment, written test, interview; eliminatory."},
    {"id": "HD11", "category": "hngv_direct", "expected": "supported",
     "question": "What written-test score allows a candidate in vacancy CPI/8/2026 to continue to the interview?",
     "reference_note": "Score of 60."},
    {"id": "HD12", "category": "hngv_direct", "expected": "supported",
     "question": "Where are the results of the HNGV competition published?",
     "reference_note": "hngv.ms.gov.tl/rekrutamentu, official HNGV Facebook page, Civil Service Commission vacancy website."},
    {"id": "HD13", "category": "hngv_direct", "expected": "supported",
     "question": "How many positions and what salary does the General Doctor vacancy CPI/1/2026 offer?",
     "reference_note": "112 positions, USD 610."},
    {"id": "HD14", "category": "hngv_direct", "expected": "supported",
     "question": "What type of appointment and probation period apply to the HNGV 2026 vacancy CPI/1/2026?",
     "reference_note": "Permanent appointment with a probation period of 1 year."},
    {"id": "HD15", "category": "hngv_direct", "expected": "supported",
     "question": "At which stage must the medical certificate be presented in vacancy CPI/2/2026?",
     "reference_note": "At the interview stage."},

    # ----------------------------------------------------------------- partial
    {"id": "HP01", "category": "hngv_partial", "expected": "partially_supported", "label_confidence": "borderline",
     "question": "How are applications scored in the document assessment stage of vacancy CPI/1/2026, and what score is needed to pass it?",
     "supported_parts": ["Document assessment is stage I; candidates who pass continue to the written test."],
     "unsupported_parts": ["Scoring criteria and pass score of stage I are not stated (accountability gap R14)."]},
    {"id": "HP02", "category": "hngv_partial", "expected": "partially_supported",
     "question": "When must a candidate for vacancy CPI/1/2026 submit the 'Bom Comportamento' good-conduct certificate?",
     "supported_parts": ["A valid Bom Comportamento certificate from the Ministry of Justice is a mandatory requirement."],
     "unsupported_parts": ["It is not in the numbered list of documents to submit; submission time is not stated."]},
    {"id": "HP03", "category": "hngv_partial", "expected": "partially_supported",
     "question": "How is English proficiency tested for applicants to vacancy CPI/2/2026?",
     "supported_parts": ["Minimum knowledge of English is required, besides Tetum and Portuguese."],
     "unsupported_parts": ["No test method, level or minimum score is described."]},
    {"id": "HP04", "category": "hngv_partial", "expected": "partially_supported",
     "question": "Does the notice for vacancy CPI/5/2026 require an employer letter as proof of the 3 months of experience?",
     "supported_parts": ["3 months of experience in a health facility are required; CV and training certificates are listed."],
     "unsupported_parts": ["An experience letter is not among the listed documents; how experience is proven is not stated."]},
    {"id": "HP05", "category": "hngv_partial", "expected": "partially_supported",
     "question": "On what date is an applicant's age measured to check the 20 to 55 limit in vacancy CPI/1/2026?",
     "supported_parts": ["Age limits are 20 and 55 years, proven by identity documents."],
     "unsupported_parts": ["The reference date (closing date, test date, appointment date) is not stated."]},
    {"id": "HP06", "category": "hngv_partial", "expected": "partially_supported",
     "question": "Which exact diploma does the Nursing Assistant vacancy CPI/4/2026 require?",
     "supported_parts": ["The notice lists Bacharelatu in nursing/midwifery and Licenciatura in Public Health."],
     "unsupported_parts": ["Item 5 restricts the vacancy to Diploma III in the assistant field; the text is inconsistent."],
     "label_confidence": "borderline"},
    {"id": "HP07", "category": "hngv_partial", "expected": "partially_supported",
     "question": "How are the 112 positions of vacancy CPI/1/2026 allocated among candidates who score above the pass mark?",
     "supported_parts": ["Candidates with a final classification of 60 or more are considered suitable; 112 positions are offered."],
     "unsupported_parts": ["The ranking and cut-off rule against the number of positions is not stated."]},
    {"id": "HP08", "category": "hngv_partial", "expected": "partially_supported",
     "question": "What weight does the document assessment stage have in the final classification of vacancy CPI/22/2026?",
     "supported_parts": ["The final classification is the simple arithmetic mean of the scores of all stages."],
     "unsupported_parts": ["Whether and how stage I produces a numeric score is not stated."],
     "label_confidence": "borderline"},

    # ------------------------------------------------------------ unsupported
    {"id": "HU01", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "How many positions does vacancy CPI/3/2026 offer?",
     "reference_note": "CPI/3/2026 was not processed into the corpus (12 other HNGV notices pending)."},
    {"id": "HU02", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "How many candidates applied for vacancy CPI/1/2026?",
     "reference_note": "No candidate or application-count data in the corpus."},
    {"id": "HU03", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "Which questions were asked in the written test of vacancy CPI/2/2026?",
     "reference_note": "Only the programme of subjects is in the notice, not test content."},
    {"id": "HU04", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "On what date and at what venue was the written test for vacancy CPI/5/2026 held?",
     "reference_note": "Test date and venue are not in the vacancy notices."},
    {"id": "HU05", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "What is the monthly salary of a Senior General Doctor at HNGV?",
     "reference_note": "Only the Junior 1 category (USD 610) is in the corpus."},
    {"id": "HU06", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "What are the outpatient clinic opening hours at the Hospital Nacional Guido Valadares?",
     "reference_note": "Not in the corpus."},
    {"id": "HU07", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "How many teaching positions did the Ministry of Education announce for 2026?",
     "reference_note": "Other institutions' notices are not in the corpus."},
    {"id": "HU08", "category": "hngv_unsupported", "expected": "unsupported",
     "question": "What interview score did the highest-ranked candidate obtain in vacancy CPI/7/2026?",
     "reference_note": "No candidate results in the corpus (candidate lists deliberately excluded)."},

    # ------------------------------------------------------------ cross-source
    {"id": "HX01", "category": "hngv_cross_source", "expected": "supported",
     "question": "Is the age range in the HNGV special-regime notices the same as the age range for public administration staff in the general rules?",
     "reference_note": "HNGV notices: 20-55. policy.pdf (Law 5/2009 amending Law 8/2004): 17-55. They differ."},
    {"id": "HX02", "category": "hngv_cross_source", "expected": "supported",
     "question": "Is a candidate with exactly 60 points disqualified under Decree-Law 34/2008, and how does the HNGV notice treat a score of 60?",
     "reference_note": "DL 34/2008 Art. 35(1): 60 points or less is disqualified. HNGV notice: 60 or more is suitable / continues. They conflict at 60."},
    {"id": "HX03", "category": "hngv_cross_source", "expected": "supported",
     "question": "How long is the probation period under Decree-Law 34/2008, and how long is it in the HNGV notices?",
     "reference_note": "DL 34/2008 Art. 43: twelve months. HNGV notices: 1 year. Consistent."},
    {"id": "HX04", "category": "hngv_cross_source", "expected": "supported",
     "question": "Which language ability does Decree-Law 34/2008 require, and what do the HNGV notices require?",
     "reference_note": "DL 34/2008 Art. 23: fluency in at least one official language. HNGV: mastery of Tetum and Portuguese (stricter)."},
    {"id": "HX05", "category": "hngv_cross_source", "expected": "partially_supported",
     "question": "How long does an excluded candidate have to appeal, and what do the HNGV 2026 notices say about appeals?",
     "supported_parts": ["DL 34/2008 Art. 33: 5 working days to lodge an appeal with the authority that opened the competition."],
     "unsupported_parts": ["The HNGV notices do not mention appeals."]},

    # ---------------------------------------------------------------- temporal
    {"id": "HT01", "category": "hngv_temporal", "expected": "unsupported",
     "question": "Are applications for the HNGV special-regime vacancies still open today?",
     "reference_note": "Corpus gives the 7-18 September 2026 period, not today's status."},
    {"id": "HT02", "category": "hngv_temporal", "expected": "unsupported",
     "question": "Has the final result list of vacancy CPI/1/2026 been published, and who ranked first?",
     "reference_note": "Corpus says where results will be published, not that they were or what they say."},
    {"id": "HT03", "category": "hngv_temporal", "expected": "unsupported",
     "question": "Which new HNGV vacancies were announced after September 2026?",
     "reference_note": "Corpus holds only the September 2026 notices."},
    {"id": "HT04", "category": "hngv_temporal", "expected": "partially_supported", "label_confidence": "borderline",
     "question": "Is the suspension of general-regime recruitment still in force today?",
     "supported_parts": ["Circular 225/2025 of 17 April suspended general-regime recruitment and does not cover the special regime."],
     "unsupported_parts": ["Whether the suspension is still in force today is not stated."]},
]


def counts():
    from collections import Counter
    return Counter((q["category"], q["expected"]) for q in HNGV_QUESTIONS)
