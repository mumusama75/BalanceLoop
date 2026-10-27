"""MockLLMClient — deterministic, offline stand-in for the language model.

It produces *plausible* structured drafts from keywords and the nutrition table so the
whole pipeline can be demonstrated and tested without network access. It deliberately
behaves like a model: it follows the user's wishes (e.g. "add satay sauce") even when
that is unsafe — the Safety Supervisor is the component that must catch it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Type, TypeVar

from pydantic import BaseModel

from ..domain.enums import AdaptationAction, ConflictType, Intensity, ReadinessResult
from ..domain.schemas import (ActivityDraft, AdaptationProposal, AdaptationProposalItem, BarrierProposal,
                              ConflictClassification, DietPlanDraft, DietRevisionDraft, ExercisePlanDraft,
                              FoodInterpretation, FoodItemInterpretation, MealDraft, MealItemDraft, ProfileDraft,
                              ReadinessProposal, RecoveryInterpretation, RevisionInstruction, SubstitutionDraft)
from ..external.nutrition_local import get_nutrition_source, normalise_allergies
from ..rules.punitive_rules import detect_punitive_request
from ..rules.text_patterns import CRITICAL_SYMPTOM_PATTERNS, describe_hits, match_any
from .gateway import LLMGateway, LLMUnavailable

T = TypeVar("T", bound=BaseModel)

PAIN_WORDS = ["sharp pain", "hurts", "stabbing", "painful", "pain when", "knee pain", "back pain", "ache badly", "can't bend"]
REDUCED_WORDS = ["exhausted", "drained", "barely slept", "didn't sleep", "no sleep", "sick", "cold", "flu", "wiped out", "very tired"]


class MockLLMClient(LLMGateway):
    model_version = "mock-llm-1.0"

    def __init__(self):
        self.ns = get_nutrition_source()
        self.last_meta = {"latency_ms": 0, "mock": True}

    def complete(self, system: str, user: str, schema: Type[T]) -> T:  # pragma: no cover
        raise LLMUnavailable("MockLLMClient does not support free-form completion")

    # ---------------------------------------------------------------- UC01
    def interpret_constraints(self, profile: Dict[str, Any], free_text: str) -> ProfileDraft:
        goals = [g.lower() for g in profile.get("goals", [])]
        conflicts, missing = [], []
        if any("lose" in g for g in goals) and any("gain" in g or "bulk" in g for g in goals):
            conflicts.append("goals include both losing and gaining weight")
        prefs = [p.lower() for p in profile.get("dietary_preferences", [])]
        if any("vegan" in p or "vegetarian" in p for p in prefs) and any("high meat" in p or "carnivore" in p for p in prefs):
            conflicts.append("vegetarian/vegan preference conflicts with a meat-based preference")
        if profile.get("allergy_status") == "unknown":
            missing.append("allergies")
        if profile.get("available_time_min") in (None, 0):
            missing.append("available_time_min")
        txt = (free_text or "").lower()
        if "allerg" in txt and profile.get("allergy_status") == "none":
            conflicts.append("free text mentions an allergy but allergy status is 'none'")
        return ProfileDraft(detected_conflicts=conflicts, missing_safety_fields=missing,
                            summary="Mock interpretation of profile constraints")

    # ---------------------------------------------------------------- UC02
    def identify_food(self, text: str, context: Dict[str, Any]) -> FoodInterpretation:
        found = self.ns.find_in_text(text)
        if not found:
            return FoodInterpretation(items=[], unidentifiable=True, clarification_needed=True,
                                      clarification_question="I couldn't recognise a food in that. Could you name the main items (e.g. 'rice, chicken, broccoli')?")
        items: List[FoodItemInterpretation] = []
        prev_end = 0
        clarify_for: List[str] = []
        clarified = " ".join(c.get("answer", "") for c in context.get("clarifications", []))
        for food, alias, span in found:
            segment = text[prev_end:span[1] + 12]
            prev_end = span[1]
            grams, evidence, desc = self.ns.parse_portion(segment, food)
            if grams is None and clarified:
                grams, evidence, desc = self.ns.parse_portion(clarified, food)
            if grams is None and (clarified or context.get("skip_clarification")):
                grams, evidence, desc = food["typical_portion_g"], "inferred", "typical serving"
            if grams is None:
                clarify_for.append(food["name"])
                grams_low = grams_high = None
            else:
                grams_low, grams_high = self.ns.range_for(grams, evidence)
            items.append(FoodItemInterpretation(name=food["name"], portion_description=desc, grams_estimate=grams,
                                                grams_low=grams_low, grams_high=grams_high,
                                                preparation=None, identification_confidence=0.85 if alias == food["name"].lower() else 0.7,
                                                portion_evidence=evidence))
        q = None
        if clarify_for:
            q = f"How much {' and '.join(clarify_for)} did you have? (e.g. 1 bowl / 2 pieces / 150 g)"
        return FoodInterpretation(items=items, clarification_needed=bool(clarify_for), clarification_question=q,
                                  notes="mock identification from nutrition table aliases")

    # ---------------------------------------------------------------- UC03
    def _allowed(self, food_id: str, allergen_keys: set, prefs: List[str]) -> bool:
        f = self.ns._by_id[food_id]
        if any(a in allergen_keys for a in f["allergens"]):
            return False
        veg = any(p in ("vegetarian", "vegan") for p in prefs)
        if veg and f["category"] == "protein" and f["id"] not in ("tofu", "tempeh", "egg", "greek_yogurt"):
            return False
        if "vegan" in prefs and f["id"] in ("egg", "greek_yogurt", "milk_whole", "milk_skim", "cheese_cheddar", "cottage_cheese", "butter"):
            return False
        return True

    def generate_diet_candidate(self, context: Dict[str, Any]) -> DietPlanDraft:
        profile = context.get("profile", {})
        allergen_keys = normalise_allergies(profile.get("allergies", []))
        prefs = [p.lower() for p in profile.get("dietary_preferences", [])]
        budget = (context.get("budget_level") or profile.get("budget_level") or "medium")
        notes = (context.get("notes") or "").lower()

        def pick(*candidates: str, grams: float) -> List[MealItemDraft]:
            for cid in candidates:
                if self._allowed(cid, allergen_keys, prefs):
                    return [MealItemDraft(food=self.ns._by_id[cid]["name"], grams=grams)]
            return []

        breakfast = pick("oats_dry", "congee", grams=60) + pick("greek_yogurt", "soy_milk", "banana", grams=170) + pick("blueberries", "apple", grams=80)
        lunch = pick("brown_rice_cooked", "rice_cooked", "quinoa_cooked", grams=180) + pick("chicken_breast", "tofu", "lentils_cooked", grams=130) + pick("broccoli", "bok_choy", grams=120)
        dinner = pick("sweet_potato", "potato_boiled", grams=180) + pick("salmon", "tofu", "chickpeas_cooked", grams=130) + pick("spinach", "salad_mixed", grams=120) + pick("olive_oil", grams=10)
        snack = pick("apple", "orange", grams=180) + pick("almonds", "edamame", grams=25)
        if budget == "low":
            lunch = pick("rice_cooked", grams=200) + pick("egg", "lentils_cooked", grams=100) + pick("cabbage", "carrot", grams=120)
            dinner = pick("potato_boiled", grams=200) + pick("black_beans", "tofu", grams=150) + pick("carrot", grams=100)
        # A model follows the user's request — even an unsafe one. The Supervisor must catch it.
        if "satay" in notes or "peanut" in notes:
            dinner.append(MealItemDraft(food="peanut satay sauce", grams=40))
        if "pad thai" in notes:
            dinner = [MealItemDraft(food="pad thai", grams=350)]

        meals = [MealDraft(name="Breakfast", time="07:30", items=breakfast, notes="Warm, quick to prepare"),
                 MealDraft(name="Lunch", time="12:30", items=lunch),
                 MealDraft(name="Snack", time="15:30", items=snack),
                 MealDraft(name="Dinner", time="18:30", items=dinner)]

        instr = " ".join(context.get("revision_instructions", []) or []).lower() + " " + (context.get("correction_request") or "").lower()
        if "allergen" in instr or "remove" in instr:
            for m in meals:
                m.items = [i for i in m.items if not any(a in allergen_keys for a in (self.ns.lookup(i.food) or {}).get("allergens", []))]
        if "timing" in instr or "earlier" in instr or "move" in instr:
            for m in meals:
                if m.name == "Lunch":
                    m.time = "11:45"
        if "energy" in instr or "increase" in instr or "more" in instr or "nutrition" in instr:
            meals.insert(3, MealDraft(name="Pre-activity snack", time="16:45", items=pick("banana", "bread_whole", grams=120)))
        subs = [SubstitutionDraft(**{"for": "salmon", "alternative": "canned tuna in water or firm tofu", "reason": "cheaper / plant-based"}),
                SubstitutionDraft(**{"for": "brown rice", "alternative": "white rice or quinoa", "reason": "availability"})]
        return DietPlanDraft(meals=meals, substitutions=subs,
                             rationale="Three regular meals and a snack built around whole grains, lean or plant protein and vegetables; portions sized for steady energy.",
                             constraints_explanation=f"Excluded allergens: {sorted(allergen_keys) or 'none'}; preferences: {prefs or 'none'}; budget: {budget}.",
                             uncertainties=["portion sizes are typical servings, adjust to appetite"])

    # ---------------------------------------------------------------- UC04
    def interpret_feedback(self, feedback: Dict[str, Any], plan: Dict[str, Any]) -> BarrierProposal:
        text = (feedback.get("text") or "").lower()
        punitive, _ = detect_punitive_request(text)
        if feedback.get("cost_issue") or "expensive" in text or "afford" in text or "cost" in text:
            barrier = "cost"
        elif (feedback.get("hunger") or 0) >= 6 or "hungry" in text or "starving" in text:
            barrier = "hunger"
        elif (feedback.get("satiety") or 0) >= 8 or "too full" in text or "too much food" in text:
            barrier = "satiety"
        elif "time" in text or "busy" in text or "late" in text:
            barrier = "timing"
        elif "hard" in text or "difficult" in text or "complicated" in text or feedback.get("adherence") in ("partial", "missed"):
            barrier = "difficulty"
        elif "don't like" in text or "dislike" in text or "hate" in text:
            barrier = "preference"
        else:
            barrier = "other"
        unclear = barrier == "other" and not punitive and len(text.split()) < 3 and feedback.get("hunger") is None and feedback.get("satiety") is None
        return BarrierProposal(barrier=barrier, punitive_request_detected=punitive,
                               explanation=f"Mock: barrier classified as {barrier}", needs_clarification=unclear,
                               clarification_question="Could you tell me what made the plan hard to follow — hunger, cost, time or taste?" if unclear else None)

    def propose_minimal_change(self, context: Dict[str, Any], strategy: str) -> DietRevisionDraft:
        plan = context["current_plan"]
        barrier = context.get("barrier", "other")
        meals = [MealDraft(name=m["name"], time=m["time"], notes=m.get("notes"),
                           items=[MealItemDraft(food=i["food"], grams=i["grams"]) for i in m["items"]]) for m in plan["meals"]]
        changed, explanation = [], ""
        if strategy == "SafeAlternative":
            explanation = ("The plan was not made stricter. Instead it keeps all meals and adds a small protein-rich snack, "
                           "which usually reduces the urge to over-restrict later.")
            meals.insert(2, MealDraft(name="Afternoon snack", time="16:00", items=[MealItemDraft(food="plain Greek yogurt", grams=150)]))
            changed.append("added afternoon snack (non-punitive alternative)")
        elif barrier == "hunger":
            for m in meals:
                for i in m.items:
                    f = self.ns.lookup(i.food)
                    if f and f["category"] in ("protein", "legume", "vegetable"):
                        i.grams = round(i.grams * 1.2)
            changed.append("protein and vegetable portions +20%")
            explanation = "Portions of protein and vegetables were increased by about 20% at each meal to improve satiety; nothing was removed."
        elif barrier == "satiety":
            for m in meals:
                for i in m.items:
                    i.grams = round(i.grams * 0.85)
            changed.append("all portions −15%")
            explanation = "All portions were reduced by about 15% because you reported feeling too full; meal structure is unchanged."
        elif barrier == "cost":
            for m in meals:
                for i in m.items:
                    if i.food == "baked salmon":
                        i.food, changed = "canned tuna in water", changed + ["salmon → canned tuna"]
                    if i.food == "almonds":
                        i.food, changed = "roasted peanuts" if "peanut" not in str(context.get("profile", {}).get("allergies", [])).lower() else "edamame", changed + ["almonds → cheaper snack"]
            explanation = "Expensive items were swapped for cheaper equivalents with similar protein; portions and timing are unchanged."
        elif barrier == "timing":
            for m in meals:
                if m.name == "Breakfast":
                    m.time, m.notes = "08:15", "Overnight oats — prepare the evening before"
            changed.append("breakfast moved to 08:15 / prepared ahead")
            explanation = "Breakfast was shifted later and made preparable the evening before to fit your schedule."
        else:
            for m in meals:
                if m.name == "Dinner" and len(m.items) > 2:
                    m.items = m.items[:3]
            changed.append("dinner simplified to 3 items")
            explanation = "Dinner was simplified to three items to make the plan easier to follow."
        new_plan = DietPlanDraft(meals=meals, substitutions=[SubstitutionDraft(**s) if "for" in s else SubstitutionDraft(for_item=s.get("for_item", ""), alternative=s["alternative"], reason=s["reason"]) for s in plan.get("substitutions", [])],
                                 rationale=plan.get("rationale", ""), constraints_explanation=plan.get("constraints_explanation", ""))
        return DietRevisionDraft(plan=new_plan, change_explanation=explanation, changed_elements=changed)

    # ---------------------------------------------------------------- UC05
    def assess_readiness(self, checkin: Dict[str, Any], context: Dict[str, Any]) -> ReadinessProposal:
        txt = (checkin.get("free_text") or "").lower()
        evidence = [f"{k}={v}" for k, v in checkin.items() if v is not None and k != "free_text"]
        pain_affects = any(w in txt for w in PAIN_WORDS) or bool(checkin.get("pain_affects_activity"))
        reduced = any(w in txt for w in REDUCED_WORDS)
        restrictions = []
        for joint in ("knee", "back", "ankle", "shoulder", "hip", "wrist"):
            if joint in txt and (pain_affects or (checkin.get("pain") or 0) > 0):
                restrictions.append(f"avoid loading the {joint}")
        missing = [k for k in ("sleep_quality", "fatigue", "soreness", "pain", "recent_activity", "available_time_min") if checkin.get(k) is None]
        return ReadinessProposal(evidence=evidence + ([f"text: {txt[:80]}"] if txt else []), pain_affects_activity=pain_affects,
                                 capacity_reduced=reduced, recovery_restrictions=restrictions, missing_information=missing, confidence=0.7)

    # ---------------------------------------------------------------- UC06
    def generate_exercise_candidate(self, context: Dict[str, Any]) -> ExercisePlanDraft:
        readiness = (context.get("readiness") or {}).get("result")
        profile = context.get("profile", {})
        available = int(context.get("available_time_min") or profile.get("available_time_min") or 30)
        equipment = [e.lower() for e in profile.get("equipment", [])]
        limits = " ".join(profile.get("physical_limits", [])).lower()
        instr = " ".join(context.get("revision_instructions", []) or []).lower() + " " + (context.get("correction_request") or "").lower()
        session_time = context.get("session_time") or "17:30"

        if readiness == ReadinessResult.RECOVERY.value:
            acts = [ActivityDraft(name="Gentle mobility flow", duration_min=10, intensity=Intensity.LIGHT, notes="slow, pain-free range only"),
                    ActivityDraft(name="Diaphragmatic breathing", duration_min=5, intensity=Intensity.LIGHT)]
            difficulty = "Very easy — recovery day; stop anything that provokes pain."
        elif readiness == ReadinessResult.REDUCED.value:
            acts = [ActivityDraft(name="Easy walk", duration_min=min(20, available - 5), intensity=Intensity.LIGHT),
                    ActivityDraft(name="Standing stretches", duration_min=5, intensity=Intensity.LIGHT)]
            difficulty = "Easy — shortened because today's capacity is reduced."
        else:
            walk = min(30, max(10, available - 15))
            acts = [ActivityDraft(name="Brisk walk", duration_min=walk, intensity=Intensity.LIGHT_MODERATE, notes="conversational pace"),
                    ActivityDraft(name="Bodyweight mobility circuit", duration_min=10, intensity=Intensity.LIGHT)]
            if "resistance band" in " ".join(equipment) and available >= 40:
                acts.append(ActivityDraft(name="Resistance band rows", duration_min=8, intensity=Intensity.LIGHT_MODERATE, notes="2 sets of 12"))
            difficulty = "Light to moderate — you should be able to talk throughout."
        if "knee" in limits:
            acts = [a for a in acts if "circuit" not in a.name.lower()] + ([ActivityDraft(name="Seated leg extensions (no load)", duration_min=6, intensity=Intensity.LIGHT)] if readiness != ReadinessResult.RECOVERY.value else [])
        # a real model occasionally over-reaches; emulate it when the user pushes
        if "push" in (context.get("notes") or "").lower() or "harder" in (context.get("notes") or "").lower():
            acts.insert(0, ActivityDraft(name="Jogging intervals", duration_min=15, intensity=Intensity.MODERATE))
        # corrections / revisions
        if "timing" in instr or "later" in instr or "move the session" in instr:
            h, m = session_time.split(":"); session_time = f"{(int(h) + 1) % 24:02d}:{m}"
        if "recovery" in instr:
            acts = [ActivityDraft(name=a.name if a.intensity == Intensity.LIGHT else "Easy walk", duration_min=min(a.duration_min, 15), intensity=Intensity.LIGHT) for a in acts]
        elif "intensity" in instr or "light" in instr:
            lower = {Intensity.VIGOROUS: Intensity.MODERATE, Intensity.MODERATE: Intensity.LIGHT_MODERATE,
                     Intensity.LIGHT_MODERATE: Intensity.LIGHT, Intensity.LIGHT: Intensity.LIGHT}
            acts = [ActivityDraft(name=a.name if a.intensity in (Intensity.LIGHT, Intensity.LIGHT_MODERATE) else "Brisk walk",
                                  duration_min=a.duration_min, intensity=lower[a.intensity], notes=a.notes) for a in acts]
        if "workload" in instr or "shorter" in instr or "reduce" in instr or "duration" in instr:
            acts = [ActivityDraft(name=a.name, duration_min=max(5, int(a.duration_min * 0.8)), intensity=a.intensity, notes=a.notes) for a in acts]
        # keep a little headroom below the available time, as a sensible coach would
        total = sum(a.duration_min for a in acts)
        while total > available * 0.85 and len(acts) > 1:
            acts.pop(); total = sum(a.duration_min for a in acts)
        if total > available * 0.85 and acts:
            acts[0] = ActivityDraft(name=acts[0].name, duration_min=max(5, int(available * 0.8)), intensity=acts[0].intensity, notes=acts[0].notes)
        return ExercisePlanDraft(session_time=session_time, activities=acts,
                                 warm_up="3 minutes of easy walking and arm circles", rest="Rest 1 minute whenever breathing becomes heavy",
                                 cool_down="3 minutes slow walking plus calf and hip stretches",
                                 alternatives=["Stationary cycling at an easy pace", "Indoor marching if weather is poor", "Swimming or water walking"],
                                 difficulty=difficulty, progression="Add 5 minutes to the walk next week only if all sessions felt easy and pain-free.",
                                 rationale=f"Built for readiness '{readiness}' within {available} min, honouring limits: {limits or 'none'}.")

    # ---------------------------------------------------------------- UC07
    def interpret_recovery_notes(self, notes: str, context: Dict[str, Any]) -> RecoveryInterpretation:
        txt = (notes or "").lower()
        signs = []
        hits = match_any(txt, CRITICAL_SYMPTOM_PATTERNS)
        if hits:
            signs.append("red-flag symptom: " + describe_hits(hits))
        for w in PAIN_WORDS:
            if w in txt:
                signs.append(w); break
        if "dizzy" in txt:
            signs.append("dizziness")
        return RecoveryInterpretation(warning_signs=signs, pain_related=any("pain" in s or "hurt" in s for s in signs) or "pain" in txt,
                                      summary="Mock recovery interpretation: " + (", ".join(signs) if signs else "no warning signs mentioned"))

    # ---------------------------------------------------------------- UC08
    def propose_adaptations(self, feedback: List[Dict[str, Any]], readiness: Dict[str, Any], plan: Dict[str, Any]) -> AdaptationProposal:
        items = []
        fb_by_item: Dict[str, List[Dict[str, Any]]] = {}
        for fb in feedback:
            fb_by_item.setdefault(fb["activity_item_id"], []).append(fb)
        for a in plan.get("activities", []):
            fbs = fb_by_item.get(a["id"], [])
            skipped = sum(1 for f in fbs if f["completion"] in ("skipped", "partial"))
            pain = any((f.get("pain") or 0) >= 3 or f.get("warning_signs") for f in fbs)
            if pain:
                items.append(AdaptationProposalItem(activity_item_id=a["id"], action=AdaptationAction.PAUSE, reason="pain or warning sign reported on this activity"))
            elif skipped >= 2:
                items.append(AdaptationProposalItem(activity_item_id=a["id"], action=AdaptationAction.REDUCE, reason="repeatedly not completed — simplify", new_duration_min=max(5, int(a["duration_min"] * 0.6))))
            elif skipped == 1:
                items.append(AdaptationProposalItem(activity_item_id=a["id"], action=AdaptationAction.REPLACE, reason="partially completed — offer an easier variant",
                                                    replacement=ActivityDraft(name=f"Easier {a['name'].lower()}", duration_min=max(5, int(a["duration_min"] * 0.8)), intensity=Intensity.LIGHT)))
            else:
                items.append(AdaptationProposalItem(activity_item_id=a["id"], action=AdaptationAction.MAINTAIN, reason="completed comfortably"))
        return AdaptationProposal(items=items, summary="Mock adaptation proposal")

    # ---------------------------------------------------------------- UC09
    def classify_conflict(self, conflict: Dict[str, Any], context: Dict[str, Any]) -> ConflictClassification:
        t = ConflictType(conflict["type"])
        agent = conflict.get("responsible_agent", "FitnessCoach")
        req = {ConflictType.TIMING: "Move the session so it starts at least 30 minutes after the nearest meal (timing conflict).",
               ConflictType.RECOVERY: "Readiness is Recovery: keep every activity light intensity and under 20 minutes total (recovery conflict).",
               ConflictType.WORKLOAD: "Reduce total duration to fit the user's available time (workload conflict).",
               ConflictType.NUTRITION: "Increase daily energy for an active day, e.g. add a pre-activity snack (nutrition conflict).",
               ConflictType.PROFILE_VERSION: "Regenerate the candidate with the latest profile version."}[t]
        return ConflictClassification(refined_type=t, responsible_agent=agent, correction_request=req)

    # ---------------------------------------------------------------- UC10
    def draft_revision_instructions(self, rules: List[Dict[str, Any]], candidate: Dict[str, Any]) -> RevisionInstruction:
        instr = []
        for r in rules:
            instr.append(f"[{r['id']}] {r['message']} — adjust the candidate to resolve this.")
        if not rules:
            instr.append("Reduce overall load/energy proximity to policy boundaries: lower intensity or duration, keep meals regular.")
        return RevisionInstruction(instructions=instr, rule_ids=[r["id"] for r in rules], summary="Mock revision instructions")
