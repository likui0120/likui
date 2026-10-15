<template>
  <div class="page">
    <div class="page-head"><h2>Excel 导入</h2></div>
    <div class="grid">
      <div v-for="it in items" :key="it.key" class="card">
        <div class="title">{{ it.title }}</div>
        <p class="hint">{{ it.desc }}</p>
        <div class="row">
          <span>生效日期</span>
          <el-date-picker v-model="it.date" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 150px" />
        </div>
        <div class="row">
          <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx,.xls,.csv" :on-change="(f) => upload(it, f)">
            <el-button type="primary" :loading="it.loading">选择文件导入</el-button>
          </el-upload>
          <el-button link type="primary" @click="download(`/api/import/template/${it.key}`)">下载模板</el-button>
        </div>
        <div v-if="it.result" class="result">
          <template v-if="it.key === 'boms'">
            <el-alert type="success" :closable="false" :title="`导入 ${it.result.imported.length} 个产品的 BOM`" />
            <div v-for="b in it.result.imported" :key="b.product" class="muted">{{ b.product }}：{{ b.lines }} 行，每锅合计 {{ b.total }} 斤</div>
            <el-alert v-if="it.result.unmatched.length" type="warning" :closable="false" :title="`${it.result.unmatched.length} 行没导入（所在产品的 BOM 整份跳过）`" class="mt" />
            <div v-for="(u, i) in it.result.unmatched" :key="i" class="muted">第 {{ u.row || '?' }} 行 {{ u.product }} / {{ u.input }}：{{ u.reason }}</div>
          </template>
          <template v-else>
            <el-alert type="success" :closable="false" :title="`新增 ${it.result.created} 条，更新 ${it.result.updated} 条`" />
            <div v-for="(u, i) in it.result.bad" :key="i" class="muted">第 {{ u.row }} 行 {{ u.name }}：{{ u.reason }}</div>
          </template>
        </div>
      </div>
    </div>
    <div class="card mt">
      <div class="title">最近的 T+ 单价导入</div>
      <p class="hint">T+ 单价在“每日录入 → 原料单价”里上传。这里列出最近 50 次导入，撤销在每日录入页的“导入记录”里做。</p>
      <el-table :data="batches" size="small" empty-text="还没有导入过">
        <el-table-column prop="date" label="单价日期" width="110" />
        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ row.created_at?.replace('T', ' ') }}</template>
        </el-table-column>
        <el-table-column prop="filename" label="文件" min-width="160" show-overflow-tooltip />
        <el-table-column prop="price_col" label="单价列" width="100" />
        <el-table-column prop="matched" label="导入" width="70" align="right" />
        <el-table-column prop="unmatched" label="没匹配" width="70" align="right" />
        <el-table-column prop="flagged" label="需核对" width="70" align="right" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }"><el-tag v-if="row.undone_at" size="small" type="info">已撤销</el-tag></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, download } from '../../api'

const items = reactive([
  { key: 'materials', title: '原料清单', date: '2020-01-01', loading: false, result: null,
    desc: '支持 .xlsx、.xls、.csv。列：编码、名称、类别（蔬菜/泡发/酱腌/肉/调料/干调/水/芝麻/其他）、是否需要处理（是/否）、标准出率（85% 或 0.85 都行）。按编码或名称匹配，已有的更新，没有的新增；标准出率按所选生效日期存一个版本。' },
  { key: 'products', title: '产品清单', date: '2020-01-01', loading: false, result: null,
    desc: '列：编码、名称、类型（成品馅/半成品油/麻油）、班组、是否制冷、是否包装、熟制标准出率、制冷标准出率、包装标准出率。按名称匹配。' },
  { key: 'boms', title: 'BOM', date: new Date().toISOString().slice(0, 10), loading: false, result: null,
    desc: '每行一个投料，列：产品、行号（可选）、投料、数量（斤/锅）。产品名只写在第一行也可以。同一产品同一生效日期已有 BOM 的会整份替换；投料匹配不上的产品整份跳过并列出。' },
])
async function upload(it, file) {
  const fd = new FormData()
  fd.append('effective_date', it.date)
  fd.append('file', file.raw)
  it.loading = true
  try { it.result = await api.post(`/api/import/${it.key}`, fd) } finally { it.loading = false }
}
const batches = ref([])
onMounted(async () => { batches.value = await api.get('/api/import/batches', { limit: 50 }) })
</script>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.title { font-weight: 600; margin-bottom: 6px; }
.row { display: flex; align-items: center; gap: 10px; margin: 8px 0; font-size: 13px; }
.result { margin-top: 10px; line-height: 1.8; }
.mt { margin-top: 8px; }
</style>
