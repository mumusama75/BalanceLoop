# BalanceLoop REST API

Base URL `http://localhost:8000`. Interactive docs at `/docs`. Every request carries the demo-login header
`X-User-Id` (`u_alex`, `u_sam`, `founder`).

## Uniform reply: `OperationResult`

Every personalised operation (UC02–UC10) returns the same envelope:

```json
{
  "request_id": "req_…",
  "status": "released | safe_response | support_notice | withheld | clarification | recorded_unestimated | not_integrated | pending_readiness | blocked | info",
  "message": "human-readable outcome",
  "content": { "…plan / entry / assessment view…" },
  "review":  { "case_id", "state", "decision", "risk_level", "risk_score", "score_breakdown": {"S","U","V","P","B","R","reasons"},
               "triggered_rules": ["HR-01"], "policy_version", "repair_count", "decisions": [ … ] },
  "trace":   [ { "seq", "agent", "step", "llm_used", "model_version", "summary", "detail" } ],
  "extra":   { "next_action": "…" }
}
```

`trace` is the agent pipeline for this request; steps with `llm_used=true` are LLM drafts/interpretations, all
others are rule or storage steps.

## Endpoints

| UC | Method & path | Body | Notes |
|---|---|---|---|
| — | `GET /api/health` | | provider, model, active/required policy |
| — | `GET /api/users` · `GET /api/users/me` | | demo login |
| — | `GET /api/notifications` | | release / safe response / support notice / clarification |
| UC01 | `GET /api/profile` · `GET /api/profile/versions` | | current version + consents |
| UC01 | `POST /api/profile` | `ProfileIn` | returns `saved`, `status` (Active / Incomplete / Conflict / AwaitingConfirmation), `missing_fields`, `conflicts`, `trace` |
| UC01 | `POST /api/consent` | `{scope: core|O1|O2, granted}` | withdrawing `core` stops processing |
| UC02 | `POST /api/food/entries` | `{text, input_type}` | clarification → `POST /api/food/entries/{id}/clarify {answer}` |
| UC02 | `GET /api/food/entries?day=` | | entries with estimate, range, confidence, flags |
| UC03 | `POST /api/diet/plans` | `{plan_date?, budget_level?, available_ingredients?, notes?}` | reconciled with a released exercise plan of the same day (UC09 1a) |
| UC04 | `POST /api/diet/feedback` | `{hunger?, satiety?, cost_issue, adherence?, text?}` | punitive requests declined (SafeAlternative) |
| UC05 | `POST /api/readiness/checkins` · `GET /api/readiness/latest` | `ReadinessCheckInIn` | rule-based status, shown without UC10 |
| UC06 | `POST /api/exercise/plans` | `{plan_date?, notes?}` | needs a readiness assessment ≤ 24 h, else `pending_readiness` |
| UC07 | `POST /api/exercise/activities/{item_id}/feedback` | `{completion, exertion?, pain?, fatigue?, recovery_notes?}` | pain ≥ 7 / red flags → `support_notice` + incident |
| UC08 | `POST /api/exercise/plans/adapt` · `GET /api/exercise/feedback` | `{notes?}` | load rule, simplify on repeated non-completion |
| UC09 | `POST /api/daily-plan` | `{plan_date?}` | both Coaches → conflict rules → corrections → UC10 |
| — | `GET /api/plans/{diet|exercise|integrated}/current` · `GET /api/plans/{kind}/versions` | | released plan / version history |
| UC10 | `GET /api/review/cases` · `GET /api/review/cases/{id}` · `GET /api/review/requests/{request_id}/trace` | | |
| Founder | `GET/POST /api/founder/policies` · `POST /api/founder/policies/{v}/activate` · `POST /api/founder/policies/deactivate-all` · `POST /api/founder/policies/{v}/flags` | `PolicyIn` / `{simulate_audit_failure}` | demo fail-closed toggles |
| Founder | `GET /api/founder/audit?request_id=&user_id=` · `GET /api/founder/requests` · `GET /api/founder/requests/{id}/replay` | | AuditLog.replay |
| Founder | `GET /api/founder/incidents` · `POST /api/founder/incidents/{id}/ack` · `GET /api/founder/notifications` · `GET /api/founder/cases` | | |
| — | `GET /api/nutrition/foods?q=` | | versioned nutrition table |
| — | `POST /api/admin/reset-demo` | | drop + re-seed |
