<template>
  <div class="page">
    <div class="page-head">
      <h2>能耗月报</h2>
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" style="width: 140px" />
      <span class="spacer" />
      <el-button @click="download('/api/reports/export/energy-month', { month })">导出 Excel</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">按日列出每块表用量、各合计、吨能耗和费用。月合计列的吨能耗 = 月合计用量 ÷ 月合计产量，不是日指标的平均。</p>
      <div v-if="rep.notes && rep.notes.length" class="notes"><div v-for="(n, i) in rep.notes" :key="i">· {{ n }}</div></div>
      <el-table :data="rep.lines" border size="small" :row-class-name="({ row }) => 'k-' + row.kind" max-height="calc(100vh - 230px)">
        <el-table-column prop="label" label="项目" width="190" fixed>
          <template #default="{ row }"><span :class="{ b: row.kind !== 'meter' }">{{ row.label }}</span><div v-if="row.note" class="muted">{{ row.note }}</div></template>
        </el-table-column>
        <el-table-column v-for="(d, i) in rep.days" :key="d" :label="d.slice(8) + '日'" width="82" align="right">
          <template #default="{ row }"><span class="num">{{ f(row, row.values[i]) }}</span></template>
        </el-table-column>
        <el-table-column label="月合计" width="110" align="right" fixed="right">
          <template #default="{ row }"><b class="num">{{ f(row, row.total) }}</b></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { api, download } from '../../api'
import { store } from '../../store'
import { fmtQ, fmtT } from '../../fmt'

const month = ref(store.day.slice(0, 7))
const loading = ref(false)
const rep = ref({ days: [], lines: [], notes: [] })
const f = (row, v) => (row.kind === 'index' ? fmtT(v) : fmtQ(v))
async function load() {
  loading.value = true
  try { rep.value = await api.get('/api/reports/energy-month', { month: month.value }) } finally { loading.value = false }
}
watch(month, load, { immediate: true })
</script>

<style scoped>
.b { font-weight: 600; }
.notes { margin: 0 0 10px; color: #5a6b7d; font-size: 13px; line-height: 1.8; }
:deep(.k-total td), :deep(.k-index td), :deep(.k-cost td) { background: #f5f8fb; }
</style>
