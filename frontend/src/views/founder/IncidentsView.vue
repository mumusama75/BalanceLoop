<script setup>
// Founder: incidents (critical stops, fail-closed events) and founder notifications.
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../store'
import { fmtDate, SEVERITY_TAG, NOTIFICATION_TAG } from '../../ui'

const incidents = ref([])
const notifications = ref([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const [a, b] = await Promise.all([api.get('/founder/incidents'), api.get('/founder/notifications')])
    incidents.value = a.data
    notifications.value = b.data
  } finally { loading.value = false }
}
async function ack(i) {
  await api.post(`/founder/incidents/${i.id}/ack`)
  ElMessage.success('Incident acknowledged (recorded in the audit log)')
  await load()
}
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="stack">
    <el-card>
      <template #header><div class="card-title">Incidents <span class="row"><span class="sub">{{ incidents.filter((i) => !i.acknowledged).length }} open</span><el-button size="small" :icon="'Refresh'" @click="load" /></span></div></template>
      <el-table :data="incidents" size="small" empty-text="No incidents recorded">
        <el-table-column label="When" width="160"><template #default="{ row }">{{ fmtDate(row.created_at) }}</template></el-table-column>
        <el-table-column label="Severity" width="110"><template #default="{ row }"><el-tag size="small" :type="SEVERITY_TAG[row.severity] || 'warning'">{{ row.severity }}</el-tag></template></el-table-column>
        <el-table-column label="Rule" prop="rule_id" width="90" />
        <el-table-column label="User" prop="user_id" width="90" />
        <el-table-column label="Description" prop="description" min-width="300" />
        <el-table-column label="Request" width="150"><template #default="{ row }"><router-link :to="{ path: '/founder/audit', query: { request_id: row.request_id } }" class="mono">{{ row.request_id }}</router-link></template></el-table-column>
        <el-table-column label="" width="140">
          <template #default="{ row }">
            <el-tag v-if="row.acknowledged" type="success" size="small">acknowledged</el-tag>
            <el-button v-else size="small" type="primary" @click="ack(row)">Acknowledge</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card>
      <template #header><div class="card-title">Founder notifications <span class="sub">{{ notifications.length }}</span></div></template>
      <el-table :data="notifications" size="small" empty-text="No notifications">
        <el-table-column label="When" width="160"><template #default="{ row }">{{ fmtDate(row.created_at) }}</template></el-table-column>
        <el-table-column label="Kind" width="110"><template #default="{ row }"><el-tag size="small" :type="NOTIFICATION_TAG[row.kind] || 'info'">{{ row.kind }}</el-tag></template></el-table-column>
        <el-table-column label="Message" prop="message" min-width="300" />
        <el-table-column label="Request" width="150"><template #default="{ row }"><router-link v-if="row.request_id" :to="{ path: '/founder/audit', query: { request_id: row.request_id } }" class="mono">{{ row.request_id }}</router-link></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
