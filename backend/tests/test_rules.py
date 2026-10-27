"""Unit tests for the deterministic rule modules (the LLM is never involved here)."""
import pytest

from app.domain.enums import AdaptationAction, CandidateKind, ConflictType, ReadinessResult, RiskLevel
from app.rules import conflict_rules, hard_rules, load_rules, punitive_rules, readiness_rules, risk_scoring


# ---------------------------------------------------------------- UC05 readiness rules (AR-04)
def _checkin(**over):
    base = {"sleep_quality": 4, "fatigue": 3, "soreness": 2, "pain": 0, "recent_activity": "walked", "available_time_min": 40}
    base.update(over)
    return base


def test_ready_when_everything_normal():
    d = readiness_rules.decide(_checkin(), False, False, [], [])
    assert d.result == ReadinessResult.READY and not d.restrictions


def test_pain_threshold_gives_recovery():
    d = readiness_rules.decide(_checkin(pain=4), False, False, [], [])
    assert d.result == ReadinessResult.RECOVERY
    assert "light mobility only" in d.restrictions


def test_low_pain_affecting_activity_gives_recovery():
    d = readiness_rules.decide(_checkin(pain=2, pain_affects_activity=True), False, False, [], [])
    assert d.result == ReadinessResult.RECOVERY


def test_llm_flag_can_only_make_it_safer():
    # LLM says capacity reduced -> Reduced; LLM cannot override a rule-based Recovery
    assert readiness_rules.decide(_checkin(), False, True, [], []).result == ReadinessResult.REDUCED
    assert readiness_rules.decide(_checkin(pain=6), False, False, [], []).result == ReadinessResult.RECOVERY


@pytest.mark.parametrize("over", [dict(fatigue=7), dict(sleep_quality=2), dict(soreness=6)])
def test_reduced_thresholds(over):
    assert readiness_rules.decide(_checkin(**over), False, False, [], []).result == ReadinessResult.REDUCED


def test_missing_information_is_never_ready():
    d = readiness_rules.decide(_checkin(pain=None), False, False, [], [])
    assert d.result is None and "pain" in d.clarification_fields


def test_contradiction_requires_clarification():
    problems = readiness_rules.validate_checkin(_checkin(recent_activity="none", soreness=9))
    assert any("soreness" in p for p in problems)
    # the app recorded activity itself → high soreness is explained, no clarification
    assert readiness_rules.validate_checkin(_checkin(recent_activity=None, soreness=9), has_recorded_activity=True) == []


def test_recent_activity_report_is_optional():
    assert readiness_rules.decide(_checkin(recent_activity=None), False, False, [], []).result == ReadinessResult.READY


def test_active_restriction_forces_recovery():
    d = readiness_rules.decide(_checkin(), False, False, [], ["progression hold after reported pain"])
    assert d.result == ReadinessResult.RECOVERY


# ---------------------------------------------------------------- UC10 hard rules (AR-07)
def _subject(**over):
    base = dict(kind=CandidateKind.DIET, candidate_id="c1", version=1, profile_version=2, current_profile_version=2,
                model_version="mock", allergy_status="known", total_kcal=1800, meals_count=3)
    base.update(over)
    return hard_rules.ReviewSubject(**base)


def _ids(subject):
    return [(t.id, t.critical) for t in hard_rules.apply_hard_rules(subject, hard_rules.DEFAULT_POLICY_HARD_RULES)]


def test_no_rule_on_clean_candidate():
    assert _ids(_subject()) == []


def test_hr01_allergen_in_diet_blocks_non_critically():
    s = _subject(allergies=["peanuts"], allergen_hits=[{"food": "peanut butter", "allergen": "peanut"}])
    assert ("HR-01", False) in _ids(s)


def test_hr02_pain_or_red_flag_is_critical():
    assert ("HR-02", True) in _ids(_subject(kind=CandidateKind.EXERCISE, pain_reported=7))
    assert ("HR-02", True) in _ids(_subject(kind=CandidateKind.EXERCISE, user_input_text="I had chest pain after the walk"))


def test_hr03_recovery_ignored():
    s = _subject(kind=CandidateKind.EXERCISE, readiness_result="Recovery", max_intensity="light-moderate")
    assert ("HR-03", False) in _ids(s)
    ok = _subject(kind=CandidateKind.EXERCISE, readiness_result="Recovery", max_intensity="light")
    assert "HR-03" not in [i for i, _ in _ids(ok)]


def test_hr04_energy_below_floor_or_punitive_language():
    assert ("HR-04", False) in _ids(_subject(total_kcal=1000))
    assert ("HR-04", False) in _ids(_subject(output_text="Skip dinner to compensate for lunch"))


def test_hr05_unknown_allergy_status():
    assert ("HR-05", False) in _ids(_subject(allergy_status="unknown"))
    assert "HR-05" not in [i for i, _ in _ids(_subject(kind=CandidateKind.EXERCISE, allergy_status="unknown"))]


def test_hr06_medical_claims():
    assert ("HR-06", False) in _ids(_subject(output_text="This plan will cure your diabetes"))


