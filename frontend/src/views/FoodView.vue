<script setup>
// UC02: log a meal, answer clarification questions inline, see today's entries.
import { ref, onMounted, computed } from 'vue'
import { api } from '../store'
import { CANDIDATE_STATUS_TAG, fmtDate, round, pct, todayUtc } from '../ui'
import ResultPanel from '../components/ResultPanel.vue'
import FoodResultCard from '../components/FoodResultCard.vue'

const text = ref('')
const busy = ref(false)
const result = ref(null)
const answer = ref('')
const entries = ref([])
const day = ref(todayUtc())
const rowAnswers = ref({})

const resultEntry = computed(() => result.value?.content?.entry || null)
const pendingId = computed(() => (result.value?.status === 'clarification' ? resultEntry.value?.id || result.value?.extra?.entry_id : null))
const ENTRY_TAG = { ...CANDIDATE_STATUS_TAG, AwaitingClarification: 'primary', RecordedUnestimated: 'info' }

async function loadEntries() {
  entries.value = (await api.get('/food/entries', { params: day.value ? { day: day.value } : {} })).data
}
async function submit() {
  if (!text.value.trim()) return
  busy.value = true
  try {
    result.value = (await api.post('/food/entries', { text: text.value.trim(), input_type: 'text' })).data
    answer.value = ''
    text.value = ''
    await loadEntries()
  } finally { busy.value = false }
}
async function clarify(entryId, ans) {
  if (!ans?.trim()) return
  busy.value = true
  try {
    result.value = (await api.post(`/food/entries/${entryId}/clarify`, { answer: ans.trim() })).data
    answer.value = ''
    rowAnswers.value[entryId] = ''
    await loadEntries()
  } finally { busy.value = false }
}
onMounted(loadEntries)
</script>

<template>
  <div class="stack">
    <el-card>
      <template #header><div class="card-title">Log a meal <span class="sub">text → LLM identifies foods → versioned nutrition table → Safety Supervisor review</span></div></template>
      <div class="row" style="align-items: stretch">
        <el-input v-model="text" placeholder="e.g. 2 boiled eggs and a bowl of rice" @keyup.enter="submit" style="flex: 1" clearable />
        <el-button type="primary" :loading="busy" @click="submit">Analyse</el-button>
      </div>
      <div class="muted small" style="margin-top: 6px">Try: “peanut butter toast” (asks for portions) · “something delicious” (recorded, not estimated).</div>

      <ResultPanel :result="result">
        <el-card v-if="pendingId" shadow="never" style="margin-top: 10px; border-color: #409eff">
          <div class="row" style="align-items: stretch">
            <el-input v-model="answer" :placeholder="result.message" @keyup.enter="clarify(pendingId, answer)" style="flex: 1" />
            <el-button type="primary" :loading="busy" @click="clarify(pendingId, answer)">Answer</el-button>
          </div>
        </el-card>
        <el-card v-else-if="resultEntry" shadow="never" style="margin-top: 10px">
          <FoodResultCard :entry="resultEntry" />
        </el-card>
      </ResultPanel>
    </el-card>

    <el-card>
      <template #header>
        <div class="card-title">
          Entries
          <span class="row">
            <span class="muted small">day (UTC)</span>
            <el-date-picker v-model="day" type="date" value-format="YYYY-MM-DD" placeholder="All days" clearable size="small" @change="loadEntries" />
            <el-button size="small" :icon="'Refresh'" @click="loadEntries" />
          </span>
        </div>
      </template>
      <el-table :data="entries" size="small" empty-text="No entries for this day" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div style="padding: 6px 12px 10px 48px">
              <FoodResultCard :entry="row" />
              <div v-if="row.status === 'AwaitingClarification'" class="row" style="margin-top: 8px; align-items: stretch">
                <el-input v-model="rowAnswers[row.id]" :placeholder="row.clarification_question" style="flex: 1" @keyup.enter="clarify(row.id, rowAnswers[row.id])" />
                <el-button type="primary" size="small" :loading="busy" @click="clarify(row.id, rowAnswers[row.id])">Answer</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="When" width="160"><template #default="{ row }">{{ fmtDate(row.submitted_at) }}</template></el-table-column>
        <el-table-column label="Input" prop="raw_input" min-width="200" />
        <el-table-column label="Status" width="170"><template #default="{ row }"><el-tag size="small" :type="ENTRY_TAG[row.status] || 'info'">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="kcal" width="90"><template #default="{ row }">{{ row.nutrient_estimate?.kcal != null ? round(row.nutrient_estimate.kcal) : '—' }}</template></el-table-column>
        <el-table-column label="Confidence" width="110"><template #default="{ row }">{{ row.confidence != null ? pct(row.confidence) + '%' : '—' }}</template></el-table-column>
        <el-table-column label="Flags" min-width="120"><template #default="{ row }"><el-tag v-for="f in row.safety_flags || []" :key="f" type="danger" size="small" style="margin-right: 4px">{{ f }}</el-tag></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
