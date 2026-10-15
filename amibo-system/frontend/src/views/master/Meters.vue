<template>
  <div class="page">
    <div class="page-head">
      <h2>计量表</h2>
      <el-radio-group v-model="energy">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button v-for="e in store.meta?.energies || []" :key="e.key" :value="e.key">{{ e.name }}</el-radio-button>
      </el-radio-group>
      <span class="spacer" />
      <el-button type="primary" @click="addOpen = true">新增计量表</el-button>
    </div>
    <div class="card">
      <p class="hint">单表用量 =（本期 − 上期）× 倍率。计入方式：“计入”加到合计，“扣减”从合计里减，“参考”只记录不进合计。增删表、改倍率或计入方式都在这里改，按生效日期存版本，不用改程序。换表在每日录入的抄表页操作。</p>
      <el-table :data="rows" border size="small" max-height="calc(100vh - 230px)">
        <el-table-column label="能源" width="70"><template #default="{ row }">{{ ename(row.energy) }}</template></el-table-column>
        <el-table-column prop="name" label="计量表" min-width="150" />
        <el-table-column label="方式" width="110"><template #default="{ row }">{{ cur(row)?.mode === 'direct' ? '直接填用量' : '读数差' }}</template></el-table-column>
        <el-table-column label="倍率" width="140"><template #default="{ row }">{{ cur(row)?.factor_text || cur(row)?.factor }}</template></el-table-column>
        <el-table-column label="全厂合计" width="90"><template #default="{ row }">{{ mname(cur(row)?.plant) }}</template></el-table-column>
        <el-table-column label="车间合计" width="90"><template #default="{ row }">{{ mname(cur(row)?.workshop) }}</template></el-table-column>
        <el-table-column label="状态" width="70"><template #default="{ row }">{{ cur(row) ? (cur(row).active ? '' : '停用') : '未生效' }}</template></el-table-column>
        <el-table-column label="备注" min-width="140"><template #default="{ row }">{{ cur(row)?.note }}</template></el-table-column>
        <el-table-column label="" width="150">
          <template #default="{ row }">
            <el-button link size="small" @click="rename(row)">改名</el-button>
            <el-button link size="small" type="primary" @click="openV(row)">配置版本</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <VersionDialog v-model="vOpen" :title="`计量表配置 · ${vFor?.name || ''}`" endpoint="/api/meter-versions" fk="meter_id" :fk-value="vFor?.id" :fields="verFields" @changed="load" />
    <FormDialog v-model="addOpen" title="新增计量表" :fields="addFields" :on-save="add" />
    <FormDialog v-model="nameOpen" title="修改计量表" :fields="[{ key: 'name', label: '名称', required: true }, { key: 'sort', label: '排序', type: 'num' }]" :data="nameFor || {}" :on-save="saveName" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import FormDialog from '../../components/FormDialog.vue'
import VersionDialog from '../../components/VersionDialog.vue'
import { api } from '../../api'
import { store } from '../../store'
import { currentVersion } from '../../versions'

const list = ref([])
const vers = ref([])
const energy = ref('')
const vOpen = ref(false)
const vFor = ref(null)
const addOpen = ref(false)
const nameOpen = ref(false)
const nameFor = ref(null)
const rows = computed(() => list.value.filter((m) => !energy.value || m.energy === energy.value))
const cur = (m) => currentVersion(vers.value, 'meter_id', m.id, store.day)
const ename = (e) => ({ gas: '燃气', water: '水', elec: '电' }[e] || e)
const mname = (m) => ({ '+': '计入', '-': '扣减', ref: '参考', '': '—' }[m ?? ''] ?? m)
const modeOpts = [{ value: '+', label: '计入' }, { value: '-', label: '扣减' }, { value: 'ref', label: '参考' }, { value: '', label: '不计' }]
const verFields = [
  { key: 'mode', label: '方式', type: 'select', required: true, default: 'reading', options: [{ value: 'reading', label: '读数差' }, { value: 'direct', label: '直接填用量' }] },
  { key: 'factor', label: '倍率', type: 'num', fmt: 'qty', required: true, default: '1', hint: '用量 = 读数差 × 倍率。“÷1000×80”填 0.08' },
  { key: 'factor_text', label: '倍率说明', type: 'text', hint: '显示用，如 ×2000、÷1000×80' },
  { key: 'plant', label: '全厂合计', type: 'select', options: modeOpts, default: '+' },
  { key: 'workshop', label: '车间合计', type: 'select', options: modeOpts, default: '', hint: '目前只有水分全厂、车间两个合计' },
  { key: 'active', label: '启用', type: 'bool', default: true },
  { key: 'note', label: '备注', type: 'text' },
]
const addFields = computed(() => [
  { key: 'energy', label: '能源', type: 'select', required: true, options: (store.meta?.energies || []).map((e) => ({ value: e.key, label: e.name })) },
  { key: 'name', label: '名称', required: true },
  ...verFields.filter((f) => f.key !== 'active'),
  { key: 'effective_date', label: '生效日期', type: 'date', required: true, default: () => store.day },
])
async function load() { ;[list.value, vers.value] = await Promise.all([api.get('/api/meters'), api.get('/api/meter-versions')]) }
function openV(row) { vFor.value = row; vOpen.value = true }
async function add(d) { await api.post('/api/meters/with-version', d); load() }
function rename(row) { nameFor.value = row; nameOpen.value = true }
async function saveName(d) { await api.put(`/api/meters/${nameFor.value.id}`, d); load() }
onMounted(load)
</script>
