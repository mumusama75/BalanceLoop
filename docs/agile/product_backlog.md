# Product backlog

Stories are derived from the Stage 1 use cases. Owner = use-case owner in the Stage 1 report. Points: Fibonacci.
Status after Sprint 3: ✅ done · ◐ partial · ○ not started.

| ID | Story (As a … I want … so that …) | UC | Owner | Pts | Sprint | Status |
|---|---|---|---|---|---|---|
| S-01 | As a user I want to save a versioned profile with explicit consent so that coaches only use authorised, current information | UC01 | Shun Lin | 5 | 1 | ✅ |
| S-02 | As a user I want an unknown allergy status to be treated as unknown (not "none") so that unsafe dietary content is withheld until I confirm | UC01 | Shun Lin | 3 | 1 | ✅ |
| S-03 | As the Founder I want every candidate reviewed by hard rules and an explainable risk score before release so that nothing unsafe reaches a user | UC10 | Haozhe Jiang | 13 | 1 | ✅ |
| S-04 | As the Founder I want Medium candidates revised at most twice with rule-linked instructions, High blocked with a checked safe template and Critical stopped with a support notice and incident | UC10 | Haozhe Jiang / Zhengzhao Chen | 8 | 1 | ✅ |
| S-05 | As the Founder I want every input, version and decision audited before it takes effect, and the system to fail closed when the policy or audit store is unavailable | AR-10 | Haozhe Jiang | 5 | 1 | ✅ |
| S-06 | As a user I want a daily readiness result (Ready / Reduced / Recovery) decided by fixed rules from my check-in, never defaulting to Ready | UC05 | Zixian Yu | 5 | 2 | ✅ |
| S-07 | As a user I want a low-intensity exercise plan drafted from my readiness and limits, with warm-up, rest, cool-down and alternatives | UC06 | Zixian Yu | 8 | 2 | ✅ |
| S-08 | As a user I want to record completion, exertion, fatigue and pain so that pain stops progression and alarming feedback is escalated | UC07 | Zhengzhao Chen | 5 | 2 | ✅ |
| S-09 | As a user I want my exercise plan adapted (maintain / reduce / replace / pause) without unsupported load increases | UC08 | Zhengzhao Chen | 5 | 2 | ✅ |
| S-10 | As a user I want to log a meal in text and get an estimate with an uncertainty range and confidence, or a clear "recorded, not estimated" | UC02 | Shun Lin | 8 | 2 | ✅ |
| S-11 | As a user I want a feasible diet plan from my profile, budget, culture and ingredients with substitutions and an explanation | UC03 | Yiheng Yang | 8 | 2 | ✅ |
| S-12 | As a user I want the smallest feasible change when I report hunger, cost or difficulty, and punitive requests declined | UC04 | Yiheng Yang | 5 | 2 | ✅ |
| S-13 | As a user I want my diet and exercise plans reconciled by rule (timing, recovery, workload, nutrition) into one daily plan | UC09 | Haozhe Jiang / Zixian Yu | 8 | 3 | ✅ |
| S-14 | As a tutor I want to see which steps were LLM drafts and which were rule decisions for every request | Stage 2 brief | all | 5 | 3 | ✅ |
| S-15 | As a user I want a web UI for profile, food, readiness, plans, feedback and my review cases | all | all | 13 | 3 | ✅ |
| S-16 | As the Founder I want a console for policies, incidents and audit replay | AR-09/10 | Haozhe Jiang | 8 | 3 | ✅ |
| S-17 | As a developer I want offline tests of rules and end-to-end flows so that the safety behaviour is regression-tested | — | all | 5 | 1–3 | ✅ |
| S-18 | As a user I want to log a meal by **image** | UC02 (optional) | Shun Lin | 5 | backlog | ○ |
| S-19 | O1 adaptive calorie disclosure | optional | Yiheng Yang | 3 | backlog | ○ |
| S-20 | O2 wearable data import at EP05-1 | optional | Zixian Yu | 5 | backlog | ○ (interface stub only) |
| S-21 | Real authentication and multi-device sessions | — | — | 5 | backlog | ○ |

Definition of done: main success scenario and the safety-related extensions of the use case pass through the API;
unit/e2e tests added; trace and audit records present; reviewed by another member; merged with a `feat(UCxx)` commit.
