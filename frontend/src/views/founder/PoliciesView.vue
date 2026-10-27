<script setup>
// Founder: review policies — activate, fail-closed demo, audit-failure flag, edit hard rules.
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, loadHealth } from '../../store'
import { fmtDate } from '../../ui'

const policies = ref([])
const loading = ref(false)
const busy = ref('')

async function load() {
  loading.value = true
  try {
    policies.value = (await api.get('/founder/policies')).data.map((p) => ({ ...p, hard_rules: p.hard_rules.map((r) => ({ ...r })), dirty: false }))
  } finally { loading.value = false; loadHealth() }
}
async function activate(p) {
  busy.value = 'activate' + p.version
  try { await api.post(`/founder/policies/${p.version}/activate`); ElMessage.success(`Policy v${p.version} is now active`); await load() } finally { busy.value = '' }
}
async function deactivateAll() {
  await ElMessageBox.confirm('With no active policy every review fails closed: users only receive the bounded non-personalised reply. Continue?', 'Deactivate all policies', { type: 'warning', confirmButtonText: 'Deactivate all' })
  await api.post('/founder/policies/deactivate-all')
  ElMessage.warning('No active policy — reviews now fail closed')
  await load()
}
async function setFlag(p, value) {
  busy.value = 'flag' + p.version
  try {
    await api.post(`/founder/policies/${p.version}/flags`, { simulate_audit_failure: value })
    ElMessage.info(value ? 'Audit store writes will now fail: nothing can be released (UC10 6a)' : 'Audit failure simulation cleared')
    await load()
  } finally { busy.value = '' }
}
async function saveRules(p) {
  busy.value = 'save' + p.version
  try {
    await api.post('/founder/policies', {
      version: p.version, hard_rules: p.hard_rules, risk_thresholds: p.risk_thresholds, max_repairs: p.max_repairs, notes: p.notes, activate: p.active,
    })
    ElMessage.success(`Policy v${p.version} saved`)
    await load()
  } finally { busy.value = '' }
}
const thresholdEntries = (p) => Object.entries(p.risk_thresholds || {}).filter(([k]) => k !== 'simulate_audit_failure')
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="stack">
    <el-alert type="info" show-icon :closable="false" title="The Safety Supervisor loads exactly one active policy per review. If none is active, or its version does not match the required version, the review fails closed and the user gets a bounded safe reply." />
    <div class="row" style="justify-content: flex-end">
      <el-button type="danger" plain @click="deactivateAll">Deactivate all (demo fail-closed)</el-button>
    </div>
    <el-card v-for="p in policies" :key="p.id">
      <template #header>
        <div class="card-title">
          <span class="row">
            Policy v{{ p.version }}
            <el-tag v-if="p.active" type="success" size="small" effect="dark">ACTIVE</el-tag>
            <el-tag v-else type="info" size="small">inactive</el-tag>
            <el-tag v-if="p.risk_thresholds?.simulate_audit_failure" type="danger" size="small">audit failure simulated</el-tag>
            <span class="sub">max repairs {{ p.max_repairs }} · created {{ fmtDate(p.created_at) }}</span>
          </span>
          <span class="row">
            <el-button size="small" type="success" :disabled="p.active" :loading="busy === 'activate' + p.version" @click="activate(p)">Activate</el-button>
            <el-button size="small" type="primary" :disabled="!p.dirty" :loading="busy === 'save' + p.version" @click="saveRules(p)">Save rules</el-button>
          </span>
        </div>
      </template>
      <div class="muted small" v-if="p.notes" style="margin-bottom: 10px">{{ p.notes }}</div>
      <el-row :gutter="16">
        <el-col :span="16">
          <el-table :data="p.hard_rules" size="small">
            <el-table-column label="Rule" prop="id" width="80" />
            <el-table-column label="Description" prop="description" min-width="220" />
            <el-table-column label="Critical" width="90">
              <template #default="{ row }"><el-switch v-model="row.critical" size="small" @change="p.dirty = true" /></template>
            </el-table-column>
            <el-table-column label="Enabled" width="90">
              <template #default="{ row }"><el-switch v-model="row.enabled" size="small" @change="p.dirty = true" /></template>
            </el-table-column>
          </el-table>
          <div class="muted small" style="margin-top: 6px">Critical rules trigger an immediate stop + support notice (CriticalStop); non-critical ones withhold or revise. Saving writes the same version in place.</div>
        </el-col>
        <el-col :span="8">
          <div class="card-title" style="margin-bottom: 6px">Risk thresholds</div>
          <dl class="kv">
            <template v-for="[k, v] in thresholdEntries(p)" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template>
            <dt>max_repairs</dt><dd><el-input-number v-model="p.max_repairs" :min="0" :max="5" size="small" @change="p.dirty = true" /></dd>
          </dl>
          <el-divider />
          <div class="card-title" style="margin-bottom: 6px">Demo flags</div>
          <div class="row" style="justify-content: space-between">
            <span class="small">simulate_audit_failure</span>
            <el-switch :model-value="!!p.risk_thresholds?.simulate_audit_failure" :loading="busy === 'flag' + p.version" @change="(v) => setFlag(p, v)" />
          </div>
          <div class="muted small" style="margin-top: 4px">When on, the audit store refuses writes; the Supervisor then withholds every candidate (no audit record, no release).</div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>
