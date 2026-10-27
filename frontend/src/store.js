// Tiny app state: selected demo user, axios instance with the X-User-Id header, notifications.
import { reactive, computed } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const LS_KEY = 'balanceloop.user'

function loadSavedUser() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || null } catch { return null }
}

export const state = reactive({
  users: [],
  user: loadSavedUser() || { id: 'u_sam', display_name: 'Sam Lee', role: 'user' },
  notifications: [],
  seenNotificationIds: new Set(),
  health: null,
})

export const isFounder = computed(() => state.user?.role === 'founder')

export const api = axios.create({ baseURL: '/api', timeout: 60000 })
api.interceptors.request.use((cfg) => {
  cfg.headers['X-User-Id'] = state.user?.id || ''
  return cfg
})
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (!err.config?.silent) ElMessage.error(errorText(err))
    return Promise.reject(err)
  },
)

export function errorText(err) {
  const d = err?.response?.data
  if (!d) return err?.message || 'Request failed'
  if (typeof d.detail === 'string') return d.detail
  if (Array.isArray(d.detail)) return d.detail.map((x) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('; ')
  return JSON.stringify(d)
}

export async function loadUsers() {
  const { data } = await api.get('/users')
  state.users = data
  const fresh = data.find((u) => u.id === state.user?.id)
  if (fresh) setUser(fresh)
  else if (data.length) setUser(data[0])
}

export function setUser(u) {
  state.user = { id: u.id, display_name: u.display_name, role: u.role }
  localStorage.setItem(LS_KEY, JSON.stringify(state.user))
  state.notifications = []
  state.seenNotificationIds = new Set()
}

export async function loadHealth() {
  try { state.health = (await api.get('/health', { silent: true })).data } catch { state.health = null }
}

export async function loadNotifications() {
  if (!state.user) return
  try {
    const url = isFounder.value ? '/founder/notifications' : '/notifications'
    state.notifications = (await api.get(url, { silent: true })).data
  } catch { /* polling: ignore transient errors */ }
}

export function markNotificationsSeen() {
  for (const n of state.notifications) state.seenNotificationIds.add(n.id)
}

export const unseenCount = computed(() => state.notifications.filter((n) => !state.seenNotificationIds.has(n.id)).length)
