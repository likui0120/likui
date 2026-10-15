import { today } from './store'

// 修改原料/产品时，影响计算的属性“从哪天起生效”。默认今天，历史日期仍按原来的设置计算；
// 勾选“改错”则所有历史日期一起改。
export function attrVersionFields(isEditing, what) {
  return [
    { key: 'attr_effective_date', label: '以上设置生效日期', type: 'date', default: () => today(), show: isEditing,
      hint: `${what}改了的话，从这天起按新设置算，之前的日期仍按原设置算。` },
    { key: 'attr_correction', label: '这是改错', type: 'bool', default: false, show: isEditing,
      hint: '打开：原来是录错了，所有历史日期都按新设置重算。' },
  ]
}

// 取某天有效的版本：effective_date <= day 中最新的一条
export function currentVersion(rows, fk, id, day) {
  let best = null
  for (const r of rows) {
    if (r[fk] !== id || r.effective_date > day) continue
    if (!best || r.effective_date > best.effective_date) best = r
  }
  return best
}
