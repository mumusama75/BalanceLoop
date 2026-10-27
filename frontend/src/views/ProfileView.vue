<script setup>
// UC01: profile form, consent panel, save result, version history.
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../store'
import { PROFILE_STATUS_TAG, fmtDate } from '../ui'
import ResultPanel from '../components/ResultPanel.vue'

const loading = ref(false)
const saving = ref(false)
const profile = ref(null)
const consents = reactive({ core: false, O1: false, O2: false })
const versions = ref([])
const saveResult = ref(null)
const consentMessage = ref('')

const form = reactive({
  goals: [], dietary_preferences: [], allergy_status: 'unknown', allergies: [], physical_limits: [],
  available_time_min: null, equipment: [], budget_level: null, cultural_preferences: '', schedule_notes: '',
  cooking_skill: null, free_text: '', confirm: true,
})

const CONSENTS = [
  { scope: 'core', title: 'Core processing (required)', text: 'Process your profile, meals, check-ins and feedback to produce reviewed suggestions. Withdrawing stops every personalised function immediately.' },
  { scope: 'O1', title: 'O1 · Adaptive calorie disclosure (optional)', text: 'Show adaptive energy targets and calorie figures. Off by default; core functions work without it.' },
  { scope: 'O2', title: 'O2 · Wearable data import (optional)', text: 'Allow importing activity data from a wearable device (not exercised in this prototype).' },
]

function fill(p) {
  if (!p) return
  for (const k of ['goals', 'dietary_preferences', 'allergies', 'physical_limits', 'equipment']) form[k] = [...(p[k] || [])]
  form.allergy_status = p.allergy_status || 'unknown'
  form.available_time_min = p.available_time_min
  form.budget_level = p.budget_level
  form.cultural_preferences = p.cultural_preferences || ''
  form.schedule_notes = p.schedule_notes || ''
  form.cooking_skill = p.cooking_skill
}

// "unknown" means no allergy information: drop any tags typed under another status.
watch(() => form.allergy_status, (v) => { if (v === 'unknown') form.allergies = [] })

async function load() {
  loading.value = true
  try {
    const [{ data: cur }, { data: vers }] = await Promise.all([api.get('/profile'), api.get('/profile/versions')])
    profile.value = cur.profile
    Object.assign(consents, cur.consents || {})
    versions.value = vers
    fill(cur.profile)
  } finally { loading.value = false }
}

async function save() {
  saving.value = true
  try {
    const body = { ...form }
    for (const k of ['cultural_preferences', 'schedule_notes', 'free_text']) if (!body[k]) body[k] = null
    const { data } = await api.post('/profile', body)
    // Not an OperationResult, so build the envelope ResultPanel expects.
    saveResult.value = {
      request_id: null,
      status: data.saved ? (data.status === 'Incomplete' ? 'clarification' : 'info') : 'warning',
      message: data.message, trace: data.trace || [], extra: { fields: data.conflicts || [], missing: data.missing_fields || [] },
      label: data.saved ? `Saved v${data.version} · ${data.status}` : `${data.status} — not saved`,
    }
    if (data.saved) ElMessage.success(`Profile v${data.version} saved (${data.status})`)
    else ElMessage.warning('Profile not saved — see the conflicts below')
    await load()
  } finally { saving.value = false }
}

