<template>
  <div class="page">
    <div class="page-head">
      <h2>干调价格</h2>
      <span class="spacer" />
      <el-button type="primary" @click="addOpen = true">新增干调</el-button>
    </div>
    <div class="card">
      <p class="hint">干调按外购料处理：每种干调一个单价（元/斤），定期更新，不展开配方。每次调价新增一个版本，填生效日期。下面显示 {{ store.day }} 当天有效的价格。</p>
      <el-table :data="list" border size="small">
        <el-table-column prop="name" label="干调" min-width="180" />
        <el-table-column label="当前单价（元/斤）" width="150" align="right">
          <template #default="{ row }">
            <span v-if="cur(row)" class="num">{{ fmtP(cur(row).price) }}</span><span v-else class="alert-text">未设</span>
          </template>
        </el-table-column>
        <el-table-column label="生效日期" width="120"><template #default="{ row }">{{ cur(row)?.effective_date }}</template></el-table-column>
        <el-table-column label="" width="140"><template #default="{ row }"><el-button link type="primary" size="small" @click="openV(row)">价格版本</el-button></template></el-table-column>
      </el-table>
    </div>
    <VersionDialog v-model="vOpen" :title="`干调价格 · ${vFor?.name || ''}`" endpoint="/api/seasoning-prices" fk="material_id" :fk-value="vFor?.id"
                   :fields="[{ key: 'price', label: '单价', type: 'num', unit: '元/斤', required: true }]" @changed="load" />
    <FormDialog v-model="addOpen" title="新增干调" :fields="[{ key: 'name', label: '名称', required: true }, { key: 'code', label: '编码' }]" :on-save="add" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import FormDialog from '../../components/FormDialog.vue'
import VersionDialog from '../../components/VersionDialog.vue'
import { api } from '../../api'
import { store } from '../../store'
import { fmtP } from '../../fmt'
import { currentVersion } from '../../versions'

const list = ref([])
const prices = ref([])
const vOpen = ref(false)
const vFor = ref(null)
const addOpen = ref(false)
const cur = (m) => currentVersion(prices.value, 'material_id', m.id, store.day)
async function load() {
  const [mats, ps] = await Promise.all([api.get('/api/materials'), api.get('/api/seasoning-prices')])
  list.value = mats.filter((m) => m.category === '干调')
  prices.value = ps
}
function openV(row) { vFor.value = row; vOpen.value = true }
async function add(d) { await api.post('/api/materials', { ...d, category: '干调', needs_process: false, active: true }); load() }
onMounted(load)
</script>
