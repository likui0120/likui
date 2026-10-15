<template>
  <div class="page">
    <div class="page-head">
      <h2>今日概览</h2>
      <DayPicker />
      <span class="spacer" />
      <el-button type="primary" @click="$router.push('/entry')">去录入</el-button>
    </div>

    <el-empty v-if="d && !d.total_output && !d.products" description="这一天还没有录入数据">
      <el-button type="primary" @click="$router.push('/entry')">开始录入</el-button>
      <el-button v-if="d.last_date" @click="goLast">看最近有数据的一天（{{ d.last_date }}）</el-button>
    </el-empty>

    <template v-else-if="d">
      <div class="stats">
        <div class="stat card">
          <div class="label">当日总产量</div>
          <div class="value num">{{ fmtW(d.total_output) }}<small> 斤</small></div>
          <div class="muted">{{ fmtT(Number(d.total_output || 0) / 2000) }} 吨（成品入库 + 麻油）</div>
        </div>
        <div class="stat card link" role="link" tabindex="0" aria-label="成本结果，打开成本日报" @click="go('/r/cost')" @keydown.enter="go('/r/cost')">
          <div class="label">成本结果</div>
          <div class="value num">{{ q.complete || 0 }}<small> / {{ d.products }} 算全</small></div>
          <div class="muted">
            <span v-if="q.estimated">含估算 {{ q.estimated }} · </span>
            <span v-if="q.partial" class="warn-text">只算到中间 {{ q.partial }} · </span>
            <span v-if="q.none" class="alert-text">算不出 {{ q.none }} · </span>
            <span v-if="q.loss" class="alert-text">全损 {{ q.loss }} · </span>
            <span>详情见下方待办</span>
          </div>
        </div>
        <div class="stat card link" role="link" tabindex="0" aria-label="偏差超限，打开异常清单" @click="go('/r/issues')" @keydown.enter="go('/r/issues')">
          <div class="label">偏差超限</div>
          <div class="value num" :class="{ 'alert-text': d.alerts }">{{ d.alerts }}</div>
          <div class="muted">另有 {{ d.warnings }} 条提示</div>
        </div>
        <div class="stat card">
          <div class="label">成品馅成本差额（实际 − 标准）</div>
          <div class="value num" :class="{ 'alert-text': Number(d.diff_amount) > 0 }">{{ fmtM(d.diff_amount) }}<small> 元</small></div>
          <div class="muted">只来自出率偏差；半成品油、麻油的差额已含在下游成品里（{{ fmtM(d.diff_amount_mid) }} 元，不重复加）</div>
          <div v-if="Number(d.loss_amount) || d.loss_count" class="alert-text">另有全损 {{ d.loss_count }} 项，损失 {{ fmtM(d.loss_amount) }} 元（未计入差额）</div>
        </div>
      </div>

      <div class="card link energy" role="link" tabindex="0" aria-label="能耗，打开能耗日报" @click="go('/r/energy-daily')" @keydown.enter="go('/r/energy-daily')">
        <div class="card-title">当日能耗 <span v-if="d.energy_complete === false" class="warn-text">（不完整）</span></div>
        <div class="energy-row">
          <span>费用 <b class="num">{{ fmtM(d.energy_cost) }}</b> 元</span>
          <template v-if="d.energy">
            <span>吨耗气 <b class="num">{{ fmtQ(d.energy.gas.per_ton) }}</b> Nm³/吨</span>
            <span>吨耗电 <b class="num">{{ fmtQ(d.energy.elec.per_ton) }}</b> 度/吨</span>
            <span>吨耗水 <b class="num">{{ fmtQ(d.energy.water.per_ton) }}</b> 吨/吨</span>
          </template>
        </div>
        <div v-for="(n, i) in d.energy_notes" :key="i" class="muted">· {{ n }}</div>
      </div>

      <div v-if="d.todo && d.todo.length" class="card">
        <div class="card-title">待办：成本没算全的产品</div>
        <el-table :data="d.todo" size="small">
          <el-table-column prop="name" label="产品" min-width="140" />
          <el-table-column prop="status" label="状态" width="130" />
          <el-table-column label="原因" min-width="260">
            <template #default="{ row }"><div v-for="(f, i) in row.flags" :key="i">{{ f }}</div></template>
          </el-table-column>
        </el-table>
      </div>
      <div class="card">
        <div class="card-title">成本差额最大的产品</div>
        <el-table :data="d.top" size="small" empty-text="没有可比较的产品">
          <el-table-column prop="name" label="产品" min-width="140" />
          <el-table-column label="差额（元/斤）" align="right">
            <template #default="{ row }"><span class="num" :class="{ 'alert-text': row.diff_price > 0 }">{{ fmtP(row.diff_price) }}</span></template>
          </el-table-column>
          <el-table-column label="当日差额（元）" align="right">
            <template #default="{ row }"><span class="num" :class="{ 'alert-text': row.diff_amount > 0 }">{{ fmtM(row.diff_amount) }}</span></template>
          </el-table-column>
        </el-table>
      </div>
      <div class="card">
        <div class="card-title">当日异常与提示</div>
        <IssueBox :issues="issues" :limit="10" />
        <div v-if="!issues.length" class="muted">没有异常</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DayPicker from '../components/DayPicker.vue'
import IssueBox from '../components/IssueBox.vue'
import { api } from '../api'
import { store } from '../store'
import { fmtM, fmtP, fmtQ, fmtT, fmtW } from '../fmt'

const d = ref(null)
const q = computed(() => d.value?.quality || {})
const issues = ref([])
let seq = 0
async function load() {
  const day = store.day
  const my = ++seq
  const [dash, r] = await Promise.all([
    api.get('/api/dashboard', { day }),
    api.get('/api/reports/issues', { start: day, end: day }),
  ])
  if (my !== seq) return // 已切到别的日期，丢掉旧结果
  d.value = dash
  issues.value = r.rows.map((x) => ({ ...x, object_name: x.name }))
}
const router = useRouter()
const go = (p) => router.push(p)
function goLast() {
  const target = d.value?.last_date
  if (!target) return
  if (store.day === target) load()
  else store.day = target
}
watch(() => store.day, load, { immediate: true })
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-bottom: 0; }
.stat .label { color: #5a6b7d; font-size: 13px; }
.stat .value { font-size: 26px; font-weight: 600; margin: 6px 0 4px; }
.stat .value small { font-size: 13px; color: #8492a6; font-weight: 400; }
.stat.link { cursor: pointer; }
.stat.link:hover { box-shadow: 0 2px 8px rgba(47, 111, 159, .18); }
.card-title { font-weight: 600; margin-bottom: 8px; }
.link { cursor: pointer; }
.link:focus-visible { outline: 2px solid #2f6f9f; outline-offset: 2px; }
.energy-row { display: flex; flex-wrap: wrap; gap: 8px 24px; }
.warn-text { color: #b26a00; }
</style>
