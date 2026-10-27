<script setup>
// UC04 diet feedback · UC07 activity feedback · UC08 plan adaptation.
import { ref, reactive, onMounted, computed } from 'vue'
import { api } from '../store'
import { fmtDate } from '../ui'
import ResultPanel from '../components/ResultPanel.vue'
import PlanCard from '../components/PlanCard.vue'

const diet = reactive({ hunger: 5, satiety: 5, cost_issue: false, adherence: 'full', text: '' })
const dietBusy = ref(false)
const dietResult = ref(null)

const plan = ref(null)
const forms = reactive({})
const actBusy = ref('')
const actResults = reactive({})
const history = ref([])

const adaptBusy = ref(false)
const adaptNotes = ref('')
const adaptResult = ref(null)

const activityName = computed(() => Object.fromEntries((plan.value?.activities || []).map((a) => [a.id, a.name])))

async function load() {
  const [{ data: cur }, { data: fb }] = await Promise.all([api.get('/plans/exercise/current'), api.get('/exercise/feedback')])
  plan.value = cur.plan
  history.value = fb
  for (const a of plan.value?.activities || []) {
    if (!forms[a.id]) forms[a.id] = { completion: 'completed', exertion: 5, pain: 0, fatigue: 3, recovery_notes: '' }
  }
}
async function sendDiet() {
  dietBusy.value = true
  try {
    dietResult.value = (await api.post('/diet/feedback', { ...diet, text: diet.text || null })).data
  } finally { dietBusy.value = false }
}
async function sendActivity(id) {
  actBusy.value = id
  try {
    const f = forms[id]
    const body = { completion: f.completion, recovery_notes: f.recovery_notes || null }
    if (f.completion !== 'skipped') Object.assign(body, { exertion: f.exertion, pain: f.pain, fatigue: f.fatigue })
    actResults[id] = (await api.post(`/exercise/activities/${id}/feedback`, body)).data
    history.value = (await api.get('/exercise/feedback')).data
  } finally { actBusy.value = '' }
}
async function adapt() {
  adaptBusy.value = true
  try {
    adaptResult.value = (await api.post('/exercise/plans/adapt', { notes: adaptNotes.value || null })).data
    await load()
  } finally { adaptBusy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="stack">
    <el-card>
      <template #header><div class="card-title">Diet feedback <span class="sub">UC04 · hunger, satiety, cost, adherence → minimal-change revision or safe alternative</span></div></template>
      <div class="row" style="gap: 24px; align-items: flex-end; margin-bottom: 4px">
        <el-form-item :label="`Hunger between meals: ${diet.hunger}/10`" style="flex: 1; min-width: 220px; margin-bottom: 8px"><el-slider v-model="diet.hunger" :min="0" :max="10" show-stops /></el-form-item>
        <el-form-item :label="`Satiety after meals: ${diet.satiety}/10`" style="flex: 1; min-width: 220px; margin-bottom: 8px"><el-slider v-model="diet.satiety" :min="0" :max="10" show-stops /></el-form-item>
        <el-form-item label="Cost was a problem" style="margin-bottom: 8px"><el-switch v-model="diet.cost_issue" /></el-form-item>
        <el-form-item label="Adherence" style="margin-bottom: 8px">
          <el-select v-model="diet.adherence" style="width: 160px"><el-option value="full" label="Followed fully" /><el-option value="partial" label="Partially" /><el-option value="missed" label="Missed" /></el-select>
        </el-form-item>
      </div>
      <div class="row" style="align-items: stretch">
        <el-input v-model="diet.text" placeholder="In your words, e.g. 'I was really hungry by 11am' (punitive requests like skipping meals are refused by rule HR-04)" style="flex: 1" />
        <el-button type="primary" :loading="dietBusy" @click="sendDiet">Send diet feedback</el-button>
      </div>
      <ResultPanel :result="dietResult">
        <el-card v-if="dietResult?.status === 'released' && dietResult?.content?.kind" shadow="never" style="margin-top: 10px"><PlanCard :plan="dietResult.content" /></el-card>
      </ResultPanel>
    </el-card>

    <el-card>
      <template #header>
        <div class="card-title">
          Activity feedback <span class="sub">UC07 · per planned activity of the current released exercise plan<template v-if="plan"> (v{{ plan.version }}, {{ plan.plan_date }})</template></span>
        </div>
      </template>
      <el-empty v-if="!plan" description="No released exercise plan yet — generate one on the Plans page." :image-size="70" />
      <div v-for="a in plan?.activities || []" :key="a.id" class="activity-card" style="margin-bottom: 12px">
        <div class="name"><span>{{ a.name }} <span class="muted small">· planned {{ a.duration_min }} min · {{ a.intensity }}</span></span><el-tag v-if="a.paused" size="small" type="info">paused</el-tag></div>
        <el-row :gutter="16" align="middle">
          <el-col :span="4">
            <el-select v-model="forms[a.id].completion" size="small"><el-option value="completed" label="Completed" /><el-option value="partial" label="Partial" /><el-option value="skipped" label="Skipped" /></el-select>
          </el-col>
          <el-col :span="4"><div class="small muted">Exertion {{ forms[a.id].exertion }}/10</div><el-slider v-model="forms[a.id].exertion" :min="0" :max="10" size="small" :disabled="forms[a.id].completion === 'skipped'" /></el-col>
          <el-col :span="4"><div class="small muted">Pain {{ forms[a.id].pain }}/10</div><el-slider v-model="forms[a.id].pain" :min="0" :max="10" size="small" :disabled="forms[a.id].completion === 'skipped'" /></el-col>
          <el-col :span="4"><div class="small muted">Fatigue {{ forms[a.id].fatigue }}/10</div><el-slider v-model="forms[a.id].fatigue" :min="0" :max="10" size="small" :disabled="forms[a.id].completion === 'skipped'" /></el-col>
          <el-col :span="6"><el-input v-model="forms[a.id].recovery_notes" size="small" placeholder="Recovery notes (interpreted by LLM, red flags checked by rule)" /></el-col>
          <el-col :span="2"><el-button type="primary" size="small" :loading="actBusy === a.id" @click="sendActivity(a.id)">Send</el-button></el-col>
        </el-row>
        <ResultPanel :result="actResults[a.id]">
          <el-alert v-if="actResults[a.id]?.content?.feedback?.progression_hold" type="warning" show-icon :closable="false" style="margin-top: 8px" title="Progression on hold"
            :description="`Progression of this activity is paused because of pain / warning signs: ${(actResults[a.id].content.feedback.warning_signs || []).join('; ') || 'pain threshold reached'}.`" />
        </ResultPanel>
      </div>

      <el-divider v-if="history.length" content-position="left">Feedback history for this plan</el-divider>
      <el-table v-if="history.length" :data="history" size="small">
        <el-table-column label="When" width="160"><template #default="{ row }">{{ fmtDate(row.created_at) }}</template></el-table-column>
        <el-table-column label="Activity" min-width="160"><template #default="{ row }">{{ activityName[row.activity_item_id] || row.activity_item_id }}</template></el-table-column>
        <el-table-column label="Completion" prop="completion" width="110" />
        <el-table-column label="Exertion / Pain / Fatigue" width="180"><template #default="{ row }">{{ row.exertion ?? '—' }} / {{ row.pain ?? '—' }} / {{ row.fatigue ?? '—' }}</template></el-table-column>
        <el-table-column label="Warning signs" min-width="160"><template #default="{ row }"><el-tag v-for="w in row.warning_signs || []" :key="w" type="danger" size="small" style="margin: 0 4px 2px 0">{{ w }}</el-tag><span v-if="!(row.warning_signs || []).length" class="muted">—</span></template></el-table-column>
        <el-table-column label="Progression" width="120"><template #default="{ row }"><el-tag v-if="row.progression_hold" type="warning" size="small">on hold</el-tag><span v-else class="muted">normal</span></template></el-table-column>
        <el-table-column label="Status" width="100"><template #default="{ row }"><el-tag size="small" :type="row.status === 'Flagged' ? 'danger' : 'success'">{{ row.status }}</el-tag></template></el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><div class="card-title">Adapt my exercise plan <span class="sub">UC08 · Maintain / Reduce / Replace / Pause per activity, load-checked by rule, then reviewed again</span></div></template>
      <div class="row" style="align-items: stretch">
        <el-input v-model="adaptNotes" placeholder="Optional notes, e.g. 'knee was sore after the walk'" style="flex: 1" />
        <el-button type="warning" :loading="adaptBusy" :disabled="!plan" @click="adapt">Adapt my exercise plan</el-button>
      </div>
      <ResultPanel :result="adaptResult">
        <el-card v-if="adaptResult?.status === 'released' && adaptResult?.content?.kind" shadow="never" style="margin-top: 10px"><PlanCard :plan="adaptResult.content" /></el-card>
      </ResultPanel>
    </el-card>
  </div>
</template>
