<template>
  <div class="page">
    <div class="page-head">
      <h2>能耗日报</h2>
      <RangePicker v-model="range" />
      <span class="spacer" />
      <el-button @click="download('/api/reports/export/energy-daily', { start: range[0], end: range[1] })">导出 Excel</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">吨能耗 = 合计用量 ÷ 当日总产量（吨），当天有表没抄、或读数差跨了几天时不算吨耗（标“不完整”，鼠标放上去看原因）。总产量 = 各产品包装入库量 + 麻油产量，吨 = 斤 ÷ 2000。能耗费用 = 全厂合计用量 × 未税单价。点日期看每块表的读数与用量。</p>
      <ReportTable :columns="rep.columns" :rows="rep.rows" :fixed="['date']" max-height="calc(100vh - 260px)">
        <template #date="{ row }">
          <el-button link type="primary" @click="openDay(row.date)">{{ row.date }}</el-button>
          <el-tooltip v-if="!row.complete" :content="row.notes || '合计不完整'"><el-tag size="small" type="warning">不完整</el-tag></el-tooltip>
        </template>
      </ReportTable>
    </div>

    <el-drawer v-model="drawer" :title="`抄表明细 ${detail?.date || ''}`" size="min(760px, 100%)">
      <template v-if="detail">
        <el-table :data="detail.meters" border size="small">
          <el-table-column label="能源" width="60"><template #default="{ row }">{{ ({ gas: '燃气', water: '水', elec: '电' })[row.energy] }}</template></el-table-column>
          <el-table-column prop="name" label="计量表" min-width="120" />
          <el-table-column label="上期" width="100" align="right"><template #default="{ row }"><span class="num">{{ fmtQ(row.prev) }}</span></template></el-table-column>
          <el-table-column label="本期" width="100" align="right"><template #default="{ row }"><span class="num">{{ fmtQ(row.reading) }}</span></template></el-table-column>
          <el-table-column label="倍率" width="90"><template #default="{ row }">{{ row.factor_text || row.factor }}</template></el-table-column>
          <el-table-column label="用量" width="100" align="right">
            <template #default="{ row }"><span class="num">{{ fmtQ(row.usage) }}</span><div v-if="row.note" class="muted">{{ row.note }}</div></template>
          </el-table-column>
          <el-table-column label="全厂/车间" width="96"><template #default="{ row }">{{ m(row.plant) }} / {{ m(row.workshop) }}</template></el-table-column>
        </el-table>
        <div v-if="detail.notes && detail.notes.length" class="notes"><div v-for="(n, i) in detail.notes" :key="i">· {{ n }}</div></div>
        <div class="sum">
          <div v-for="(v, k) in detail.summary" :key="k">
            <b>{{ ({ gas: '燃气', water: '水', elec: '电' })[k] }}</b>：全厂合计 {{ fmtQ(v.plant) }}
            <template v-if="k === 'water'">，车间合计 {{ fmtQ(v.workshop) }}</template>
            ；单价 {{ fmtP(v.price) }}，费用 {{ fmtM(v.cost) }} 元
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import RangePicker from '../../components/RangePicker.vue'
import ReportTable from '../../components/ReportTable.vue'
import { api, download } from '../../api'
import { store } from '../../store'
import { fmtM, fmtP, fmtQ } from '../../fmt'

const range = ref([store.day.slice(0, 8) + '01', store.day])
const loading = ref(false)
const rep = ref({ columns: [], rows: [] })
const drawer = ref(false)
const detail = ref(null)
const m = (x) => ({ '+': '计入', '-': '扣减', ref: '参考', '': '—' }[x] ?? x)
async function load() {
  loading.value = true
  try { rep.value = await api.get('/api/reports/energy-daily', { start: range.value[0], end: range.value[1] }) } finally { loading.value = false }
}
async function openDay(day) {
  detail.value = await api.get('/api/reports/energy-day', { day })
  drawer.value = true
}
watch(range, load, { immediate: true })
</script>

<style scoped>
.sum { margin-top: 12px; line-height: 2; font-size: 13px; }
.notes { margin-top: 10px; color: #b26a00; font-size: 13px; line-height: 1.8; }
</style>
