<template>
  <div class="page">
    <div class="page-head">
      <h2>产品</h2>
      <el-select v-model="team" placeholder="全部班组" clearable style="width: 130px">
        <el-option v-for="t in store.meta?.teams || []" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input v-model="kw" placeholder="名称" clearable style="width: 140px" />
      <span class="spacer" />
      <el-button type="primary" @click="edit(null)">新增产品</el-button>
    </div>
    <div class="card">
      <p class="hint">类型：成品馅（包装入库）、半成品油（走到制冷为止，次日投入拌馅）、麻油（芝麻 → 麻油）。标准出率显示 {{ store.day }} 当天有效的版本；麻油的“熟制”出率即麻油出率。</p>
      <el-table :data="rows" border size="small" max-height="calc(100vh - 230px)">
        <el-table-column prop="code" label="编码" width="100" />
        <el-table-column label="名称" min-width="150">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push({ path: '/m/boms', query: { product_id: row.id } })">{{ row.name }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="ptype" label="类型" width="90" />
        <el-table-column prop="team" label="班组" width="100" />
        <el-table-column label="制冷" width="56"><template #default="{ row }">{{ row.cooled ? '✓' : '' }}</template></el-table-column>
        <el-table-column label="包装" width="56"><template #default="{ row }">{{ row.packed ? '✓' : '' }}</template></el-table-column>
        <el-table-column label="熟制/拌馅标准" width="110" align="right"><template #default="{ row }"><span class="num">{{ fmtY(std(row)?.cook_yield) }}</span></template></el-table-column>
        <el-table-column label="制冷标准" width="90" align="right"><template #default="{ row }"><span class="num">{{ row.cooled ? fmtY(std(row)?.cool_yield) : '' }}</span></template></el-table-column>
        <el-table-column label="包装标准" width="90" align="right"><template #default="{ row }"><span class="num">{{ row.packed ? fmtY(std(row)?.pack_yield) : '' }}</span></template></el-table-column>
        <el-table-column label="启用" width="56"><template #default="{ row }">{{ row.active ? '' : '停用' }}</template></el-table-column>
        <el-table-column label="" width="190">
          <template #default="{ row }">
            <el-button link size="small" @click="edit(row)">修改</el-button>
            <el-button link size="small" type="primary" @click="openStd(row)">标准出率版本</el-button>
            <el-popconfirm title="删除这个产品？已有录入的不能删，可改成停用。" width="220" @confirm="remove(row)">
              <template #reference><el-button link size="small" type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <FormDialog v-model="open" :title="editing ? '修改产品' : '新增产品'" :fields="fields" :data="editing || {}" :on-save="save" />
    <VersionDialog v-model="stdOpen" :title="`标准出率 · ${stdFor?.name || ''}`" endpoint="/api/product-std-yields" fk="product_id"
                   :fk-value="stdFor?.id" :fields="stdFields" @changed="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import FormDialog from '../../components/FormDialog.vue'
import VersionDialog from '../../components/VersionDialog.vue'
import { api } from '../../api'
import { store } from '../../store'
import { fmtY } from '../../fmt'
import { attrVersionFields, currentVersion } from '../../versions'

const list = ref([])
const stds = ref([])
const mats = ref([])
const team = ref('')
const kw = ref('')
const open = ref(false)
const editing = ref(null)
const stdOpen = ref(false)
const stdFor = ref(null)
const rows = computed(() => list.value.filter((p) => (!team.value || p.team === team.value) && (!kw.value || p.name.includes(kw.value))))
const std = (p) => currentVersion(stds.value, 'product_id', p.id, store.day)
const fields = computed(() => [
  { key: 'code', label: '编码' },
  { key: 'name', label: '名称', required: true },
  { key: 'ptype', label: '类型', type: 'select', options: store.meta?.product_types || [], required: true, default: '成品馅' },
  { key: 'team', label: '生产班组', type: 'select', options: store.meta?.teams || [], required: true, default: '热加工' },
  { key: 'cooled', label: '经过制冷', type: 'bool', show: (f) => f.ptype !== '麻油' },
  { key: 'packed', label: '包装入库', type: 'bool', default: true, show: (f) => f.ptype === '成品馅' },
  { key: 'source_material_id', label: '芝麻原料', type: 'select', show: (f) => f.ptype === '麻油',
    options: mats.value.filter((m) => m.category === '芝麻').map((m) => ({ value: m.id, label: m.name })) },
  { key: 'fallback_price', label: '标准单价', type: 'num', unit: '元/斤', show: (f) => f.ptype !== '成品馅',
    hint: '下游产品投料时，若取不到历史实际单价就用这个价' },
  { key: 'unit_weight', label: '每袋/盒斤数', type: 'num', unit: '斤', hint: '预留：以后成品按袋或盒计量时用' },
  { key: 'sort', label: '排序', type: 'num', default: 0 },
  { key: 'active', label: '启用', type: 'bool', default: true },
  { key: 'note', label: '备注', type: 'textarea' },
  ...attrVersionFields(() => !!editing.value, '类型、班组、是否制冷、是否包装、芝麻原料'),
])
const stdFields = computed(() => {
  const p = stdFor.value || {}
  const f = [{ key: 'cook_yield', label: p.ptype === '麻油' ? '麻油出率' : '熟制/拌馅', type: 'pct' }]
  if (p.cooled) f.push({ key: 'cool_yield', label: '制冷', type: 'pct' })
  if (p.packed && p.ptype === '成品馅') f.push({ key: 'pack_yield', label: '包装', type: 'pct' })
  return f
})
async function load() {
  ;[list.value, stds.value, mats.value] = await Promise.all([api.get('/api/products'), api.get('/api/product-std-yields'), api.get('/api/materials')])
}
function edit(row) { editing.value = row; open.value = true }
async function save(data) {
  if (data.ptype !== '成品馅') data.packed = false
  if (editing.value) await api.put(`/api/products/${editing.value.id}`, data)
  else await api.post('/api/products', data)
  ElMessage.success('已保存')
  load()
}
async function remove(row) { await api.del(`/api/products/${row.id}`); load() }
function openStd(row) { stdFor.value = row; stdOpen.value = true }
onMounted(load)
</script>
