<script setup>
// The key demo artifact: a vertical timeline of agent steps that makes explicit
// which steps were LLM drafts/interpretations and which were deterministic rules.
import { ref, computed } from 'vue'
import { agentColor, fmtTime } from '../ui'

const props = defineProps({
  modelValue: Boolean,
  trace: { type: Array, default: () => [] },
  title: { type: String, default: 'Agent pipeline' },
})
const emit = defineEmits(['update:modelValue'])
const open = ref({})
const agents = computed(() => [...new Set(props.trace.map((t) => t.agent))])
const llmCount = computed(() => props.trace.filter((t) => t.llm_used).length)
const hasDetail = (t) => t.detail && Object.keys(t.detail).length > 0
</script>

<template>
  <el-drawer :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)" size="580px" :title="title">
    <div class="trace-legend">
      <p>
        <el-tag type="warning" size="small" effect="dark">LLM draft</el-tag> = the language model interpreted input or proposed a draft.
        <el-tag type="info" size="small">Rule</el-tag> = deterministic code (profile gates, readiness rules, hard rules, risk score, release).
        <b>The LLM never decides what is released; only rule steps of the Safety Supervisor do.</b>
      </p>
      <div class="legend-agents">
        <span v-for="a in agents" :key="a" :style="{ color: agentColor(a) }">● {{ a }}</span>
      </div>
      <div class="muted small" style="margin-top: 4px">{{ trace.length }} steps · {{ llmCount }} LLM · {{ trace.length - llmCount }} rule</div>
    </div>

    <el-timeline>
      <el-timeline-item v-for="(t, i) in trace" :key="i" :color="agentColor(t.agent)" :timestamp="t.at ? fmtTime(t.at) : `step ${t.seq}`" placement="top">
        <div class="trace-step">
          <div class="trace-head">
            <span class="agent-chip" :style="{ background: agentColor(t.agent) }">{{ t.agent }}</span>
            <code class="step-name">{{ t.step }}</code>
            <el-tag v-if="t.llm_used" type="warning" size="small" effect="dark">LLM draft<template v-if="t.model_version"> · {{ t.model_version }}</template></el-tag>
            <el-tag v-else type="info" size="small">Rule</el-tag>
          </div>
          <div class="trace-summary">{{ t.summary }}</div>
          <el-button v-if="hasDetail(t)" link type="primary" size="small" @click="open[i] = !open[i]">{{ open[i] ? 'Hide detail' : 'Show detail' }}</el-button>
          <pre v-if="open[i]" class="json">{{ JSON.stringify(t.detail, null, 2) }}</pre>
        </div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-if="!trace.length" description="No trace recorded" />
  </el-drawer>
</template>
