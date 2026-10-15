<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '200px'" class="aside">
      <div class="brand" @click="collapsed = !collapsed">
        <span class="logo">出</span><span v-if="!collapsed" class="brand-text">出率与成本核算</span>
      </div>
      <el-menu :default-active="$route.path" router :collapse="collapsed" class="menu"
               background-color="#1f3346" text-color="#c9d6e3" active-text-color="#ffffff">
        <template v-for="m in menu" :key="m.title">
          <el-sub-menu v-if="m.children" :index="m.title">
            <template #title><el-icon><component :is="icons[m.icon]" /></el-icon><span>{{ m.title }}</span></template>
            <el-menu-item v-for="c in m.children" :key="c.path" :index="c.path">{{ c.title }}</el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="m.path">
            <el-icon><component :is="icons[m.icon]" /></el-icon><template #title>{{ m.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>
    <el-main class="main">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { House, EditPen, DataAnalysis, Files } from '@element-plus/icons-vue'
import { menu } from './router'
import { api } from './api'
import { store } from './store'

const icons = { House, EditPen, DataAnalysis, Files }
const collapsed = ref(window.innerWidth < 900)
onMounted(async () => { store.meta = await api.get('/api/meta') })
</script>

<style scoped>
.layout { height: 100%; }
.aside { background: #1f3346; transition: width .2s; overflow-x: hidden; }
.brand { height: 56px; display: flex; align-items: center; gap: 10px; padding: 0 16px; color: #fff; cursor: pointer; white-space: nowrap; }
.logo { width: 30px; height: 30px; border-radius: 6px; background: #2f6f9f; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex: none; }
.brand-text { font-weight: 600; letter-spacing: 1px; }
.menu { border-right: none; }
.main { padding: 0; overflow-y: auto; }
</style>
