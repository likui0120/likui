<template>
  <el-table :data="rows" border stripe size="small" :row-class-name="rowClass" :max-height="maxHeight"
            empty-text="没有数据" style="width: 100%">
    <el-table-column v-for="c in visible" :key="c[0]" :prop="c[0]" :label="c[1]"
                     :min-width="c[2] === 'text' ? 110 : 100" :align="c[2] === 'text' ? 'left' : 'right'"
                     :fixed="fixed.includes(c[0]) ? 'left' : false" show-overflow-tooltip>
      <template #default="{ row }">
        <slot :name="c[0]" :row="row">
          <span :class="cellClass(c, row)" class="num">{{ fmtBy(c[2], row[c[0]]) }}</span>
        </slot>
      </template>
    </el-table-column>
    <slot name="extra" />
  </el-table>
</template>

<script setup>
import { computed } from 'vue'
import { fmtBy } from '../fmt'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  hide: { type: Array, default: () => [] },
  fixed: { type: Array, default: () => [] },
  maxHeight: { type: [Number, String], default: 'calc(100vh - 210px)' },
})
const visible = computed(() => props.columns.filter((c) => !props.hide.includes(c[0])))
const rowClass = ({ row }) => (row.alert || row.kind === 'alert' ? 'alert-row' : '')
function cellClass(c, row) {
  if ((c[0] === 'dev' || c[0] === 'actual') && row.alert) return 'alert-text'
  if (c[0].startsWith('diff') && Number(row[c[0]]) > 0) return 'alert-text'
  if (c[0] === 'source' && row.source !== '实际') return 'std-tag'
  return ''
}
</script>
