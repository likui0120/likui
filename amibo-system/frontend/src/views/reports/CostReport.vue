<template>
  <div class="page">
    <div class="page-head">
      <h2>成本日报</h2>
      <RangePicker v-model="range" />
      <el-select v-model="ptype" placeholder="全部类型" clearable style="width: 120px">
        <el-option v-for="t in store.meta?.product_types || []" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input v-model="kw" placeholder="产品名称" clearable style="width: 130px" />
      <span class="spacer" />
      <el-button @click="download('/api/reports/export/cost', { start: range[0], end: range[1] })">导出 Excel</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">单价单位 元/斤。标准单价 = 同样的公式把实际出率全部换成标准出率，单价仍用当天的，所以差额全部来自出率偏差。点产品名查看成本链路。</p>
      <ReportTable :columns="rep.columns" :rows="rows" :fixed="['date', 'name']">
        <template #name="{ row }">
          <el-button link type="primary" @click="$router.push({ path: '/r/trace', query: { product_id: row.product_id, day: row.date } })">{{ row.name }}</el-button>
          <el-tag v-if="!row.ok" type="danger" size="small">未出成本</el-tag>
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
const loading = ref(false)
const rep = ref({ columns: [], rows: [] })
const rows = computed(() => rep.value.rows.filter((r) => (!ptype.value || r.ptype === ptype.value) && (!kw.value || r.name.includes(kw.value))))
async function load() {
  loading.value = true
  try { rep.value = await api.get('/api/reports/cost', { start: range.value[0], end: range.value[1] }) } finally { loading.value = false }
}
watch(range, load, { immediate: true })
watch(() => store.day, (d) => { range.value = [d, d] })
</script>
