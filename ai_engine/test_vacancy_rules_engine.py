"""
Unit tests for ai_engine/services/vacancy_rules_engine.py.

All candidates are SYNTHETIC. Run with either:
    python -m unittest ai_engine.test_vacancy_rules_engine -v
    python manage.py test ai_engine.test_vacancy_rules_engine
No Django, network or embedding model is needed.
"""
import json
import unittest
from datetime import date

from ai_engine.services import vacancy_rules_engine as eng

VAC = "CPI/1/2026"   # General doctor, Licenciatura, 112 positions
IN_TIME = "2026-09-10T09:30:00"


def docs(**override):
    base = {k: {"present": True, "valid": True} for k in (
        "application_letter", "cv", "diploma_legalised", "birth_certificate",
        "voter_card", "bi_card", "training_certificates", "photo_3x4")}
    base.update(override)
    return base


def candidate(**kw):
    c = {
        "date_of_birth": "1995-05-10",
        "education_level": "licenciatura",
        "education_field": "general medicine",
        "diploma_legalised": True,
        "work_history": [{"start": "2025-01-01", "end": "2025-06-30",
                          "field": "general medicine", "facility_type": "health facility"}],
        "documents": docs(),
        "submission_datetime": IN_TIME,
        "cv_lists_training_certificates": True,
    }
    c.update(kw)
    return c


def rule(result, rid):
    return next(r for r in result["rules"] if r["rule_id"] == rid)


class DataIntegrity(unittest.TestCase):
    def test_ten_vacancies_430_positions(self):
        d = eng.load_rules()
        self.assertEqual(len(d["vacancies"]), 10)
        self.assertEqual(sum(v["positions"] for v in d["vacancies"]), 430)

    def test_fourteen_rules_and_types(self):
        d = eng.load_rules()
        self.assertEqual([r["id"] for r in d["rules"]], [f"R{i:02d}" for i in range(1, 15)])
        self.assertEqual({r["id"] for r in d["rules"] if r["type"] == "human"}, {"R05", "R14"})

    def test_no_personal_data_flag_and_status(self):
        d = eng.load_rules()
        self.assertFalse(d["contains_personal_data"])
        self.assertTrue(d["status"].startswith("UNVERIFIED"))

    def test_schema_required_keys_present(self):
        with open(eng.RULES_PATH.parent / "vacancy_rules.schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        d = eng.load_rules()
        for k in schema["required"]:
            self.assertIn(k, d)
        need = schema["properties"]["vacancies"]["items"]["required"]
        for v in d["vacancies"]:
            for k in need:
                self.assertIn(k, v, v["code"])

    def test_every_vacancy_has_age_20_55_and_pass_mark_60(self):
        for v in eng.load_rules()["vacancies"]:
            r = v["requirements"]
            self.assertEqual((r["R02"]["min_age"], r["R02"]["max_age"]), (20, 55), v["code"])
            self.assertEqual(r["R11"]["written_min_score"], 60)
            self.assertAlmostEqual(r["R13"]["general_weight"] + r["R13"]["specific_weight"], 1.0)


class AgeBoundaries(unittest.TestCase):
    REF = date(2026, 9, 18)

    def age_outcome(self, dob):
        return rule(eng.evaluate_vacancy_eligibility(candidate(date_of_birth=dob), VAC), "R02")["outcome"]

    def test_19_is_review_because_law_allows_17(self):
        # notice (min 20) says FAIL, reference law (min 17) says PASS -> person decides
        self.assertEqual(self.age_outcome("2006-09-19"), eng.REVIEW)   # turns 20 the day after closing

    def test_19_fails_only_under_notice_policy(self):
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2006-09-19"), VAC,
                                               conflict_policy="notice")
        self.assertEqual(rule(res, "R02")["outcome"], eng.FAIL)
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2006-09-19"), VAC,
                                               conflict_policy="law")
        self.assertEqual(rule(res, "R02")["outcome"], eng.PASS)

    def test_16_fails_under_both_notice_and_law(self):
        self.assertEqual(self.age_outcome("2010-09-18"), eng.FAIL)     # exactly 16
        self.assertEqual(self.age_outcome("2009-09-18"), eng.REVIEW)   # exactly 17: law passes, notice fails

    def test_age_conflict_is_reported_with_citation(self):
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2007-01-01"), VAC)
        c = res["law_conflicts"][0]
        self.assertEqual((c["rule_id"], c["notice"], c["law"]), ("R02", "20-55", "17-55"))
        self.assertIn("Law 5/2009", c["citation"])

    def test_exactly_20_passes(self):
        self.assertEqual(self.age_outcome("2006-09-18"), eng.PASS)

    def test_exactly_55_passes(self):
        self.assertEqual(self.age_outcome("1971-09-18"), eng.PASS)   # turned 55 on closing day

    def test_day_before_56th_birthday_passes(self):
        self.assertEqual(self.age_outcome("1970-09-19"), eng.PASS)   # still 55 completed years

    def test_56_fails(self):
        self.assertEqual(self.age_outcome("1970-09-18"), eng.FAIL)

    def test_missing_dob_needs_review(self):
        r = rule(eng.evaluate_vacancy_eligibility(candidate(date_of_birth=None), VAC), "R02")
        self.assertEqual(r["outcome"], eng.REVIEW)

    def test_age_function_leap_day(self):
        self.assertEqual(eng.age_in_years("2000-02-29", "2026-02-28"), 25)
        self.assertEqual(eng.age_in_years("2000-02-29", "2026-03-01"), 26)

    def test_reference_date_changes_result_and_assumption_is_reported(self):
        c = candidate(date_of_birth="2006-10-01")
        early = eng.evaluate_vacancy_eligibility(c, VAC, reference_date="2026-09-18")
        later = eng.evaluate_vacancy_eligibility(c, VAC, reference_date="2026-10-02")
        self.assertEqual(rule(early, "R02")["outcome"], eng.REVIEW)   # 19: notice FAIL, law PASS
        self.assertEqual(rule(later, "R02")["outcome"], eng.PASS)
        self.assertTrue(any("R02" in a for a in early["assumptions"]))


