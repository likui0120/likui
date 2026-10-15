<template>
  <div class="page">
    <div class="page-head">
      <h2>包装规格</h2>
      <span class="spacer" />
      <el-button type="primary" @click="addOpen = true">新增规格</el-button>
    </div>
    <div class="card">
      <p class="hint">包装费按袋计，不同规格不同价。袋费调整时新增版本并填生效日期。下面显示 {{ store.day }} 当天有效的版本。</p>
      <el-table :data="list" border size="small">
        <el-table-column prop="name" label="规格" min-width="140" />
        <el-table-column label="每袋斤数" width="110" align="right"><template #default="{ row }"><span class="num">{{ fmtW(cur(row)?.bag_weight) }}</span></template></el-table-column>
        <el-table-column label="袋费（元/袋）" width="130" align="right">
          <template #default="{ row }"><span class="num" :class="{ 'alert-text': cur(row) && Number(cur(row).fee) === 0 }">{{ fmtP(cur(row)?.fee) }}</span></template>
        </el-table-column>
        <el-table-column label="生效日期" width="120"><template #default="{ row }">{{ cur(row)?.effective_date }}</template></el-table-column>
        <el-table-column label="启用" width="70"><template #default="{ row }"><el-switch v-model="row.active" size="small" @change="toggle(row)" /></template></el-table-column>
        <el-table-column label="" width="120"><template #default="{ row }"><el-button link type="primary" size="small" @click="openV(row)">版本</el-button></template></el-table-column>
      </el-table>
      <p v-if="list.some((s) => cur(s) && Number(cur(s).fee) === 0)" class="hint alert-text">有规格的袋费还是 0，等工厂提供袋费清单后在“版本”里填写。</p>
    </div>
    <VersionDialog v-model="vOpen" :title="`包装规格 · ${vFor?.name || ''}`" endpoint="/api/pack-spec-versions" fk="spec_id" :fk-value="vFor?.id"
                   :fields="[{ key: 'bag_weight', label: '每袋斤数', type: 'num', fmt: 'weight', required: true }, { key: 'fee', label: '袋费', type: 'num', unit: '元/袋', required: true }]" @changed="load" />
    <FormDialog v-model="addOpen" title="新增包装规格" :fields="addFields" :on-save="add" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import FormDialog from '../../components/FormDialog.vue'
import VersionDialog from '../../components/VersionDialog.vue'
import { api } from '../../api'
import { store } from '../../store'
import { fmtP, fmtW } from '../../fmt'
import { currentVersion } from '../../versions'

const list = ref([])
const vers = ref([])
const vOpen = ref(false)
const vFor = ref(null)
const addOpen = ref(false)
const addFields = [
  { key: 'name', label: '规格名称', required: true },
  { key: 'bag_weight', label: '每袋斤数', type: 'num', unit: '斤', required: true },
  { key: 'fee', label: '袋费', type: 'num', unit: '元/袋', required: true },
  { key: 'effective_date', label: '生效日期', type: 'date', required: true, default: () => store.day },
]
const cur = (s) => currentVersion(vers.value, 'spec_id', s.id, store.day)
async function load() { ;[list.value, vers.value] = await Promise.all([api.get('/api/pack-specs'), api.get('/api/pack-spec-versions')]) }
function openV(row) { vFor.value = row; vOpen.value = true }
async function add(d) { await api.post('/api/pack-specs/with-version', d); load() }
async function toggle(row) { await api.put(`/api/pack-specs/${row.id}`, { active: row.active }) }
onMounted(load)
</script>
