<script setup>
// UC10 review cases: the user's own (/reviews) or every user's (founder: /founder/cases).
import { ref, onMounted } from 'vue'
import { api } from '../store'
import { kindLabel, CASE_STATE_TAG, CANDIDATE_STATUS_TAG, fmtDate } from '../ui'
import ReviewBadge from '../components/ReviewBadge.vue'

const props = defineProps({ founder: { type: Boolean, default: false } })
const cases = ref([])
const loading = ref(false)
const last = (c) => (c.decisions?.length ? c.decisions[c.decisions.length - 1] : null)

async function load() {
  loading.value = true
  try { cases.value = (await api.get(props.founder ? '/founder/cases' : '/review/cases')).data } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="card-title">
        {{ founder ? 'All review cases' : 'My review cases' }}
        <span class="row"><span class="sub">{{ cases.length }} case(s) · every personalised candidate passes through exactly one case</span><el-button size="small" :icon="'Refresh'" @click="load" /></span>
      </div>
    </template>
    <el-table :data="cases" size="small" row-key="id" empty-text="No review cases yet">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div style="padding: 6px 16px 10px 48px">
            <div class="muted small" style="margin-bottom: 6px">case {{ row.id }} · request {{ row.request_id }} · candidate {{ row.candidate_id }} · opened {{ fmtDate(row.created_at) }}<span v-if="row.closed_at"> · closed {{ fmtDate(row.closed_at) }}</span></div>
            <el-timeline>
              <el-timeline-item v-for="d in row.decisions" :key="d.id" :timestamp="fmtDate(d.created_at)" placement="top" :type="d.decision === 'Approve' ? 'success' : d.decision === 'ReviseAndReview' ? 'warning' : 'danger'">
                <div class="row">
                  <span>candidate v{{ d.candidate_version }}</span>
                  <ReviewBadge :review="{ ...d, repair_count: 0 }" />
                  <span class="muted small">policy v{{ d.policy_version }}</span>
                </div>
                <div class="small" style="margin-top: 4px">{{ d.rationale }}</div>
                <div v-if="d.revision_instructions?.instructions?.length" class="explain" style="margin-top: 6px">
                  <b>Rule-linked revision instructions</b>
                  <ul class="plain-list"><li v-for="(ins, i) in d.revision_instructions.instructions" :key="i">{{ ins }}</li></ul>
                </div>
                <div v-if="(d.triggered_rules || []).length" class="small" style="margin-top: 4px">Hard rules: <el-tag v-for="r in d.triggered_rules" :key="r" size="small" type="danger">{{ r }}</el-tag></div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </template>
      </el-table-column>
      <el-table-column v-if="founder" label="User" prop="user_id" width="90" />
      <el-table-column label="Kind" width="170"><template #default="{ row }">{{ kindLabel(row.kind) }}</template></el-table-column>
      <el-table-column label="Candidate" width="90"><template #default="{ row }">v{{ row.candidate_version }}</template></el-table-column>
      <el-table-column label="State" width="130"><template #default="{ row }"><el-tag size="small" :type="CASE_STATE_TAG[row.state] || 'info'">{{ row.state }}</el-tag></template></el-table-column>
      <el-table-column label="Repairs" prop="repair_count" width="80" />
      <el-table-column label="Final status" width="120"><template #default="{ row }"><el-tag v-if="row.final_status" size="small" :type="CANDIDATE_STATUS_TAG[row.final_status] || 'info'">{{ row.final_status }}</el-tag><span v-else class="muted">—</span></template></el-table-column>
      <el-table-column label="Last decision · risk" min-width="260"><template #default="{ row }"><ReviewBadge v-if="last(row)" :review="{ ...last(row), repair_count: row.repair_count }" /><span v-else class="muted">—</span></template></el-table-column>
      <el-table-column label="Opened" width="160"><template #default="{ row }">{{ fmtDate(row.created_at) }}</template></el-table-column>
    </el-table>
  </el-card>
</template>