class Experience(unittest.TestCase):
    def hist(self, start, end, field="general medicine", fac="health facility"):
        return [{"start": start, "end": end, "field": field, "facility_type": fac}]

    def exp(self, history):
        return rule(eng.evaluate_vacancy_eligibility(candidate(work_history=history), VAC), "R04")

    def test_full_months_edges(self):
        self.assertEqual(eng.full_months("2026-01-01", "2026-03-31"), 3)
        self.assertEqual(eng.full_months("2026-01-01", "2026-03-30"), 2)
        # month-end clamp: 31 Jan + 3 months = 30 Apr, so 31 Jan..29 Apr inclusive is 3 months, ..28 Apr is 2
        self.assertEqual(eng.full_months("2026-01-31", "2026-04-29"), 3)
        self.assertEqual(eng.full_months("2026-01-31", "2026-04-28"), 2)
        self.assertEqual(eng.full_months("2026-05-01", "2026-04-01"), 0)

    def test_exactly_three_months_passes(self):
        self.assertEqual(self.exp(self.hist("2026-01-01", "2026-03-31"))["outcome"], eng.PASS)

    def test_two_months_fails(self):
        self.assertEqual(self.exp(self.hist("2026-01-01", "2026-02-28"))["outcome"], eng.FAIL)

    def test_no_experience_fails(self):
        self.assertEqual(self.exp([])["outcome"], eng.FAIL)

    def test_overlapping_jobs_not_double_counted(self):
        h = self.hist("2026-01-01", "2026-02-28") + self.hist("2026-01-15", "2026-02-20")
        self.assertEqual(self.exp(h)["outcome"], eng.FAIL)
        self.assertEqual(self.exp(h)["evidence"]["matching_months"], 2)

    def test_adjacent_jobs_are_merged(self):
        h = self.hist("2026-01-01", "2026-01-31") + self.hist("2026-02-01", "2026-03-31")
        self.assertEqual(self.exp(h)["outcome"], eng.PASS)

    def test_other_field_enough_months_goes_to_review_not_fail(self):
        r = self.exp(self.hist("2025-01-01", "2025-12-31", field="administration"))
        self.assertEqual(r["outcome"], eng.REVIEW)

    def test_not_a_health_facility_goes_to_review(self):
        r = self.exp(self.hist("2025-01-01", "2025-12-31", fac="private company"))
        self.assertEqual(r["outcome"], eng.REVIEW)


