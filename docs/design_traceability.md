# Design → implementation traceability

How the Stage 1 models (report §4–§6) appear in the prototype. Paths are relative to `backend/app/`.

## Class diagram (Fig. 3)

| Class / interface | Implementation |
|---|---|
| `«abstract» Agent` (agentId, role, modelVersion; perceive/reason/act/explain) | `agents/base.py` → `Agent`, `AgentContext` |
| `Orchestrator` (dispatch, reconcilePlans, detectConflicts, notifyUser, submitProfile, recordConsent, findAcceptedCounterpart…) | `agents/orchestrator.py` |
| `NutritionCoach` (recordMeal, requestDietPlan, submitDietFeedback, computeEstimate, checkAllergens, checkAgainstPunitiveRule, widenUncertaintyRange, requestCorrection…) | `agents/nutrition_coach.py` |
| `FitnessCoach` (submitCheckIn, applyReadinessRules, requestExercisePlan, createInternalPlaceholder, submitActivityFeedback, applyPainRule, stopProgression, applyLoadRule, conservativeOption, simplify…) | `agents/fitness_coach.py` |
| `SafetySupervisor` (maxRepairs=2, reviewCandidate, computeRiskScore, applyHardRules, determineDecision, requestRevision, prepareSafeReply, stopPersonalisedPlanning, prepareSupportNotice, raiseIncident) | `agents/safety_supervisor.py` |
| `«interface» Repository` → `VersionedRecordStore` | `repository/base.py`, `repository/versioned_store.py` |
| `«interface» LLMGateway` → `CloudLLMClient` (de-identified input) / `PrivateLLMClient` | `llm/gateway.py`, `llm/cloud_client.py`; the private variant is represented by `llm/mock_client.py` (runs in-process) |
| `«interface» ExternalDataSource` (fetchNutritionData, importWearableData O2) | `external/data_source.py`, `external/nutrition_local.py` |
| `User`, `UserProfile` (versioned), `ConsentRecord` | `db/models.py` → `users`, `user_profiles`, `consent_records` |
| `FoodEntry` | `food_entries` + `food_analysis` candidate for UC10 |
| `ReadinessAssessment` ◆ `ReadinessCheckIn` | `readiness_assessments`, `readiness_checkins` |
| `ExercisePlanningRequest` ◆ `ExercisePlanCandidate` ◆ `ActivityItem` | `exercise_planning_requests`, `plan_candidates (kind=exercise)`, `activity_items` |
| `DietPlanCandidate` — `DietFeedback` | `plan_candidates (kind=diet)`, `diet_feedback` |
| `IntegratedPlan` ◆ `PlanConflict`, aggregates one diet + one exercise candidate | `plan_candidates (kind=integrated, diet_candidate_id, exercise_candidate_id)`, `plan_conflicts` |
| `ActivityFeedback`, `AdaptationDecision` | `activity_feedback`, `adaptation_decisions` |
| `ReviewDecision` under `ReviewPolicy`; `Founder` configures policy | `review_cases`, `review_decisions`, `review_policies`; `api/routes_founder.py` |
| `AuditLog` ◆ `AuditRecord`, `replay(requestId)` | `audit_records`, `agent_traces`; `GET /api/founder/requests/{id}/replay` |
| Enumerations (ReadinessResult, AssessmentStatus, RequestState, AdaptationAction, DecisionType, ProfileStatus, FoodEntryStatus, FeedbackStatus, DietAdaptationStrategy, FeedbackRecordStatus, AdaptationStatus, RiskLevel, IntegrationState) | `domain/enums.py` |

## Structured class (Fig. 4)

`BalanceLoopSystem` = one `Orchestrator` per request owning `nutrition`, `fitness`, `supervisor` as parts
(`Orchestrator.workers`). `userPort` → `api/routes_*.py`; `founderPort` → `api/routes_founder.py`;
`dataPort` → `LocalNutritionSource`; `wearablePort` → `ExternalDataSource.import_wearable_data` (stub, O2).
All agents reach the model only via `LLMGateway` and storage only via `Repository`, exactly as the connectors show.

## Use cases → entry points

