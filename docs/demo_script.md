# Demo script (≈ 12 minutes)

Preparation: backend running (`BL_LLM_PROVIDER=cloud` with a DeepSeek key, or `mock` for an offline-safe run),
frontend on :5173, `POST /api/admin/reset-demo` done. Keep the **agent pipeline drawer** open on every result —
it is the evidence that the LLM only drafts and the rules decide.

| # | Scenario | Steps (user **Sam**: profile ready, peanut allergy, mild knee limit, 40 min/day) | Expected |
|---|---|---|---|
| 1 | Happy path | Readiness: sleep 4, fatigue 3, soreness 2, pain 0, "walked 20 min", 40 min → **Ready**. Plans › Exercise › Generate. | Exercise plan **released**, Low risk; trace: FitnessCoach *generateExerciseCandidate* (LLM draft) → SafetySupervisor *applyHardRules* → *computeRiskScore* → *release*. |
| 2 | Integration (UC09) | Plans › Diet › Generate. | A released exercise plan exists for today → Orchestrator *findAcceptedCounterpart* → *detectConflicts* → **integrated daily plan** released; Daily tab shows both. |
| 3 | Food with uncertainty (UC02) | Food: "2 boiled eggs and a bowl of rice" → analysis. Then "peanut butter toast" → clarification question → answer "2 slices and 1 tbsp". | Estimate with kcal range, confidence and basis; second entry released **with a red allergen notice** (original entry preserved). |
| 4 | Allergen hard rule (UC10 HR-01) | Plans › Diet › Generate with notes "I love satay sauce". | Coach draft contains satay (peanut) → **HR-01** → bounded **safe response**; no meal plan shown. |
| 5 | Non-punitive rule (UC04) | Feedback › Diet: "I ate too much today so tomorrow I will skip dinner and only drink water". | Request **declined**, SafeAlternative strategy; explanation in message; trace shows *checkAgainstPunitiveRule*. |
| 6 | Pain → critical (UC07 HR-02) | Feedback › Activity: partial, exertion 6, pain 2, notes "I had chest pain and felt faint". | Immediate **support notice**; progression hold; Founder › Incidents shows a critical incident; Founder notification. |
| 7 | Recovery day (UC05/UC06/HR-03) | Readiness: pain 5, "knee hurts" → **Recovery**. Plans › Exercise › Generate with notes "push me harder" and plan date tomorrow. | Draft contains moderate activity → **HR-03** → safe response. (Same request *today* is caught earlier by UC09 recovery conflict → corrected to light → released.) |
| 8 | Medium → revision → Low (UC10 4a) | User **Alex** (no limits): consent on, profile allergy=none, 45 min; Readiness Ready; Plans › Exercise notes "push me harder today". | Decision 1 **ReviseAndReview (Medium, S=2)** → *draftRevisionInstructions* (LLM) → Coach revises → decision 2 **Approve (Low)**; review badge shows `repair_count = 1`. |
| 9 | Fail-closed (UC10 2b / 6a) | Founder › Policies: activate **0.9-draft** (≠ required 1.0) → any plan request. Then reactivate 1.0 and toggle `simulate_audit_failure`. | Non-personalised reply both times; incidents "Fail-closed" recorded. |
| 10 | Traceability (AR-10) | Founder › Audit: pick the request from step 2 → Replay. | One timeline: agent trace, audit records with versions (profile, policy, model, candidate), review case & decisions, conflicts. |

Talking points while the drawer is open:
* **Perception** — `identifyFood`, `assessReadiness`, `interpretRecoveryNotes` turn free text into structured evidence (JSON-schema validated).
* **Decision support** — the Coaches' drafts; the readiness result, hard rules, risk level and release are all deterministic.
* **Interaction** — clarification questions, rationale, rule-linked revision instructions, bounded safe templates.
* **Degradation** — set `BL_LLM_PROVIDER=mock` or unplug the network: every flow still ends safely (4b, 5b, 4a paths).