def test_hr07_outdated_profile_version():
    assert ("HR-07", False) in _ids(_subject(profile_version=1, current_profile_version=2))
    assert ("HR-07", False) in _ids(_subject(model_version=None))


def test_hr08_self_harm_is_critical():
    assert ("HR-08", True) in _ids(_subject(user_input_text="I will starve myself and use laxatives"))


def test_hr08_colloquial_hunger_is_not_self_harm():
    assert "HR-08" not in [i for i, _ in _ids(_subject(user_input_text="I'm starving by mid-morning"))]


def test_hr04_exercise_text_about_knee_is_not_punitive():
    s = _subject(kind=CandidateKind.EXERCISE, total_kcal=None, meals_count=0,
                 output_text="Rest for a minute to make up for the knee discomfort; walk at a brisk but comfortable pace")
    assert "HR-04" not in [i for i, _ in _ids(s)]
    assert ("HR-04", False) in _ids(_subject(output_text="Skip dinner to make up for the party"))


def test_policy_can_disable_a_rule():
    rules = [dict(r, enabled=(r["id"] != "HR-01")) for r in hard_rules.DEFAULT_POLICY_HARD_RULES]
    s = _subject(allergen_hits=[{"food": "peanut butter", "allergen": "peanut"}])
    assert "HR-01" not in [t.id for t in hard_rules.apply_hard_rules(s, rules)]


# ---------------------------------------------------------------- UC10 risk score  R = 2S + U + V + P + B
def test_score_low_for_light_exercise_fresh_readiness():
    s = _subject(kind=CandidateKind.EXERCISE, max_intensity="light", total_duration_min=20, available_time_min=40,
                 readiness_result="Ready", readiness_age_hours=1, total_kcal=None, meals_count=0)
    sc = risk_scoring.compute_risk_score(s)
    assert sc.R <= 3 and risk_scoring.classify(sc, False, {}) == RiskLevel.LOW


def test_score_formula_and_levels():
    sc = risk_scoring.RiskScore(S=2, U=1, V=1, P=1, B=0)
    assert sc.R == 7 and risk_scoring.classify(sc, False, {}) == RiskLevel.HIGH
    assert risk_scoring.classify(risk_scoring.RiskScore(1, 1, 1, 0, 0), False, {}) == RiskLevel.MEDIUM
    assert risk_scoring.classify(risk_scoring.RiskScore(3, 0, 0, 0, 0), False, {}) == RiskLevel.HIGH   # S = 3 -> High
    assert risk_scoring.classify(risk_scoring.RiskScore(3, 3, 2, 2, 2), False, {}) == RiskLevel.CRITICAL
    assert risk_scoring.classify(risk_scoring.RiskScore(0, 0, 0, 0, 0), True, {}) == RiskLevel.CRITICAL  # critical hard rule wins


def test_vulnerability_counted_only_where_relevant():
    ex = _subject(kind=CandidateKind.EXERCISE, allergies=["peanuts"], physical_limits=[], max_intensity="light", total_kcal=None, meals_count=0)
    assert risk_scoring.compute_risk_score(ex).V == 0          # allergies irrelevant to exercise
    diet = _subject(allergies=["peanuts"], physical_limits=["knee"])
    assert risk_scoring.compute_risk_score(diet).V == 1        # limits irrelevant to diet


def test_missing_readiness_raises_uncertainty():
    s = _subject(kind=CandidateKind.EXERCISE, max_intensity="light", readiness_result=None, total_kcal=None, meals_count=0)
    assert risk_scoring.compute_risk_score(s).U >= 2


def test_widened_range_lowers_uncertainty():
    s = _subject(kind=CandidateKind.FOOD_ANALYSIS, confidence=0.3, content={"range_widened": True}, total_kcal=None, meals_count=0)
    assert risk_scoring.compute_risk_score(s).U == 0


# ---------------------------------------------------------------- UC09 conflicts (AR-06)
def _diet(**over):
    d = {"meals": [{"name": "Lunch", "time": "12:00"}], "total_kcal": 1800}
    d.update(over)
    return d


def _exercise(**over):
    e = {"session_time": "17:30", "activities": [{"name": "walk", "duration_min": 30, "intensity": "light-moderate"}]}
    e.update(over)
    return e


def test_no_conflict_on_consistent_candidates():
    assert conflict_rules.detect_conflicts(_diet(), _exercise(), "Ready", 60, 1, 1) == []


def test_timing_conflict_routes_to_fitness_coach():
    c = conflict_rules.detect_conflicts(_diet(), _exercise(session_time="12:15"), "Ready", 60, 1, 1)
    assert c[0].type == ConflictType.TIMING and c[0].responsible_agent.value == "FitnessCoach"


def test_recovery_conflict():
    c = conflict_rules.detect_conflicts(_diet(), _exercise(), "Recovery", 60, 1, 1)
    assert ConflictType.RECOVERY in [x.type for x in c]


