<script setup>
// Renders a plan candidate (candidate_view shape) of kind diet / exercise / integrated.
// Integrated plans render their two components recursively.
import { computed } from 'vue'
import { kindLabel, CANDIDATE_STATUS_TAG, INTENSITY_TAG, READINESS, fmtDate, round } from '../ui'

const props = defineProps({
  plan: { type: Object, required: true },
  nested: { type: Boolean, default: false }, // component inside an integrated plan: no header meta
})
const kind = computed(() => props.plan.kind || (props.plan.meals ? 'diet' : props.plan.activities ? 'exercise' : 'unknown'))
const totals = computed(() => props.plan.totals || (props.plan.total_kcal != null ? { kcal: props.plan.total_kcal } : null))
</script>

<template>
  <div class="plan-card">
    <div v-if="!nested" class="plan-head">
      <span class="kind">{{ kindLabel(kind) }}</span>
      <el-tag size="small" type="primary" effect="plain">v{{ plan.version }}</el-tag>
      <el-tag v-if="plan.status" size="small" :type="CANDIDATE_STATUS_TAG[plan.status] || 'info'">{{ plan.status }}</el-tag>
      <span class="muted small">
        <span v-if="plan.plan_date">for {{ plan.plan_date }}</span>
        <span v-if="plan.created_at"> · created {{ fmtDate(plan.created_at) }}</span>
        <span v-if="plan.profile_version"> · profile v{{ plan.profile_version }}</span>
        <span v-if="plan.model_version"> · draft by {{ plan.model_version }}</span>
        <span v-if="plan.repair_count"> · {{ plan.repair_count }} repair(s)</span>
      </span>
    </div>
    <el-alert v-if="!nested && plan.change_explanation" type="info" :closable="false" show-icon title="What changed in this version" :description="plan.change_explanation" style="margin-bottom: 10px" />

    <!-- ============================ DIET ============================ -->
    <template v-if="kind === 'diet'">
      <div class="stats" v-if="totals">
        <el-statistic title="Total energy" :value="Math.round(totals.kcal || 0)" suffix="kcal" />
        <el-statistic v-if="totals.protein_g != null" title="Protein" :value="Math.round(totals.protein_g)" suffix="g" />
        <el-statistic v-if="totals.carbs_g != null" title="Carbs" :value="Math.round(totals.carbs_g)" suffix="g" />
        <el-statistic v-if="totals.fat_g != null" title="Fat" :value="Math.round(totals.fat_g)" suffix="g" />
        <el-statistic title="Meals" :value="(plan.meals || []).length" />
      </div>
      <el-timeline>
        <el-timeline-item v-for="(m, i) in plan.meals || []" :key="i" :timestamp="m.time" placement="top" type="success">
          <div class="meal-card">
            <div class="meal-title">
              <span>{{ m.name }}</span>
              <span class="muted">{{ round(m.kcal) }} kcal</span>
            </div>
            <el-table :data="m.items || []" size="small" :show-header="i === 0" empty-text="No feasible items (see notes)">
              <el-table-column label="Food" prop="food" min-width="160" />
              <el-table-column label="g" width="60"><template #default="{ row }">{{ round(row.grams) }}</template></el-table-column>
              <el-table-column label="kcal" width="64"><template #default="{ row }">{{ round(row.kcal) }}</template></el-table-column>
              <el-table-column label="P/C/F g" width="96">
                <template #default="{ row }">{{ round(row.protein_g) }} / {{ round(row.carbs_g) }} / {{ round(row.fat_g) }}</template>
              </el-table-column>
              <el-table-column label="Source" width="92">
                <template #default="{ row }">
                  <el-tag v-if="row.verified" type="success" size="small">verified</el-tag>
                  <el-tag v-else type="warning" size="small">unverified</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Allergens" min-width="110">
                <template #default="{ row }">
                  <el-tag v-for="a in row.allergens || []" :key="a" size="small" type="danger" effect="plain" style="margin-right: 4px">{{ a }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="m.notes" class="muted small" style="margin-top: 6px">{{ m.notes }}</div>
          </div>
        </el-timeline-item>
      </el-timeline>

      <div v-if="(plan.substitutions || []).length" style="margin-bottom: 10px">
        <div class="muted small" style="margin-bottom: 4px">Substitutions</div>
        <el-table :data="plan.substitutions" size="small">
          <el-table-column label="Instead of" prop="for" width="180" />
          <el-table-column label="Alternative" prop="alternative" />
          <el-table-column label="Reason" prop="reason" />
        </el-table>
      </div>
      <div class="explain" v-if="plan.rationale"><b>Rationale</b>{{ plan.rationale }}</div>
      <div class="explain" v-if="plan.constraints_explanation"><b>Constraints applied</b>{{ plan.constraints_explanation }}</div>
      <div class="explain" v-if="(plan.uncertainties || []).length"><b>Uncertainties</b><ul class="plain-list"><li v-for="u in plan.uncertainties" :key="u">{{ u }}</li></ul></div>
      <div class="explain" v-if="(plan.unverified_foods || []).length"><b>Unverified foods</b>{{ plan.unverified_foods.join(', ') }}</div>
      <div class="muted small" v-if="plan.nutrition_data_version" style="margin-top: 6px">nutrition data {{ plan.nutrition_data_version }}</div>
    </template>

    <!-- ========================== EXERCISE ========================== -->
    <template v-else-if="kind === 'exercise'">
      <div class="row" style="margin-bottom: 10px">
        <el-tag type="primary" effect="plain">Session {{ plan.session_time }}</el-tag>
        <el-tag type="info" effect="plain">{{ plan.total_min }} min total</el-tag>
        <el-tag v-if="plan.readiness_result" effect="dark" :color="READINESS[plan.readiness_result]?.color" style="border: none">Readiness: {{ plan.readiness_result }}</el-tag>
        <span v-if="(plan.readiness_restrictions || []).length" class="small muted">restrictions: {{ plan.readiness_restrictions.join('; ') }}</span>
      </div>
      <div class="activity-grid">
        <div v-for="a in plan.activities || []" :key="a.id || a.name" class="activity-card" :class="{ paused: a.paused }">
          <div class="name">
            <span>{{ a.name }}</span>
            <el-tag :type="INTENSITY_TAG[a.intensity] || 'info'" size="small">{{ a.intensity }}</el-tag>
          </div>
          <div>{{ a.duration_min }} min <el-tag v-if="a.paused" size="small" type="info" style="margin-left: 6px">paused</el-tag></div>
          <div v-if="a.notes" class="muted small">{{ a.notes }}</div>
        </div>
      </div>
      <dl class="kv" style="margin: 12px 0">
        <dt>Warm-up</dt><dd>{{ plan.warm_up }}</dd>
        <dt>Rest</dt><dd>{{ plan.rest }}</dd>
        <dt>Cool-down</dt><dd>{{ plan.cool_down }}</dd>
        <dt>Difficulty</dt><dd>{{ plan.difficulty }}</dd>
        <dt v-if="plan.progression">Progression</dt><dd v-if="plan.progression">{{ plan.progression }}</dd>
        <dt v-if="(plan.alternatives || []).length">Alternatives</dt>
        <dd v-if="(plan.alternatives || []).length"><el-tag v-for="x in plan.alternatives" :key="x" size="small" effect="plain" style="margin: 0 4px 4px 0">{{ x }}</el-tag></dd>
      </dl>
      <div class="explain" v-if="plan.rationale"><b>Rationale</b>{{ plan.rationale }}</div>
      <div class="explain" v-if="(plan.adaptations || []).length"><b>Adaptations</b><ul class="plain-list"><li v-for="(ad, i) in plan.adaptations" :key="i">{{ typeof ad === 'string' ? ad : JSON.stringify(ad) }}</li></ul></div>
    </template>

    <!-- ========================= INTEGRATED ========================= -->
    <template v-else-if="kind === 'integrated'">
      <el-alert :type="(plan.conflicts_resolved || []).length ? 'warning' : 'success'" :closable="false" show-icon style="margin-bottom: 10px">
        <template #title>
          Conflicts resolved: {{ (plan.conflicts_resolved || []).length || 'none detected' }}
          <span class="muted small"> (timing · recovery · workload · nutrition · profile version)</span>
        </template>
        <ul v-if="(plan.conflicts_resolved || []).length" class="plain-list">
          <li v-for="(c, i) in plan.conflicts_resolved" :key="i"><b>{{ c.type }}</b> (round {{ c.round }}): {{ c.description }}</li>
        </ul>
      </el-alert>
      <div class="explain" v-if="plan.rationale"><b>Integration</b>{{ plan.rationale }}</div>
      <div class="nested-plan">
        <div class="card-title">Diet component <span class="sub">v{{ plan.diet_version }}</span></div>
        <PlanCard v-if="plan.diet" :plan="{ ...plan.diet, kind: 'diet' }" nested />
      </div>
      <div class="nested-plan">
        <div class="card-title">Exercise component <span class="sub">v{{ plan.exercise_version }}</span></div>
        <PlanCard v-if="plan.exercise" :plan="{ ...plan.exercise, kind: 'exercise' }" nested />
      </div>
    </template>

    <pre v-else class="json">{{ JSON.stringify(plan, null, 2) }}</pre>
  </div>
</template>
