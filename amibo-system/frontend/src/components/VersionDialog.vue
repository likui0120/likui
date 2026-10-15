<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(760px, 96vw)" @update:model-value="$emit('update:modelValue', $event)">
    <p class="hint">按生效日期保存版本，不覆盖历史：每天按当天有效的版本计算。改了以后，从生效日期起的数据会自动重算。</p>
    <el-table :data="rows" border size="small" empty-text="还没有版本">
      <el-table-column prop="effective_date" label="生效日期" width="120" />
      <el-table-column v-for="f in fields" :key="f.key" :label="f.label" min-width="100" :align="f.type === 'text' || f.type === 'select' || f.type === 'bool' ? 'left' : 'right'">
        <template #default="{ row }"><span class="num">{{ show(f, row[f.key]) }}</span></template>
      </el-table-column>
      <el-table-column label="" width="120">
        <template #default="{ row }">
          <el-button link size="small" @click="edit(row)">修改</el-button>
          <el-popconfirm title="删除这个版本？" @confirm="remove(row)"><template #reference><el-button link size="small" type="danger">删除</el-button></template></el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <div class="add"><el-button type="primary" @click="edit(null)">新增版本</el-button></div>
    <FormDialog v-model="formOpen" :title="editing ? '修改版本' : '新增版本'" :fields="formFields" :data="editing || defaults" :on-save="save" append-to-body />
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import FormDialog from './FormDialog.vue'
import { api } from '../api'
import { store } from '../store'
import { fmtBy, fmtY } from '../fmt'

const props = defineProps({
  modelValue: Boolean,
  title: String,
  endpoint: { type: String, required: true },
  fk: { type: String, required: true },
  fkValue: { type: [Number, String], default: null },
  fields: { type: Array, required: true },
})
const emit = defineEmits(['update:modelValue', 'changed'])
const all = ref([])
const formOpen = ref(false)
const editing = ref(null)
const defaults = computed(() => ({ effective_date: store.day }))
const formFields = computed(() => [{ key: 'effective_date', label: '生效日期', type: 'date', required: true }, ...props.fields])
const rows = computed(() => all.value.filter((r) => String(r[props.fk]) === String(props.fkValue))
  .sort((a, b) => (a.effective_date < b.effective_date ? 1 : -1)))

function show(f, v) {
  if (f.type === 'pct') return fmtY(v)
  if (f.type === 'bool') return v ? '是' : '否'
  if (f.type === 'select') {
    const o = (f.options || []).find((x) => (typeof x === 'object' ? x.value : x) === v)
    return o ? (typeof o === 'object' ? o.label : o) : v
  }
  if (f.type === 'num') return fmtBy(f.fmt || 'price', v)
  return v
}
async function load() { all.value = await api.get(props.endpoint) }
function edit(row) { editing.value = row; formOpen.value = true }
async function save(data) {
  const body = { ...data, [props.fk]: props.fkValue }
  if (editing.value) await api.put(`${props.endpoint}/${editing.value.id}`, body)
  else await api.post(props.endpoint, body)
  ElMessage.success('已保存，并已重算受影响的日期')
  await load()
  emitChanged()
}
async function remove(row) {
  await api.del(`${props.endpoint}/${row.id}`)
  await load()
  emitChanged()
}
function emitChanged() { emit('changed') }
watch(() => props.modelValue, (v) => { if (v) load() })
</script>

<style scoped>
.add { margin-top: 10px; }
</style>
