// 显示格式：重量 2 位小数，单价 4 位，出率到 0.01%。中间计算不在前端做四舍五入。
function n(v) {
  if (v === null || v === undefined || v === '') return null
  const x = Number(v)
  return Number.isFinite(x) ? x : null
}
const fixed = (d) => (v) => {
  const x = n(v)
  return x === null ? '' : x.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}
export const fmtW = fixed(2)
export const fmtP = fixed(4)
export const fmtM = fixed(2)
export const fmtQ = fixed(2)
export const fmtT = fixed(4)
export function fmtY(v) {
  const x = n(v)
  return x === null ? '' : (x * 100).toFixed(2) + '%'
}
export function fmtPP(v) {
  const x = n(v)
  return x === null ? '' : (x > 0 ? '+' : '') + x.toFixed(2)
}
export const FORMATTERS = { weight: fmtW, price: fmtP, yield: fmtY, pp: fmtPP, money: fmtM, qty: fmtQ, ton: fmtT }
export function fmtBy(type, v) {
  if (type === 'bool') return v ? '是' : ''
  const f = FORMATTERS[type]
  return f ? f(v) : v ?? ''
}
// 输入框里的出率：用户填百分数，存小数
export function pctIn(v) {
  if (v === null || v === undefined || v === '') return null
  return String(Number(v) / 100)
}
export function pctOut(v) {
  if (v === null || v === undefined || v === '') return ''
  return String(+(Number(v) * 100).toFixed(6))
}
