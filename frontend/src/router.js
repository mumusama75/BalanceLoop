import { createRouter, createWebHistory } from 'vue-router'
import { isFounder } from './store'

const routes = [
  { path: '/', redirect: () => (isFounder.value ? '/founder/policies' : '/profile') },
  { path: '/profile', component: () => import('./views/ProfileView.vue'), meta: { title: 'Profile & consent', uc: 'UC01' } },
  { path: '/food', component: () => import('./views/FoodView.vue'), meta: { title: 'Food log', uc: 'UC02' } },
  { path: '/readiness', component: () => import('./views/ReadinessView.vue'), meta: { title: 'Readiness check-in', uc: 'UC05' } },
  { path: '/plans', component: () => import('./views/PlansView.vue'), meta: { title: 'Plans', uc: 'UC03 · UC06 · UC09' } },
  { path: '/feedback', component: () => import('./views/FeedbackView.vue'), meta: { title: 'Feedback & adaptation', uc: 'UC04 · UC07 · UC08' } },
  { path: '/reviews', component: () => import('./views/CasesView.vue'), meta: { title: 'My review cases', uc: 'UC10' } },
  { path: '/founder/policies', component: () => import('./views/founder/PoliciesView.vue'), meta: { title: 'Review policies', founder: true } },
  { path: '/founder/incidents', component: () => import('./views/founder/IncidentsView.vue'), meta: { title: 'Incidents', founder: true } },
  { path: '/founder/audit', component: () => import('./views/founder/AuditView.vue'), meta: { title: 'Audit replay', founder: true } },
  { path: '/founder/cases', component: () => import('./views/CasesView.vue'), props: { founder: true }, meta: { title: 'All review cases', founder: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

// Founder sees only the console; users never see founder routes.
router.beforeEach((to) => {
  if (to.path === '/') return true
  if (to.meta.founder && !isFounder.value) return '/profile'
  if (!to.meta.founder && isFounder.value) return '/founder/policies'
  return true
})

export default router
