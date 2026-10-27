<script setup>
// Meal analysis result (UC02): items with portion evidence, nutrient estimate, uncertainty, confidence, safety flags.
import { computed } from 'vue'
import { CANDIDATE_STATUS_TAG, round, pct, fmtDate } from '../ui'

const props = defineProps({ entry: { type: Object, required: true } })
const est = computed(() => props.entry.nutrient_estimate || {})
const range = computed(() => props.entry.uncertainty_range || {})
const confidence = computed(() => pct(props.entry.confidence))
const confColor = computed(() => (confidence.value >= 70 ? '#67c23a' : confidence.value >= 50 ? '#e6a23c' : '#f56c6c'))
const ENTRY_TAG = { ...CANDIDATE_STATUS_TAG, AwaitingClarification: 'primary', RecordedUnestimated: 'info', PendingReview: 'warning' }
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 8px">
      <el-tag :type="ENTRY_TAG[entry.status] || 'info'" size="small">{{ entry.status }}</el-tag>
      <span><b>“{{ entry.raw_input }}”</b></span>
      <span class="muted small" v-if="entry.submitted_at">{{ fmtDate(entry.submitted_at) }}</span>
      <span class="muted small" v-if="entry.data_version">· data {{ entry.data_version }}</span>
      <span class="muted small" v-if="entry.model_version">· draft by {{ entry.model_version }}</span>
    </div>

    <div v-if="(entry.safety_flags || []).length" class="row" style="margin-bottom: 8px">
      <el-tag v-for="f in entry.safety_flags" :key="f" type="danger" effect="dark" size="small">{{ f }}</el-tag>
    </div>

    <el-table v-if="(entry.items || []).length" :data="entry.items" size="small" style="margin-bottom: 10px">
      <el-table-column label="Item" min-width="150">
        <template #default="{ row }">{{ row.name }}<div v-if="row.matched_food && row.matched_food !== row.name" class="muted small">matched: {{ row.matched_food }}</div></template>
      </el-table-column>
      <el-table-column label="Portion" min-width="110">
        <template #default="{ row }">{{ row.portion_description || '—' }}</template>
      </el-table-column>
      <el-table-column label="Grams (range)" width="130">
        <template #default="{ row }">{{ round(row.grams) }} <span class="muted small" v-if="row.grams_low != null">({{ round(row.grams_low) }}–{{ round(row.grams_high) }})</span></template>
      </el-table-column>
      <el-table-column label="Evidence" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.portion_evidence === 'stated' ? 'success' : row.portion_evidence === 'inferred' ? 'warning' : 'info'">{{ row.portion_evidence }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="kcal" width="70"><template #default="{ row }">{{ round(row.kcal) }}</template></el-table-column>
      <el-table-column label="Verified" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.verified" size="small" type="success">verified</el-tag>
          <el-tag v-else size="small" type="warning">unverified</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Allergens" min-width="100">
        <template #default="{ row }"><el-tag v-for="a in row.allergens || []" :key="a" size="small" type="danger" effect="plain" style="margin-right: 4px">{{ a }}</el-tag></template>
      </el-table-column>
    </el-table>

    <div class="stats" v-if="est.kcal != null">
      <el-statistic title="Energy" :value="Math.round(est.kcal)" suffix="kcal" />
      <el-statistic title="Protein" :value="Math.round(est.protein_g || 0)" suffix="g" />
      <el-statistic title="Carbs" :value="Math.round(est.carbs_g || 0)" suffix="g" />
      <el-statistic title="Fat" :value="Math.round(est.fat_g || 0)" suffix="g" />
      <div v-if="range.kcal_low != null">
        <div class="muted small">Likely range</div>
        <div style="font-size: 20px; font-weight: 600">{{ round(range.kcal_low) }}–{{ round(range.kcal_high) }} <span class="small muted">kcal</span></div>
      </div>
    </div>

    <div v-if="entry.confidence != null" style="margin: 8px 0">
      <div class="muted small">Confidence {{ confidence }}%</div>
      <el-progress :percentage="confidence" :color="confColor" :stroke-width="10" />
      <div class="small" style="margin-top: 4px">{{ entry.confidence_basis }}</div>
    </div>

    <div v-if="(entry.missing_evidence || []).length" class="explain"><b>Missing evidence</b>{{ entry.missing_evidence.join('; ') }}</div>
    <div v-if="(entry.clarifications || []).length" class="explain">
      <b>Clarifications</b>
      <div v-for="(c, i) in entry.clarifications" :key="i">Q: {{ c.question }} <br />A: <b>{{ c.answer }}</b></div>
    </div>
  </div>
</template>