class Documents(unittest.TestCase):
    def test_complete_candidate_needs_human_only_for_human_rules(self):
        res = eng.evaluate_vacancy_eligibility(candidate(), VAC)
        self.assertEqual(res["failed_rule_ids"], [])
        self.assertEqual(res["overall"], "HUMAN_REVIEW")   # R05/R14 are always human; R07/R08 not provided
        self.assertIn("R05", res["review_rule_ids"])
        self.assertIn("R14", res["review_rule_ids"])
        self.assertEqual(res["decision_authority"], "jury")

    def test_missing_voter_card_fails_r01_and_r09(self):
        c = candidate(documents=docs(voter_card={"present": False}))
        res = eng.evaluate_vacancy_eligibility(c, VAC)
        self.assertEqual(res["overall"], "REJECT_RECOMMENDED")
        self.assertEqual(res["failed_rule_ids"], ["R01", "R09"])

    def test_missing_training_certificates_ok_when_cv_lists_none(self):
        c = candidate(documents=docs(training_certificates={"present": False}),
                      cv_lists_training_certificates=False)
        self.assertEqual(rule(eng.evaluate_vacancy_eligibility(c, VAC), "R09")["outcome"], eng.PASS)

    def test_missing_training_certificates_fails_when_cv_lists_them(self):
        c = candidate(documents=docs(training_certificates={"present": False}))
        self.assertEqual(rule(eng.evaluate_vacancy_eligibility(c, VAC), "R09")["outcome"], eng.FAIL)

    def test_expired_bi_fails_r01(self):
        c = candidate(documents=docs(bi_card={"present": True, "valid": False}))
        self.assertEqual(rule(eng.evaluate_vacancy_eligibility(c, VAC), "R01")["outcome"], eng.FAIL)

    def test_medical_certificate_not_due_at_document_stage(self):
        res = eng.evaluate_vacancy_eligibility(candidate(), VAC)
        self.assertEqual(rule(res, "R06")["outcome"], eng.NOT_DUE)

    def test_medical_certificate_due_at_interview(self):
        res = eng.evaluate_vacancy_eligibility(candidate(), VAC, stage="interview")
        self.assertEqual(rule(res, "R06")["outcome"], eng.REVIEW)
        c = candidate(documents=docs(medical_certificate={"present": True, "valid": True}))
        res = eng.evaluate_vacancy_eligibility(c, VAC, stage="interview")
        self.assertEqual(rule(res, "R06")["outcome"], eng.PASS)

    def test_all_optional_documents_present_still_human_review(self):
        extra = {"medical_certificate": {"present": True, "valid": True},
                 "good_conduct_certificate": {"present": True, "valid": True},
                 "professional_card_mds": {"present": True, "valid": True}}
        res = eng.evaluate_vacancy_eligibility(candidate(documents=docs(**extra)), VAC, stage="interview")
        self.assertEqual(sorted(res["review_rule_ids"]), ["R05", "R14"])


