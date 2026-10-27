// Shared colour maps, labels and formatting helpers (kept consistent across every page).

export const STATUS = {
  released:             { tag: 'success', alert: 'success', label: 'Released' },
  safe_response:        { tag: 'warning', alert: 'warning', label: 'Safe response (bounded)' },
  support_notice:       { tag: 'danger',  alert: 'error',   label: 'Support notice' },
  withheld:             { tag: 'danger',  alert: 'error',   label: 'Withheld' },
  clarification:        { tag: 'primary', alert: 'info',    label: 'Clarification needed', cls: 'alert-blue' },
  recorded_unestimated: { tag: 'info',    alert: 'info',    label: 'Recorded, not estimated' },
  not_integrated:       { tag: 'warning', alert: 'warning', label: 'Not integrated' },
  pending_readiness:    { tag: 'warning', alert: 'warning', label: 'Readiness check-in needed' },
  blocked:              { tag: 'danger',  alert: 'error',   label: 'Blocked (precondition)' },
  info:                 { tag: 'info',    alert: 'info',    label: 'Info' },
  warning:              { tag: 'warning', alert: 'warning', label: 'Warning' },
}
export const statusInfo = (s) => STATUS[s] || { tag: 'info', alert: 'info', label: s || '—' }

export const AGENT_COLORS = {
  Orchestrator: '#409eff',
  NutritionCoach: '#67c23a',
  FitnessCoach: '#e6a23c',
  SafetySupervisor: '#8e44ad',
  Founder: '#606266',
}
export const agentColor = (a) => AGENT_COLORS[a] || '#909399'

export const KIND_LABEL = { diet: 'Diet plan', exercise: 'Exercise plan', integrated: 'Integrated daily plan', food_analysis: 'Meal analysis' }
export const kindLabel = (k) => KIND_LABEL[k] || k

export const RISK_TAG = { Low: 'success', Medium: 'warning', High: 'danger', Critical: 'danger' }
export const DECISION_TAG = { Approve: 'success', ReviseAndReview: 'warning', SafeFallback: 'warning', Withhold: 'danger', CriticalStop: 'danger' }
export const CASE_STATE_TAG = { Released: 'success', Approved: 'success', Withheld: 'danger', AwaitingRevision: 'warning', UnderReview: 'warning', CheckingSafeFallback: 'warning', PendingValidation: 'info' }
export const CANDIDATE_STATUS_TAG = { Released: 'success', Withheld: 'danger', Superseded: 'info', Draft: 'info', PendingReview: 'warning', RevisionRequired: 'warning', Placeholder: 'info' }
export const PROFILE_STATUS_TAG = { Active: 'success', Incomplete: 'warning', ConsentWithdrawn: 'danger', Conflict: 'danger', AwaitingConfirmation: 'warning' }
export const INTENSITY_TAG = { light: 'success', 'light-moderate': 'success', moderate: 'warning', vigorous: 'danger' }
export const NOTIFICATION_TAG = { release: 'success', safe_response: 'warning', support_notice: 'danger', clarification: 'primary', info: 'info', incident: 'danger' }
export const SEVERITY_TAG = { critical: 'danger', governance: 'warning', high: 'danger', medium: 'warning', low: 'info' }

export const READINESS = {
  Ready:    { color: '#67c23a', bg: '#f0f9eb', text: 'You are good to go: a normal session within your limits.' },
  Reduced:  { color: '#e6a23c', bg: '#fdf6ec', text: 'Capacity is reduced today: lighter, shorter activity only.' },
  Recovery: { color: '#f56c6c', bg: '#fef0f0', text: 'Recovery day: only light movement; no training load.' },
}

export const SCORE_PARTS = [
  { key: 'S', name: 'Severity of worst plausible harm', range: '0–3, weighted ×2' },
  { key: 'U', name: 'Uncertainty of the evidence', range: '0–3' },
  { key: 'V', name: 'Vulnerability recorded in the profile', range: '0–2' },
  { key: 'P', name: 'Proximity to a policy boundary', range: '0–2' },
  { key: 'B', name: 'Behavioural pattern', range: '0–2' },
]

// Backend timestamps are naive UTC ISO strings; add a Z so the browser converts to local time.
function parseIso(iso) {
  if (!iso) return null
  const s = /Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}
export function fmtDate(iso) {
  const d = parseIso(iso)
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}
export function fmtTime(iso) {
  const d = parseIso(iso)
  return d ? d.toLocaleTimeString(undefined, { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0') : ''
}
// The backend stores and filters timestamps in UTC, so "today" for list filters is the UTC date.
export const todayUtc = () => new Date().toISOString().slice(0, 10)
export const round = (n, digits = 0) => (n == null || Number.isNaN(Number(n)) ? '—' : Number(n).toFixed(digits))
export const pct = (x) => (x == null ? 0 : Math.round(Number(x) * 100))
