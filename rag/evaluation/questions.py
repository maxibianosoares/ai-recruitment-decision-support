# =============================================================
# RAG BENCHMARK — 40 QUESTION MATRIX
#
# Every question below was checked against the actual indexed
# corpus (knowledge_base/vector_store/metadata.pkl - 366 chunks
# across 6 policy/legal documents) before being added here.
# "reference_note" is a short, non-binding pointer for a human
# reviewer to sanity-check the model's answer against - it is
# NOT used by the scoring code, which only compares
# "expected" against the pipeline's returned evidence_status.
#
# Categories (per thesis methodology):
#   direct_evidence         - 10
#   partial_evidence        - 10
#   unsupported              - 10
#   temporal                 - 5
#   recruitment_specific      - 5
# =============================================================

BENCHMARK_QUESTIONS = [

    # =========================================================
    # DIRECT EVIDENCE (10) - expected: supported
    # =========================================================

    {
        "id": "DE01",
        "category": "direct_evidence",
        "question": "Can AI replace human recruiters in the civil service?",
        "expected": "supported",
        "reference_note":
            "ai_recruitment_policy.pdf: AI shall assist HR officers but "
            "shall never replace final human decisions."
    },
    {
        "id": "DE02",
        "category": "direct_evidence",
        "question":
            "What information should every AI recommendation provide?",
        "expected": "supported",
        "reference_note":
            "ai_recruitment_policy.pdf: Overall Score, Matching Reason, "
            "Strengths, Weaknesses, Skill Gap Analysis, Confidence Score."
    },
    {
        "id": "DE03",
        "category": "direct_evidence",
        "question": "What is the purpose of the AI recruitment policy?",
        "expected": "supported",
        "reference_note":
            "ai_recruitment_policy.pdf: ensure recruitment is fair, "
            "transparent, accountable, explainable, merit-based."
    },
    {
        "id": "DE04",
        "category": "direct_evidence",
        "question":
            "What is the minimum age requirement to apply for a permanent "
            "position in the Public Administration?",
        "expected": "supported",
        "reference_note":
            "policy.pdf Article 14: candidate must be between 17 and 55 "
            "years old."
    },
    {
        "id": "DE05",
        "category": "direct_evidence",
        "question":
            "Who has the authority to convene and preside over meetings of "
            "the Civil Service Commission?",
        "expected": "supported",
        "reference_note":
            "civil_service_commission_law.pdf Article 15: Competence of "
            "the Chairperson."
    },
    {
        "id": "DE06",
        "category": "direct_evidence",
        "question":
            "Which body has the authority to open a recruitment "
            "competition for Public Service careers?",
        "expected": "supported",
        "reference_note":
            "recruitment_law.pdf Article 9: Comissao da Funcao Publica."
    },
    {
        "id": "DE07",
        "category": "direct_evidence",
        "question":
            "Can the Commission's authority to open a recruitment "
            "competition be delegated to another official?",
        "expected": "supported",
        "reference_note":
            "recruitment_law.pdf Article 9(2): may be delegated to the "
            "Director-General or equivalent."
    },
    {
        "id": "DE08",
        "category": "direct_evidence",
        "question":
            "Who acts as secretary of the selection jury during a "
            "recruitment competition?",
        "expected": "supported",
        "reference_note":
            "recruitment_law.pdf: a jury member chosen by the jury "
            "president."
    },
    {
        "id": "DE09",
        "category": "direct_evidence",
        "question":
            "What is one of the core functions of the Civil Service "
            "Commission regarding recruitment?",
        "expected": "supported",
        "reference_note":
            "civil_service_commission_law.pdf Article 5: ensure "
            "recruitment is based on merit."
    },
    {
        "id": "DE10",
        "category": "direct_evidence",
        "question":
            "What principle governs the selection and recruitment of "
            "personnel according to the civil service law?",
        "expected": "supported",
        "reference_note":
            "policy.pdf Article 8: Igualdade (equality)."
    },

    # =========================================================
    # PARTIAL EVIDENCE (10) - expected: partially_supported
    # =========================================================

    {
        "id": "PE01",
        "category": "partial_evidence",
        "question":
            "What does the AI recruitment system do, and what salary "
            "should the selected candidate receive?",
        "expected": "partially_supported",
        "supported_parts": [
            "The AI system assists with resume screening, candidate "
            "ranking, skill matching, interview recommendation, and "
            "recruitment analytics."
        ],
        "unsupported_parts": [
            "The knowledge base does not specify a salary for the "
            "selected candidate."
        ]
    },
    {
        "id": "PE02",
        "category": "partial_evidence",
        "question":
            "Can AI rank candidates and determine their monthly salary?",
        "expected": "partially_supported",
        "supported_parts": ["AI can assist with candidate ranking."],
        "unsupported_parts": [
            "The policy does not say AI determines monthly salary."
        ]
    },
    {
        "id": "PE03",
        "category": "partial_evidence",
        "question":
            "The Commission ensures merit-based recruitment - but what "
            "exact score threshold does the AI system use to reject a "
            "candidate?",
        "expected": "partially_supported",
        "supported_parts": [
            "Recruitment must follow a merit-based process."
        ],
        "unsupported_parts": [
            "No specific AI rejection score threshold is defined in the "
            "knowledge base."
        ]
    },
    {
        "id": "PE04",
        "category": "partial_evidence",
        "question":
            "The recruitment jury has legal duties during a competition - "
            "but how much is each jury member paid for this duty?",
        "expected": "partially_supported",
        "supported_parts": [
            "The jury has defined legal functions and duties during a "
            "recruitment competition."
        ],
        "unsupported_parts": [
            "No jury member payment/allowance amount is specified."
        ]
    },
    {
        "id": "PE05",
        "category": "partial_evidence",
        "question":
            "Public servants are entitled to several types of paid leave - "
            "but how many days of annual leave is a new recruit entitled "
            "to in their first year?",
        "expected": "partially_supported",
        "supported_parts": [
            "Public servants are entitled to categories of paid leave "
            "including annual leave, medical leave, bereavement leave, "
            "and maternity leave."
        ],
        "unsupported_parts": [
            "The exact number of annual leave days for a first-year "
            "recruit is not established in the retrieved evidence."
        ]
    },
    {
        "id": "PE06",
        "category": "partial_evidence",
        "question":
            "Officials sent for training abroad receive daily allowances "
            "- but what is the exact daily allowance amount for an ICT "
            "specialist?",
        "expected": "partially_supported",
        "supported_parts": [
            "Officials on foreign training activities are entitled to "
            "daily allowances (ajudas de custo diarias)."
        ],
        "unsupported_parts": [
            "No specific amount tied to an ICT specialist role is "
            "defined."
        ]
    },
    {
        "id": "PE07",
        "category": "partial_evidence",
        "question":
            "The Chairperson can assign functions to commissioners - but "
            "who specifically holds that position right now?",
        "expected": "partially_supported",
        "supported_parts": [
            "The Chairperson has the power to assign functions to "
            "commissioners."
        ],
        "unsupported_parts": [
            "The current, present-day identity of the Chairperson is not "
            "established by the static policy documents."
        ]
    },
    {
        "id": "PE08",
        "category": "partial_evidence",
        "question":
            "AI recommendations must include a skill gap analysis - but "
            "what specific skill gap percentage triggers a 'Not "
            "Recommended' decision?",
        "expected": "partially_supported",
        "supported_parts": [
            "Every AI recommendation must include a Skill Gap Analysis."
        ],
        "unsupported_parts": [
            "No numeric threshold connecting skill gap to a "
            "'Not Recommended' outcome is defined."
        ]
    },
    {
        "id": "PE09",
        "category": "partial_evidence",
        "question":
            "A candidate must meet a minimum age to be recruited - but "
            "what is the minimum required years of prior work experience?",
        "expected": "partially_supported",
        "supported_parts": [
            "A minimum age requirement (17-55 years) applies to "
            "recruitment."
        ],
        "unsupported_parts": [
            "A minimum years-of-experience requirement is not "
            "established in the retrieved evidence."
        ]
    },
    {
        "id": "PE10",
        "category": "partial_evidence",
        "question":
            "The recruitment law authorizes the Commission to open "
            "competitions - but what is the maximum number of days a "
            "competition must stay open for applications?",
        "expected": "partially_supported",
        "supported_parts": [
            "The Commission holds the authority to open recruitment "
            "competitions."
        ],
        "unsupported_parts": [
            "A specific maximum number of open-application days is not "
            "established in the retrieved evidence."
        ]
    },

    # =========================================================
    # UNSUPPORTED / OUT-OF-SCOPE (10) - expected: unsupported
    # =========================================================

    {
        "id": "OS01",
        "category": "unsupported",
        "question":
            "What is the monthly salary of a civil servant in "
            "Timor-Leste?",
        "expected": "unsupported"
    },
    {
        "id": "OS02",
        "category": "unsupported",
        "question": "What is the best tourist destination in Dili?",
        "expected": "unsupported"
    },
    {
        "id": "OS03",
        "category": "unsupported",
        "question": "How do I apply for a Timor-Leste passport?",
        "expected": "unsupported"
    },
    {
        "id": "OS04",
        "category": "unsupported",
        "question": "What is the capital city of Indonesia?",
        "expected": "unsupported"
    },
    {
        "id": "OS05",
        "category": "unsupported",
        "question": "What is the weather forecast for Dili this week?",
        "expected": "unsupported"
    },
    {
        "id": "OS06",
        "category": "unsupported",
        "question":
            "Which team won the most recent Liga Futebol Amadora "
            "championship?",
        "expected": "unsupported"
    },
    {
        "id": "OS07",
        "category": "unsupported",
        "question":
            "What programming languages are required for a software "
            "engineering job at a private tech company?",
        "expected": "unsupported"
    },
    {
        "id": "OS08",
        "category": "unsupported",
        "question": "How do I renew a driver's license in Timor-Leste?",
        "expected": "unsupported"
    },
    {
        "id": "OS09",
        "category": "unsupported",
        "question":
            "What is the exchange rate between US dollars and Indonesian "
            "rupiah?",
        "expected": "unsupported"
    },
    {
        "id": "OS10",
        "category": "unsupported",
        "question":
            "What is the recommended diet for improving productivity at "
            "work?",
        "expected": "unsupported"
    },

    # =========================================================
    # TEMPORAL / COMPLEX (5) - expected: unsupported
    # (evidence exists but is historical; temporal_guard must
    # refuse to treat it as establishing the CURRENT fact)
    # =========================================================

    {
        "id": "TC01",
        "category": "temporal",
        "question": "Who is the current President of Timor-Leste?",
        "expected": "unsupported",
        "reference_note":
            "Corpus contains only historical/promulgation references."
    },
    {
        "id": "TC02",
        "category": "temporal",
        "question": "Who is the current Prime Minister of Timor-Leste?",
        "expected": "unsupported",
        "reference_note":
            "Corpus contains only historical/promulgation references."
    },
    {
        "id": "TC03",
        "category": "temporal",
        "question":
            "Who is the current Chairperson of the Civil Service "
            "Commission?",
        "expected": "unsupported",
        "reference_note":
            "Law defines the role's powers, not who currently holds it."
    },
    {
        "id": "TC04",
        "category": "temporal",
        "question":
            "What is the latest amendment made to the recruitment law?",
        "expected": "unsupported",
        "reference_note":
            "Corpus holds dated legal text, not a changelog of the most "
            "recent amendment."
    },
    {
        "id": "TC05",
        "category": "temporal",
        "question":
            "Who currently holds the position of Director-General "
            "overseeing public sector training programs?",
        "expected": "unsupported",
        "reference_note":
            "Regime-Formacao-Desenvolvimento.pdf defines the role, not "
            "the present-day officeholder."
    },

    # =========================================================
    # RECRUITMENT-SPECIFIC (5) - expected: supported
    # (Commission authority / jury discipline & sanctions)
    # =========================================================

    {
        "id": "RS01",
        "category": "recruitment_specific",
        "question":
            "Who may not be appointed as a Commissioner of the Civil "
            "Service Commission?",
        "expected": "supported",
        "reference_note":
            "civil_service_commission_law.pdf: President of the "
            "Republic, National Parliament members, Government members, "
            "sitting judges/prosecutors, election candidates."
    },
    {
        "id": "RS02",
        "category": "recruitment_specific",
        "question":
            "What happens if a jury member fails to meet the deadlines "
            "required for their jury duties?",
        "expected": "supported",
        "reference_note":
            "recruitment_law.pdf Article 16: jury members incur "
            "disciplinary responsibility for unjustified delays."
    },
    {
        "id": "RS03",
        "category": "recruitment_specific",
        "question":
            "How many commissioners must be present at minimum for a "
            "Commission decision to be approved?",
        "expected": "supported",
        "reference_note":
            "civil_service_commission_law.pdf: minimum of three "
            "commissioners present, approved by majority."
    },
    {
        "id": "RS04",
        "category": "recruitment_specific",
        "question":
            "What professional background is required to be eligible for "
            "appointment as a Commissioner?",
        "expected": "supported",
        "reference_note":
            "civil_service_commission_law.pdf: experience in policies, "
            "management, public administration, law, industrial "
            "relations, or employment."
    },
    {
        "id": "RS05",
        "category": "recruitment_specific",
        "question":
            "Does jury duty take precedence over a jury member's other "
            "official functions during a recruitment competition?",
        "expected": "supported",
        "reference_note":
            "recruitment_law.pdf Article 16: jury duties prevail over "
            "all other functions."
    }

]