class SubmissionWindow(unittest.TestCase):
    def r09(self, ts):
        return rule(eng.evaluate_vacancy_eligibility(candidate(submission_datetime=ts), VAC), "R09")["outcome"]

    def test_first_day_start_of_hours_passes(self):
        self.assertEqual(self.r09("2026-09-07T08:00:00"), eng.PASS)

    def test_last_day_end_of_hours_passes(self):
        self.assertEqual(self.r09("2026-09-18T17:30:00"), eng.PASS)

    def test_day_before_window_fails(self):
        self.assertEqual(self.r09("2026-09-04T10:00:00"), eng.FAIL)

    def test_day_after_window_fails(self):
        self.assertEqual(self.r09("2026-09-21T10:00:00"), eng.FAIL)

    def test_lunch_break_fails(self):
        self.assertEqual(self.r09("2026-09-10T12:30:00"), eng.FAIL)

    def test_after_hours_fails(self):
        self.assertEqual(self.r09("2026-09-10T17:31:00"), eng.FAIL)

    def test_weekend_inside_window_fails(self):
        self.assertEqual(self.r09("2026-09-12T10:00:00"), eng.FAIL)   # Saturday

    def test_missing_timestamp_fails(self):
        self.assertEqual(self.r09(None), eng.FAIL)


class Education(unittest.TestCase):
    def edu(self, **kw):
        return rule(eng.evaluate_vacancy_eligibility(candidate(**kw), VAC), "R03")["outcome"]

    def test_match_passes(self):
        self.assertEqual(self.edu(), eng.PASS)

    def test_lower_level_fails(self):
        self.assertEqual(self.edu(education_level="bacharelatu"), eng.FAIL)

    def test_other_field_needs_review(self):
        self.assertEqual(self.edu(education_field="nursing"), eng.REVIEW)

    def test_legalisation_unconfirmed_needs_review(self):
        self.assertEqual(self.edu(diploma_legalised=None), eng.REVIEW)

    def test_higher_level_than_bachelor_vacancy_needs_review(self):
        res = eng.evaluate_vacancy_eligibility(
            candidate(education_level="licenciatura", education_field="refractionist"), "CPI/18/2026")
        self.assertEqual(rule(res, "R03")["outcome"], eng.REVIEW)

    def test_cpi4_inconsistent_text_always_review(self):
        res = eng.evaluate_vacancy_eligibility(
            candidate(education_level="bacharelatu", education_field="nursing"), "CPI/4/2026")
        self.assertEqual(rule(res, "R03")["outcome"], eng.REVIEW)


class Stages(unittest.TestCase):
    def test_weighted_written_score(self):
        self.assertEqual(eng.weighted_written_score(80, 60, VAC), 65.0)
        self.assertEqual(eng.weighted_written_score(100, 0), 25.0)

    def test_stage_one_unknown_is_human(self):
        self.assertEqual(eng.evaluate_stage_progress(VAC)["rules"][0]["outcome"], eng.HUMAN)

    def test_eliminated_at_stage_one(self):
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=False, written_score=90)
        self.assertEqual(res["next_stage"], None)
        self.assertEqual(res["rules"][0]["outcome"], eng.FAIL)

    def test_written_below_60_eliminated_above_60_continues_60_is_review(self):
        low = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=59.99)
        edge = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=60)
        ok = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=60.01)
        self.assertEqual(low["rules"][-1]["outcome"], eng.FAIL)
        self.assertEqual(edge["rules"][-1]["outcome"], eng.REVIEW)
        self.assertEqual(edge["next_stage"], "HUMAN_DECISION")
        self.assertEqual(ok["next_stage"], "interview")

    def test_final_mean_boundary(self):
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=61, interview_score=61)
        self.assertEqual(res["final_score"], 61.0)
        self.assertEqual(res["rules"][-1]["outcome"], eng.PASS)
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=61, interview_score=59)
        self.assertEqual(res["final_score"], 60.0)
        self.assertEqual(res["rules"][-1]["outcome"], eng.REVIEW)     # exactly 60: notice PASS, law FAIL
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=61, interview_score=58)
        self.assertEqual(res["rules"][-1]["outcome"], eng.FAIL)

    def test_stage_one_score_included_when_given(self):
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, document_stage_score=90,
                                          written_score=70, interview_score=50)
        self.assertEqual(res["final_score"], 70.0)
        self.assertEqual(len(res["scores_used"]), 3)