async function setConsent(scope, granted) {
  const { data } = await api.post('/consent', { scope, granted })
  Object.assign(consents, data.consents || {})
  consentMessage.value = data.message
  await load()
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="stack">
    <el-row :gutter="16">
      <el-col :span="15">
        <el-card>
          <template #header>
            <div class="card-title">
              Profile
              <span class="sub" v-if="profile">v{{ profile.version }} · <el-tag size="small" :type="PROFILE_STATUS_TAG[profile.status] || 'info'">{{ profile.status }}</el-tag> · saved {{ fmtDate(profile.saved_at) }}</span>
              <span class="sub" v-else>No profile yet — fill in the form to create version 1</span>
            </div>
          </template>
          <el-alert v-if="profile?.missing_fields?.length" type="warning" show-icon :closable="false" style="margin-bottom: 12px" title="Missing safety fields">
            <ul class="plain-list"><li v-for="m in profile.missing_fields" :key="m">{{ m }}</li></ul>
          </el-alert>
          <el-form label-position="top" size="default">
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="Goals"><el-input-tag v-model="form.goals" placeholder="Type a goal and press Enter" clearable /></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Dietary preferences"><el-input-tag v-model="form.dietary_preferences" placeholder="e.g. pescatarian, no pork" clearable /></el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="Allergy status">
              <el-radio-group v-model="form.allergy_status">
                <el-radio-button value="none">None (confirmed)</el-radio-button>
                <el-radio-button value="known">Known allergies</el-radio-button>
                <el-radio-button value="unknown">Unknown / not answered</el-radio-button>
              </el-radio-group>
              <div class="muted small" style="width: 100%; margin-top: 4px">“Unknown” is never treated as “no allergies”: personalised dietary planning stays restricted until it is answered.</div>
            </el-form-item>
            <el-form-item label="Allergies" v-if="form.allergy_status !== 'unknown'">
              <el-input-tag v-model="form.allergies" placeholder="e.g. peanuts, milk" clearable tag-type="danger" />
            </el-form-item>
            <el-form-item label="Physical limits"><el-input-tag v-model="form.physical_limits" placeholder="e.g. mild knee discomfort on stairs" clearable /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="8"><el-form-item label="Available time per day (min)"><el-input-number v-model="form.available_time_min" :min="0" :max="600" style="width: 100%" /></el-form-item></el-col>
              <el-col :span="8">
                <el-form-item label="Budget level">
                  <el-select v-model="form.budget_level" clearable placeholder="—"><el-option value="low" label="Low" /><el-option value="medium" label="Medium" /><el-option value="high" label="High" /></el-select>
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="Cooking skill">
                  <el-select v-model="form.cooking_skill" clearable placeholder="—"><el-option value="beginner" label="Beginner" /><el-option value="intermediate" label="Intermediate" /><el-option value="advanced" label="Advanced" /></el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="Equipment"><el-input-tag v-model="form.equipment" placeholder="e.g. resistance band, yoga mat" clearable /></el-form-item>
            <el-row :gutter="12">
              <el-col :span="12"><el-form-item label="Cultural preferences"><el-input v-model="form.cultural_preferences" placeholder="e.g. East Asian home cooking" /></el-form-item></el-col>
              <el-col :span="12"><el-form-item label="Schedule notes"><el-input v-model="form.schedule_notes" placeholder="e.g. office hours 9-6, free after 17:30" /></el-form-item></el-col>
            </el-row>
            <el-form-item label="Anything else, in your own words (optional — interpreted by the LLM, then checked by rules)">
              <el-input v-model="form.free_text" type="textarea" :rows="2" placeholder="e.g. I get dizzy if I skip breakfast; my left knee hurts on stairs" />
            </el-form-item>
            <div class="row">
              <el-button type="primary" :loading="saving" @click="save">Save as new version</el-button>
              <el-checkbox v-model="form.confirm">I confirm these changes</el-checkbox>
            </div>
          </el-form>
          <ResultPanel :result="saveResult" :label="saveResult?.label" />
        </el-card>
      </el-col>

      <el-col :span="9">
        <el-card>
          <template #header><div class="card-title">Consent <span class="sub">UC01 · purposes</span></div></template>
          <div v-for="c in CONSENTS" :key="c.scope" style="margin-bottom: 14px">
            <div class="row" style="justify-content: space-between">
              <b>{{ c.title }}</b>
              <el-switch :model-value="consents[c.scope]" @change="(v) => setConsent(c.scope, v)" />
            </div>
            <div class="muted small" style="line-height: 1.5">{{ c.text }}</div>
          </div>
          <el-alert v-if="consentMessage" type="info" :closable="false" :title="consentMessage" />
          <el-alert v-if="!consents.core" type="error" :closable="false" show-icon title="Core consent is not active" description="Every personalised function (meals, plans, feedback) is blocked until core consent is granted." style="margin-top: 8px" />
        </el-card>

        <el-card>
          <template #header><div class="card-title">Current profile summary</div></template>
          <dl class="kv" v-if="profile">
            <dt>Version</dt><dd>{{ profile.version }} <span class="muted small" v-if="profile.previous_version_id">(previous {{ profile.previous_version_id }})</span></dd>
            <dt>Status</dt><dd><el-tag size="small" :type="PROFILE_STATUS_TAG[profile.status] || 'info'">{{ profile.status }}</el-tag></dd>
            <dt>Allergies</dt><dd>{{ profile.allergy_status }}<span v-if="profile.allergies?.length">: {{ profile.allergies.join(', ') }}</span></dd>
            <dt>Limits</dt><dd>{{ profile.physical_limits?.join('; ') || '—' }}</dd>
            <dt>Time</dt><dd>{{ profile.available_time_min ?? '—' }} min</dd>
            <dt>Conflicts</dt><dd>{{ profile.conflicts?.length ? profile.conflicts.join('; ') : 'none' }}</dd>
          </dl>
          <el-empty v-else description="No profile saved yet" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-card>
      <template #header><div class="card-title">Version history <span class="sub">{{ versions.length }} version(s); every save creates a new immutable version</span></div></template>
      <el-table :data="versions" size="small" empty-text="No versions yet">
        <el-table-column label="v" prop="version" width="50" />
        <el-table-column label="Status" width="150"><template #default="{ row }"><el-tag size="small" :type="PROFILE_STATUS_TAG[row.status] || 'info'">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="Saved" width="170"><template #default="{ row }">{{ fmtDate(row.saved_at) }}</template></el-table-column>
        <el-table-column label="Goals"><template #default="{ row }">{{ row.goals.join(', ') || '—' }}</template></el-table-column>
        <el-table-column label="Allergies" width="160"><template #default="{ row }">{{ row.allergy_status }}<span v-if="row.allergies.length">: {{ row.allergies.join(', ') }}</span></template></el-table-column>
        <el-table-column label="Time" width="70"><template #default="{ row }">{{ row.available_time_min ?? '—' }}</template></el-table-column>
        <el-table-column label="Missing fields"><template #default="{ row }"><span class="small">{{ row.missing_fields.join('; ') || '—' }}</span></template></el-table-column>
        <el-table-column label="Previous" width="150"><template #default="{ row }"><span class="mono muted">{{ row.previous_version_id || '—' }}</span></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
