<script setup>
// Founder: AuditLog.replay(requestId) — trace, audit records, review decisions and conflicts on one timeline.
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, state } from '../../store'
import { agentColor, fmtDate, fmtTime, kindLabel, DECISION_TAG, RISK_TAG } from '../../ui'
import ReviewBadge from '../../components/ReviewBadge.vue'

const route = useRoute()
const userFilter = ref('')
const requests = ref([])
const selected = ref(null)
const replay = ref(null)
const loadingReplay = ref(false)
const auditRows = ref([])
const auditFilter = ref({ request_id: '', user_id: '' })
const openDetail = ref({})

async function loadRequests() {
  requests.value = (await api.get('/founder/requests', { params: userFilter.value ? { user_id: userFilter.value } : {} })).data
}
async function select(row) {
  if (!row) return
  selected.value = row.request_id
  loadingReplay.value = true
  openDetail.value = {}
  try { replay.value = (await api.get(`/founder/requests/${row.request_id}/replay`)).data } finally { loadingReplay.value = false }
}
async function loadAudit() {
  const params = {}
  if (auditFilter.value.request_id) params.request_id = auditFilter.value.request_id
  if (auditFilter.value.user_id) params.user_id = auditFilter.value.user_id
  auditRows.value = (await api.get('/founder/audit', { params })).data
}

// Unified timeline. Trace steps are persisted together when a request completes (identical
// timestamps), while audit records and decisions carry real wall-clock times. So the trace is the
// backbone (execution order) and each audit/decision event is inserted after the trace step that
// produced it: the first step at/after the previous anchor from the same agent whose name matches
// the action (e.g. reviewDecision -> determineDecision, release -> release); "...Saved" actions sit
// at the end of that agent's block of steps.
function anchorIndex(trace, ev, cursor) {
  const idxs = []
  for (let i = cursor; i < trace.length; i++) if (trace[i].agent === ev.agent) idxs.push(i)
  if (!idxs.length) return trace.length - 1
  const first = idxs[0]
  let end = first
  while (trace[end + 1]?.agent === ev.agent) end++
  const name = (i) => trace[i].step.toLowerCase()
  if (/saved$/i.test(ev.action)) {
    for (let i = first; i <= end; i++) if (/save|store/.test(name(i))) return i
    return end
  }
  const stems = ev.action.split(/(?=[A-Z])/).map((t) => t.toLowerCase().slice(0, 5)).filter((t) => t.length >= 4)
  const hit = idxs.find((i) => stems.some((st) => name(i).includes(st)))
  return hit ?? end
}

const timeline = computed(() => {
  const r = replay.value
  if (!r) return []
  const events = []
  for (const a of r.audit) events.push({ at: a.timestamp, type: 'audit', agent: a.actor, action: a.action, title: a.action, text: a.decision ? `decision: ${a.decision}` : '', detail: { versions: a.versions, payload: a.payload } })
  for (const c of r.cases) for (const d of c.decisions) events.push({ at: d.created_at, type: 'decision', agent: 'SafetySupervisor', action: 'reviewDecision', title: `${kindLabel(c.kind)} v${d.candidate_version}`, decision: d, detail: null })
  events.sort((x, y) => String(x.at).localeCompare(String(y.at)))
  const trace = r.trace
  if (!trace.length) return events
  const attached = trace.map(() => [])
  let cursor = 0
  for (const ev of events) {
    const i = anchorIndex(trace, ev, cursor)
    attached[i].push(ev)
    cursor = Math.max(cursor, i)
  }
  const out = []
  trace.forEach((t, i) => {
    out.push({ at: t.at, type: 'trace', seq: t.seq, agent: t.agent, title: t.step, text: t.summary, llm: t.llm_used, model: t.model_version, detail: t.detail })
    out.push(...attached[i])
  })
  return out
})
const hasDetail = (d) => d && Object.values(d).some((v) => v && (typeof v !== 'object' || Object.keys(v).length))

onMounted(async () => {
  await Promise.all([loadRequests(), loadAudit()])
  const q = route.query.request_id
  if (q) { auditFilter.value.request_id = q; select({ request_id: q }); loadAudit() }
  else if (requests.value.length) select(requests.value[0])
})
watch(userFilter, loadRequests)
</script>

