import { createRouter, createWebHashHistory } from 'vue-router'

export const menu = [
  { path: '/', title: '今日概览', icon: 'House', component: () => import('./views/Dashboard.vue') },
  { path: '/entry', title: '每日录入', icon: 'EditPen', component: () => import('./views/DailyEntry.vue') },
  {
    title: '报表', icon: 'DataAnalysis', children: [
      { path: '/r/yield', title: '出率日报', component: () => import('./views/reports/YieldReport.vue') },
      { path: '/r/cost', title: '成本日报', component: () => import('./views/reports/CostReport.vue') },
      { path: '/r/monthly', title: '月度汇总', component: () => import('./views/reports/Monthly.vue') },
      { path: '/r/trace', title: '成本链路查询', component: () => import('./views/reports/TraceReport.vue') },
      { path: '/r/issues', title: '异常清单', component: () => import('./views/reports/IssueList.vue') },
      { path: '/r/energy-daily', title: '能耗日报', component: () => import('./views/reports/EnergyDaily.vue') },
      { path: '/r/energy-month', title: '能耗月报', component: () => import('./views/reports/EnergyMonth.vue') },
      { path: '/r/trend', title: '趋势', component: () => import('./views/reports/Trend.vue') },
    ],
  },
  {
    title: '基础资料', icon: 'Files', children: [
      { path: '/m/materials', title: '原料', component: () => import('./views/master/Materials.vue') },
      { path: '/m/seasoning', title: '干调价格', component: () => import('./views/master/SeasoningPrices.vue') },
      { path: '/m/products', title: '产品', component: () => import('./views/master/Products.vue') },
      { path: '/m/boms', title: 'BOM', component: () => import('./views/master/Boms.vue') },
      { path: '/m/specs', title: '包装规格', component: () => import('./views/master/PackSpecs.vue') },
      { path: '/m/meters', title: '计量表', component: () => import('./views/master/Meters.vue') },
      { path: '/m/energy-prices', title: '能源单价', component: () => import('./views/master/EnergyPrices.vue') },
      { path: '/m/thresholds', title: '预警阈值', component: () => import('./views/master/Thresholds.vue') },
      { path: '/m/imports', title: 'Excel 导入', component: () => import('./views/master/Imports.vue') },
      { path: '/m/settings', title: '系统设置', component: () => import('./views/master/Settings.vue') },
    ],
  },
]

const routes = []
for (const m of menu) {
  if (m.children) m.children.forEach((c) => routes.push({ path: c.path, component: c.component, meta: { title: c.title } }))
  else routes.push({ path: m.path, component: m.component, meta: { title: m.title } })
}

const router = createRouter({ history: createWebHashHistory(), routes })
router.afterEach((to) => { document.title = `${to.meta.title || ''} · 车间出率与成本核算` })
export default router