class StatuteConflict(unittest.TestCase):
    """Notice: 60 passes. Decree-Law 34/2008 Art. 35(1): 60 or less is disqualified.
    Default policy = REVIEW; 'notice' and 'law' are explicit what-if readings."""

    def test_written_exactly_60_by_policy(self):
        kw = dict(document_stage_passed=True, written_score=60)
        d = eng.evaluate_stage_progress(VAC, **kw)
        n = eng.evaluate_stage_progress(VAC, conflict_policy="notice", **kw)
        l = eng.evaluate_stage_progress(VAC, conflict_policy="law", **kw)
        self.assertEqual(d["rules"][-1]["outcome"], eng.REVIEW)
        self.assertEqual(n["next_stage"], "interview")
        self.assertEqual(l["next_stage"], None)
        self.assertEqual(l["rules"][-1]["outcome"], eng.FAIL)

    def test_statute_strict_is_alias_for_law_policy(self):
        b = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=60, statute_strict=True)
        self.assertEqual(b["conflict_policy"], "law")
        self.assertEqual(b["rules"][-1]["outcome"], eng.FAIL)

    def test_final_exactly_60_by_policy(self):
        kw = dict(document_stage_passed=True, written_score=61, interview_score=59)
        self.assertEqual(eng.evaluate_stage_progress(VAC, **kw)["rules"][-1]["outcome"], eng.REVIEW)
        self.assertEqual(eng.evaluate_stage_progress(VAC, conflict_policy="notice", **kw)["rules"][-1]["outcome"], eng.PASS)
        self.assertEqual(eng.evaluate_stage_progress(VAC, conflict_policy="law", **kw)["rules"][-1]["outcome"], eng.FAIL)

    def test_conflict_is_reported_with_citation(self):
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=60)
        c = res["law_conflicts"][0]
        self.assertIn("Art. 35", c["citation"])
        self.assertEqual((c["notice_outcome"], c["law_outcome"]), ("PASS", "FAIL"))

    def test_no_conflict_away_from_the_boundary(self):
        res = eng.evaluate_stage_progress(VAC, document_stage_passed=True, written_score=75)
        self.assertEqual(res["law_conflicts"], [])

    def test_bad_policy_rejected(self):
        with self.assertRaises(ValueError):
            eng.evaluate_stage_progress(VAC, conflict_policy="whatever")


class ReferenceLawFile(unittest.TestCase):
    def test_every_constraint_has_citation_and_existing_rag_source(self):
        law = eng.load_law()
        docs = eng.RULES_DIR.parents[0] / "documents"
        for name, c in law.items():
            self.assertTrue(c.get("citation"), name)
            self.assertTrue((docs / c["rag_source"]).exists(), f"{name}: {c['rag_source']} not in knowledge_base/documents")

    def test_law_values(self):
        law = eng.load_law()
        self.assertEqual((law["age"]["min"], law["age"]["max"]), (17, 55))
        self.assertEqual(law["pass_mark"]["threshold"], 60)
        self.assertEqual(law["probation_months"]["value"], 12)

    def test_law_file_is_not_listed_as_a_job_profile(self):
        self.assertNotIn(eng.LAW_PATH, eng.list_rule_files())


class AuditAgainstLaw(unittest.TestCase):
    def topics(self, code):
        return {d["topic"]: d for d in eng.audit_vacancy_against_law(eng.get_vacancy(code))}

    def test_hngv_differences_found(self):
        t = self.topics(VAC)
        self.assertEqual(t["age range"]["notice"], "20-55")
        self.assertEqual(t["age range"]["law"], "17-55")
        self.assertIn("stricter", t["age range"]["note"])
        self.assertIn("pass-mark boundary", t)
        self.assertIn("official languages", t)
        self.assertIn("appeal clause", t)

    def test_probation_matches_law_so_no_diff(self):
        self.assertNotIn("probation", self.topics(VAC))


