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
    <div class="card" v-if="bk">
      <div style="font-weight: 600; margin-bottom: 8px">数据备份</div>
      <p class="hint">
        所有数据都在 <code>{{ bk.db_file }}</code>（{{ size(bk.db_size) }}）。系统开着时每天自动备份一份到 <code>{{ bk.dir }}</code>，保留最近 {{ bk.keep_auto }} 份。
        备份在同一块硬盘上，电脑坏了会一起丢，建议在下面设一个“另存目录”（U 盘或网盘同步文件夹），每次备份会同时复制一份过去；或者定期点“下载”存到别处。
      </p>
      <div class="bk-row">
        <span>另存目录</span>
        <el-input v-model="extraDir" placeholder="例如 E:\Amibo备份（不填就只存在本机）" style="width: 340px" clearable />
        <el-button :loading="savingDir" @click="saveDir">保存</el-button>
        <span class="spacer" />
        <el-button type="primary" :loading="backingUp" @click="backupNow">立即备份</el-button>
      </div>
      <el-table :data="bk.backups" size="small" max-height="360" empty-text="还没有备份">
        <el-table-column label="备份时间" width="170">
          <template #default="{ row }">{{ row.created_at.replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column prop="reason_text" label="类型" width="80" />
        <el-table-column label="大小" width="90" align="right">
          <template #default="{ row }">{{ size(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="name" label="文件" min-width="200" show-overflow-tooltip />
        <el-table-column label="" width="140" align="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="download(`/api/backups/${row.name}/download`)">下载</el-button>
            <el-button link type="danger" size="small" @click="restore(row)">恢复到此</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, download } from '../../api'

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

const bk = ref(null)
const extraDir = ref('')
const savingDir = ref(false)
const backingUp = ref(false)
const size = (n) => (n == null ? '' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')
async function loadBackups() {
  bk.value = await api.get('/api/backups')
  extraDir.value = bk.value.extra_dir
}
async function saveDir() {
  savingDir.value = true
  try {
    await api.put('/api/backups/config', { extra_dir: extraDir.value })
    ElMessage.success(extraDir.value ? '已保存，之后每次备份都会复制一份到这个目录' : '已取消另存目录')
    await loadBackups()
  } finally { savingDir.value = false }
}
async function backupNow() {
  backingUp.value = true
  try {
    const r = await api.post('/api/backups')
    if (r.extra_error) ElMessage.warning(`已备份到本机，但${r.extra_error}`)
    else ElMessage.success(r.extra ? '已备份，并已复制到另存目录' : '已备份')
    await loadBackups()
  } finally { backingUp.value = false }
}
async function restore(row) {
  const ok = await ElMessageBox.confirm(
    `把系统里的全部数据恢复成 ${row.created_at.replace('T', ' ')} 这份备份的样子？之后录入和修改的数据都会消失。` +
      '恢复前系统会先自动备份当前数据（类型“恢复前”），恢复错了可以再恢复回来。恢复时请确认没有人正在录入。',
    '恢复数据', { confirmButtonText: '恢复', cancelButtonText: '取消', type: 'warning' }).catch(() => false)
  if (!ok) return
  await api.post(`/api/backups/${row.name}/restore`)
  ElMessage.success('已恢复，页面会重新加载')
  setTimeout(() => window.location.reload(), 800)
}
onMounted(() => { load(); loadBackups() })
</script>

<style scoped>
.bk-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 6px 0 10px; font-size: 13px; }
.bk-row .spacer { flex: 1; }
code { background: #f2f5f8; padding: 0 4px; border-radius: 3px; font-size: 12px; word-break: break-all; }
</style>