<template>
  <div class="stack">
    <div class="two-col">
      <el-card>
        <template #header>
          <div class="card-title">Requests
            <el-select v-model="userFilter" clearable placeholder="All users" size="small" style="width: 140px">
              <el-option v-for="u in state.users" :key="u.id" :value="u.id" :label="u.display_name" />
            </el-select>
          </div>
        </template>
        <el-table :data="requests" size="small" highlight-current-row @current-change="select" max-height="640" empty-text="No requests yet">
          <el-table-column label="Request" min-width="150"><template #default="{ row }"><span class="mono">{{ row.request_id }}</span></template></el-table-column>
          <el-table-column label="User" prop="user_id" width="80" />
          <el-table-column label="Started" width="130"><template #default="{ row }">{{ fmtDate(row.started_at) }}</template></el-table-column>
          <el-table-column label="#" prop="records" width="45" />
        </el-table>
      </el-card>

      <el-card v-loading="loadingReplay">
        <template #header>
          <div class="card-title">
            Replay <span class="mono sub" v-if="selected">{{ selected }}</span>
            <span class="sub" v-if="replay">{{ replay.trace.length }} trace · {{ replay.audit.length }} audit · {{ replay.cases.length }} case(s) · {{ replay.conflicts.length }} conflict(s)</span>
          </div>
        </template>
        <el-empty v-if="!replay" description="Select a request to replay its full chain" :image-size="70" />
        <template v-else>
          <div class="row small" style="margin-bottom: 10px">
            <el-tag size="small" type="info">trace step</el-tag>
            <el-tag size="small" type="primary" effect="plain">audit record</el-tag>
            <el-tag size="small" type="warning" effect="plain">review decision</el-tag>
            <span class="muted">· colours = agent · trace steps in execution order; audit records and decisions are placed after the step that produced them</span>
          </div>
          <el-timeline>
            <el-timeline-item v-for="(it, i) in timeline" :key="i" :color="agentColor(it.agent)" :timestamp="it.type === 'trace' ? `step ${it.seq}` : fmtTime(it.at)" placement="top" :hollow="it.type !== 'trace'">
              <div class="replay-item">
                <div class="head">
                  <span class="agent-chip" :style="{ background: agentColor(it.agent) }">{{ it.agent }}</span>
                  <el-tag v-if="it.type === 'audit'" size="small" type="primary" effect="plain">audit</el-tag>
                  <el-tag v-else-if="it.type === 'decision'" size="small" type="warning" effect="plain">decision</el-tag>
                  <code class="step-name">{{ it.title }}</code>
                  <el-tag v-if="it.type === 'trace' && it.llm" type="warning" size="small" effect="dark">LLM draft<template v-if="it.model"> · {{ it.model }}</template></el-tag>
                  <el-tag v-else-if="it.type === 'trace'" type="info" size="small">Rule</el-tag>
                  <ReviewBadge v-if="it.decision" :review="{ ...it.decision, repair_count: 0 }" />
                </div>
                <div v-if="it.text" class="trace-summary">{{ it.text }}</div>
                <div v-if="it.decision" class="trace-summary">{{ it.decision.rationale }}</div>
                <el-button v-if="hasDetail(it.detail)" link type="primary" size="small" @click="openDetail[i] = !openDetail[i]">{{ openDetail[i] ? 'Hide detail' : 'Show detail' }}</el-button>
                <pre v-if="openDetail[i]" class="json">{{ JSON.stringify(it.detail, null, 2) }}</pre>
              </div>
            </el-timeline-item>
          </el-timeline>

          <el-divider content-position="left">Review cases in this request</el-divider>
          <el-table :data="replay.cases" size="small" empty-text="No review case (no personalised candidate in this request)">
            <el-table-column label="Kind" width="170"><template #default="{ row }">{{ kindLabel(row.kind) }}</template></el-table-column>
            <el-table-column label="Candidate" width="90"><template #default="{ row }">v{{ row.candidate_version }}</template></el-table-column>
            <el-table-column label="State" prop="state" width="120" />
            <el-table-column label="Repairs" prop="repair_count" width="80" />
            <el-table-column label="Decisions" min-width="200">
              <template #default="{ row }">
                <span v-for="d in row.decisions" :key="d.id" style="margin-right: 8px">
                  <el-tag size="small" :type="DECISION_TAG[d.decision] || 'info'">{{ d.decision }}</el-tag>
                  <el-tag size="small" :type="RISK_TAG[d.risk_level] || 'info'" effect="plain">R={{ d.risk_score }}</el-tag>
                </span>
              </template>
            </el-table-column>
          </el-table>

          <el-divider content-position="left">Conflicts (UC09 reconciliation)</el-divider>
          <el-table :data="replay.conflicts" size="small" empty-text="No conflicts recorded">
            <el-table-column label="Round" prop="round" width="70" />
            <el-table-column label="Type" prop="type" width="120" />
            <el-table-column label="Responsible agent" prop="responsible_agent" width="150" />
            <el-table-column label="Description" prop="description" min-width="250" />
            <el-table-column label="Resolved" width="90"><template #default="{ row }"><el-tag size="small" :type="row.resolved ? 'success' : 'danger'">{{ row.resolved ? 'yes' : 'no' }}</el-tag></template></el-table-column>
          </el-table>
        </template>
      </el-card>
    </div>

    <el-card>
      <template #header>
        <div class="card-title">Raw audit log
          <span class="row">
            <el-input v-model="auditFilter.request_id" placeholder="request_id" size="small" clearable style="width: 180px" @change="loadAudit" />
            <el-select v-model="auditFilter.user_id" clearable placeholder="user" size="small" style="width: 130px" @change="loadAudit">
              <el-option v-for="u in state.users" :key="u.id" :value="u.id" :label="u.display_name" />
            </el-select>
            <el-button size="small" :icon="'Refresh'" @click="loadAudit" />
          </span>
        </div>
      </template>
      <el-table :data="auditRows" size="small" max-height="420" empty-text="No audit records">
        <el-table-column label="Timestamp" width="190"><template #default="{ row }">{{ fmtDate(row.timestamp) }} <span class="muted small">{{ fmtTime(row.timestamp).slice(-4) }}</span></template></el-table-column>
        <el-table-column label="Request" width="150"><template #default="{ row }"><el-button link type="primary" size="small" class="mono" @click="select({ request_id: row.request_id })">{{ row.request_id }}</el-button></template></el-table-column>
        <el-table-column label="User" prop="user_id" width="80" />
        <el-table-column label="Actor" width="140"><template #default="{ row }"><span :style="{ color: agentColor(row.actor), fontWeight: 600 }">{{ row.actor }}</span></template></el-table-column>
        <el-table-column label="Action" prop="action" width="170" />
        <el-table-column label="Decision" prop="decision" width="120" />
        <el-table-column label="Versions" min-width="220"><template #default="{ row }"><span class="mono small">{{ Object.entries(row.versions || {}).map(([k, v]) => `${k}=${v}`).join(' · ') }}</span></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
