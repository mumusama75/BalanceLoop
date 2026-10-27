<script setup>
// UC05: readiness check-in → Ready / Reduced / Recovery decided by fixed rules.
import { ref, reactive, onMounted, computed } from 'vue'
import { api } from '../store'
import { READINESS, fmtDate, pct } from '../ui'
import ResultPanel from '../components/ResultPanel.vue'

const form = reactive({ sleep_quality: 4, fatigue: 3, soreness: 2, pain: 0, pain_affects_activity: false, recent_activity: '', available_time_min: 40, free_text: '' })
const busy = ref(false)
const result = ref(null)
const latest = ref(null)
const history = ref({ recorded_activity: [], summary: '', previous: [] })

const assessment = computed(() => result.value?.content?.assessment || latest.value)
const theme = computed(() => READINESS[assessment.value?.result] || { color: '#909399', bg: '#f4f4f5', text: '' })

async function loadLatest() {
  latest.value = (await api.get('/readiness/latest')).data.assessment
  history.value = (await api.get('/readiness/history')).data
}
async function submit() {
  busy.value = true
  try {
    const body = { ...form, recent_activity: form.recent_activity || null, free_text: form.free_text || null }
    result.value = (await api.post('/readiness/checkins', body)).data
    await loadLatest()
  } finally { busy.value = false }
}
onMounted(loadLatest)
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="11">
      <el-card>
        <template #header><div class="card-title">Daily check-in <span class="sub">LLM summarises evidence; fixed rules decide</span></div></template>
        <el-form label-position="top">
          <el-form-item label="Sleep quality (1 = very poor · 5 = excellent)"><el-rate v-model="form.sleep_quality" :max="5" show-score /></el-form-item>
          <el-form-item :label="`Fatigue: ${form.fatigue}/10`"><el-slider v-model="form.fatigue" :min="0" :max="10" show-stops /></el-form-item>
          <el-form-item :label="`Soreness: ${form.soreness}/10`"><el-slider v-model="form.soreness" :min="0" :max="10" show-stops /></el-form-item>
          <el-form-item :label="`Pain: ${form.pain}/10`"><el-slider v-model="form.pain" :min="0" :max="10" show-stops /></el-form-item>
          <el-form-item label="Does the pain affect activity?"><el-switch v-model="form.pain_affects_activity" active-text="Yes" inactive-text="No" /></el-form-item>
          <el-form-item label="Already recorded in the app (last 48 h) — loaded automatically">
            <div class="history-box">
              <template v-if="history.recorded_activity.length">
                <div v-for="(h, i) in history.recorded_activity" :key="i" class="history-row">
                  <span class="muted">{{ h.plan_date }}</span>
                  <b>{{ h.activity }}</b> {{ h.planned_min }} min
                  <el-tag size="small" :type="h.completion === 'completed' ? 'success' : h.completion === 'partial' ? 'warning' : 'info'">{{ h.completion }}</el-tag>
                  <span v-if="h.exertion != null" class="muted">exertion {{ h.exertion }}/10</span>
                  <el-tag v-if="h.pain" size="small" type="danger">pain {{ h.pain }}/10</el-tag>
                  <el-tag v-if="h.progression_hold" size="small" type="danger">progression hold</el-tag>
                </div>
              </template>
              <span v-else class="muted">Nothing recorded in the last 48 h.</span>
            </div>
          </el-form-item>
          <el-form-item label="Other activity today, before this check-in, or anything the app has no record of (optional)">
            <el-input v-model="form.recent_activity" placeholder="e.g. cycled 10 min to work / played football yesterday / none" />
          </el-form-item>
          <el-form-item label="Available time today (min)"><el-input-number v-model="form.available_time_min" :min="0" :max="600" /></el-form-item>
          <el-form-item label="Anything else (optional)"><el-input v-model="form.free_text" type="textarea" :rows="2" placeholder="e.g. knee feels fine, slept badly" /></el-form-item>
          <el-button type="primary" :loading="busy" @click="submit">Submit check-in</el-button>
        </el-form>
        <ResultPanel :result="result" />
      </el-card>
    </el-col>

    <el-col :span="13">
      <el-card>
        <template #header>
          <div class="card-title">
            Readiness result
            <span class="sub" v-if="assessment">{{ result?.content?.assessment ? 'from this check-in' : 'latest on record' }} · {{ fmtDate(assessment.created_at) }}</span>
          </div>
        </template>
        <div v-if="assessment" class="readiness-block" :style="{ background: theme.bg, borderColor: theme.color, color: theme.color }">
          <h2>{{ assessment.result || 'Incomplete' }}</h2>
          <div style="color: #303133">{{ theme.text }}</div>
          <div class="row" style="margin-top: 8px">
            <el-tag size="small" :type="assessment.status === 'Completed' ? 'success' : 'warning'">{{ assessment.status }}</el-tag>
            <el-tag size="small" type="info" v-if="assessment.confidence != null">confidence {{ pct(assessment.confidence) }}%</el-tag>
            <el-tag size="small" type="info">{{ assessment.rule_version }}</el-tag>
            <el-tag size="small" type="warning" v-if="assessment.model_version">LLM {{ assessment.model_version }}</el-tag>
            <el-tag size="small" type="info">profile v{{ assessment.profile_version }}</el-tag>
          </div>
        </div>
        <el-empty v-else description="No check-in yet today. Exercise plans need a readiness result first." />

        <template v-if="assessment">
          <div class="explain" style="margin-top: 12px" v-if="(assessment.evidence || []).length">
            <b>Evidence</b>
            <ul class="plain-list"><li v-for="e in assessment.evidence" :key="e">{{ e }}</li></ul>
          </div>
          <div class="explain" v-if="(assessment.restrictions || []).length">
            <b>Restrictions applied to today's plan</b>
            <ul class="plain-list"><li v-for="r in assessment.restrictions" :key="r">{{ r }}</li></ul>
          </div>
          <div class="explain" v-if="(assessment.clarification_fields || []).length">
            <b>Missing fields (clarification requested)</b>
            <el-tag v-for="f in assessment.clarification_fields" :key="f" type="primary" size="small" style="margin-right: 4px">{{ f }}</el-tag>
          </div>
        </template>
        <div class="row" style="margin-top: 12px" v-if="assessment?.result">
          <router-link to="/plans"><el-button type="primary" plain>Generate today's exercise plan →</el-button></router-link>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.history-box { width: 100%; background: #f7f8fa; border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; line-height: 1.9; }
.history-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.muted { color: #909399; font-size: 12px; }
</style>