def synthetic_job(**req_over):
    """A made-up job profile with only some rule blocks: proves profiles are generic."""
    req = {
        "R02": {"min_age": 18, "max_age": 50, "default_reference_date": "2027-03-01"},
        "R03": {"required_level": "licenciatura", "accepted_fields": ["computer science"],
                "education_text": "Licenciatura in Computer Science",
                "level_rank": {"bacharelatu": 1, "licenciatura": 2}},
        "R04": {"min_months": 12, "field": "software development"},
        "R11": {"written_min_score": 70, "scale_max": 100},
        "R12": {"final_pass_score": 70, "scale_max": 100},
    }
    req.update(req_over)
    return {"code": "SYN/1/2027", "job_title": "Synthetic IT Officer", "positions": 1,
            "source_file": "synthetic", "verification": {"status": "synthetic"}, "requirements": req}


class GenericProfiles(unittest.TestCase):
    def test_vacancy_dict_without_registering_anything(self):
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth="1995-01-01"), vacancy=synthetic_job())
        self.assertEqual(res["vacancy"], "SYN/1/2027")
        self.assertEqual(rule(res, "R02")["outcome"], eng.PASS)

    def test_missing_rule_blocks_are_not_applicable(self):
        res = eng.evaluate_vacancy_eligibility(candidate(), vacancy=synthetic_job())
        for rid in ("R01", "R05", "R06", "R07", "R08", "R09", "R14"):
            self.assertEqual(rule(res, rid)["outcome"], eng.NOT_APPLICABLE, rid)
        self.assertNotIn("R09", res["failed_rule_ids"])

    def test_own_thresholds_are_used(self):
        # notice min age 18; law min 17 -> a 17-year-old is a conflict (REVIEW), 16 fails both
        c17 = candidate(date_of_birth="2010-03-01")
        c16 = candidate(date_of_birth="2011-03-01")
        self.assertEqual(rule(eng.evaluate_vacancy_eligibility(c17, vacancy=synthetic_job()), "R02")["outcome"], eng.REVIEW)
        self.assertEqual(rule(eng.evaluate_vacancy_eligibility(c16, vacancy=synthetic_job()), "R02")["outcome"], eng.FAIL)

    def test_stricter_pass_mark_conflicts_with_law_only_between_the_two(self):
        j = synthetic_job()
        out = lambda s: eng.evaluate_stage_progress(vacancy=j, document_stage_passed=True, written_score=s)["rules"][-1]["outcome"]
        self.assertEqual(out(60), eng.FAIL)      # fails notice (70) and law (60 or less)
        self.assertEqual(out(65), eng.REVIEW)    # fails notice, passes law
        self.assertEqual(out(70), eng.PASS)

    def test_job_without_law_constraint_runs_without_conflicts(self):
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2010-03-01"), vacancy=synthetic_job(), law={}, allow_no_law=True)
        self.assertEqual(rule(res, "R02")["outcome"], eng.FAIL)
        self.assertEqual(res["law_conflicts"], [])

    def test_profile_file_in_a_folder_is_discovered_but_not_applied_elsewhere(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "my_ministry.json"
            f.write_text(json.dumps({"vacancies": [synthetic_job()]}), encoding="utf-8")
            (pathlib.Path(d) / "not_a_profile.json").write_text("{}", encoding="utf-8")
            self.assertEqual(eng.list_rule_files(d), [f])
            self.assertEqual(eng.get_vacancy("SYN/1/2027", path=f)["job_title"], "Synthetic IT Officer")
        with self.assertRaises(KeyError):                      # HNGV lookup does not see it
            eng.get_vacancy("SYN/1/2027")

    def test_default_profile_discovery_finds_hngv(self):
        self.assertIn(eng.RULES_PATH, eng.list_rule_files())

    def test_weights_default_and_custom(self):
        j = synthetic_job(R13={"general_weight": 0.5, "specific_weight": 0.5})
        self.assertEqual(eng.weighted_written_score(80, 60, vacancy=j), 70.0)
        self.assertEqual(eng.weighted_written_score(80, 60), 65.0)          # no job named: 25/75 default
        with self.assertRaises(ValueError):                                  # job named, no R13: no silent default
            eng.weighted_written_score(80, 60, vacancy=synthetic_job())


def bare_job(**req):
    """A job that declares NO rules of its own."""
    j = synthetic_job()
    j["requirements"] = dict(req)
    return j


class LawAppliesToEveryJob(unittest.TestCase):
    """The reference law is mandatory for all civil-service jobs; a profile only adds to it."""

    def r02(self, dob, job=None, ref="2027-03-01"):
        res = eng.evaluate_vacancy_eligibility(candidate(date_of_birth=dob), vacancy=job or bare_job(),
                                               reference_date=ref)
        return rule(res, "R02")

    def test_job_without_an_age_rule_is_still_checked_against_the_law(self):
        self.assertEqual(self.r02("2010-03-01")["outcome"], eng.PASS)    # exactly 17
        self.assertEqual(self.r02("2011-03-01")["outcome"], eng.FAIL)    # 16

    def test_law_only_age_upper_limit(self):
        self.assertEqual(self.r02("1972-03-01")["outcome"], eng.PASS)    # exactly 55
        self.assertEqual(self.r02("1971-03-01")["outcome"], eng.FAIL)    # 56
        self.assertIn("reference law only", self.r02("1990-01-01")["evidence"]["source"])

    def test_job_without_pass_mark_still_uses_the_law_pass_mark(self):
        out = lambda sc: eng.evaluate_stage_progress(vacancy=bare_job(), document_stage_passed=True,
                                                     written_score=sc)
        self.assertEqual(out(60)["rules"][-1]["outcome"], eng.FAIL)      # law: 60 or less disqualified
        self.assertEqual(out(60.01)["next_stage"], "interview")

    def test_switching_the_law_off_needs_an_explicit_flag(self):
        with self.assertRaises(ValueError):
            eng.evaluate_vacancy_eligibility(candidate(), vacancy=bare_job(), law={})
        with self.assertRaises(ValueError):
            eng.evaluate_stage_progress(vacancy=bare_job(), document_stage_passed=True, written_score=70, law={})

    def test_result_without_law_is_never_a_clean_pass(self):
        res = eng.evaluate_vacancy_eligibility(candidate(), vacancy=bare_job(), law={}, allow_no_law=True)
        self.assertFalse(res["law_applied"])
        self.assertEqual(res["overall"], "HUMAN_REVIEW")
        self.assertTrue(any("WARNING" in a for a in res["assumptions"]))

    def test_law_applied_flag_is_true_by_default(self):
        self.assertTrue(eng.evaluate_vacancy_eligibility(candidate(), VAC)["law_applied"])

    def test_one_jobs_extra_rules_do_not_leak_into_another(self):
        strict = synthetic_job(R02={"min_age": 30, "max_age": 40, "default_reference_date": "2027-03-01"})
        plain = bare_job()
        dob = "1997-03-01"          # 30 on the reference date
        a = rule(eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2000-03-01"), vacancy=strict), "R02")
        b = rule(eng.evaluate_vacancy_eligibility(candidate(date_of_birth="2000-03-01"), vacancy=plain,
                                                  reference_date="2027-03-01"), "R02")
        self.assertEqual(a["outcome"], eng.REVIEW)     # 27: notice FAIL (min 30), law PASS -> person decides
        self.assertEqual(b["outcome"], eng.PASS)       # the other job is untouched by that extra rule


class Adapter(unittest.TestCase):
    def test_job_requirement_shape(self):
        j = eng.vacancy_to_job_requirement("CPI/2/2026")
        self.assertEqual(j["years_experience"], 0.25)
        for k in ("education", "languages", "certifications", "skills", "job_title"):
            self.assertIn(k, j)

    def test_unknown_vacancy_raises(self):
        with self.assertRaises(KeyError):
            eng.get_vacancy("CPI/99/2026")


if __name__ == "__main__":
    unittest.main()
