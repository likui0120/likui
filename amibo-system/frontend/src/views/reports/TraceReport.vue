<template>
  <div class="page">
    <div class="page-head">
      <h2>成本链路查询</h2>
      <el-select v-model="productId" filterable placeholder="选择产品" style="width: 200px">
        <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <DayPicker />
      <span class="spacer" />
      <el-button :disabled="!t" @click="download('/api/reports/export/trace', { product_id: productId, day: store.day })">导出 Excel</el-button>
    </div>

    <el-empty v-if="!productId" description="选择一个产品和日期，从 1 级原料逐级展开到成品" />
    <el-empty v-else-if="notFound" description="这一天没有这个产品的生产记录" />

    <template v-else-if="t">
      <div class="card">
        <div class="title-row">
          <span class="pname">{{ t.product.name }}</span>
          <el-tag size="small">{{ t.product.ptype }}</el-tag>
          <el-tag size="small" type="info">{{ t.product.team }}</el-tag>
          <el-tag v-if="t.quality" size="small" :type="qType(t.quality.status)">{{ t.quality.label }}</el-tag>
          <el-tag v-else-if="!t.ok" size="small" type="danger">未出成本</el-tag>
          <span class="muted" v-if="t.trace.bom">BOM 版本：{{ t.trace.bom.effective_date }} 起生效 · 锅数 {{ fmtQ(t.trace.batches) }} · 每锅投料 {{ fmtW(t.trace.per_batch) }} 斤</span>
        </div>
        <!-- 先给结论：最终单价、差额、全损 -->
        <div class="summary">
          <div><span class="muted">{{ finalLabel }}·实际</span><b class="num">{{ fmtP(finalA) }}</b></div>
          <div><span class="muted">标准</span><b class="num">{{ fmtP(finalS) }}</b></div>
          <div><span class="muted">差额（元/斤）</span><b class="num" :class="{ 'alert-text': Number(t.calc.diff_price) > 0 }">{{ fmtP(t.calc.diff_price) }}</b></div>
          <div><span class="muted">当日差额（元）</span><b class="num" :class="{ 'alert-text': Number(t.calc.diff_amount) > 0 }">{{ fmtM(t.calc.diff_amount) }}</b></div>
          <div v-if="t.loss_amount"><span class="muted">全损损失（元）</span><b class="num alert-text">{{ fmtM(t.loss_amount) }}</b></div>
        </div>
        <div v-if="t.quality && t.quality.flags.length" class="flags">
          <div v-for="(f, i) in t.quality.flags" :key="i">· {{ f }}</div>
        </div>
        <IssueBox :issues="t.issues.map((i) => ({ ...i, object_name: t.product.name }))" />
      </div>

      <!-- 麻油 -->
      <div v-if="t.product.ptype === '麻油'" class="card">
        <div class="flow">
          <div class="step"><div class="h">芝麻</div><div>用量 {{ fmtW(t.trace.sesame_qty) }} 斤</div><div>1 级单价 {{ fmtP(t.trace.price1) }}</div></div>
          <div class="arrow">→</div>
          <div class="step"><div class="h">麻油</div><div>产量 {{ fmtW(t.calc.output_weight) }} 斤</div>
            <div>出率 {{ fmtY(t.calc.cook_yield_actual) }} <span class="muted">标准 {{ fmtY(t.calc.cook_yield_std) }}</span></div>
            <div class="price">单价 {{ fmtP(t.calc.out_price_actual) }} <span class="muted">标准 {{ fmtP(t.calc.out_price_std) }}</span></div></div>
        </div>
      </div>

      <template v-else>
        <div class="card">
          <div class="sec">① 投料（1 级 → 2 级）</div>
          <el-table :data="t.trace.lines" border size="small">
            <el-table-column prop="line_no" label="行" width="44" />
            <el-table-column label="投料" min-width="150">
              <template #default="{ row }">
                <el-button v-if="row.kind === '半成品油' && row.date" link type="primary" @click="goUp(row)">{{ row.name }}</el-button>
                <span v-else>{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="kind" label="类型" width="96" />
            <el-table-column label="每锅（斤）" width="100" align="right"><template #default="{ row }"><span class="num">{{ fmtW(row.qty) }}</span></template></el-table-column>
            <el-table-column label="1 级单价" width="90" align="right"><template #default="{ row }"><span class="num">{{ fmtP(row.price1) }}</span></template></el-table-column>
            <el-table-column label="1→2 级出率" width="150" align="right">
              <template #default="{ row }">
                <template v-if="row.yield_source && row.yield_source !== 'fixed'">
                  <span class="num">{{ fmtY(row.yield_actual) }}</span>
                  <span v-if="row.yield_source === 'std'" class="std-tag">（用标准）</span>
                  <div class="muted">标准 {{ fmtY(row.yield_std) }}</div>
                </template>
                <span v-else-if="row.yield_source === 'fixed'" class="muted">100%（不处理）</span>
              </template>
            </el-table-column>
            <el-table-column label="单价·实际" width="96" align="right"><template #default="{ row }"><span class="num">{{ fmtP(row.price_actual) }}</span></template></el-table-column>
            <el-table-column label="单价·标准" width="96" align="right"><template #default="{ row }"><span class="num">{{ fmtP(row.price_std) }}</span></template></el-table-column>
            <el-table-column label="单价来源" min-width="160">
              <template #default="{ row }">
                <span class="muted">{{ source(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="当日投料成本（元）" width="130" align="right"><template #default="{ row }"><span class="num">{{ fmtM(row.cost_actual) }}</span></template></el-table-column>
          </el-table>
        </div>

        <div class="card">
          <div class="sec">② 逐级单价（元/斤）</div>
          <div class="flow">
            <div class="step">
              <div class="h">投料</div>
              <div>合计 {{ fmtW(t.calc.input_weight) }} 斤</div>
              <div>成本 {{ fmtM(t.calc.input_cost_actual) }} 元</div>
              <div class="muted">标准口径 {{ fmtM(t.calc.input_cost_std) }} 元</div>
            </div>
            <div class="arrow">→</div>
            <div class="step">
              <div class="h">{{ t.product.team === '拌馅组' ? '拌馅' : '熟制' }}</div>
              <div>出锅/出机重 {{ fmtW(t.calc.output_weight) }} 斤</div>
              <div>出率 {{ fmtY(t.calc.cook_yield_actual) }} <span class="muted">标准 {{ fmtY(t.calc.cook_yield_std) }}</span></div>
              <div class="price">出机单价 {{ fmtP(t.calc.out_price_actual) }}</div>
              <div class="muted">标准 {{ fmtP(t.calc.out_price_std) }}</div>
            </div>
            <template v-if="t.product.cooled">
              <div class="arrow">→</div>
              <div class="step">
                <div class="h">制冷 <span v-if="t.calc.cool_source === 'std'" class="std-tag">（缺记录，用标准）</span></div>
                <div>打冷出机重 {{ fmtW(t.calc.cooled_weight) }} 斤</div>
                <div>出率 {{ fmtY(t.calc.cool_yield_actual) }} <span class="muted">标准 {{ fmtY(t.calc.cool_yield_std) }}</span></div>
                <div class="price">冷后单价 {{ fmtP(t.calc.cooled_price_actual) }}</div>
                <div class="muted">标准 {{ fmtP(t.calc.cooled_price_std) }}</div>
              </div>
            </template>
            <template v-if="t.calc.packed_weight">
              <div class="arrow">→</div>
              <div class="step">
                <div class="h">包装</div>
                <div>包装前 {{ fmtW(t.calc.prepack_weight) }} → 入库 {{ fmtW(t.calc.packed_weight) }} 斤</div>
                <div>出率 {{ fmtY(t.calc.pack_yield_actual) }} <span class="muted">标准 {{ fmtY(t.calc.pack_yield_std) }}</span></div>
                <div>袋费 {{ fmtM(t.calc.bag_fee) }} 元 <span class="muted">（{{ fmtP(t.trace.bag_per_jin) }} 元/斤）</span></div>
                <div class="price">成品单价 {{ fmtP(t.calc.final_price_actual) }}</div>
                <div class="muted">标准 {{ fmtP(t.calc.final_price_std) }}</div>
              </div>
            </template>
          </div>
          <div v-if="t.trace.bags && t.trace.bags.length" class="muted bags">
            袋数：<span v-for="b in t.trace.bags" :key="b.spec_id">{{ b.spec }} {{ fmtQ(b.bags) }} 袋 × {{ fmtP(b.fee) }} 元；</span>
          </div>
        </div>
      </template>

      <div class="card" v-if="t.calc.diff_price !== null">
        <div class="sec">③ 实际与标准的差额：{{ fmtP(t.calc.diff_price) }} 元/斤，当日 {{ fmtM(t.calc.diff_amount) }} 元</div>
        <p class="hint">按固定顺序（各原料 1→2 级 → 上游投料价 → 熟制/拌馅 → 制冷 → 包装）依次把实际出率换成标准出率，看单价变化多少。各项相加等于总差额；单项大小与替换顺序有关，用来找“主要是哪一步”，不是唯一的责任划分。正数表示这一项让成本高于标准。</p>
        <el-table :data="t.attribution" border size="small" empty-text="实际出率与标准一致，没有差额">
          <el-table-column prop="factor" label="因素" min-width="200" />
          <el-table-column label="元/斤" width="120" align="right"><template #default="{ row }"><span class="num" :class="{ 'alert-text': row.per_jin > 0 }">{{ fmtP(row.per_jin) }}</span></template></el-table-column>
          <el-table-column label="当日金额（元）" width="140" align="right"><template #default="{ row }"><span class="num" :class="{ 'alert-text': row.amount > 0 }">{{ fmtM(row.amount) }}</span></template></el-table-column>
          <el-table-column label="" min-width="200">
            <template #default="{ row }"><div class="bar" :style="barStyle(row)" /></template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import DayPicker from '../../components/DayPicker.vue'
import IssueBox from '../../components/IssueBox.vue'
import { api, download } from '../../api'
import { store } from '../../store'
import { fmtM, fmtP, fmtQ, fmtW, fmtY } from '../../fmt'

const route = useRoute()
const products = ref([])
const productId = ref(route.query.product_id ? Number(route.query.product_id) : null)
if (route.query.day) store.day = String(route.query.day)
const t = ref(null)
const notFound = ref(false)
const qType = (s) => ({ complete: 'success', estimated: 'warning', partial: 'warning', loss: 'danger', none: 'danger' }[s] || 'info')
// 这个产品最终看哪一个单价：成品看成品单价，半成品油看冷后单价，其余看出机单价
const finalKey = computed(() => {
  const p = t.value?.product || {}
  if (p.ptype === '成品馅' && p.packed) return ['final', '成品单价']
  if (p.cooled && p.ptype !== '麻油') return ['cooled', '冷后单价']
  return ['out', '出机单价']
})
const finalLabel = computed(() => finalKey.value[1])
const finalA = computed(() => t.value?.calc[finalKey.value[0] + '_price_actual'])
const finalS = computed(() => t.value?.calc[finalKey.value[0] + '_price_std'])

let seq = 0
async function load() {
  const my = ++seq
  t.value = null
  notFound.value = false
  if (!productId.value) return
  try {
    const r = await api.get('/api/reports/trace', { product_id: productId.value, day: store.day }, { silent: true })
    if (my === seq) t.value = r
  } catch (e) {
    if (my === seq && e.status === 404) notFound.value = true
  }
}
function source(row) {
  if (row.kind === '水') return '水不计价'
  if (row.kind === '干调') return '干调价格表当天有效价'
  if (row.rule) return row.rule + (row.date ? `（${row.date}）` : row.from ? `（${row.from} 至 ${row.to}）` : '')
  if (row.price1 !== undefined) return '当天 1 级单价 ÷ 出率'
  return ''
}
function goUp(row) {
  const up = products.value.find((p) => p.name === row.name)
  if (up) { productId.value = up.id; store.day = row.date }
}
function barStyle(row) {
  const all = t.value.attribution.map((a) => Math.abs(Number(a.per_jin)))
  const max = Math.max(...all, 1e-12)
  const w = (Math.abs(Number(row.per_jin)) / max) * 100
  return { width: w + '%', background: Number(row.per_jin) > 0 ? '#e57373' : '#81c784' }
}
onMounted(async () => { products.value = await api.get('/api/products') })
watch([productId, () => store.day], load, { immediate: true })
</script>

<style scoped>
.title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pname { font-size: 18px; font-weight: 600; }
.sec { font-weight: 600; margin-bottom: 10px; }
.flow { display: flex; align-items: stretch; gap: 8px; flex-wrap: wrap; }
.step { border: 1px solid #dce3ea; border-radius: 8px; padding: 10px 12px; min-width: 190px; line-height: 1.8; font-size: 13px; background: #fafcfe; }
.step .h { font-weight: 600; color: #2f6f9f; }
.step .price { font-weight: 600; font-size: 14px; }
.arrow { display: flex; align-items: center; color: #8492a6; font-size: 20px; }
.bags { margin-top: 8px; }
.bar { height: 10px; border-radius: 3px; }
.summary { display: flex; flex-wrap: wrap; gap: 8px 28px; margin: 12px 0 4px; }
.summary > div { display: flex; flex-direction: column; }
.summary b { font-size: 20px; }
.flags { margin-top: 6px; color: #b26a00; font-size: 13px; line-height: 1.8; }
</style>
