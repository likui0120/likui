import { ElMessage } from 'element-plus'

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(url, init)
  } catch (e) {
    ElMessage.error('连不上服务器，请确认系统已启动')
    throw e
  }
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`
    try {
      const j = await res.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch (_) { /* ignore */ }
    if (!opts.silent) ElMessage.error(msg)
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  get: (url, params, opts) => request('GET', params ? `${url}?${new URLSearchParams(clean(params))}` : url, undefined, opts),
  post: (url, body) => request('POST', url, body),
  put: (url, body) => request('PUT', url, body),
  del: (url) => request('DELETE', url),
}

function clean(p) {
  const o = {}
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '') o[k] = v
  return o
}

export function download(url, params) {
  const q = params ? `?${new URLSearchParams(clean(params))}` : ''
  window.open(url + q, '_blank')
}
