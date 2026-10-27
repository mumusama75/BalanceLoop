<script setup>
// Compact Safety Supervisor decision with a popover explaining R = 2S + U + V + P + B.
import { computed } from 'vue'
import { RISK_TAG, DECISION_TAG, SCORE_PARTS } from '../ui'

const props = defineProps({ review: { type: Object, required: true } })
const bd = computed(() => props.review.score_breakdown || {})
const reasons = computed(() => bd.value.reasons || {})
</script>

<template>
  <el-popover trigger="hover" width="420" placement="bottom-start">
    <template #reference>
      <span class="review-badge">
        <el-tag :type="DECISION_TAG[review.decision] || 'info'" size="small" effect="dark">{{ review.decision || review.state }}</el-tag>
        <el-tag v-if="review.risk_level" :type="RISK_TAG[review.risk_level] || 'info'" size="small">{{ review.risk_level }} risk · R = {{ review.risk_score }}</el-tag>
        <el-tag v-for="r in review.triggered_rules || []" :key="r" type="danger" size="small" effect="plain">{{ r }}</el-tag>
        <span v-if="review.repair_count" class="muted small">repairs: {{ review.repair_count }}</span>
      </span>
    </template>
    <div class="score-pop">
      <div class="formula">{{ bd.formula || 'R = 2S + U + V + P + B' }}</div>
      <table>
        <thead><tr><th></th><th>Component</th><th>Value</th><th>Why</th></tr></thead>
        <tbody>
          <tr v-for="p in SCORE_PARTS" :key="p.key">
            <td><b>{{ p.key }}</b></td>
            <td>{{ p.name }}<div class="muted small">{{ p.range }}</div></td>
            <td class="val">{{ bd[p.key] ?? '—' }}</td>
            <td>
              <span v-if="(reasons[p.key] || []).length">{{ reasons[p.key].join('; ') }}</span>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top: 8px"><b>R = {{ bd.R ?? review.risk_score ?? '—' }}</b> → {{ review.risk_level || '—' }} risk → decision <b>{{ review.decision || '—' }}</b></div>
      <div v-if="(review.triggered_rules || []).length" style="margin-top: 4px">Hard rules triggered: <b>{{ review.triggered_rules.join(', ') }}</b> (hard rules override the score)</div>
      <div v-if="review.rationale" class="small" style="margin-top: 4px">{{ review.rationale }}</div>
      <div class="muted small" style="margin-top: 6px">
        <span v-if="review.policy_version">policy v{{ review.policy_version }}</span>
        <span v-if="review.case_id"> · case {{ review.case_id }}</span>
        <span v-if="review.state"> · state {{ review.state }}</span>
        <span v-if="review.decisions?.length > 1"> · {{ review.decisions.length }} decisions in this case</span>
      </div>
    </div>
  </el-popover>
</template>
