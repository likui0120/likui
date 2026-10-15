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
      <el-button v-if="d.last_date" @click="store.day = d.last_date">看最近有数据的一天（{{ d.last_date }}）</el-button>
    </el-empty>

    <template v-else-if="d">
      <div class="stats">
        <div class="stat card">
          <div class="label">当日总产量</div>
          <div class="value num">{{ fmtW(d.total_output) }}<small> 斤</small></div>
          <div class="muted">{{ fmtT(Number(d.total_output || 0) / 2000) }} 吨</div>
        </div>
        <div class="stat card link" @click="$router.push('/r/cost')">
          <div class="label">算出成本的产品</div>
          <div class="value num">{{ d.products_ok }}<small> / {{ d.products }}</small></div>
          <div class="muted">缺单价的产品不出成本</div>
        </div>
        <div class="stat card link" @click="$router.push('/r/issues')">
          <div class="label">偏差超限</div>
          <div class="value num" :class="{ 'alert-text': d.alerts }">{{ d.alerts }}</div>
          <div class="muted">另有 {{ d.warnings }} 条提示</div>
        </div>
        <div class="stat card">
          <div class="label">成本差额合计（实际 − 标准）</div>
          <div class="value num" :class="{ 'alert-text': Number(d.diff_amount) > 0 }">{{ fmtM(d.diff_amount) }}<small> 元</small></div>
          <div class="muted">正数表示实际成本高于标准</div>
        </div>
        <div class="stat card link" @click="$router.push('/r/energy-daily')">
          <div class="label">当日能耗费用</div>
          <div class="value num">{{ fmtM(d.energy_cost) }}<small> 元</small></div>
          <div class="muted" v-if="d.energy">
            吨耗气 {{ fmtQ(d.energy.gas.per_ton) }} · 吨耗电 {{ fmtQ(d.energy.elec.per_ton) }} · 吨耗水 {{ fmtQ(d.energy.water.per_ton) }}
          </div>
        </div>
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
import { ref, watch } from 'vue'
import DayPicker from '../components/DayPicker.vue'
import IssueBox from '../components/IssueBox.vue'
import { api } from '../api'
import { store } from '../store'
import { fmtM, fmtP, fmtQ, fmtT, fmtW } from '../fmt'

const d = ref(null)
const issues = ref([])
async function load() {
  const day = store.day
  d.value = await api.get('/api/dashboard', { day })
  const r = await api.get('/api/reports/issues', { start: day, end: day })
  issues.value = r.rows.map((x) => ({ ...x, object_name: x.name }))
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
</style>
