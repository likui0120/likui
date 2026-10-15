<template>
  <div class="page">
    <div class="page-head">
      <h2>成本日报</h2>
      <RangePicker v-model="range" />
      <el-select v-model="ptype" placeholder="全部类型" clearable style="width: 120px" aria-label="按产品类型筛选">
        <el-option v-for="t in store.meta?.product_types || []" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input v-model="kw" placeholder="产品名称" clearable style="width: 130px" aria-label="按产品名称筛选" />
      <el-switch v-model="allCols" active-text="显示全部列" />
      <span class="spacer" />
      <el-button @click="exportNow">导出 Excel{{ ptype || kw ? '（按当前筛选）' : '' }}</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">单价单位 元/斤。差额只表示<b>出率偏差</b>造成的原料和袋费成本差：标准单价用同样的公式，把实际出率全部换成标准出率，单价仍用当天的。不含采购价变化、人工、能耗。点产品名查看成本链路和差额归因。</p>
      <ReportTable :columns="rep.columns" :rows="rows" :hide="hidden" :fixed="['date', 'name']">
        <template #name="{ row }">
          <el-button link type="primary" @click="$router.push({ path: '/r/trace', query: { product_id: row.product_id, day: row.date } })">{{ row.name }}</el-button>
        </template>
        <template #quality="{ row }">
          <el-tooltip :disabled="!row.quality_flags" :content="row.quality_flags" placement="top">
            <el-tag :type="tagType(row.quality_status)" size="small">{{ row.quality }}</el-tag>
          </el-tooltip>
        </template>
      </ReportTable>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import RangePicker from '../../components/RangePicker.vue'
import ReportTable from '../../components/ReportTable.vue'
import { api, download } from '../../api'
import { store } from '../../store'

const range = ref([store.day, store.day])
const ptype = ref('')
const kw = ref('')
const allCols = ref(false)
const loading = ref(false)
const rep = ref({ columns: [], rows: [] })
// 默认只看关键结果；出机/冷后/袋费等过程单价打开“显示全部列”再看，导出始终是全部列
const DETAIL = ['team', 'input_cost', 'out_a', 'out_s', 'cooled_a', 'cooled_s', 'bag_fee', 'quality_flags']
const hidden = computed(() => (allCols.value ? [] : DETAIL))
const rows = computed(() => rep.value.rows.filter((r) => (!ptype.value || r.ptype === ptype.value) && (!kw.value || r.name.includes(kw.value))))
const tagType = (s) => ({ complete: 'success', estimated: 'warning', partial: 'warning', loss: 'danger', none: 'danger' }[s] || 'info')
let seq = 0
async function load() {
  const my = ++seq
  loading.value = true
  try {
    const r = await api.get('/api/reports/cost', { start: range.value[0], end: range.value[1] })
    if (my === seq) rep.value = r
  } finally {
    if (my === seq) loading.value = false
  }
}
function exportNow() {
  const p = { start: range.value[0], end: range.value[1] }
  if (ptype.value) p.ptype = ptype.value
  if (kw.value) p.kw = kw.value
  download('/api/reports/export/cost', p)
}
watch(range, load, { immediate: true })
watch(() => store.day, (d) => { range.value = [d, d] })
</script>