| UC | API | Agent method(s) | LLM used for | Rules decide |
|---|---|---|---|---|
| UC01 | `POST /api/profile`, `POST /api/consent` | `Orchestrator.submit_profile / record_consent` | `interpretConstraints` (optional free text) | missing safety fields, contradictions, Incomplete status |
| UC02 | `POST /api/food/entries[/{id}/clarify]` | `NutritionCoach.record_meal / clarify_entry / _analyse` | `identifyFood` | portions → nutrition table, confidence, allergen flags, RecordedUnestimated |
| UC03 | `POST /api/diet/plans` | `NutritionCoach.generate_diet_candidate` | `generateDietCandidate` | allergy completeness, kcal from table, feasibility, flags |
| UC04 | `POST /api/diet/feedback` | `NutritionCoach.adapt_diet` | `interpretFeedback`, `proposeMinimalChange` | punitive request → SafeAlternative; floor / −20 % rule |
| UC05 | `POST /api/readiness/checkins` | `FitnessCoach.submit_checkin` | `assessReadiness` | `rules/readiness_rules.py` |
| UC06 | `POST /api/exercise/plans` | `FitnessCoach.generate_exercise_candidate` | `generateExerciseCandidate` | readiness sufficiency (placeholder), enforce revision |
| UC07 | `POST /api/exercise/activities/{id}/feedback` | `FitnessCoach.submit_activity_feedback` | `interpretRecoveryNotes` | consistency, pain rule → UC10 critical |
| UC08 | `POST /api/exercise/plans/adapt` | `FitnessCoach.adapt_exercise` | `proposeAdaptations` | allowed actions, `rules/load_rules.py` |
| UC09 | `POST /api/daily-plan` (+ every single-candidate submit) | `Orchestrator.request_daily_plan / submit_candidate / reconcile_plans` | `classifyConflict` (refine + draft request) | `rules/conflict_rules.py`, profile-version check, same-conflict guard |
| UC10 | internal (`Orchestrator.run_review_pipeline`) | `SafetySupervisor.review_candidate / release / prepare_safe_reply / stop_personalised_planning` | `draftRevisionInstructions` | `rules/hard_rules.py`, `rules/risk_scoring.py`, policy version, audit-before-effect |

## State machines → persisted states

| Figure | Subject | Where the state lives |
|---|---|---|
| Fig. 7 FoodEntry lifecycle | Draft → AwaitingClarification → PendingReview → RevisionRequired → Released / Withheld / RecordedUnestimated | `food_entries.status` (`FoodEntryStatus`) |
| Fig. 10 Diet plan lifecycle | Drafting → Candidate Under Review → Active / Drafting Revision → Revision Under Review | `plan_candidates.status` (`CandidateStatus`) + `review_cases.state` |
| Fig. 13 Readiness assessment | AwaitingInput → Validating → AwaitingClarification / Assessing → Saving → Completed / Incomplete | `readiness_assessments.status` (`AssessmentStatus`) |
| Fig. 16 Exercise planning request | Drafting (CheckingReadiness / AwaitingReadiness / Generating / SavingCandidate) → Submitting → PendingReview → RevisionRequired / Released / Withheld / Abandoned | `exercise_planning_requests.state` (`RequestState`), `repair_count` |
| Fig. 21 / 22 Feedback & adaptation | Recording → Validating → Comparing → Recorded / Escalating; Loading → Analysing → Deciding → Checking load → Cross-plan → Review → Released / Withheld | `activity_feedback.status` (`FeedbackRecordStatus`), `adaptation_decisions.status` (`AdaptationStatus`) |
| Fig. 25 Review case | PendingValidation → UnderReview → Approved / AwaitingRevision / CheckingSafeFallback → Released / Withheld | `review_cases.state` (`ReviewCaseState`), `final_status` |

## Assumptions carried into the prototype

Prototype thresholds (pain ≥ 4 → Recovery, energy floor 1200 kcal, R bands, two repairs) are course values, not
clinical. The nutrition source is a local versioned table standing in for a provider. All LLM I/O is structured and
validated (JSON Schema). A single-domain plan is reviewed alone when no counterpart exists for the day.
