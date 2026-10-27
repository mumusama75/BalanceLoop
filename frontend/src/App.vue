<script setup>
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { state, isFounder, loadUsers, setUser, loadHealth, loadNotifications, markNotificationsSeen, unseenCount } from './store'
import { fmtDate, NOTIFICATION_TAG } from './ui'

const route = useRoute()
const router = useRouter()

const userNav = [
  { path: '/profile', label: 'Profile & consent', uc: 'UC01', icon: 'User' },
  { path: '/food', label: 'Food log', uc: 'UC02', icon: 'Bowl' },
  { path: '/readiness', label: 'Readiness', uc: 'UC05', icon: 'Odometer' },
  { path: '/plans', label: 'Plans', uc: 'UC03/06/09', icon: 'Calendar' },
  { path: '/feedback', label: 'Feedback', uc: 'UC04/07/08', icon: 'ChatLineSquare' },
  { path: '/reviews', label: 'Review cases', uc: 'UC10', icon: 'Finished' },
]
const founderNav = [
  { path: '/founder/policies', label: 'Review policies', uc: 'AR-09', icon: 'Setting' },
  { path: '/founder/incidents', label: 'Incidents', uc: 'UC10 3a', icon: 'WarningFilled' },
  { path: '/founder/audit', label: 'Audit replay', uc: 'AR-10', icon: 'DataLine' },
  { path: '/founder/cases', label: 'All review cases', uc: 'UC10', icon: 'Files' },
]
const nav = computed(() => (isFounder.value ? founderNav : userNav))

// Views are keyed by route + reloadKey (not by user id): on a role switch the route changes and the
// old view unmounts; on a same-route switch (Alex -> Sam) we bump the key to reload the view.
const reloadKey = ref(0)
async function onUserChange(id) {
  const u = state.users.find((x) => x.id === id)
  if (!u) return
  setUser(u)
  const target = u.role === 'founder' ? '/founder/policies' : '/profile'
  if (route.path === target) reloadKey.value++
  else await router.replace(target)
  loadNotifications()
}

const notifOpen = ref(false)
watch(notifOpen, (open) => { if (open) markNotificationsSeen() })

let timer = null
onMounted(async () => {
  await loadUsers()
  loadHealth()
  loadNotifications()
  timer = setInterval(loadNotifications, 15000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <el-container style="min-height: 100vh">
    <el-header class="bl-header" height="56px">
      <div class="brand">
        <span class="logo" />
        BalanceLoop
        <span class="tag">reviewed lifestyle support · multi-agent prototype</span>
      </div>
      <div class="header-right">
        <span v-if="state.health" class="health-chip">
          LLM: <b>{{ state.health.llm_provider }}</b> ({{ state.health.llm_model_version }}) ·
          policy <b>{{ state.health.active_policy_version || 'none (fail-closed)' }}</b>
        </span>
        <el-popover v-model:visible="notifOpen" trigger="click" width="380" placement="bottom-end">
          <template #reference>
            <el-badge :value="unseenCount" :hidden="!unseenCount" :max="99">
              <el-button circle :icon="'Bell'" aria-label="Notifications" />
            </el-badge>
          </template>
          <div style="max-height: 360px; overflow: auto">
            <div v-if="!state.notifications.length" class="muted small">No notifications yet.</div>
            <div v-for="n in state.notifications" :key="n.id" class="notif-item">
              <el-tag :type="NOTIFICATION_TAG[n.kind] || 'info'" size="small" style="margin-right: 6px">{{ n.kind }}</el-tag>
              <span>{{ n.message }}</span>
              <div class="when">{{ fmtDate(n.created_at) }} <span v-if="n.request_id" class="mono">· {{ n.request_id }}</span></div>
            </div>
          </div>
        </el-popover>
        <el-select :model-value="state.user?.id" @change="onUserChange" style="width: 220px" placeholder="Demo user" aria-label="Demo user">
          <el-option v-for="u in state.users" :key="u.id" :value="u.id" :label="`${u.display_name} (${u.role})`" />
        </el-select>
      </div>
    </el-header>

    <el-container>
      <el-aside width="236px" class="bl-aside">
        <el-menu :default-active="route.path" router>
          <el-menu-item v-for="item in nav" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span style="flex: 1">{{ item.label }}</span>
            <span class="muted small nav-uc">{{ item.uc }}</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main>
        <div class="page">
          <div class="page-head">
            <h1>{{ route.meta.title }}</h1>
            <span class="uc" v-if="route.meta.uc">{{ route.meta.uc }} · signed in as {{ state.user?.display_name }}</span>
            <span class="uc" v-else>Founder console · {{ state.user?.display_name }}</span>
          </div>
          <router-view :key="`${route.path}#${reloadKey}`" />
        </div>
        <div class="bl-footer">Lifestyle support only — not medical advice.</div>
      </el-main>
    </el-container>
  </el-container>
</template>
