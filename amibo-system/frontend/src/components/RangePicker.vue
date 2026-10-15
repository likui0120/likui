<template>
  <div class="range">
    <el-date-picker v-model="val" type="daterange" value-format="YYYY-MM-DD" range-separator="至"
                    start-placeholder="开始" end-placeholder="结束" :clearable="false" style="width: 260px" />
    <el-button-group>
      <el-button @click="preset(0)">当天</el-button>
      <el-button @click="preset(6)">近7天</el-button>
      <el-button @click="month()">本月</el-button>
    </el-button-group>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { store, shiftDay } from '../store'

const props = defineProps({ modelValue: { type: Array, required: true } })
const emit = defineEmits(['update:modelValue'])
const val = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const preset = (n) => emit('update:modelValue', [shiftDay(store.day, -n), store.day])
const month = () => emit('update:modelValue', [store.day.slice(0, 8) + '01', store.day])
</script>

<style scoped>
.range { display: inline-flex; gap: 8px; flex-wrap: wrap; align-items: center; }
</style>
