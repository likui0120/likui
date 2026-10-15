<template>
  <div class="page">
    <div class="page-head">
      <h2>出率日报</h2>
      <RangePicker v-model="range" />
      <el-select v-model="stage" placeholder="全部环节" clearable style="width: 130px">
        <el-option v-for="s in stages" :key="s.key" :label="s.name" :value="s.key" />
      </el-select>
      <el-input v-model="kw" placeholder="名称" clearable style="width: 130px" />
      <el-switch v-model="onlyAlert" active-text="只看超限" />
      <el-switch v-model="allMaterials" active-text="含不需处理的原料" />
      <span class="spacer" />
      <el-button @click="exportXlsx">导出 Excel</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">偏差 = 实际出率 − 标准出率（百分点），超过阈值标红。“取值”为“标准”表示当天没有处理记录，按标准出率计。</p>
      <ReportTable :columns="rep.columns" :rows="rows" :fixed="['date', 'stage_name', 'name']" />
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
const stage = ref('')
const kw = ref('')
const onlyAlert = ref(false)
const allMaterials = ref(false)
const loading = ref(false)
const rep = ref({ columns: [], rows: [] })
const stages = computed(() => store.meta?.stages || [])
const rows = computed(() => rep.value.rows.filter((r) =>
  (!stage.value || r.stage === stage.value) && (!kw.value || r.name.includes(kw.value)) && (!onlyAlert.value || r.alert)))
const params = () => ({ start: range.value[0], end: range.value[1], all_materials: allMaterials.value })
async function load() {
  loading.value = true
  try { rep.value = await api.get('/api/reports/yield', params()) } finally { loading.value = false }
}
const exportXlsx = () => download('/api/reports/export/yield', params())
watch([range, allMaterials], load, { immediate: true })
watch(() => store.day, (d) => { range.value = [d, d] })
</script>
