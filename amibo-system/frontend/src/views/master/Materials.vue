<template>
  <div class="page">
    <div class="page-head">
      <h2>原料</h2>
      <el-select v-model="cat" placeholder="全部类别" clearable style="width: 120px">
        <el-option v-for="c in store.meta?.material_categories || []" :key="c" :label="c" :value="c" />
      </el-select>
      <el-input v-model="kw" placeholder="名称或编码" clearable style="width: 150px" />
      <span class="spacer" />
      <el-button @click="$router.push('/m/imports')">Excel 批量导入</el-button>
      <el-button type="primary" @click="edit(null)">新增原料</el-button>
    </div>
    <div class="card">
      <p class="hint">原料包括干调、水、芝麻。类别决定单价取法：干调取“干调价格”，水为 0 元，其他取当天 T+ 的 1 级单价。“需要处理”的原料按 1→2 级出率折算 2 级单价，不需要处理的固定 100%。标准出率显示的是 {{ store.day }} 当天有效的版本。</p>
      <el-table :data="rows" border size="small" max-height="calc(100vh - 230px)">
        <el-table-column prop="code" label="编码" width="110" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="category" label="类别" width="80" />
        <el-table-column label="需要处理" width="86"><template #default="{ row }">{{ row.needs_process ? '是' : '' }}</template></el-table-column>
        <el-table-column label="标准出率" width="110" align="right">
          <template #default="{ row }">
            <template v-if="row.needs_process">
              <span v-if="std(row)" class="num">{{ fmtY(std(row).std_yield) }}</span>
              <span v-else class="alert-text">未设</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="60"><template #default="{ row }">{{ row.active ? '' : '停用' }}</template></el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="" width="200">
          <template #default="{ row }">
            <el-button link size="small" @click="edit(row)">修改</el-button>
            <el-button v-if="row.needs_process" link size="small" type="primary" @click="openStd(row)">标准出率版本</el-button>
            <el-popconfirm title="删除这个原料？已被录入或 BOM 引用的不能删，可改成停用。" width="240" @confirm="remove(row)">
              <template #reference><el-button link size="small" type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <FormDialog v-model="open" :title="editing ? '修改原料' : '新增原料'" :fields="fields" :data="editing || {}" :on-save="save" />
    <VersionDialog v-model="stdOpen" :title="`标准出率 · ${stdFor?.name || ''}`" endpoint="/api/material-std-yields" fk="material_id"
                   :fk-value="stdFor?.id" :fields="[{ key: 'std_yield', label: '标准出率', type: 'pct', required: true, hint: '泡发类可超过 100%，如 260' }]" @changed="load" />
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
const cat = ref('')
const kw = ref('')
const open = ref(false)
const editing = ref(null)
const stdOpen = ref(false)
const stdFor = ref(null)
const rows = computed(() => list.value.filter((m) => (!cat.value || m.category === cat.value) &&
  (!kw.value || m.name.includes(kw.value) || (m.code || '').includes(kw.value))))
const std = (m) => currentVersion(stds.value, 'material_id', m.id, store.day)
const fields = computed(() => [
  { key: 'code', label: '编码', hint: '与 T+ 存货编码一致，导入单价时优先按编码匹配' },
  { key: 'name', label: '名称', required: true },
  { key: 'category', label: '类别', type: 'select', options: store.meta?.material_categories || [], required: true, default: '其他' },
  { key: 'needs_process', label: '需要 1→2 级处理', type: 'bool' },
  { key: 'active', label: '启用', type: 'bool', default: true },
  { key: 'note', label: '备注', type: 'textarea' },
  ...attrVersionFields(() => !!editing.value, '类别、是否需要处理'),
])
async function load() {
  ;[list.value, stds.value] = await Promise.all([api.get('/api/materials'), api.get('/api/material-std-yields')])
}
function edit(row) { editing.value = row; open.value = true }
async function save(data) {
  if (editing.value) await api.put(`/api/materials/${editing.value.id}`, data)
  else await api.post('/api/materials', data)
  ElMessage.success('已保存')
  load()
}
async function remove(row) { await api.del(`/api/materials/${row.id}`); load() }
function openStd(row) { stdFor.value = row; stdOpen.value = true }
onMounted(load)
</script>
