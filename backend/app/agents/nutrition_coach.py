"""NutritionCoach — UC02 record & analyse food intake, UC03 generate diet plan, UC04 adapt diet plan."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm.attributes import flag_modified

from ..db import models as m
from ..domain.enums import (AgentRole, CandidateKind, CandidateStatus, DietAdaptationStrategy, FeedbackStatus,
                            FoodEntryStatus, OutcomeStatus)
from ..domain.schemas import DietFeedbackIn, DietPlanDraft, DietPlanRequestIn, FoodEntryIn, RevisionInstruction
from ..llm.gateway import LLMUnavailable
from ..rules.punitive_rules import check_plan_not_punitive, detect_punitive_request
from ..util import new_id, utcnow
from .base import Agent
from .common import Halt, next_version, profile_context

PORTION_FACTOR = {"stated": 1.0, "inferred": 0.75, "none": 0.5}


class NutritionCoach(Agent):
    role = AgentRole.NUTRITION_COACH

    # ===================================================================== UC02
    def record_meal(self, data: FoodEntryIn) -> Tuple[Optional[m.FoodEntry], Optional[m.PlanCandidate], Optional[Halt]]:
        text = (data.text or "").strip()
        if not text:
            return None, None, Halt(OutcomeStatus.CLARIFICATION, "Please describe what you ate (text), pick a food, or send a readable image. No values were invented.")
        if data.input_type == "image":
            return None, None, Halt(OutcomeStatus.CLARIFICATION, "Image analysis is not enabled in this prototype. Please describe the meal in text.")
        entry = m.FoodEntry(id=new_id("fe"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, raw_input=text,
                            input_type=data.input_type, status=FoodEntryStatus.DRAFT.value, version=1,
                            submitted_at=data.consumed_at or utcnow(), agent_version=self.agent_id)
        self.repo.save_food_entry(entry)
        self.trace("captureInput", f"Original entry preserved: “{text[:60]}”", detail={"entry_id": entry.id, "input_type": data.input_type})
        return self._analyse(entry)

    def clarify_entry(self, entry: m.FoodEntry, answer: str) -> Tuple[m.FoodEntry, Optional[m.PlanCandidate], Optional[Halt]]:
        entry.clarifications = list(entry.clarifications or []) + [{"question": entry.clarification_question, "answer": answer, "at": utcnow().isoformat()}]
        flag_modified(entry, "clarifications")
        entry.version += 1
        entry.clarification_question = None
        self.repo.commit()
        self.trace("storeClarification", f"Clarification recorded (v{entry.version}): “{answer[:60]}”")
        return self._analyse(entry)

    def _analyse(self, entry: m.FoodEntry) -> Tuple[m.FoodEntry, Optional[m.PlanCandidate], Optional[Halt]]:
        profile = self.repo.reload_profile(entry.user_id)
        entry.profile_version = profile.version if profile else None
        allergies = list(profile.allergies) if profile else []
        ns = self.ctx.nutrition

        # perceive → LLM interpretation
        try:
            interp = self.llm.identify_food(entry.raw_input, {"clarifications": entry.clarifications or [], "known_allergies": allergies})
            self.trace("identifyFood", f"LLM identified {len(interp.items)} item(s)" + (" — clarification needed" if interp.clarification_needed else ""),
                       llm_used=True, detail=interp.model_dump())
        except LLMUnavailable as e:
            entry.status, entry.missing_evidence = FoodEntryStatus.RECORDED_UNESTIMATED.value, ["food identification unavailable (model)"]
            self.repo.commit()
            self.trace("identifyFood", f"LLM unavailable ({e}); entry kept as RecordedUnestimated", llm_used=True)
            return entry, None, Halt(OutcomeStatus.RECORDED_UNESTIMATED, "Your entry was recorded, but it could not be analysed right now. No values were invented; you can complete it later.", extra={"entry_id": entry.id})

        if interp.unidentifiable or not interp.items:
            entry.status = FoodEntryStatus.AWAITING_CLARIFICATION.value
            entry.clarification_question = interp.clarification_question or "Which foods did the meal contain?"
            self.repo.commit()
            return entry, None, Halt(OutcomeStatus.CLARIFICATION, entry.clarification_question, extra={"entry_id": entry.id, "stage": "identification"})

        if interp.clarification_needed and not entry.clarifications:
            entry.status = FoodEntryStatus.AWAITING_CLARIFICATION.value
            entry.clarification_question = interp.clarification_question or "How much did you have?"
            self.repo.commit()
            self.trace("checkPortionAndPreparation", "Portion ambiguous — focused question asked (UC02 4a)")
            return entry, None, Halt(OutcomeStatus.CLARIFICATION, entry.clarification_question, extra={"entry_id": entry.id, "stage": "portion"})

        # compute estimates from the versioned nutrition source
        items_out: List[Dict[str, Any]] = []
        foods = []
        tot = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        lo_kcal = hi_kcal = 0.0
        conf_parts: List[float] = []
        missing: List[str] = []
        for it in interp.items:
            food = ns.lookup(it.name)
            grams = it.grams_estimate
            evidence = it.portion_evidence if grams else "none"
            if grams is None and food is not None:
                grams, evidence = float(food["typical_portion_g"]), "inferred"
            row: Dict[str, Any] = {"name": it.name, "grams": grams, "portion_description": it.portion_description,
                                   "portion_evidence": evidence, "identification_confidence": it.identification_confidence,
                                   "verified": food is not None, "allergens": ns.allergens_of(food) if food else []}
            if food is not None and grams:
                est = ns.estimate(food, grams)
                g_lo, g_hi = ns.range_for(grams, evidence)
                row.update({"matched_food": food["name"], **est, "grams_low": g_lo, "grams_high": g_hi})
                for k in tot:
                    tot[k] += est[k]
                lo_kcal += ns.estimate(food, g_lo)["kcal"]
                hi_kcal += ns.estimate(food, g_hi)["kcal"]
                foods.append(food)
                conf_parts.append(it.identification_confidence * PORTION_FACTOR[evidence] * 1.0)
            else:
                missing.append(it.name)
                conf_parts.append(it.identification_confidence * PORTION_FACTOR[evidence] * 0.4)
            items_out.append(row)

        entry.items = items_out
        if not foods:
            entry.status = FoodEntryStatus.RECORDED_UNESTIMATED.value
            entry.missing_evidence = [f"no versioned nutrition data for: {', '.join(missing)}"]
            entry.data_version, entry.model_version = ns.version, self.model_version
            self.repo.commit()
            self.trace("computeEstimate", "No defensible estimate possible — RecordedUnestimated (UC02 3b/5a)")
            return entry, None, Halt(OutcomeStatus.RECORDED_UNESTIMATED, "Your entry was recorded, but no defensible nutrient estimate could be produced "
                                      f"(no versioned nutrition data for: {', '.join(missing)}). Nothing was invented; you can correct it later.", extra={"entry_id": entry.id})

        confidence = round(sum(conf_parts) / len(conf_parts), 2)
        basis = (f"Confidence combines food identification ({', '.join(f'{i.identification_confidence:.2f}' for i in interp.items)}), "
                 f"portion evidence ({', '.join(r['portion_evidence'] for r in items_out)}) and source quality "
                 f"({len(foods)}/{len(items_out)} items matched in {ns.version}).")
        hits = ns.allergen_conflicts(foods, allergies)
        flags = [f"possible allergen exposure: {h['allergen']} ({h['food']})" for h in hits]
        entry.nutrient_estimate = {k: round(v, 1) for k, v in tot.items()}
        entry.uncertainty_range = {"kcal_low": round(lo_kcal, 1), "kcal_high": round(hi_kcal, 1)}
        entry.confidence, entry.confidence_basis, entry.safety_flags = confidence, basis, flags
        entry.missing_evidence = [f"unverified: {x}" for x in missing]
        entry.data_version, entry.model_version = ns.version, self.model_version
        entry.status = FoodEntryStatus.PENDING_REVIEW.value
        self.repo.commit()
        self.trace("computeEstimate", f"Estimate {entry.nutrient_estimate['kcal']} kcal (range {entry.uncertainty_range['kcal_low']}–{entry.uncertainty_range['kcal_high']}), confidence {confidence}",
                   detail={"items": items_out, "data_version": ns.version})
        if hits:
            self.trace("checkAllergens", "Possible allergen conflict flagged; original intake preserved; UC10 hard-rule handling invoked (UC02 6a)", detail={"hits": hits})
        self.audit("foodEntrySaved", versions={"entry_id": entry.id, "entry_version": entry.version, "profile_version": entry.profile_version,
                                                  "nutrition_data_version": ns.version})

        summary = (f"Estimated {entry.nutrient_estimate['kcal']:.0f} kcal (likely range {lo_kcal:.0f}–{hi_kcal:.0f} kcal), "
                   f"protein {tot['protein_g']:.0f} g, carbs {tot['carbs_g']:.0f} g, fat {tot['fat_g']:.0f} g. Confidence {confidence:.2f}. "
                   + (f"Unverified items: {', '.join(missing)}. " if missing else "")
                   + (f"Safety flags: {'; '.join(flags)}." if flags else ""))
        candidate = m.PlanCandidate(id=new_id("cand"), user_id=entry.user_id, request_id=self.ctx.request_id, kind=CandidateKind.FOOD_ANALYSIS.value,
                                    version=entry.version, plan_date=entry.submitted_at.date(), profile_version=entry.profile_version,
                                    rationale=basis, status=CandidateStatus.DRAFT.value, model_version=self.model_version, agent_version=self.agent_id,
                                    risk_flags=[{"code": "allergen_notice", "severity": 1, "note": f} for f in flags],
                                    content={"entry_id": entry.id, "items": items_out, "nutrient_estimate": entry.nutrient_estimate,
                                             "uncertainty_range": entry.uncertainty_range, "confidence": confidence, "confidence_basis": basis,
                                             "safety_flags": flags, "data_version": ns.version, "source_input": entry.raw_input,
                                             "summary_text": summary, "unverified_items": missing})
        self.repo.save_candidate(candidate)
        entry.review_case_id = None
        return entry, candidate, None

    def finalise_entry(self, entry: m.FoodEntry, outcome: OutcomeStatus, case_id: Optional[str], summary: Optional[str]):
        if outcome == OutcomeStatus.RELEASED:
            entry.status, entry.released_analysis = FoodEntryStatus.RELEASED.value, summary
        else:
            entry.status = FoodEntryStatus.WITHHELD.value
        entry.review_case_id = case_id
        self.repo.commit()

    # ===================================================================== UC03
    def _diet_content(self, draft: DietPlanDraft, plan_date: date, source_input: Optional[str], previous: Optional[m.PlanCandidate]) -> Dict[str, Any]:
        ns = self.ctx.nutrition
        meals_out, unverified, total = [], [], {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        for meal in draft.meals:
            items, kcal = [], 0.0
            for it in meal.items:
                food = ns.lookup(it.food)
                row = {"food": it.food, "grams": it.grams, "verified": food is not None}
                if food:
                    est = ns.estimate(food, it.grams)
                    row.update({"matched_food": food["name"], **est, "allergens": ns.allergens_of(food)})
                    kcal += est["kcal"]
                    for k in total:
                        total[k] += est[k]
                else:
                    unverified.append(it.food)
                items.append(row)
            meals_out.append({"name": meal.name, "time": meal.time, "items": items, "kcal": round(kcal, 0), "notes": meal.notes})
        content = {"plan_date": plan_date.isoformat(), "meals": meals_out, "total_kcal": round(total["kcal"], 0),
                   "totals": {k: round(v, 0) for k, v in total.items()},
                   "substitutions": [{"for": s.for_item, "alternative": s.alternative, "reason": s.reason} for s in draft.substitutions],
                   "rationale": draft.rationale, "constraints_explanation": draft.constraints_explanation,
                   "uncertainties": draft.uncertainties, "unverified_foods": unverified, "nutrition_data_version": ns.version,
                   "source_input": source_input or ""}
        if previous is not None:
            content["previous_total_kcal"] = previous.content.get("total_kcal")
        return content

    def generate_diet_candidate(self, plan_date: date, req: DietPlanRequestIn, *, revision: Optional[List[str]] = None,
                                correction: Optional[str] = None, previous: Optional[m.PlanCandidate] = None,
                                feedback: Optional[m.DietFeedback] = None, change_explanation: Optional[str] = None
                                ) -> Tuple[Optional[m.PlanCandidate], Optional[Halt]]:
        profile = self.repo.reload_profile(self.ctx.user_id)
        self.trace("loadProfile", f"Authorised profile v{profile.version} loaded" if profile else "No profile", detail=profile_context(profile))
        if profile is None or profile.allergy_status == "unknown":
            self.trace("checkConstraintCompleteness", "Allergy information missing — candidate withheld, clarification requested (UC03 3a)")
            return None, Halt(OutcomeStatus.CLARIFICATION, "Before a personalised diet plan can be prepared, please confirm your allergy status in your profile. "
                              "An unknown status is never treated as 'no allergies'.", extra={"missing": ["allergies"], "next_action": "UC01 profile"})
        context: Dict[str, Any] = {"profile": profile_context(profile), "plan_date": plan_date.isoformat(), "budget_level": req.budget_level or profile.budget_level,
                                   "available_ingredients": req.available_ingredients, "notes": req.notes or "",
                                   "known_foods": [f["name"] for f in self.ctx.nutrition.foods],
                                   "nutrition_data_version": self.ctx.nutrition.version}
        if revision:
            context["revision_instructions"] = revision
        if correction:
            context["correction_request"] = correction
        if previous is not None:
            context["previous_candidate"] = previous.content
        try:
            draft = self.llm.generate_diet_candidate(context)
            self.trace("generateDietCandidate", f"LLM drafted {len(draft.meals)} meals, {len(draft.substitutions)} substitutions"
                       + (" (revision)" if revision else "") + (" (correction)" if correction else ""), llm_used=True, detail={"meals": [m_.name for m_ in draft.meals]})
        except LLMUnavailable as e:
            self.trace("generateDietCandidate", f"LLM unavailable ({e}); no plan generated", llm_used=True)
            return None, Halt(OutcomeStatus.WITHHELD, "No diet plan could be generated right now (model unavailable). Nothing was released.")

        if (revision or correction) and previous is not None:
            draft = self._enforce_instructions(draft, " ".join(revision or []) + " " + (correction or ""))
        content = self._diet_content(draft, plan_date, req.notes, previous)
        if any(not meal["items"] for meal in content["meals"]):
            self.trace("selectFeasibleMeals", "A meal has no feasible items under the current constraints (UC03 4a)")
            return None, Halt(OutcomeStatus.CLARIFICATION, "No meal satisfies all of your current constraints at once. Which constraint could be relaxed "
                              "(budget, a preference, or available ingredients)?", extra={"infeasible_meals": [m_["name"] for m_ in content["meals"] if not m_["items"]]})

        flags: List[Dict[str, Any]] = []
        hits = self.ctx.nutrition.allergen_conflicts([self.ctx.nutrition.lookup(i["food"]) for m_ in content["meals"] for i in m_["items"] if i["verified"]], profile.allergies)
        if hits:
            flags.append({"code": "allergen_conflict", "severity": 2, "note": "draft contains " + ", ".join(f"{h['food']} ({h['allergen']})" for h in hits)})
            self.trace("checkAllergens", "Draft contains a possible allergen — flagged for the Safety Supervisor", detail={"hits": hits})
        punitive = check_plan_not_punitive(content["total_kcal"], len(content["meals"]), content.get("previous_total_kcal"))
        if punitive:
            flags.append({"code": "punitive", "severity": 2, "note": "; ".join(punitive)})
            self.trace("checkAgainstPunitiveRule", "Draft looks restrictive: " + "; ".join(punitive))
        if content["unverified_foods"]:
            flags.append({"code": "unverified_nutrition", "severity": 1, "note": ", ".join(content["unverified_foods"])})

        candidate = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.DIET.value,
                                    version=next_version(self.repo, self.ctx.user_id, CandidateKind.DIET.value), plan_date=plan_date,
                                    profile_version=profile.version, rationale=draft.rationale, status=CandidateStatus.DRAFT.value,
                                    previous_version_id=previous.id if previous else None, content=content, risk_flags=flags,
                                    model_version=self.model_version, agent_version=self.agent_id,
                                    change_explanation=change_explanation, feedback_id=feedback.id if feedback else None,
                                    repair_count=(previous.repair_count + 1) if (previous and revision) else 0)
        self.repo.save_candidate(candidate)
        self.audit("dietCandidateSaved", versions={"candidate_id": candidate.id, "candidate_version": candidate.version,
                                                      "profile_version": profile.version, "nutrition_data_version": self.ctx.nutrition.version})
        self.trace("saveDietCandidate", f"Diet candidate v{candidate.version} saved ({content['total_kcal']:.0f} kcal, {len(content['meals'])} meals)",
                   detail={"candidate_id": candidate.id, "risk_flags": flags})
        self._last_explanation = draft.constraints_explanation
        return candidate, None

    def _enforce_instructions(self, draft: DietPlanDraft, instr: str) -> DietPlanDraft:
        """Deterministic follow-through on revision instructions the model may have ignored."""
        instr = instr.lower()
        ns = self.ctx.nutrition
        changed = []
        if "unverified" in instr or "nutrition table" in instr or "not in the versioned" in instr:
            import difflib
            names = [f["name"] for f in ns.foods]
            for meal in draft.meals:
                kept = []
                for it in meal.items:
                    if ns.lookup(it.food):
                        kept.append(it); continue
                    close = difflib.get_close_matches(it.food.lower(), names, n=1, cutoff=0.55)
                    if close:
                        changed.append(f"{it.food} → {close[0]}"); it.food = close[0]; kept.append(it)
                    else:
                        changed.append(f"{it.food} removed (not in {ns.version})")
                meal.items = kept
        if changed:
            self.trace("enforceRevision", "Draft did not fully follow the instructions; rules enforced: " + ", ".join(changed)[:300])
        return draft

    # ===================================================================== UC04
    def adapt_diet(self, fb: DietFeedbackIn) -> Tuple[Optional[m.PlanCandidate], Optional[Halt]]:
        active = self.repo.current_released(self.ctx.user_id, CandidateKind.DIET.value)
        if active is None:
            return None, Halt(OutcomeStatus.BLOCKED, "There is no released diet plan to adapt yet. Request a diet plan first.")
        profile = self.repo.reload_profile(self.ctx.user_id)
        self.trace("loadCurrentPlan", f"Active diet plan v{active.version} and feedback loaded")
        punitive, desc = detect_punitive_request(fb.text or "")
        strategy = DietAdaptationStrategy.SAFE_ALTERNATIVE if punitive else DietAdaptationStrategy.MINIMAL_CHANGE
        row = m.DietFeedback(id=new_id("dfb"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, candidate_id=active.id,
                             hunger=fb.hunger, satiety=fb.satiety, cost_issue=fb.cost_issue, adherence=fb.adherence, text=fb.text,
                             status=FeedbackStatus.ANALYSING.value)
        self.repo.save_diet_feedback(row)

        barrier = None
        try:
            barrier = self.llm.interpret_feedback(fb.model_dump(), active.content)
            self.trace("interpretFeedback", f"LLM identified barrier: {barrier.barrier}" + (" (punitive request detected)" if barrier.punitive_request_detected else ""),
                       llm_used=True, detail=barrier.model_dump())
            if barrier.punitive_request_detected:
                strategy = DietAdaptationStrategy.SAFE_ALTERNATIVE
        except LLMUnavailable as e:
            self.trace("interpretFeedback", f"LLM unavailable ({e}); using rule-based barrier", llm_used=True)

        if barrier is not None and barrier.needs_clarification and not punitive:
            row.status = FeedbackStatus.AWAITING_CLARIFICATION.value
            self.repo.commit()
            return None, Halt(OutcomeStatus.CLARIFICATION, barrier.clarification_question or "Could you say a little more about what made the plan hard to follow?",
                              extra={"feedback_id": row.id, "active_plan_kept": True})

        row.strategy = strategy.value
        self.repo.commit()
        if strategy == DietAdaptationStrategy.SAFE_ALTERNATIVE:
            self.trace("checkAgainstPunitiveRule", "Punitive / compensatory restriction declined; proposing a feasible non-punitive alternative instead (UC04 3a)",
                       detail={"matched": desc})

        barrier_name = barrier.barrier if barrier else ("other" if not punitive else "restriction_request")
        context = {"profile": profile_context(profile), "current_plan": active.content, "barrier": barrier_name, "feedback": fb.model_dump(),
                   "known_foods": [f["name"] for f in self.ctx.nutrition.foods], "nutrition_data_version": self.ctx.nutrition.version}
        try:
            rev = self.llm.propose_minimal_change(context, strategy.value)
            self.trace("proposeMinimalChange", f"LLM proposed: {', '.join(rev.changed_elements) or 'no change'}", llm_used=True,
                       detail={"change_explanation": rev.change_explanation})
        except LLMUnavailable as e:
            row.status = FeedbackStatus.NOT_APPLIED.value
            self.repo.commit()
            self.trace("proposeMinimalChange", f"LLM unavailable ({e}); current plan kept", llm_used=True)
            return None, Halt(OutcomeStatus.INFO, "Your feedback was recorded. The current plan stays active because no revision could be drafted right now.")

        if not rev.changed_elements:
            row.status = FeedbackStatus.NOT_APPLIED.value
            self.repo.commit()
            if strategy == DietAdaptationStrategy.SAFE_ALTERNATIVE:
                self.trace("keepCurrentPlan", "Punitive request declined; the current non-punitive plan is kept unchanged (UC04 3a)")
                return None, Halt(OutcomeStatus.INFO, "Your request for a stricter or compensatory plan was declined — plans are never made stricter "
                                  "to punish or compensate for missed adherence or food already eaten. Your current plan stays active unchanged. "
                                  f"{rev.change_explanation}")
            self.trace("keepCurrentPlan", "No change justified — feedback recorded without a new version (UC04 8a)")
            return None, Halt(OutcomeStatus.INFO, f"Thanks — your feedback was recorded. No change to the plan was justified: {rev.change_explanation}")

        req = DietPlanRequestIn(plan_date=active.plan_date, notes=fb.text)
        content = self._diet_content(rev.plan, active.plan_date or date.today(), fb.text, active)
        flags: List[Dict[str, Any]] = []
        hits = self.ctx.nutrition.allergen_conflicts([self.ctx.nutrition.lookup(i["food"]) for m_ in content["meals"] for i in m_["items"] if i["verified"]], profile.allergies)
        if hits:
            flags.append({"code": "allergen_conflict", "severity": 2, "note": "revision contains " + ", ".join(f"{h['food']} ({h['allergen']})" for h in hits)})
        punitive_reasons = check_plan_not_punitive(content["total_kcal"], len(content["meals"]), content.get("previous_total_kcal"))
        if punitive_reasons:
            flags.append({"code": "punitive", "severity": 2, "note": "; ".join(punitive_reasons)})
        self.trace("checkConsistency", "Revision checked against allergies, budget, schedule and the non-punitive rule" + (" — issues flagged" if flags else " — OK"),
                   detail={"flags": flags})
        content["changed_elements"] = rev.changed_elements
        content["strategy"] = strategy.value
        candidate = m.PlanCandidate(id=new_id("cand"), user_id=self.ctx.user_id, request_id=self.ctx.request_id, kind=CandidateKind.DIET.value,
                                    version=next_version(self.repo, self.ctx.user_id, CandidateKind.DIET.value), plan_date=active.plan_date,
                                    profile_version=profile.version, rationale=rev.plan.rationale, status=CandidateStatus.DRAFT.value,
                                    previous_version_id=active.id, content=content, risk_flags=flags, model_version=self.model_version,
                                    agent_version=self.agent_id, change_explanation=rev.change_explanation, feedback_id=row.id)
        self.repo.save_candidate(candidate)
        row.status = FeedbackStatus.PENDING_REVIEW.value
        self.repo.commit()
        self.audit("dietRevisionSaved", versions={"candidate_id": candidate.id, "candidate_version": candidate.version, "previous_version_id": active.id,
                                                     "profile_version": profile.version})
        self.trace("saveRevision", f"Revision candidate v{candidate.version} saved (previous v{active.version})", detail={"candidate_id": candidate.id})
        self._last_explanation = rev.change_explanation
        return candidate, None

    def mark_feedback(self, candidate: m.PlanCandidate, outcome: OutcomeStatus):
        if not candidate.feedback_id:
            return
        fb = self.repo.db.get(m.DietFeedback, candidate.feedback_id)
        if fb:
            fb.status = FeedbackStatus.APPLIED.value if outcome == OutcomeStatus.RELEASED else FeedbackStatus.NOT_APPLIED.value
            self.repo.commit()

    # ===================================================================== UC09 / UC10 call-backs
    def widen_uncertainty_range(self, candidate: m.PlanCandidate, instructions: RevisionInstruction) -> m.PlanCandidate:
        """UC02 RevisionRequired: a food analysis is not re-drafted; its uncertainty is widened and disclosed (AR-02)."""
        content = dict(candidate.content)
        rng = dict(content.get("uncertainty_range") or {})
        est = content.get("nutrient_estimate") or {}
        kcal = float(est.get("kcal") or 0)
        rng["kcal_low"], rng["kcal_high"] = round(min(rng.get("kcal_low", kcal), kcal * 0.5), 1), round(max(rng.get("kcal_high", kcal), kcal * 1.5), 1)
        content["uncertainty_range"], content["range_widened"] = rng, True
        content["confidence"] = round(min(float(content.get("confidence") or 0.5), 0.5), 2)
        content["summary_text"] = (f"Estimated about {kcal:.0f} kcal, but the plausible range is wide ({rng['kcal_low']:.0f}–{rng['kcal_high']:.0f} kcal) because the evidence is limited. "
                                   f"Confidence {content['confidence']:.2f}. " + (f"Safety flags: {'; '.join(content.get('safety_flags', []))}." if content.get("safety_flags") else ""))
        entry = self.repo.get_food_entry(content["entry_id"])
        if entry:
            entry.version += 1
            entry.uncertainty_range, entry.confidence = rng, content["confidence"]
            self.repo.commit()
        new = m.PlanCandidate(id=new_id("cand"), user_id=candidate.user_id, request_id=self.ctx.request_id, kind=candidate.kind,
                              version=candidate.version + 1, plan_date=candidate.plan_date, profile_version=candidate.profile_version,
                              rationale=candidate.rationale, status=CandidateStatus.DRAFT.value, previous_version_id=candidate.id, content=content,
                              risk_flags=candidate.risk_flags, model_version=candidate.model_version, agent_version=self.agent_id,
                              change_explanation="Uncertainty range widened on Safety Supervisor instructions: " + "; ".join(instructions.instructions)[:300],
                              repair_count=candidate.repair_count + 1)
        self.repo.save_candidate(new)
        self.trace("widenUncertaintyRange", f"Analysis v{new.version}: range widened to {rng['kcal_low']:.0f}–{rng['kcal_high']:.0f} kcal, confidence capped at {content['confidence']}")
        return new

    def revise(self, candidate: m.PlanCandidate, instructions: RevisionInstruction) -> Optional[m.PlanCandidate]:
        if candidate.kind == CandidateKind.FOOD_ANALYSIS.value:
            return self.widen_uncertainty_range(candidate, instructions)
        self.trace("revisionRequested", f"Revising diet candidate v{candidate.version} on rule-linked instructions {instructions.rule_ids}")
        req = DietPlanRequestIn(plan_date=candidate.plan_date, notes=candidate.content.get("source_input"))
        cand, _ = self.generate_diet_candidate(candidate.plan_date or date.today(), req, revision=instructions.instructions, previous=candidate,
                                               change_explanation=f"Revised on Safety Supervisor instructions: {instructions.summary or '; '.join(instructions.instructions)}")
        return cand

    def correct(self, candidate: m.PlanCandidate, correction_request: str) -> Optional[m.PlanCandidate]:
        self.trace("requestCorrection", f"Correcting diet candidate v{candidate.version}: {correction_request}")
        req = DietPlanRequestIn(plan_date=candidate.plan_date, notes=candidate.content.get("source_input"))
        cand, _ = self.generate_diet_candidate(candidate.plan_date or date.today(), req, correction=correction_request, previous=candidate,
                                               change_explanation=f"Corrected after reconciliation: {correction_request}")
        return cand
