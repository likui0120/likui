<template>
  <div class="page">
    <div class="page-head">
      <h2>每日录入</h2>
      <DayPicker />
      <el-input v-model="kw" placeholder="按名称筛选" clearable style="width: 160px" />
      <el-switch v-model="onlyFilled" active-text="只看已填" />
      <span class="spacer" />
      <span v-if="dirty" class="muted">有未保存的修改</span>
    </div>

    <div class="card" v-loading="loading">
      <el-tabs v-model="tab">
        <!-- 原料处理 -->
        <el-tab-pane :label="`原料处理（${filledCount(data.process, ['qty1'])}）`" name="process">
          <p class="hint">需要 1→2 级处理的原料：填 1 级领用量和 2 级称重（斤）。没填的原料按标准出率计算。泡发类出率超过 100% 是正常的。</p>
          <el-table :data="view(data.process, ['qty1', 'qty2'])" border size="small" class="entry-table" max-height="calc(100vh - 330px)">
            <el-table-column prop="name" label="原料" min-width="130" fixed />
            <el-table-column prop="category" label="类别" width="70" />
            <el-table-column label="1 级领用量（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.qty1" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="2 级称重（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.qty2" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="实际出率" width="100" align="right">
              <template #default="{ row }"><span class="num" :class="devClass(ratio(row.qty2, row.qty1), row.std_yield)">{{ fmtY(ratio(row.qty2, row.qty1)) }}</span></template>
            </el-table-column>
            <el-table-column label="标准出率" width="100" align="right">
              <template #default="{ row }"><span class="num">{{ fmtY(row.std_yield) }}</span></template>
            </el-table-column>
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('process', data.process)">保存原料处理</el-button></div>
        </el-tab-pane>

        <!-- 制馅 -->
        <el-tab-pane :label="`制馅（${filledCount(data.production, ['batches'])}）`" name="production">
          <p class="hint">每个当天生产的产品：锅数/机数，以及出锅重（热加工）或出机重（拌馅）。投料合计 = 锅数 × BOM 每锅投料合计。</p>
          <el-table :data="view(data.production, ['batches', 'output_weight'])" border size="small" class="entry-table" max-height="calc(100vh - 330px)">
            <el-table-column prop="name" label="产品" min-width="140" fixed />
            <el-table-column prop="team" label="班组" width="96" />
            <el-table-column label="锅数/机数" min-width="100">
              <template #default="{ row }"><el-input v-model="row.batches" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="出锅重/出机重（斤）" min-width="140">
              <template #default="{ row }"><el-input v-model="row.output_weight" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="投料合计（斤）" width="120" align="right">
              <template #default="{ row }">
                <span v-if="!row.has_bom" class="alert-text">无 BOM</span>
                <span v-else class="num">{{ fmtW(mul(row.batches, row.per_batch)) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="实际出率" width="100" align="right">
              <template #default="{ row }"><span class="num" :class="devClass(ratio(row.output_weight, mul(row.batches, row.per_batch)), row.std_yield)">{{ fmtY(ratio(row.output_weight, mul(row.batches, row.per_batch))) }}</span></template>
            </el-table-column>
            <el-table-column label="标准出率" width="100" align="right">
              <template #default="{ row }"><span class="num">{{ fmtY(row.std_yield) }}</span></template>
            </el-table-column>
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('production', data.production)">保存制馅</el-button></div>
        </el-tab-pane>

        <!-- 麻油 -->
        <el-tab-pane label="麻油" name="sesame">
          <p class="hint">芝麻用量 → 麻油产量。麻油单价 = 芝麻 1 级单价 ÷ 麻油出率，麻油产量计入当日总产量。</p>
          <el-table :data="data.sesame" border size="small" class="entry-table">
            <el-table-column prop="name" label="产品" min-width="120" />
            <el-table-column label="芝麻用量（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.qty_in" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="麻油产量（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.output_weight" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="实际出率" width="100" align="right">
              <template #default="{ row }"><span class="num" :class="devClass(ratio(row.output_weight, row.qty_in), row.std_yield)">{{ fmtY(ratio(row.output_weight, row.qty_in)) }}</span></template>
            </el-table-column>
            <el-table-column label="标准出率" width="100" align="right">
              <template #default="{ row }"><span class="num">{{ fmtY(row.std_yield) }}</span></template>
            </el-table-column>
          </el-table>
          <div v-if="!data.sesame.length" class="muted">产品资料里还没有“麻油”类型的产品。</div>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('sesame', data.sesame)">保存麻油</el-button></div>
        </el-tab-pane>

        <!-- 制冷 -->
        <el-tab-pane :label="`制冷（${filledCount(data.cooling, ['cooled_weight'])}）`" name="cooling">
          <p class="hint">经过制冷的产品填打冷出机重。制冷出率 = 打冷出机重 ÷ 出锅重。出锅重来自“制馅”页（先保存制馅）。</p>
          <el-table :data="view(data.cooling, ['cooled_weight'])" border size="small" class="entry-table" max-height="calc(100vh - 330px)">
            <el-table-column prop="name" label="产品" min-width="140" fixed />
            <el-table-column label="出锅重（斤）" width="120" align="right">
              <template #default="{ row }"><span class="num">{{ fmtW(row.output_weight) }}</span></template>
            </el-table-column>
            <el-table-column label="打冷出机重（斤）" min-width="140">
              <template #default="{ row }"><el-input v-model="row.cooled_weight" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="实际出率" width="100" align="right">
              <template #default="{ row }"><span class="num" :class="devClass(ratio(row.cooled_weight, row.output_weight), row.std_yield)">{{ fmtY(ratio(row.cooled_weight, row.output_weight)) }}</span></template>
            </el-table-column>
            <el-table-column label="标准出率" width="100" align="right">
              <template #default="{ row }"><span class="num">{{ fmtY(row.std_yield) }}</span></template>
            </el-table-column>
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('cooling', data.cooling)">保存制冷</el-button></div>
        </el-tab-pane>

        <!-- 包装 -->
        <el-tab-pane :label="`包装（${filledCount(data.packing, ['packed_weight'])}）`" name="packing">
          <p class="hint">包装入库量单独录入，并填各规格袋数（用来算袋费）。包装前重量默认取上一环节产出（熟馅取打冷出机重，生馅取出机重），需要时可手工改。</p>
          <el-table :data="view(data.packing, ['packed_weight'])" border size="small" class="entry-table" max-height="calc(100vh - 330px)">
            <el-table-column prop="name" label="产品" min-width="140" fixed />
            <el-table-column label="包装前重量（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.prepack_weight" inputmode="decimal" :placeholder="row.default_prepack ? fmtW(row.default_prepack) : '先填上一环节'" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="包装入库量（斤）" min-width="130">
              <template #default="{ row }"><el-input v-model="row.packed_weight" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column v-for="sp in data.specs" :key="sp.spec_id" :label="`${sp.name}（袋）`" min-width="90">
              <template #default="{ row }"><el-input v-model="row.bags[sp.spec_id]" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column label="实际出率" width="96" align="right">
              <template #default="{ row }"><span class="num" :class="devClass(ratio(row.packed_weight, row.prepack_weight || row.default_prepack), row.std_yield)">{{ fmtY(ratio(row.packed_weight, row.prepack_weight || row.default_prepack)) }}</span></template>
            </el-table-column>
            <el-table-column label="袋数×斤数" width="100" align="right">
              <template #default="{ row }"><span class="num" :class="{ 'alert-text': bagGap(row) }">{{ fmtW(bagWeight(row)) }}</span></template>
            </el-table-column>
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('packing', data.packing)">保存包装</el-button></div>
        </el-tab-pane>

        <!-- 抄表 -->
        <el-tab-pane label="抄表" name="meters">
          <p class="hint">每块表只填本期读数，上期自动取之前最近一天的读数。光伏填当日发电量。换表当天点“换表”，填旧表最终读数和新表起始读数。</p>
          <el-table :data="view(data.meters, ['reading'])" border size="small" class="entry-table" max-height="calc(100vh - 330px)">
            <el-table-column label="能源" width="64"><template #default="{ row }">{{ energyName(row.energy) }}</template></el-table-column>
            <el-table-column prop="name" label="计量表" min-width="130" />
            <el-table-column label="上期读数" width="130" align="right">
              <template #default="{ row }"><span class="num">{{ row.mode === 'direct' ? '—' : fmtQ(row.prev) }}</span><div class="muted">{{ row.prev_date }}</div></template>
            </el-table-column>
            <el-table-column :label="'本期读数'" min-width="130">
              <template #default="{ row }">
                <el-input v-model="row.reading" inputmode="decimal" :placeholder="row.mode === 'direct' ? '当日用量' : ''" @input="touch" />
                <div v-if="row.replace" class="replace">
                  <el-input v-model="row.old_final" placeholder="旧表最终读数" inputmode="decimal" @input="touch" />
                  <el-input v-model="row.new_start" placeholder="新表起始读数" inputmode="decimal" @input="touch" />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="倍率" width="100"><template #default="{ row }">{{ row.factor_text || '×' + row.factor }}</template></el-table-column>
            <el-table-column label="用量" width="110" align="right">
              <template #default="{ row }"><span class="num" :class="{ 'alert-text': usage(row) !== null && usage(row) < 0 }">{{ fmtQ(usage(row)) }}</span></template>
            </el-table-column>
            <el-table-column label="计入" width="90">
              <template #default="{ row }">{{ modeName(row.plant) }}<span v-if="row.workshop"> / 车间{{ modeName(row.workshop) }}</span></template>
            </el-table-column>
            <el-table-column label="" width="70">
              <template #default="{ row }"><el-button v-if="row.mode === 'reading'" link size="small" @click="row.replace = !row.replace">换表</el-button></template>
            </el-table-column>
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="save('meters', data.meters)">保存抄表</el-button></div>
        </el-tab-pane>

        <!-- 原料单价 -->
        <el-tab-pane :label="`原料单价（${filledCount(data.prices, ['price'])}）`" name="prices">
          <div class="upload-row">
            <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx,.csv" :on-change="uploadTplus">
              <el-button type="primary">上传 T+ 导出的 Excel</el-button>
            </el-upload>
            <span>表里没有“计量单位”列时，单价单位按</span>
            <el-radio-group v-model="tplusUnit" size="small">
              <el-radio-button value="jin">元/斤</el-radio-button>
              <el-radio-button value="kg">元/公斤</el-radio-button>
            </el-radio-group>
            <el-button link type="primary" @click="download('/api/import/template/tplus')">样例格式</el-button>
          </div>
          <p class="hint">导入后单价记到当前选择的日期（{{ store.day }}）。按存货编码优先、名称其次匹配原料；同一原料多行时按金额 ÷ 数量加权。也可以在下面手工填写或修改（元/斤）。缺单价的产品不出成本，系统不会自动取旧价。</p>
          <el-alert v-if="tplusResult" :type="tplusResult.unmatched.length || tplusResult.bad.length ? 'warning' : 'success'" :closable="true" @close="tplusResult = null" class="mb">
            <template #title>导入 {{ tplusResult.matched.length }} 个原料的单价；{{ tplusResult.unmatched.length }} 行没匹配上{{ tplusResult.bad.length ? `，${tplusResult.bad.length} 行有问题` : '' }}</template>
            <div v-for="u in tplusResult.unmatched" :key="'u' + u.row">第 {{ u.row }} 行：{{ u.code || '' }} {{ u.name }} 在原料资料里找不到（可在“基础资料 → 原料”里新增或补编码后重新导入）</div>
            <div v-for="u in tplusResult.bad" :key="'b' + u.row">第 {{ u.row }} 行：{{ u.name }} {{ u.reason }}</div>
          </el-alert>
          <el-table :data="view(data.prices, ['price'])" border size="small" class="entry-table" max-height="calc(100vh - 380px)">
            <el-table-column prop="name" label="原料" min-width="140" />
            <el-table-column prop="code" label="编码" width="110" />
            <el-table-column prop="category" label="类别" width="70" />
            <el-table-column label="1 级单价（元/斤）" min-width="140">
              <template #default="{ row }"><el-input v-model="row.price" inputmode="decimal" @input="touch" /></template>
            </el-table-column>
            <el-table-column prop="source" label="来源" min-width="120" show-overflow-tooltip />
          </el-table>
          <div class="actions"><el-button type="primary" :loading="saving" @click="savePrices">保存单价</el-button></div>
        </el-tab-pane>
      </el-tabs>
      <IssueBox :issues="data.issues" />
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import DayPicker from '../components/DayPicker.vue'
import IssueBox from '../components/IssueBox.vue'
import { api, download } from '../api'
import { store } from '../store'
import { fmtQ, fmtW, fmtY } from '../fmt'

const tab = ref('process')
const kw = ref('')
const onlyFilled = ref(false)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const tplusUnit = ref('jin')
const tplusResult = ref(null)
const data = reactive({ process: [], production: [], sesame: [], cooling: [], packing: [], specs: [], meters: [], prices: [], issues: [] })

const touch = () => { dirty.value = true }
const has = (v) => v !== null && v !== undefined && v !== ''
const num = (v) => (has(v) ? Number(v) : null)
const ratio = (a, b) => (num(a) !== null && num(b) ? num(a) / num(b) : null)
const mul = (a, b) => (num(a) !== null && num(b) !== null ? num(a) * num(b) : null)
const filledCount = (rows, keys) => rows.filter((r) => keys.some((k) => has(r[k]))).length
function view(rows, keys) {
  let out = rows
  if (kw.value) out = out.filter((r) => (r.name || '').includes(kw.value) || (r.code || '').includes(kw.value))
  if (onlyFilled.value) out = out.filter((r) => keys.some((k) => has(r[k])))
  return out
}
function devClass(actual, std) {
  if (actual === null || !has(std)) return ''
  return Math.abs((actual - Number(std)) * 100) > 3 ? 'alert-text' : 'ok-text'
}
function bagWeight(row) {
  let w = 0
  let any = false
  for (const sp of data.specs) {
    const n = num(row.bags[sp.spec_id])
    if (n) { w += n * Number(sp.bag_weight); any = true }
  }
  return any ? w : null
}
function bagGap(row) {
  const w = bagWeight(row)
  const p = num(row.packed_weight)
  return w !== null && p ? Math.abs(w - p) / p > 0.05 : false
}
function usage(row) {
  if (!has(row.reading)) return null
  const f = Number(row.factor)
  if (row.mode === 'direct') return Number(row.reading) * f
  if (has(row.new_start)) {
    let d = Number(row.reading) - Number(row.new_start)
    if (has(row.old_final) && has(row.prev)) d += Number(row.old_final) - Number(row.prev)
    return d * f
  }
  if (!has(row.prev)) return null
  return (Number(row.reading) - Number(row.prev)) * f
}
const energyName = (e) => ({ gas: '燃气', water: '水', elec: '电' }[e] || e)
const modeName = (m) => ({ '+': '计入', '-': '扣减', ref: '参考', '': '—' }[m] ?? m)

async function load() {
  loading.value = true
  try {
    const d = await api.get(`/api/daily/${store.day}`)
    d.meters.forEach((m) => { m.replace = has(m.new_start) })
    Object.assign(data, d)
    dirty.value = false
  } finally {
    loading.value = false
  }
}

async function save(section, rows) {
  saving.value = true
  try {
    const r = await api.put(`/api/daily/${store.day}/${section}`, rows)
    data.issues = r.issues
    const alerts = r.issues.filter((i) => i.kind === 'alert').length
    ElMessage.success(`已保存并重算 ${r.recalc.days} 天${alerts ? `，当天有 ${alerts} 项偏差超限` : ''}`)
    await load()
  } finally {
    saving.value = false
  }
}

async function savePrices() {
  saving.value = true
  try {
    await api.put(`/api/material-prices/${store.day}`, data.prices.map((p) => ({ material_id: p.material_id, price: p.price })))
    ElMessage.success('单价已保存并重算')
    await load()
  } finally {
    saving.value = false
  }
}

async function uploadTplus(file) {
  const fd = new FormData()
  fd.append('day', store.day)
  fd.append('unit', tplusUnit.value)
  fd.append('file', file.raw)
  loading.value = true
  try {
    tplusResult.value = await api.post('/api/import/tplus', fd)
    await load()
  } finally {
    loading.value = false
  }
}

let lastDay = store.day
let reverting = false
watch(() => store.day, async (v) => {
  if (reverting) { reverting = false; return }
  if (dirty.value) {
    try {
      await ElMessageBox.confirm('当前日期有未保存的修改，切换日期会丢掉这些修改。', '提示', { confirmButtonText: '丢掉并切换', cancelButtonText: '留在这里' })
    } catch (_) {
      reverting = true
      store.day = lastDay
      return
    }
  }
  lastDay = v
  tplusResult.value = null
  load()
})
load()

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的修改，离开会丢掉这些修改。', '提示', { confirmButtonText: '离开', cancelButtonText: '留在这里' })
    return true
  } catch (_) {
    return false
  }
})
const beforeUnload = (e) => { if (dirty.value) { e.preventDefault(); e.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.actions { margin-top: 12px; }
.upload-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; font-size: 13px; }
.replace { display: flex; gap: 4px; margin-top: 4px; }
.mb { margin-bottom: 10px; }
</style>
