<template>
  <div class="day-picker">
    <el-button :icon="ArrowLeft" @click="move(-1)" />
    <el-date-picker v-model="store.day" type="date" value-format="YYYY-MM-DD" :clearable="false" style="width: 150px" />
    <el-button :icon="ArrowRight" @click="move(1)" />
    <el-button link type="primary" @click="store.day = today()">今天</el-button>
  </div>
</template>

<script setup>
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { store, shiftDay, today } from '../store'
const move = (n) => { store.day = shiftDay(store.day, n) }
</script>

<style scoped>
.day-picker { display: inline-flex; align-items: center; gap: 6px; }
</style>
