<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(560px, 96vw)" @update:model-value="$emit('update:modelValue', $event)">
    <el-form :model="form" label-width="120px" @submit.prevent>
      <template v-for="f in fields" :key="f.key">
        <el-form-item v-if="!f.show || f.show(form)" :label="f.label" :required="f.required">
          <el-select v-if="f.type === 'select'" v-model="form[f.key]" :clearable="!f.required" filterable style="width: 100%">
            <el-option v-for="o in options(f)" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-switch v-else-if="f.type === 'bool'" v-model="form[f.key]" />
          <el-date-picker v-else-if="f.type === 'date'" v-model="form[f.key]" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          <el-input v-else-if="f.type === 'pct'" v-model="form[f.key]" inputmode="decimal"><template #append>%</template></el-input>
          <el-input v-else-if="f.type === 'num'" v-model="form[f.key]" inputmode="decimal"><template v-if="f.unit" #append>{{ f.unit }}</template></el-input>
          <el-input v-else-if="f.type === 'textarea'" v-model="form[f.key]" type="textarea" :rows="2" />
          <el-input v-else v-model="form[f.key]" />
          <div v-if="f.hint" class="hint">{{ f.hint }}</div>
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { pctIn, pctOut } from '../fmt'

const props = defineProps({
  modelValue: Boolean,
  title: String,
  fields: { type: Array, required: true },
  data: { type: Object, default: () => ({}) },
  onSave: { type: Function, required: true },
})
const emit = defineEmits(['update:modelValue'])
const form = ref({})
const saving = ref(false)
const options = (f) => (typeof f.options === 'function' ? f.options(form.value) : f.options || []).map((o) =>
  typeof o === 'object' ? o : { value: o, label: o })

watch(() => props.modelValue, (v) => {
  if (!v) return
  const o = {}
  for (const f of props.fields) {
    let x = props.data[f.key]
    if (x === undefined) x = f.default !== undefined ? (typeof f.default === 'function' ? f.default() : f.default) : f.type === 'bool' ? false : null
    o[f.key] = f.type === 'pct' ? pctOut(x) : x
  }
  form.value = o
})

async function submit() {
  for (const f of props.fields) {
    if (f.required && (!f.show || f.show(form.value)) && (form.value[f.key] === null || form.value[f.key] === '' || form.value[f.key] === undefined)) {
      ElMessage.warning(`请填写${f.label}`)
      return
    }
  }
  const out = {}
  for (const f of props.fields) out[f.key] = f.type === 'pct' ? pctIn(form.value[f.key]) : form.value[f.key]
  saving.value = true
  try {
    await props.onSave(out)
    emit('update:modelValue', false)
  } finally {
    saving.value = false
  }
}
</script>
