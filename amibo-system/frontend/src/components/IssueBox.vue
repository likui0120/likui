<template>
  <div v-if="issues && issues.length" class="issues">
    <el-alert v-for="(i, k) in shown" :key="k" :type="i.kind === 'alert' ? 'error' : 'warning'" :closable="false" show-icon
              :title="`${i.object_name}：${i.message}`" />
    <el-button v-if="issues.length > limit" link type="primary" @click="all = !all">
      {{ all ? '收起' : `还有 ${issues.length - limit} 条，展开` }}
    </el-button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ issues: { type: Array, default: () => [] }, limit: { type: Number, default: 6 } })
const all = ref(false)
const shown = computed(() => (all.value ? props.issues : props.issues.slice(0, props.limit)))
</script>
