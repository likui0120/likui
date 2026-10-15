<template>
  <div class="page">
    <div class="page-head">
      <h2>预警阈值</h2>
      <span class="spacer" />
      <el-button type="primary" @click="edit(null)">新增阈值</el-button>
    </div>
    <div class="card">
      <p class="hint">实际出率与标准出率的偏差（百分点）超过阈值就标红，进入当日异常清单。优先级：某个原料 &gt; 某类原料 &gt; 全局默认；某个产品的某个环节 &gt; 所有产品的某个环节 &gt; 全局默认。全局默认现在是 {{ globalValue }} 个百分点（在“系统设置”里改）。</p>
      <el-table :data="list" border size="small" empty-text="还没有单独设置的阈值，全部用全局默认">
        <el-table-column label="适用范围" width="140"><template #default="{ row }">{{ scopeName(row.scope) }}</template></el-table-column>
        <el-table-column label="对象" min-width="200"><template #default="{ row }">{{ target(row) }}</template></el-table-column>
        <el-table-column label="阈值（百分点）" width="140" align="right"><template #default="{ row }"><span class="num">±{{ row.value }}</span></template></el-table-column>
        <el-table-column label="" width="120">
          <template #default="{ row }">
            <el-button link size="small" @click="edit(row)">修改</el-button>
            <el-popconfirm title="删除？" @confirm="remove(row)"><template #reference><el-button link size="small" type="danger">删除</el-button></template></el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <FormDialog v-model="open" :title="editing ? '修改阈值' : '新增阈值'" :fields="fields" :data="editing || {}" :on-save="save" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import FormDialog from '../../components/FormDialog.vue'
import { api } from '../../api'
import { store } from '../../store'

const list = ref([])
const mats = ref([])
const prods = ref([])
const globalValue = ref('3')
const open = ref(false)
const editing = ref(null)
const scopes = [
  { value: 'category', label: '某类原料' }, { value: 'material', label: '某个原料' },
  { value: 'stage', label: '某个环节（所有产品）' }, { value: 'product_stage', label: '某个产品的某个环节' },
]
const productStages = computed(() => (store.meta?.stages || []).filter((s) => s.key !== 'process').map((s) => ({ value: s.key, label: s.name })))
const scopeName = (s) => scopes.find((x) => x.value === s)?.label || s
const stageName = (k) => (store.meta?.stages || []).find((s) => s.key === k)?.name || k
function target(r) {
  if (r.scope === 'category') return r.category
  if (r.scope === 'material') return mats.value.find((m) => m.id === r.material_id)?.name
  if (r.scope === 'stage') return stageName(r.stage)
  if (r.scope === 'product_stage') return `${prods.value.find((p) => p.id === r.product_id)?.name} · ${stageName(r.stage)}`
  return ''
}
const fields = computed(() => [
  { key: 'scope', label: '适用范围', type: 'select', required: true, options: scopes },
  { key: 'category', label: '原料类别', type: 'select', show: (f) => f.scope === 'category', required: true, options: store.meta?.material_categories || [] },
  { key: 'material_id', label: '原料', type: 'select', show: (f) => f.scope === 'material', required: true,
    options: mats.value.filter((m) => m.needs_process).map((m) => ({ value: m.id, label: m.name })) },
  { key: 'product_id', label: '产品', type: 'select', show: (f) => f.scope === 'product_stage', required: true,
    options: prods.value.map((p) => ({ value: p.id, label: p.name })) },
  { key: 'stage', label: '环节', type: 'select', show: (f) => f.scope === 'stage' || f.scope === 'product_stage', required: true, options: productStages.value },
  { key: 'value', label: '阈值', type: 'num', unit: '百分点', required: true },
])
async function load() {
  const [l, m, p, s] = await Promise.all([api.get('/api/thresholds'), api.get('/api/materials'), api.get('/api/products'), api.get('/api/settings')])
  list.value = l.filter((x) => x.scope !== 'global')
  mats.value = m
  prods.value = p
  globalValue.value = s.find((x) => x.key === 'global_threshold')?.value
}
function edit(row) { editing.value = row; open.value = true }
async function save(d) {
  if (editing.value) await api.put(`/api/thresholds/${editing.value.id}`, d)
  else await api.post('/api/thresholds', d)
  load()
}
async function remove(row) { await api.del(`/api/thresholds/${row.id}`); load() }
onMounted(load)
</script>
