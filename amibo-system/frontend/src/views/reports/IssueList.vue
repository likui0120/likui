<template>
  <div class="page">
    <div class="page-head">
      <h2>异常清单</h2>
      <RangePicker v-model="range" />
      <el-radio-group v-model="kind">
        <el-radio-button value="alert">偏差超限</el-radio-button>
        <el-radio-button value="warning">提示</el-radio-button>
        <el-radio-button value="">全部</el-radio-button>
      </el-radio-group>
      <span class="spacer" />
      <el-button @click="download('/api/reports/export/issues', { start: range[0], end: range[1], kind })">导出 Excel</el-button>
    </div>
    <div class="card" v-loading="loading">
      <p class="hint">“偏差超限”是实际出率与标准出率差距超过阈值的项，供车间追查原因，查到原因后填在“原因备注”里，方便日后回看。“提示”是缺数、疑似录错等需要处理的情况。</p>
      <el-table :data="rep.rows" border size="small" :row-class-name="({ row }) => row.kind === 'alert' ? 'alert-row' : ''" max-height="calc(100vh - 230px)" empty-text="没有异常">
        <el-table-column prop="date" label="日期" width="100" />
        <el-table-column prop="kind_name" label="类型" width="64" />
        <el-table-column prop="name" label="对象" min-width="130" />
        <el-table-column prop="stage_name" label="环节" width="90" />
        <el-table-column label="实际" width="90" align="right"><template #default="{ row }"><span class="num">{{ fmtY(row.actual) }}</span></template></el-table-column>
        <el-table-column label="标准" width="90" align="right"><template #default="{ row }"><span class="num">{{ fmtY(row.std) }}</span></template></el-table-column>
        <el-table-column label="偏差" width="80" align="right"><template #default="{ row }"><span class="num alert-text">{{ fmtPP(row.dev) }}</span></template></el-table-column>
        <el-table-column prop="message" label="说明" min-width="260" />
        <el-table-column label="原因备注" min-width="220">
          <template #default="{ row }">
            <el-input v-model="row.note" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" placeholder="填写追查到的原因" @change="saveNote(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import RangePicker from '../../components/RangePicker.vue'
import { api, download } from '../../api'
import { store } from '../../store'
import { fmtPP, fmtY } from '../../fmt'

const range = ref([store.day, store.day])
const kind = ref('alert')
const loading = ref(false)
const rep = ref({ rows: [] })
async function load() {
  loading.value = true
  try { rep.value = await api.get('/api/reports/issues', { start: range.value[0], end: range.value[1], kind: kind.value }) } finally { loading.value = false }
}
async function saveNote(row) {
  await api.put('/api/reports/notes', { date: row.date, item_key: row.item_key, note: row.note })
  ElMessage.success('备注已保存')
}
watch([range, kind], load, { immediate: true })
watch(() => store.day, (d) => { range.value = [d, d] })
</script>
