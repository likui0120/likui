import { reactive, watch } from 'vue'

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

let saved = null
try { saved = localStorage.getItem('amibo.day') } catch (_) { /* ignore */ }

// 各页面共用的“当前日期”，切换页面时保持不变
export const store = reactive({ day: saved || today(), meta: null })
watch(() => store.day, (v) => { try { localStorage.setItem('amibo.day', v) } catch (_) { /* ignore */ } })

export { today }

export function shiftDay(day, n) {
  const d = new Date(day + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
