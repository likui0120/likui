<template>
  <div class="page">
    <div class="page-head">
      <h2>趋势</h2>
      <el-select v-model="kind" style="width: 140px">
        <el-option label="原料出率" value="material" />
        <el-option label="产品环节出率" value="product_yield" />
        <el-option label="产品单价" value="product_cost" />
        <el-option label="能耗指标" value="energy" />
      </el-select>
      <el-select v-if="kind === 'material'" v-model="refId" filterable placeholder="选择原料" style="width: 160px">
        <el-option v-for="m in materials" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <template v-if="kind === 'product_yield' || kind === 'product_cost'">
        <el-select v-model="refId" filterable placeholder="选择产品" style="width: 160px">
          <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-select v-model="stage" style="width: 120px">
          <el-option v-for="s in stageOptions" :key="s.v" :label="s.l" :value="s.v" />
        </el-select>
      </template>
      <el-select v-if="kind === 'energy'" v-model="metric" style="width: 160px">
        <el-option v-for="o in energyMetrics" :key="o.v" :label="o.l" :value="o.v" />
      </el-select>
      <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" :clearable="false" style="width: 250px" />
    </div>
    <div class="card">
      <div ref="chartEl" class="chart" />
      <div v-if="!points.length" class="muted">选择对象和日期区间后显示按日走势。</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../../api'
import { store, shiftDay } from '../../store'
import { fmtP, fmtQ, fmtY } from '../../fmt'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const kind = ref('material')
const refId = ref(null)
const stage = ref('cook')
const metric = ref('gas.per_ton')
const range = ref([shiftDay(store.day, -29), store.day])
const materials = ref([])
const products = ref([])
const points = ref([])
const unit = ref('yield')
const chartEl = ref(null)
let chart = null

const stageOptions = computed(() => kind.value === 'product_yield'
  ? [{ v: 'cook', l: '熟制/拌馅' }, { v: 'cool', l: '制冷' }, { v: 'pack', l: '包装' }]
  : [{ v: 'out', l: '出机单价' }, { v: 'cooled', l: '冷后单价' }, { v: 'final', l: '成品单价' }])
const energyMetrics = [
  { v: 'gas.per_ton', l: '吨耗气' }, { v: 'elec.per_ton', l: '吨耗电' }, { v: 'water.per_ton', l: '吨耗水' },
  { v: 'water.workshop_per_ton', l: '车间吨耗水' }, { v: 'gas.cost', l: '燃气费' }, { v: 'elec.cost', l: '电费' },
  { v: 'water.cost', l: '水费' },
]
watch(kind, (k) => {
  refId.value = null
  stage.value = k === 'product_cost' ? 'final' : 'cook'
  points.value = []
  draw()
})

async function load() {
  if (kind.value !== 'energy' && !refId.value) return
  const r = await api.get('/api/reports/trend', {
    kind: kind.value, ref_id: refId.value, stage: stage.value, metric: metric.value,
    start: range.value[0], end: range.value[1],
  })
  points.value = r.points
  unit.value = r.unit
  draw()
}
function draw() {
  if (!chart) return
  const f = unit.value === 'yield' ? fmtY : unit.value === 'price' ? fmtP : fmtQ
  const val = (v) => (v === null || v === undefined ? null : Number(v) * (unit.value === 'yield' ? 100 : 1))
  const series = [{ name: '实际', type: 'line', data: points.value.map((p) => val(p.actual)), connectNulls: false, symbolSize: 6 }]
  if (points.value.some((p) => p.std !== null && p.std !== undefined)) {
    series.push({ name: '标准', type: 'line', data: points.value.map((p) => val(p.std)), lineStyle: { type: 'dashed' }, symbol: 'none' })
  }
  chart.setOption({
    color: ['#2f6f9f', '#d08b2c'],
    tooltip: { trigger: 'axis', valueFormatter: (v) => (v === null ? '—' : unit.value === 'yield' ? v.toFixed(2) + '%' : f(v)) },
    legend: { top: 0 },
    grid: { left: 60, right: 20, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: points.value.map((p) => p.date.slice(5)) },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v) => (unit.value === 'yield' ? v + '%' : v) } },
    series,
  }, true)
}
onMounted(async () => {
  materials.value = (await api.get('/api/materials')).filter((m) => m.needs_process)
  products.value = await api.get('/api/products')
  await nextTick()
  chart = echarts.init(chartEl.value)
  window.addEventListener('resize', resize)
  load()
})
const resize = () => chart && chart.resize()
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart && chart.dispose() })
watch([refId, stage, metric, range], load)
</script>

<style scoped>
.chart { width: 100%; height: 420px; }
</style>
