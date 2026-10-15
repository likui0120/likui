<template>
  <div class="page">
    <div class="page-head"><h2>能源单价</h2></div>
    <div class="card">
      <p class="hint">水、电、燃气的未税单价。调价时新增版本填生效日期，历史日期按当时的单价计算能耗费用。</p>
      <el-table :data="store.meta?.energies || []" border size="small">
        <el-table-column prop="name" label="能源" width="90" />
        <el-table-column label="当前单价" width="160" align="right">
          <template #default="{ row }"><span class="num">{{ fmtP(cur(row.key)?.price) }}</span> 元/{{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="生效日期" width="120"><template #default="{ row }">{{ cur(row.key)?.effective_date }}</template></el-table-column>
        <el-table-column label=""><template #default="{ row }"><el-button link type="primary" size="small" @click="openV(row)">价格版本</el-button></template></el-table-column>
      </el-table>
    </div>
    <VersionDialog v-model="vOpen" :title="`能源单价 · ${vFor?.name || ''}`" endpoint="/api/energy-prices" fk="energy" :fk-value="vFor?.key"
                   :fields="[{ key: 'price', label: '未税单价', type: 'num', unit: vFor ? '元/' + vFor.unit : '', required: true }]" @changed="load" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import VersionDialog from '../../components/VersionDialog.vue'
import { api } from '../../api'
import { store } from '../../store'
import { fmtP } from '../../fmt'
import { currentVersion } from '../../versions'

const prices = ref([])
const vOpen = ref(false)
const vFor = ref(null)
const cur = (e) => currentVersion(prices.value, 'energy', e, store.day)
async function load() { prices.value = await api.get('/api/energy-prices') }
function openV(row) { vFor.value = row; vOpen.value = true }
onMounted(load)
</script>
