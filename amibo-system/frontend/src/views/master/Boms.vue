<template>
  <div class="page">
    <div class="page-head">
      <h2>BOM</h2>
      <el-select v-model="productId" filterable placeholder="选择产品" style="width: 220px">
        <el-option v-for="p in products.filter((x) => x.ptype !== '麻油')" :key="p.id" :label="`${p.name}（${p.team}）`" :value="p.id" />
      </el-select>
      <el-select v-if="versions.length" v-model="bomId" style="width: 200px">
        <el-option v-for="b in versions" :key="b.id" :label="`${b.effective_date} 起生效`" :value="b.id" />
      </el-select>
      <span class="spacer" />
      <el-button @click="$router.push('/m/imports')">从 Excel 导入</el-button>
      <el-button v-if="productId" type="primary" @click="newVersion">新建版本</el-button>
    </div>
    <el-empty v-if="!productId" description="选择一个产品查看或编辑它的 BOM" />
    <div v-else class="card">
      <p class="hint">每锅（每机）投多少斤，含水、油、调料。一个产品同一时间只有一个有效 BOM；改配方请“新建版本”填生效日期，历史日期仍按当时的版本计算。同一种投料可以分多行（如分两次下锅），计算时合并。</p>
      <div v-if="draft" class="draft-head">
        <span>生效日期</span>
        <el-date-picker v-model="draft.effective_date" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 150px" />
        <el-input v-model="draft.note" placeholder="备注" style="width: 240px" />
        <span class="spacer" />
        <b>每锅投料合计：<span class="num">{{ fmtW(total) }}</span> 斤</b>
      </div>
      <el-table v-if="draft" :data="draft.lines" border size="small" class="entry-table">
        <el-table-column label="行号" width="70"><template #default="{ row }"><el-input v-model="row.line_no" /></template></el-table-column>
        <el-table-column label="投料" min-width="220">
          <template #default="{ row }">
            <el-select v-model="row.ref" filterable placeholder="原料 / 干调 / 水 / 半成品油 / 麻油" style="width: 100%">
              <el-option-group label="原料、干调、水">
                <el-option v-for="m in materials" :key="'m' + m.id" :label="`${m.name}（${m.category}${m.needs_process ? '·需处理' : ''}）`" :value="'m' + m.id" />
              </el-option-group>
              <el-option-group label="半成品油、麻油">
                <el-option v-for="p in upstream" :key="'p' + p.id" :label="`${p.name}（${p.ptype}）`" :value="'p' + p.id" />
              </el-option-group>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="每锅数量（斤）" width="160"><template #default="{ row }"><el-input v-model="row.qty" inputmode="decimal" /></template></el-table-column>
        <el-table-column label="备注" min-width="140"><template #default="{ row }"><el-input v-model="row.note" /></template></el-table-column>
        <el-table-column label="" width="110">
          <template #default="{ $index }">
            <el-button link size="small" @click="draft.lines.splice($index + 1, 0, blank())">插入</el-button>
            <el-button link size="small" type="danger" @click="draft.lines.splice($index, 1)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="draft" class="actions">
        <el-button @click="draft.lines.push(blank())">添加一行</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-popconfirm v-if="draft.id" title="删除这个 BOM 版本？" @confirm="remove"><template #reference><el-button type="danger" plain>删除此版本</el-button></template></el-popconfirm>
      </div>
      <el-empty v-if="!draft" description="这个产品还没有 BOM"><el-button type="primary" @click="newVersion">新建</el-button></el-empty>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../../api'
import { store } from '../../store'
import { fmtW } from '../../fmt'

const route = useRoute()
const products = ref([])
const materials = ref([])
const productId = ref(route.query.product_id ? Number(route.query.product_id) : null)
const versions = ref([])
const bomId = ref(null)
const draft = ref(null)
const saving = ref(false)
const upstream = computed(() => products.value.filter((p) => p.ptype !== '成品馅' && p.id !== productId.value))
const total = computed(() => (draft.value?.lines || []).reduce((s, l) => s + (Number(l.qty) || 0), 0))
const blank = () => ({ line_no: '', ref: null, qty: '', note: '' })

function toDraft(b) {
  return {
    id: b.id, effective_date: b.effective_date, note: b.note,
    lines: b.lines.map((l) => ({ line_no: l.line_no, ref: l.input_product_id ? 'p' + l.input_product_id : 'm' + l.material_id, qty: l.qty, note: l.note })),
  }
}
async function loadVersions(keep) {
  versions.value = productId.value ? await api.get('/api/boms', { product_id: productId.value }) : []
  const cur = versions.value.find((b) => b.id === keep) || versions.value.find((b) => b.effective_date <= store.day) || versions.value[0]
  bomId.value = cur ? cur.id : null
  draft.value = cur ? toDraft(cur) : null
}
watch(productId, () => loadVersions())
watch(bomId, (id) => { const b = versions.value.find((x) => x.id === id); if (b) draft.value = toDraft(b) })
function newVersion() {
  const base = draft.value ? JSON.parse(JSON.stringify(draft.value)) : { lines: [blank()] }
  draft.value = { ...base, id: null, effective_date: store.day, note: '' }
  bomId.value = null
}
async function save() {
  const lines = []
  for (const [i, l] of draft.value.lines.entries()) {
    if (!l.ref && !l.qty) continue
    if (!l.ref || !l.qty) { ElMessage.warning(`第 ${i + 1} 行请选投料并填数量`); return }
    lines.push({ line_no: l.line_no || i + 1, qty: l.qty, note: l.note,
      material_id: l.ref[0] === 'm' ? Number(l.ref.slice(1)) : null, input_product_id: l.ref[0] === 'p' ? Number(l.ref.slice(1)) : null })
  }
  const body = { product_id: productId.value, effective_date: draft.value.effective_date, note: draft.value.note, lines }
  saving.value = true
  try {
    const r = draft.value.id ? await api.put(`/api/boms/${draft.value.id}`, body) : await api.post('/api/boms', body)
    ElMessage.success('BOM 已保存，并已重算受影响的日期')
    await loadVersions(r.id)
  } finally { saving.value = false }
}
async function remove() { await api.del(`/api/boms/${draft.value.id}`); await loadVersions() }
onMounted(async () => {
  ;[products.value, materials.value] = await Promise.all([api.get('/api/products'), api.get('/api/materials')])
  if (productId.value) loadVersions()
})
</script>

<style scoped>
.draft-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.draft-head .spacer { flex: 1; }
.actions { margin-top: 12px; display: flex; gap: 8px; }
</style>
