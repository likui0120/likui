<template>
  <div class="page">
    <div class="page-head"><h2>系统设置</h2></div>
    <div class="card">
      <el-form label-width="300px" style="max-width: 760px">
        <el-form-item v-for="s in list" :key="s.key" :label="s.label">
          <el-select v-if="s.key === 'sesame_rule'" v-model="s.value" style="width: 280px">
            <el-option value="rolling7" label="前 7 天按产量加权平均" />
            <el-option value="prev_week" label="上一自然周（周一至周日）按产量加权平均" />
          </el-select>
          <el-input v-else v-model="s.value" style="width: 280px" />
          <span class="muted" style="margin-left: 8px">默认 {{ s.default || '空' }}</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存（会全部重算）</el-button>
        </el-form-item>
      </el-form>
    </div>
    <div class="card">
      <div style="font-weight: 600; margin-bottom: 8px">重算</div>
      <p class="hint">平时录入、改资料后系统会自动重算受影响的日期，一般不需要手工重算。如果怀疑结果不对，可以从某天起全部重算。</p>
      <el-date-picker v-model="from" type="date" value-format="YYYY-MM-DD" placeholder="从最早一天" style="width: 160px" />
      <el-button style="margin-left: 8px" :loading="recalcing" @click="recalc">开始重算</el-button>
      <span v-if="result" class="muted" style="margin-left: 10px">重算了 {{ result.days }} 天（{{ result.from }} 至 {{ result.to }}），{{ result.alerts }} 项超限、{{ result.warnings }} 条提示</span>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api'

const list = ref([])
const saving = ref(false)
const recalcing = ref(false)
const from = ref(null)
const result = ref(null)
async function load() { list.value = await api.get('/api/settings') }
async function save() {
  saving.value = true
  try {
    list.value = await api.put('/api/settings', Object.fromEntries(list.value.map((s) => [s.key, s.value])))
    ElMessage.success('已保存并重算')
  } finally { saving.value = false }
}
async function recalc() {
  recalcing.value = true
  try { result.value = await api.post(`/api/recalc${from.value ? '?start=' + from.value : ''}`) } finally { recalcing.value = false }
}
onMounted(load)
</script>
