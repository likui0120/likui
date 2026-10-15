<template>
  <div class="page">
    <div class="page-head">
      <h2>月度汇总</h2>
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" style="width: 140px" />
      <span class="spacer" />
      <el-button @click="download('/api/reports/monthly/export', { month })">导出 Excel</el-button>
    </div>

    <div v-loading="loading">
      <div class="stats">
        <div class="stat card">
          <div class="label">月总产量</div>
          <div class="value num">{{ fmtW(sm.output) }}<small> 斤</small></div>
          <div class="muted">{{ fmtT(sm.output_ton) }} 吨 · 生产 {{ sm.production_days || 0 }} 天</div>
        </div>
        <div class="stat card">
          <div class="label">成本差额合计（实际 − 标准）</div>
          <div class="value num" :class="{ 'alert-text': Number(sm.diff_amount) > 0 }">{{ fmtM(sm.diff_amount) }}<small> 元</small></div>
          <div class="muted">各产品月差额之和，正数表示出率低于标准多花的钱</div>
        </div>
        <div class="stat card">
          <div class="label">原料出率偏差金额</div>
          <div class="value num" :class="{ 'alert-text': Number(sm.material_impact) > 0 }">{{ fmtM(sm.material_impact) }}<small> 元</small></div>
          <div class="muted">1→2 级处理比标准多耗的原料折成金额</div>
        </div>
        <div class="stat card">
          <div class="label">能耗费用</div>
          <div class="value num">{{ fmtM(sm.energy_cost) }}<small> 元</small></div>
          <div class="muted" v-if="sm.energy_cost_per_ton">每吨产品 {{ fmtM(sm.energy_cost_per_ton) }} 元</div>
        </div>
        <div class="stat card" v-if="Number(sm.loss_cost) > 0">
          <div class="label">整批报废损失</div>
          <div class="value num alert-text">{{ fmtM(sm.loss_cost) }}<small> 元</small></div>
          <div class="muted">某个环节产出为 0 的批次，按当天投料成本计</div>
        </div>
        <div class="stat card link" @click="$router.push('/r/issues')">
          <div class="label">有超限的天数</div>
          <div class="value num" :class="{ 'alert-text': sm.alert_days }">{{ sm.alert_days || 0 }}</div>
          <div class="muted">点开看异常清单</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">产品</div>
        <p class="hint">
          月单价 = 月总成本 ÷ 月产量（每天单价按当天产量加权），不是每天单价的简单平均。成品馅按成品单价和入库量，半成品油按冷后单价，麻油按出机单价。
          月熟制出率 = 月出锅重合计 ÷ 月投料合计。“比上月”是和 {{ rep.prev_month }} 的实际单价比。按月差额从大到小排。
        </p>
        <ReportTable :columns="pcols" :rows="rep.products" :fixed="['name']" max-height="calc(100vh - 260px)">
          <template #name="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.no_cost_days" size="small" type="warning" class="ml">{{ row.no_cost_days }} 天未出成本</el-tag>
          </template>
          <template #price_change="{ row }">
            <span class="num" :class="{ 'alert-text': Number(row.price_change) > 0 }">{{ pct(row.price_change) }}</span>
          </template>
          <template #yield_dev="{ row }">
            <span class="num" :class="{ 'alert-text': Number(row.yield_dev) < 0 }">{{ fmtPP(row.yield_dev) }}</span>
          </template>
          <template #alert_days="{ row }">
            <span :class="{ 'alert-text': row.alert_days }">{{ row.alert_days || '' }}</span>
          </template>
        </ReportTable>
      </div>

      <div class="card">
        <div class="card-title">原料 1→2 级出率</div>
        <p class="hint">
          只统计需要处理、当天有处理记录的原料。月出率 = 月 2 级称重合计 ÷ 月 1 级领用合计；标准出率按领用量加权。
          出率偏差金额 = 每天 1 级单价 ×（1 级领用 − 2 级称重 ÷ 标准出率）之和，即同样的产出按标准出率本可以少用的原料值多少钱，负数表示比标准省。
          “缺处理记录天数”是产品用到了这个原料、但当天没录处理记录（按标准出率算）的天数。
        </p>
        <ReportTable :columns="mcols" :rows="rep.materials" :fixed="['name']" max-height="calc(100vh - 260px)">
          <template #impact="{ row }">
            <span class="num" :class="{ 'alert-text': Number(row.impact) > 0 }">{{ fmtM(row.impact) }}</span>
          </template>
          <template #yield_dev="{ row }">
            <span class="num" :class="{ 'alert-text': Number(row.yield_dev) < 0 }">{{ fmtPP(row.yield_dev) }}</span>
          </template>
          <template #alert_days="{ row }">
            <span :class="{ 'alert-text': row.alert_days }">{{ row.alert_days || '' }}</span>
          </template>
          <template #std_days="{ row }">
            <span :class="{ 'warn-text': row.std_days }">{{ row.std_days || '' }}</span>
          </template>
        </ReportTable>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import ReportTable from '../../components/ReportTable.vue'
import { api, download } from '../../api'
import { store } from '../../store'
import { fmtM, fmtPP, fmtT, fmtW } from '../../fmt'

const month = ref(store.day.slice(0, 7))
const loading = ref(false)
const rep = ref({ summary: {}, products: [], materials: [], product_columns: [], material_columns: [] })
const sm = computed(() => rep.value.summary || {})
// 表格里不重复显示已在名称旁提示的列
const pcols = computed(() => rep.value.product_columns.filter((c) => !['no_cost_days', 'ptype'].includes(c[0])))
const mcols = computed(() => rep.value.material_columns)
const pct = (v) => (v === null || v === undefined ? '' : (Number(v) > 0 ? '+' : '') + (Number(v) * 100).toFixed(1) + '%')

let seq = 0
async function load() {
  const my = ++seq
  loading.value = true
  try {
    const r = await api.get('/api/reports/monthly', { month: month.value })
    if (my === seq) rep.value = r
  } finally {
    if (my === seq) loading.value = false
  }
}
watch(month, load, { immediate: true })
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-bottom: 14px; }
.stat .label { color: #5a6b7d; font-size: 13px; }
.stat .value { font-size: 24px; font-weight: 600; margin: 6px 0 4px; }
.stat .value small { font-size: 13px; color: #8492a6; font-weight: 400; }
.stat.link { cursor: pointer; }
.card-title { font-weight: 600; margin-bottom: 6px; }
.ml { margin-left: 6px; }
.warn-text { color: #b88230; font-weight: 600; }
</style>