def test_workload_conflict():
    c = conflict_rules.detect_conflicts(_diet(), _exercise(), "Ready", 20, 1, 1)
    assert ConflictType.WORKLOAD in [x.type for x in c]


def test_nutrition_conflict_routes_to_nutrition_coach():
    c = conflict_rules.detect_conflicts(_diet(total_kcal=1250), _exercise(activities=[{"name": "walk", "duration_min": 50, "intensity": "light"}]), "Ready", 60, 1, 1)
    assert [x for x in c if x.type == ConflictType.NUTRITION][0].responsible_agent.value == "NutritionCoach"


def test_profile_version_mismatch_regenerates_older_side():
    c = conflict_rules.detect_conflicts(_diet(), _exercise(), "Ready", 60, 1, 2)
    assert c == [c[0]] and c[0].type == ConflictType.PROFILE_VERSION and c[0].responsible_agent.value == "NutritionCoach"


# ---------------------------------------------------------------- UC08 load rules (AR-05)
def test_load_increase_detected():
    ok, reasons = load_rules.check_load_increase([{"duration_min": 20, "intensity": "light"}], [{"duration_min": 30, "intensity": "light-moderate"}])
    assert not ok and len(reasons) == 2


def test_small_growth_allowed():
    ok, _ = load_rules.check_load_increase([{"duration_min": 20, "intensity": "light"}], [{"duration_min": 22, "intensity": "light"}])
    assert ok


def test_repeated_non_completion_simplifies():
    assert AdaptationAction.MAINTAIN not in load_rules.allowed_actions(2, False)
    assert load_rules.allowed_actions(0, True) == [AdaptationAction.PAUSE, AdaptationAction.REPLACE]
    assert load_rules.conservative_action(0, True) == AdaptationAction.PAUSE


# ---------------------------------------------------------------- AR-03 non-punitive rule
@pytest.mark.parametrize("text", ["I ate too much today so I will skip dinner", "make me a stricter plan to compensate",
                                  "only drink water tomorrow", "double my cardio to burn it off"])
def test_punitive_requests_detected(text):
    assert punitive_rules.detect_punitive_request(text)[0]


def test_normal_feedback_not_punitive():
    assert not punitive_rules.detect_punitive_request("I was hungry by 11am, could I have a bigger breakfast?")[0]


def test_plan_floor_and_cut():
    assert punitive_rules.check_plan_not_punitive(1100, 3) and punitive_rules.check_plan_not_punitive(1600, 2)
    assert punitive_rules.check_plan_not_punitive(1300, 3, previous_total_kcal=1800)
    assert not punitive_rules.check_plan_not_punitive(1700, 4, previous_total_kcal=1800)


# ---------------------------------------------------------------- nutrition source: allergen vocabulary
def test_allergy_normalisation_uses_whole_words():
    from app.external.nutrition_local import normalise_allergies
    assert normalise_allergies(["peanuts"]) == {"peanut"}
    assert normalise_allergies(["tree nuts", "Dairy", "shellfish (prawns)"]) == {"tree_nut", "milk", "shellfish"}
    assert normalise_allergies(["almond allergy"]) == {"tree_nut"}


def test_negated_phrases_do_not_trigger_output_rules():
    s = _subject(kind=CandidateKind.EXERCISE, total_kcal=None, meals_count=0,
                 output_text="The session is for general movement only, not to compensate for food. This is not a medical diagnosis.")
    ids = [i for i, _ in _ids(s)]
    assert "HR-04" not in ids and "HR-06" not in ids
    assert ("HR-04", False) in _ids(_subject(output_text="Walk an extra 30 minutes to compensate for the meal"))


def test_lookup_ignores_exclusions():
    from app.external.nutrition_local import get_nutrition_source
    ns = get_nutrition_source()
    assert ns.lookup("mapo tofu (without peanuts)")["id"] == "tofu"
    assert ns.lookup("nut-free granola") is None or "peanut" not in ns.lookup("nut-free granola")["allergens"]
    assert ns.lookup("chicken with peanut sauce")["id"] == "satay_sauce"
    assert ns.lookup("stir-fried bok choy with garlic")["id"] == "bok_choy"


def test_hr04_ignores_explanatory_prose_but_not_directives():
    s = _subject(output_text="You asked for a stricter plan to compensate for the party; that request was declined. Breakfast: oats.",
                 directive_text="Breakfast: oats, yogurt. Lunch: rice, tofu.")
    assert "HR-04" not in [i for i, _ in _ids(s)]
    s2 = _subject(output_text="…", directive_text="Dinner: skip dinner to compensate for the party")
    assert ("HR-04", False) in _ids(s2)


def test_cloud_client_base_url_normalisation():
    from app.llm.cloud_client import CloudLLMClient
    n = CloudLLMClient.normalise_base_url
    assert n("https://api.deepseek.com") == "https://api.deepseek.com/v1"
    assert n("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    assert n("http://10.0.0.5:8000/v1/chat/completions") == "http://10.0.0.5:8000/v1"
    assert n("https://llm.school.edu/api") == "https://llm.school.edu/api/v1"
