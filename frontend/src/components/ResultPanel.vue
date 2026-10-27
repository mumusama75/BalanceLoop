<script setup>
// Renders the uniform OperationResult envelope: status alert, message, review badge, trace drawer button.
import { ref, computed } from 'vue'
import { statusInfo } from '../ui'
import ReviewBadge from './ReviewBadge.vue'
import TraceDrawer from './TraceDrawer.vue'

const props = defineProps({
  result: { type: Object, default: null },
  label: { type: String, default: '' }, // optional override of the status chip text
})
const showTrace = ref(false)
const st = computed(() => statusInfo(props.result?.status))
const extra = computed(() => props.result?.extra || {})
const trace = computed(() => props.result?.trace || [])
const llmSteps = computed(() => trace.value.filter((t) => t.llm_used).length)
const profileLink = computed(() => props.result?.status === 'blocked' || String(extra.value.next_action || '').startsWith('UC01'))
</script>

<template>
  <div v-if="result" class="result-panel">
    <el-alert :type="st.alert" :class="st.cls" show-icon :closable="false">
      <template #title>
        <span class="result-title">
          <el-tag :type="st.tag" size="small" effect="dark">{{ label || st.label }}</el-tag>
          <el-tag v-if="extra.fail_closed" type="danger" size="small">fail-closed</el-tag>
          <span v-if="result.request_id" class="muted mono">{{ result.request_id }}</span>
        </span>
      </template>
      <div class="result-message">{{ result.message }}</div>
      <ul v-if="extra.fields?.length" class="plain-list">
        <li v-for="f in extra.fields" :key="f">Missing / inconsistent: <b>{{ f }}</b></li>
      </ul>
      <ul v-if="extra.missing?.length" class="plain-list">
        <li v-for="f in extra.missing" :key="f">Missing: <b>{{ f }}</b></li>
      </ul>
      <div v-if="extra.infeasible_meals?.length" class="small">Meals that could not be filled: {{ extra.infeasible_meals.join(', ') }}</div>
      <div class="result-actions" v-if="result.status === 'pending_readiness' || profileLink">
        <router-link v-if="result.status === 'pending_readiness'" to="/readiness">
          <el-button size="small" type="warning" plain>Go to readiness check-in (UC05)</el-button>
        </router-link>
        <router-link v-if="profileLink" to="/profile">
          <el-button size="small" type="danger" plain>Open profile & consent (UC01)</el-button>
        </router-link>
      </div>
    </el-alert>

    <div class="result-footer">
      <ReviewBadge v-if="result.review" :review="result.review" />
      <span v-else />
      <el-button v-if="trace.length" size="small" @click="showTrace = true" :icon="'Share'">
        Show agent pipeline ({{ trace.length }} steps · {{ llmSteps }} LLM)
      </el-button>
    </div>
    <slot />
    <TraceDrawer v-model="showTrace" :trace="trace" :title="`Agent pipeline · ${result.request_id || ''}`" />
  </div>
</template>
