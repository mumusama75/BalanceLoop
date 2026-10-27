# Sprints

Three one-week sprints between the Stage 1 presentation and the Stage 2 demonstration. Ceremonies: sprint
planning (Mon), 10-minute stand-ups (Mon/Wed/Fri on Teams), review + retrospective (Sun). Board: GitHub
Projects (To do / In progress / Review / Done). Dates below are the planned weeks — adjust to the actual calendar.

## Sprint 1 — skeleton + safety core (week of 7 Oct 2026)

**Goal:** a running FastAPI/SQLite backend where a hand-made candidate can be pushed through UC10 and audited.

| Story | Outcome |
|---|---|
| S-01, S-02 | versioned `user_profiles` + `consent_records`; allergy "unknown" ≠ "none"; Incomplete status restricts dietary planning |
| S-03, S-04, S-05 | `SafetySupervisor` with hard rules HR-01…HR-08, `R = 2S+U+V+P+B`, revision loop (max 2), safe templates checked against the rules, critical stop → incident, fail-closed on policy/audit failure |
| S-17 | 40 rule unit tests |

**Review:** demoed the review gate with mock candidates. **Retrospective:** (+) building UC10 first forced every
later story to go through the gate; (−) the first risk calibration was too strict (a plain brisk walk scored High) —
we added a calibration step to the DoD of every Coach story.

## Sprint 2 — the two Coach lines (week of 14 Oct 2026)

**Goal:** Fitness line UC05→UC08 and Nutrition line UC02→UC04 working end-to-end through UC10, with the real model.

| Story | Outcome |
|---|---|
| S-06…S-09 | `FitnessCoach`: readiness rules, placeholder when readiness is insufficient, pain rule → UC10, load rule |
| S-10…S-12 | `NutritionCoach`: nutrition-table estimates with ranges/confidence, RecordedUnestimated, allergen flags, SafeAlternative for punitive requests |
| LLM gateway | JSON-schema-validated outputs; `MockLLMClient` for offline tests; DeepSeek via OpenAI-compatible client |

**Review:** first run against DeepSeek. **Retrospective:** (+) structured outputs validated on the first try;
(−) two false positives in text rules found only with the real model ("I'm starving by mid-morning" → HR-08;
"rest to make up for the knee" → HR-04) — fixed by requiring intent/food context in the patterns and adding
regression tests; lesson: run the real model against every prompt before the sprint review.

## Sprint 3 — integration, UI, demo (week of 21 Oct 2026)

**Goal:** UC09 reconciliation, the agent trace, the Vue UI and Founder console, demo script.

| Story | Outcome |
|---|---|
| S-13 | rule-based conflict detection, LLM-refined correction requests, Coach corrections, "same conflict returns" guard |
| S-14 | `trace` on every reply; drawer marks **LLM draft** vs **Rule** |
| S-15, S-16 | Vue 3 + Element Plus app: Profile, Food, Readiness, Plans, Feedback, Reviews; Founder: Policies, Incidents, Audit replay, Cases |
| docs | README, API reference, demo script, this backlog |

**Review:** full demo run (docs/demo_script.md). **Retrospective:** (+) uniform `OperationResult` made the UI
simple; (−) image input (S-18) and O1/O2 deferred to the backlog — core use cases work without them, as the
Stage 1 report required.

## Change assessment and acceptance

* A change request is accepted when it maps to a use case or requirement of the Stage 1 report, has a story with
  acceptance criteria, and does not weaken a safety rule without a Founder policy version bump.
* Acceptance of a story = e2e scenario passing in `backend/tests/test_e2e_mock.py` + manual check against the real model.
