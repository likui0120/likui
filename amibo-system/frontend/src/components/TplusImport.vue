<template>
  <div>
    <div class="upload-row">
      <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx,.xls,.csv" :on-change="pick">
        <el-button type="primary" :loading="busy">上传 T+ 导出的 Excel</el-button>
      </el-upload>
      <span>表里没有“计量单位”列时，单价单位按</span>
      <el-radio-group v-model="unit" size="small">
        <el-radio-button value="jin">元/斤</el-radio-button>
        <el-radio-button value="kg">元/公斤</el-radio-button>
      </el-radio-group>
      <el-button link type="primary" @click="download('/api/import/template/tplus')">样例格式</el-button>
      <el-button link type="primary" @click="openHistory">导入记录{{ history.length ? `（${history.length}）` : '' }}</el-button>
    </div>
    <p class="hint">
      上传后先预览，核对无误再点“确认导入”，单价记到当前日期（{{ day }}）。按存货编码优先、名称其次匹配原料；同一原料多行时按数量加权平均。
      支持 .xlsx、旧版 .xls 和 .csv。也可以在下面手工填写或修改（元/斤）。缺单价的产品不出成本，系统不会自动取旧价。
    </p>
    <el-alert v-if="done" type="success" :closable="true" class="mb" @close="done = null"
      :title="`已导入 ${done.items.length} 个原料的单价${done.unmatched.length ? `；${done.unmatched.length} 行没匹配上` : ''}`">
      <span>想退回导入前的单价，可以在“导入记录”里撤销这次导入。</span>
    </el-alert>

    <!-- 预览 -->
    <el-dialog v-model="show" title="核对 T+ 单价" width="min(1100px, 96vw)" top="4vh" :close-on-click-modal="false">
      <template v-if="pv">
        <div class="pv-head">
          <span>文件：{{ pv.file }}</span>
          <span>记到：<b>{{ day }}</b></span>
          <span>
            单价列：
            <el-select v-if="pv.price_cols.length > 1" :model-value="pv.price_col" size="small" style="width: 150px" @change="reprice">
              <el-option v-for="c in pv.price_cols" :key="c.name" :label="`${c.name}（${c.tax}）`" :value="c.name" />
            </el-select>
            <b v-else>{{ pv.price_col }}</b>
            <el-tag size="small" :type="pv.price_tax === '含税' ? 'warning' : 'info'" class="ml">{{ pv.price_tax }}</el-tag>
          </span>
          <span v-if="pv.unit_default">表里没有单位列，按 {{ pv.unit_default }}</span>
        </div>
        <el-alert v-if="pv.price_tax === '含税'" type="warning" :closable="false" class="mb"
          title="用的是含税单价。能耗单价按未税计，原料单价一般也用不含税单价，确认一下口径。" />
        <div class="pv-sum">
          <span>能导入 <b>{{ pv.items.length }}</b> 个原料</span>
          <span :class="{ 'alert-text': pv.flagged }">需要核对 <b>{{ pv.flagged }}</b> 个</span>
          <span :class="{ 'alert-text': pv.unmatched.length }">没匹配上 <b>{{ pv.unmatched.length }}</b> 行</span>
          <span v-if="pv.bad.length" class="alert-text">跳过 <b>{{ pv.bad.length }}</b> 行</span>
        </div>
        <el-table :data="pv.items" size="small" border max-height="52vh" :row-class-name="({ row }) => (row.notes.length ? 'flag-row' : '')">
          <el-table-column label="原料" min-width="130">
            <template #default="{ row }">
              {{ row.name }}
              <div v-if="row.file_names.length" class="muted">T+：{{ row.file_names.join('、') }}</div>
            </template>
          </el-table-column>
          <el-table-column label="匹配" width="64" prop="match" />
          <el-table-column label="行号" width="80">
            <template #default="{ row }">{{ row.rows.join(',') }}</template>
          </el-table-column>
          <el-table-column label="导入单价（元/斤）" width="130" align="right">
            <template #default="{ row }"><b class="num">{{ fmtP(row.price) }}</b></template>
          </el-table-column>
          <el-table-column label="当天已有" width="120" align="right">
            <template #default="{ row }">
              <span v-if="row.old_price !== null" class="num">{{ fmtP(row.old_price) }}</span>
              <div v-if="row.old_source" class="muted">{{ row.old_source }}</div>
            </template>
          </el-table-column>
          <el-table-column label="上次单价" width="120" align="right">
            <template #default="{ row }">
              <span v-if="row.prev_price !== null" class="num">{{ fmtP(row.prev_price) }}</span>
              <div v-if="row.prev_date" class="muted">{{ row.prev_date }}</div>
            </template>
          </el-table-column>
          <el-table-column label="变化" width="80" align="right">
            <template #default="{ row }">
              <span v-if="row.change !== null" class="num" :class="{ 'alert-text': Math.abs(row.change) > 0.3 }">{{ pct(row.change) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="需要核对" min-width="220">
            <template #default="{ row }">
              <div v-for="(n, i) in row.notes" :key="i" class="note">{{ n }}</div>
              <div v-for="(n, i) in row.info" :key="'i' + i" class="muted">{{ n }}</div>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="pv.unmatched.length" class="extra">
          <div class="extra-title">没匹配上的行（去“基础资料 → 原料”新增，或给原料补上 T+ 编码后重新上传）</div>
          <div v-for="u in pv.unmatched" :key="'u' + u.row" class="muted">第 {{ u.row }} 行：{{ u.code || '' }} {{ u.name }}{{ u.price ? `，单价 ${u.price}` : '' }}</div>
        </div>
        <div v-if="pv.bad.length" class="extra">
          <div class="extra-title">跳过的行</div>
          <div v-for="u in pv.bad" :key="'b' + u.row" class="muted">第 {{ u.row }} 行：{{ u.code || '' }} {{ u.name }}，{{ u.reason }}</div>
        </div>
      </template>
      <template #footer>
        <el-button @click="show = false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!pv || !pv.items.length" @click="commit">
          确认导入 {{ pv ? pv.items.length : 0 }} 个单价
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入记录 -->
    <el-drawer v-model="showHistory" :title="`${day} 的 T+ 导入记录`" size="min(560px, 96vw)">
      <el-empty v-if="!history.length" description="这一天还没有导入过" />
      <div v-for="b in history" :key="b.id" class="batch card">
        <div class="batch-head">
          <b>#{{ b.id }}</b>
          <span>{{ b.created_at?.replace('T', ' ') }}</span>
          <el-tag v-if="b.undone_at" size="small" type="info">已撤销</el-tag>
          <span class="spacer" />
          <el-button size="small" link type="primary" @click="toggle(b)">{{ b.detail ? '收起' : '明细' }}</el-button>
          <el-button v-if="!b.undone_at" size="small" type="danger" plain @click="undo(b)">撤销</el-button>
        </div>
        <div class="muted">{{ b.filename }} · 单价列 {{ b.price_col }} · 导入 {{ b.matched }} 个，没匹配 {{ b.unmatched }} 行，需核对 {{ b.flagged }} 个</div>
        <el-table v-if="b.detail" :data="b.detail" size="small" class="mt">
          <el-table-column prop="name" label="原料" />
          <el-table-column label="导入前" align="right">
            <template #default="{ row }">{{ row.old_price === null ? '（没有）' : fmtP(row.old_price) }}</template>
          </el-table-column>
          <el-table-column label="导入" align="right">
            <template #default="{ row }">{{ fmtP(row.new_price) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, download } from '../api'
import { fmtP } from '../fmt'

const props = defineProps({ day: { type: String, required: true } })
const emit = defineEmits(['imported'])

const unit = ref('jin')
const busy = ref(false)
const show = ref(false)
const pv = ref(null)
const done = ref(null)
const showHistory = ref(false)
const history = ref([])
let file = null
let priceCol = null

const pct = (v) => (Number(v) > 0 ? '+' : '') + (Number(v) * 100).toFixed(1) + '%'

function form(preview) {
  const fd = new FormData()
  fd.append('day', props.day)
  fd.append('unit', unit.value)
  fd.append('file', file)
  if (preview) fd.append('preview', 'true')
  if (priceCol) fd.append('price_col', priceCol)
  return fd
}

async function preview() {
  busy.value = true
  try {
    pv.value = await api.post('/api/import/tplus', form(true))
    show.value = true
  } finally {
    busy.value = false
  }
}

function pick(f) {
  file = f.raw
  priceCol = null
  done.value = null
  preview()
}

function reprice(name) {
  priceCol = name
  preview()
}

async function commit() {
  busy.value = true
  try {
    done.value = await api.post('/api/import/tplus', form(false))
    show.value = false
    ElMessage.success('单价已导入并重算')
    emit('imported')
    loadHistory()
  } finally {
    busy.value = false
  }
}

async function loadHistory() {
  history.value = await api.get('/api/import/batches', { day: props.day }, { silent: true }).catch(() => [])
}

function openHistory() {
  showHistory.value = true
  loadHistory()
}

async function toggle(b) {
  if (b.detail) { b.detail = null; return }
  b.detail = (await api.get(`/api/import/batches/${b.id}`)).detail
}

async function undo(b) {
  const ok = await ElMessageBox.confirm(`把 #${b.id} 这次导入的 ${b.matched} 个单价恢复成导入前的值？导入后又手工改过的原料不会动。`, '撤销导入',
    { confirmButtonText: '撤销', cancelButtonText: '取消', type: 'warning' }).catch(() => false)
  if (!ok) return
  const r = await api.post(`/api/import/batches/${b.id}/undo`)
  done.value = null
  ElMessage.success(`已恢复 ${r.restored.length} 个单价${r.skipped.length ? `，${r.skipped.length} 个导入后改过的没动` : ''}`)
  emit('imported')
  loadHistory()
}

watch(() => props.day, () => { done.value = null; loadHistory() }, { immediate: true })
</script>

<style scoped>
.upload-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; font-size: 13px; }
.pv-head, .pv-sum { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; margin-bottom: 10px; font-size: 13px; }
.pv-sum b { font-size: 15px; }
.ml { margin-left: 6px; }
.mt { margin-top: 8px; }
.mb { margin-bottom: 10px; }
.note { color: #c45656; line-height: 1.5; }
.extra { margin-top: 12px; font-size: 13px; line-height: 1.8; }
.extra-title { font-weight: 600; }
.batch { margin-bottom: 10px; }
.batch-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.batch-head .spacer { flex: 1; }
:deep(.flag-row) { background: #fdf6ec; }
</style>
