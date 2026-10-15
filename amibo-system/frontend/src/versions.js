// 取某天有效的版本：effective_date <= day 中最新的一条
export function currentVersion(rows, fk, id, day) {
  let best = null
  for (const r of rows) {
    if (r[fk] !== id || r.effective_date > day) continue
    if (!best || r.effective_date > best.effective_date) best = r
  }
  return best
}
