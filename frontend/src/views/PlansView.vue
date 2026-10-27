<script setup>
// UC03 diet · UC06 exercise · UC09 integrated daily plan: generate, current released plan, version history.
import { ref, reactive, onMounted, computed } from 'vue'
import { api } from '../store'
import { CANDIDATE_STATUS_TAG, kindLabel, fmtDate } from '../ui'
import ResultPanel from '../components/ResultPanel.vue'
import PlanCard from '../components/PlanCard.vue'

const TABS = [
  { kind: 'diet', label: 'Diet (UC03)', endpoint: '/diet/plans', hint: 'Nutrition Coach drafts meals with the LLM, prices every item against the versioned nutrition table, then the Safety Supervisor reviews.' },
  { kind: 'exercise', label: 'Exercise (UC06)', endpoint: '/exercise/plans', hint: 'Requires a readiness result from today (UC05). Fitness Coach drafts within your limits; readiness and hard rules bound intensity.' },
  { kind: 'integrated', label: 'Daily plan (UC09)', endpoint: '/daily-plan', hint: 'Both coaches produce candidates; the Orchestrator reconciles timing, recovery, workload and nutrition conflicts before one review.' },
]
const tab = ref('diet')
const busy = ref(false)
const results = reactive({ diet: null, exercise: null, integrated: null })
const current = reactive({ diet: null, exercise: null, integrated: null })
const versions = reactive({ diet: [], exercise: [], integrated: [] })
const req = reactive({ notes: '', budget_level: null })
const tableRefs = {}

const active = computed(() => TABS.find((t) => t.kind === tab.value))

async function refresh() {
  await Promise.all(TABS.map(async ({ kind }) => {
    const [{ data: cur }, { data: vers }] = await Promise.all([api.get(`/plans/${kind}/current`), api.get(`/plans/${kind}/versions`)])
    current[kind] = cur.plan
    versions[kind] = [...vers].sort((a, b) => b.version - a.version)
  }))
}
async function generate() {
  busy.value = true
  try {
    const kind = tab.value
    const body = kind === 'integrated' ? {} : { notes: req.notes || null }
    if (kind === 'diet' && req.budget_level) body.budget_level = req.budget_level
    results[kind] = (await api.post(active.value.endpoint, body)).data
    await refresh() // an integrated release also releases its diet/exercise components
  } finally { busy.value = false }
}
function openVersion(kind, candidateId) {
  const row = versions[kind].find((v) => v.candidate_id === candidateId)
  if (row && tableRefs[kind]) tableRefs[kind].toggleRowExpansion(row, true)
}
onMounted(refresh)
</script>

<template>
  <el-tabs v-model="tab" type="border-card">
    <el-tab-pane v-for="t in TABS" :key="t.kind" :label="t.label" :name="t.kind">
      <div class="stack">
        <div>
          <div class="muted small" style="margin-bottom: 10px">{{ t.hint }}</div>
          <div class="row" style="align-items: stretch">
            <el-input v-if="t.kind !== 'integrated'" v-model="req.notes" placeholder="Optional notes for the coach (e.g. 'push me harder', 'I love satay sauce')" style="flex: 1" />
            <el-select v-if="t.kind === 'diet'" v-model="req.budget_level" clearable placeholder="Budget (profile default)" style="width: 200px">
              <el-option value="low" label="Low budget" /><el-option value="medium" label="Medium budget" /><el-option value="high" label="High budget" />
            </el-select>
            <el-button type="primary" :loading="busy && tab === t.kind" @click="generate">Generate {{ kindLabel(t.kind).toLowerCase() }}</el-button>
          </div>
          <ResultPanel :result="results[t.kind]">
            <el-card v-if="results[t.kind]?.status === 'released' && results[t.kind]?.content" shadow="never" style="margin-top: 10px">
              <PlanCard :plan="results[t.kind].content" />
            </el-card>
          </ResultPanel>
        </div>

        <el-card shadow="never">
          <template #header><div class="card-title">Current released {{ kindLabel(t.kind).toLowerCase() }} <span class="sub" v-if="current[t.kind]">v{{ current[t.kind].version }} · {{ current[t.kind].plan_date }}</span></div></template>
          <PlanCard v-if="current[t.kind]" :plan="current[t.kind]" />
          <el-empty v-else :description="`No released ${kindLabel(t.kind).toLowerCase()} yet`" :image-size="70" />
        </el-card>

        <el-card shadow="never">
          <template #header><div class="card-title">Version history <span class="sub">{{ versions[t.kind].length }} version(s) — superseded and withheld candidates stay on record</span></div></template>
          <el-table :ref="(el) => (tableRefs[t.kind] = el)" :data="versions[t.kind]" size="small" row-key="candidate_id" empty-text="No versions yet">
            <el-table-column type="expand"><template #default="{ row }"><div style="padding: 8px 16px 12px 48px"><PlanCard :plan="row" /></div></template></el-table-column>
            <el-table-column label="v" prop="version" width="50" />
            <el-table-column label="Status" width="140"><template #default="{ row }"><el-tag size="small" :type="CANDIDATE_STATUS_TAG[row.status] || 'info'">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column label="Plan date" prop="plan_date" width="110" />
            <el-table-column label="Created" width="170"><template #default="{ row }">{{ fmtDate(row.created_at) }}</template></el-table-column>
            <el-table-column label="Repairs" prop="repair_count" width="80" />
            <el-table-column label="Change explanation" min-width="220"><template #default="{ row }"><span class="small">{{ row.change_explanation || '—' }}</span></template></el-table-column>
            <el-table-column label="Previous version" width="170">
              <template #default="{ row }">
                <el-button v-if="row.previous_version_id" link type="primary" size="small" @click="openVersion(t.kind, row.previous_version_id)">{{ row.previous_version_id }}</el-button>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </el-tab-pane>
  </el-tabs>
</template>
