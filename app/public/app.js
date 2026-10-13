'use strict';
// 桃喜团子收银系统 · 店内端（收银员、后厨、店主共用，按角色显示页面）

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const yuan = (c) => (Number(c || 0) / 100).toFixed(2);
const faceText = (c) => (c % 100 ? (c / 100).toFixed(1) : String(c / 100)); // 餐票面额：1000 → "10"
const toCents = (v) => { const n = parseFloat(String(v).trim()); return Number.isFinite(n) ? Math.round(n * 100) : NaN; };
const pad = (n) => String(n).padStart(2, '0');
const dateStr = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (s, n) => { const d = new Date(s + 'T12:00:00'); d.setDate(d.getDate() + n); return dateStr(d); };
const METHOD = { cash: '现金', pos: '收银机', ticket: '临时用票', stored: '存票余额' };
const TX = { deposit: '存入', spend: '消费', refund: '撤单退回', adjust: '调整', close: '销户退还' };
const ROLE = { owner: '店主', cashier: '收银员', kitchen: '后厨' };
const PROD_TYPE = { output: '出炉', loss: '报损', leftover: '收档剩余' };
const MOVE = { in: '入库', use: '领用', loss: '损耗', count: '盘点', bom: '出炉耗用' };

async function api(method, url, body) {
  const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && url !== '/api/login') { state.me = null; render(); }
  if (!r.ok) throw new Error(data.error || '请求失败');
  return data;
}
function toast(msg, err) {
  $$('.toast').forEach((x) => x.remove());
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 4000 : 2500);
}
async function act(fn) { try { return await fn(); } catch (e) { toast(e.message, true); } }

// 弹窗：html 为内容，返回 {el, close}
function modal(html, { onClose } = {}) {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { bg.remove(); onClose && onClose(); };
  bg.addEventListener('click', (e) => { if (e.target === bg) close(); });
  bg.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) close(); });
  document.body.appendChild(bg);
  const first = bg.querySelector('input:not([type=file]),select');
  if (first) setTimeout(() => { if (!bg.contains(document.activeElement)) first.focus(); }, 30);
  return { el: bg.querySelector('.modal'), close };
}
function showImage(src) { modal(`<img class="imgview" src="${esc(src)}" alt="消费照片"><div class="acts"><button class="btn" data-close>关闭</button></div>`); }
document.addEventListener('click', (e) => { const t = e.target.closest('img.thumb'); if (t) showImage(t.src); });

// 照片压缩：长边 1280，JPEG
function compressImage(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, 1280 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL('image/jpeg', 0.75));
    };
    img.onerror = () => reject(new Error('照片读取失败'));
    img.src = URL.createObjectURL(file);
  });
}

const state = { me: null, view: null, products: [], cart: [], cat: '全部', photo: null, lastOrder: null, discount: undefined };
const zhe = (pct) => `${pct / 10}折`;

// ---------- 小票打印 ----------
const canPrint = () => state.me && state.me.print.mode !== 'none';
function receiptHtml({ paper, lines }) {
  const row = (ln) => {
    if (ln.hr) return '<div class="hr"></div>';
    const cls = `${ln.b ? 'b' : ''} ${ln.big ? 'big' : ''}`;
    if (ln.l !== undefined) return `<div class="lr ${cls}"><span>${esc(ln.l)}</span><span class="rt">${esc(ln.r || '')}</span></div>`;
    return `<div class="${cls} ${ln.a === 'c' ? 'c' : ln.a === 'r' ? 'r' : ''}">${esc(ln.t)}</div>`;
  };
  return `<!doctype html><html><head><meta charset="utf-8"><title>小票</title><style>
    @page{margin:0} html,body{margin:0;background:#fff;color:#000}
    body{width:${paper === '80' ? '72mm' : '48mm'};padding:2mm;font:12px/1.5 "SimSun","Songti SC",monospace}
    .lr{display:flex;justify-content:space-between;gap:4px}.lr span:first-child{white-space:pre-wrap}.rt{white-space:pre;text-align:right}
    .c{text-align:center}.r{text-align:right}.b{font-weight:700}.big{font-size:18px}
    .hr{border-top:1px dashed #000;margin:4px 0}
  </style></head><body>${lines.map(row).join('')}</body></html>`;
}
function browserPrint(r) {
  const f = document.createElement('iframe');
  f.setAttribute('aria-hidden', 'true');
  f.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
  f.onload = () => {
    const w = f.contentWindow;
    w.addEventListener('afterprint', () => setTimeout(() => f.remove(), 500));
    setTimeout(() => f.remove(), 120000);
    w.focus(); w.print();
  };
  f.srcdoc = receiptHtml(r);
  document.body.appendChild(f);
}
// type: order / account_code / account_balance / dayclose / test
async function printReceipt(type, params = {}) {
  return act(async () => {
    if (!canPrint()) throw new Error('还没有设置小票打印机，请店主到"设置"里设置');
    if (state.me.print.mode === 'browser') {
      const r = await api('GET', '/api/receipt?' + new URLSearchParams({ type, ...params }));
      browserPrint(r);
      return;
    }
    await api('POST', '/api/print', { type, ...params });
    toast('已发送到打印机');
  });
}

// ---------- 表格导出、打印（所有查询页通用） ----------
// 读表格内容：表头为空的列（操作按钮、勾选框）不导出；输入框取填写的值
function tableData(table) {
  const ths = $$('thead th', table);
  const keep = ths.map((th) => th.textContent.trim() !== '');
  const head = ths.map((th) => th.textContent.trim()).filter((_, i) => keep[i]);
  const rows = $$('tbody tr', table).filter((tr) => !tr.querySelector('td.empty')).map((tr) => [...tr.children].map((td) => {
    const inp = td.querySelector('input:not([type=checkbox]),select');
    if (inp) return inp.tagName === 'SELECT' ? inp.options[inp.selectedIndex]?.text || '' : inp.value;
    const c = td.cloneNode(true);
    $$('button,img', c).forEach((x) => x.remove());
    $$('br', c).forEach((x) => x.replaceWith(' '));
    return c.textContent.replace(/\s+/g, ' ').trim();
  }).filter((_, i) => keep[i]));
  return { head, rows };
}
function downloadCsv(name, head, rows) {
  const q = (v) => { const t = String(v ?? ''); return /[",\r\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const text = '\ufeff' + [head, ...rows].map((r) => r.map(q).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  a.download = name.replace(/[\\/:*?"<>|]/g, '_') + '.csv';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
// 用浏览器打印成 A4 表格（选默认打印机或"另存为 PDF"）
function printTables(title, sub, tables) {
  const body = tables.map(({ name, head, rows }) => `${name ? `<h2>${esc(name)}</h2>` : ''}<table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${head.length}">（没有数据）</td></tr>`}</tbody></table>`).join('');
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title><style>
    @page{size:A4;margin:12mm} body{font:12px/1.5 "Microsoft YaHei","PingFang SC",sans-serif;color:#000;margin:0}
    h1{font-size:18px;margin:0 0 2px} .sub{color:#444;margin-bottom:10px} h2{font-size:14px;margin:14px 0 6px}
    table{border-collapse:collapse;width:100%} th,td{border:1px solid #888;padding:4px 6px;text-align:left;vertical-align:top} th{background:#eee}
    tr{page-break-inside:avoid}
  </style></head><body><h1>${esc(title)}</h1><div class="sub">${esc(sub)}</div>${body}</body></html>`;
  const f = document.createElement('iframe');
  f.setAttribute('aria-hidden', 'true');
  f.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
  f.onload = () => { const w = f.contentWindow; w.addEventListener('afterprint', () => setTimeout(() => f.remove(), 500)); setTimeout(() => f.remove(), 120000); w.focus(); w.print(); };
  f.srcdoc = html;
  document.body.appendChild(f);
}
// 给区域里每个表格卡片底部加"导出 Excel""打印"按钮；ctx 是说明（例如日期）
function tableTools(root, page, ctx = '') {
  $$('.card.tbl', root).forEach((card) => {
    const table = $('table', card);
    if (!table || $('.ttools', card)) return;
    const h = $('h3', card);
    const name = h ? h.childNodes[0].textContent.trim() : '';
    const title = `${page}${name && name !== page ? ' · ' + name : ''}`;
    const bar = document.createElement('div');
    bar.className = 'ttools';
    bar.innerHTML = '<button class="btn small" data-t="csv">导出 Excel</button><button class="btn small" data-t="print">打印</button>';
    card.appendChild(bar);
    const sub = () => `${state.me.shop_name}　${typeof ctx === 'function' ? ctx() : ctx}　打印时间 ${dateStr()} ${new Date().toTimeString().slice(0, 5)}`;
    $('[data-t=csv]', bar).onclick = () => { const d = tableData($('table', card)); downloadCsv(`${title}_${typeof ctx === 'function' ? ctx() : ctx || dateStr()}`, d.head, d.rows); };
    $('[data-t=print]', bar).onclick = () => { const d = tableData($('table', card)); printTables(title, sub(), [d]); };
  });
}

// ---------- 页面注册 ----------
const VIEWS = [
  { key: 'pos', label: '收银', roles: ['owner', 'cashier'], render: renderPos },
  { key: 'accounts', label: '存票', roles: ['owner', 'cashier'], render: renderAccounts },
  { key: 'orders', label: '订单', roles: ['owner', 'cashier'], render: renderOrders },
  { key: 'close', label: '日结', roles: ['owner', 'cashier'], render: renderClose },
  { key: 'production', label: '出品', roles: ['owner', 'kitchen'], render: renderProduction },
  { key: 'plan', label: '生产计划', roles: ['owner', 'kitchen'], render: renderPlan },
  { key: 'stock', label: '盘存', roles: ['owner', 'kitchen'], render: renderStock },
  { key: 'tickets', label: '餐票', roles: ['owner'], render: renderTickets },
  { key: 'reports', label: '报表', roles: ['owner'], render: renderReports },
  { key: 'settings', label: '设置', roles: ['owner'], render: renderSettings },
];

async function boot() {
  try { state.me = await api('GET', '/api/me'); } catch { state.me = null; }
  render();
}
function render() {
  const app = $('#app');
  if (!state.me) return renderLogin(app);
  document.title = `${state.me.shop_name}收银`;
  const views = VIEWS.filter((v) => v.roles.includes(state.me.role));
  if (!state.view || !views.find((v) => v.key === state.view)) {
    let saved = null; try { saved = localStorage.getItem('view'); } catch {}
    state.view = views.find((v) => v.key === saved) ? saved : views[0].key;
  }
  app.innerHTML = `
    ${state.me.default_pin ? '<div class="banner">店主密码还是初始的 123456，请到"设置"里修改。</div>' : ''}
    <header class="top">
      <span class="brand">${esc(state.me.shop_name)}</span>
      <nav class="tabs">${views.map((v) => `<button data-view="${v.key}" class="${v.key === state.view ? 'on' : ''}">${v.label}</button>`).join('')}</nav>
      <span class="who">${esc(state.me.name)} · ${ROLE[state.me.role]} <button class="btn small" id="logout">退出</button></span>
    </header>
    <main id="main"></main>`;
  $$('[data-view]').forEach((b) => b.onclick = () => { state.view = b.dataset.view; try { localStorage.setItem('view', state.view); } catch {} render(); });
  $('#logout').onclick = async () => { await api('POST', '/api/logout'); state.me = null; render(); };
  const v = views.find((x) => x.key === state.view);
  v.render($('#main'));
}

// ---------- 登录 ----------
async function renderLogin(app) {
  let names = []; let shop = '桃喜团子';
  try { names = await api('GET', '/api/login-names'); } catch {}
  try { shop = (await api('GET', '/api/public/info')).shop_name || shop; } catch {}
  document.title = `${shop}收银`;
  let pin = '';
  app.innerHTML = `<div class="login"><div class="card">
    <h2>${esc(shop)}收银</h2>
    <label class="f"><span>员工</span><select id="lname">${names.map((n) => `<option>${esc(n)}</option>`).join('')}</select></label>
    <div class="dots" id="dots"></div>
    <div class="keypad">${[1, 2, 3, 4, 5, 6, 7, 8, 9, '清空', 0, '登录'].map((k) => `<button data-k="${k}">${k}</button>`).join('')}</div>
  </div></div>`;
  let last = null; try { last = localStorage.getItem('lastName'); } catch {}
  if (last && names.includes(last)) $('#lname').value = last;
  const dots = () => { const d = $('#dots'); if (d) d.innerHTML = '<i></i>'.repeat(pin.length); };
  const submit = () => act(async () => {
    const name = $('#lname').value;
    await api('POST', '/api/login', { name, pin });
    try { localStorage.setItem('lastName', name); } catch {}
    await boot();
  }).finally(() => { pin = ''; dots(); });
  $$('.keypad button').forEach((b) => b.onclick = () => {
    const k = b.dataset.k;
    if (k === '清空') pin = '';
    else if (k === '登录') return submit();
    else if (pin.length < 8) pin += k;
    dots();
  });
  document.onkeydown = (e) => {
    if (state.me) return;
    if (/^\d$/.test(e.key) && pin.length < 8) { pin += e.key; dots(); }
    else if (e.key === 'Backspace') { pin = pin.slice(0, -1); dots(); }
    else if (e.key === 'Enter') submit();
  };
}

// ---------- 收银 ----------
async function renderPos(main) {
  await act(async () => {
    const [products, me] = await Promise.all([api('GET', '/api/products'), api('GET', '/api/me')]);
    state.products = products; state.me = me;
  });
  if (state.discount === undefined || !state.me.discount.on) state.discount = state.me.discount.all;
  // 按近 30 天销量排序，卖得多的在前
  const prods = state.products.filter((p) => p.active).sort((a, b) => b.sold_30d - a.sold_30d || a.sort - b.sort || a.id - b.id);
  const cats = ['全部', ...new Set(prods.map((p) => p.category))];
  if (!cats.includes(state.cat)) state.cat = '全部';
  main.innerHTML = `<div class="pos">
    <section>
      <div class="cats">${cats.map((c) => `<button data-cat="${esc(c)}" class="${c === state.cat ? 'on' : ''}">${esc(c)}</button>`).join('')}</div>
      <div class="prods">${prods.filter((p) => state.cat === '全部' || p.category === state.cat)
        .map((p) => `<button class="prod" data-pid="${p.id}"><b>${esc(p.name)}</b><span class="num">¥${yuan(p.price_cents)}</span><span class="pstat" data-ps="${p.id}">${prodStat(p)}</span></button>`).join('')
        || '<p class="muted">还没有商品，请店主在"设置"里添加。</p>'}
        <button class="prod" id="custom"><b>+ 临时商品</b><span class="muted">自定义名称价格</span></button>
      </div>
    </section>
    <aside class="card cart" id="cart"></aside>
  </div>
  <div class="mbar" id="mbar"></div>`;
  $$('[data-cat]').forEach((b) => b.onclick = () => { state.cat = b.dataset.cat; renderPos(main); });
  $$('[data-pid]').forEach((b) => b.onclick = () => {
    const p = state.products.find((x) => x.id === Number(b.dataset.pid));
    const line = state.cart.find((l) => l.product_id === p.id);
    if (line) line.qty++; else state.cart.push({ product_id: p.id, name: p.name, price_cents: p.price_cents, qty: 1 });
    drawCart();
  });
  $('#custom').onclick = () => {
    const m = modal(`<h3>临时商品</h3>
      <label class="f"><span>名称</span><input id="cn" placeholder="例如：生日蛋糕定金"></label>
      <label class="f"><span>单价（元）</span><input id="cp" inputmode="decimal"></label>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">加入</button></div>`);
    $('#ok', m.el).onclick = () => {
      const name = $('#cn', m.el).value.trim(); const price = toCents($('#cp', m.el).value);
      if (!name || !(price >= 0)) return toast('请填写名称和价格', true);
      state.cart.push({ product_id: null, name, price_cents: price, qty: 1 });
      m.close(); drawCart();
    };
  };
  drawCart();
}
// 商品卡片上的小字：今日已售 / 目前库存 / 剩余待做
function prodStat(p) {
  const st = p.stock === null ? '—' : `<b class="${p.stock <= 0 ? 'warn' : ''}">${p.stock}</b>`;
  return `售 <b>${p.sold_today}</b> · 存 ${st} · 待做 ${p.todo === null ? '—' : `<b>${p.todo}</b>`}`;
}
async function refreshProdStats() {
  const list = await api('GET', '/api/products').catch(() => null);
  if (!list) return;
  state.products = list;
  for (const p of list) { const el = $(`[data-ps="${p.id}"]`); if (el) el.innerHTML = prodStat(p); }
}
const cartSubtotal = () => state.cart.reduce((s, l) => s + l.qty * l.price_cents, 0);
const cartTotal = () => { const s = cartSubtotal(); return state.discount ? Math.round(s * state.discount / 100) : s; };
function discountHtml() {
  const d = state.me.discount;
  if (!d.on) return '';
  const cur = state.discount;
  const custom = cur && !d.presets.includes(cur);
  return `<div class="disc">
    <div class="discbtns"><button data-disc="" class="${cur ? '' : 'on'}">原价</button>${d.presets.map((p) => `<button data-disc="${p}" class="${cur === p ? 'on' : ''}">${zhe(p)}</button>`).join('')}<button data-disc="custom" class="${custom ? 'on' : ''}">${custom ? zhe(cur) : '其他'}</button></div>
    <label class="discall"><input type="checkbox" id="discall" ${d.all ? 'checked' : ''}> 全部订单打折${d.all ? `（现在每单都打 ${zhe(d.all)}）` : ''}</label></div>`;
}
async function setDiscount(pct) {
  state.discount = pct;
  if (state.me.discount.all && pct) {
    await act(async () => { state.me.discount = await api('POST', '/api/discount-all', { pct }); });
  } else if (state.me.discount.all && !pct) {
    await act(async () => { state.me.discount = await api('POST', '/api/discount-all', { pct: null }); });
  }
  drawCart();
}
function drawCart() {
  const el = $('#cart'); if (!el) return;
  const sub = cartSubtotal();
  const total = cartTotal();
  const lo = state.lastOrder;
  el.innerHTML = `
    ${lo ? `<div class="lastorder"><span>上一单 #${lo.id} 已收 <b class="num">¥${yuan(lo.paid_cents)}</b>${lo.overpay_cents ? `<span class="muted">（含溢收 ¥${yuan(lo.overpay_cents)}）</span>` : ''}</span>${canPrint() ? '<button class="btn small" id="printlast">打印小票</button>' : ''}</div>` : ''}
    <div class="row between"><h3>本单</h3>${state.cart.length ? '<button class="btn small" id="clear">清空</button>' : ''}</div>
    <div class="cart-lines">${state.cart.map((l, i) => `<div class="cline">
      <span>${esc(l.name)}<br><span class="muted num">¥${yuan(l.price_cents)}</span></span>
      <span class="qty"><button data-dec="${i}" aria-label="减少">−</button><span class="num">${l.qty}</span><button data-inc="${i}" aria-label="增加">+</button></span>
      <span class="num">${yuan(l.qty * l.price_cents)}</span></div>`).join('') || '<p class="muted">点左边的商品加入</p>'}</div>
    <div class="row">
      <label class="btn small" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">📷 ${state.photo ? '换照片' : '拍照'}<input type="file" accept="image/*" capture="environment" id="photo" hidden></label>
      ${state.photo ? `<img class="thumb sm" src="${state.photo}" alt="商品照片"><button class="btn small" id="rmphoto">删除照片</button>` : '<span class="muted" style="font-size:12px">存票消费时建议拍照</span>'}
    </div>
    ${discountHtml()}
    ${state.discount && sub ? `<div class="row between muted" style="font-size:14px"><span>原价 <span class="num">¥${yuan(sub)}</span>　${zhe(state.discount)}</span><span class="num">优惠 −${yuan(sub - total)}</span></div>` : ''}
    <div class="total"><span>合计</span><span class="num">¥${yuan(total)}</span></div>
    <div class="paybtns">${Object.entries(METHOD).map(([k, v]) => `<button class="m-${k}" data-pay="${k}" ${state.cart.length ? '' : 'disabled'}>${v}</button>`).join('')}</div>`;
  $$('[data-inc]', el).forEach((b) => b.onclick = () => { state.cart[b.dataset.inc].qty++; drawCart(); });
  $$('[data-dec]', el).forEach((b) => b.onclick = () => { const l = state.cart[b.dataset.dec]; if (--l.qty <= 0) state.cart.splice(b.dataset.dec, 1); drawCart(); });
  const c = $('#clear', el); if (c) c.onclick = () => { state.cart = []; state.photo = null; drawCart(); };
  $('#photo', el).onchange = (e) => act(async () => { const f = e.target.files[0]; if (f) { state.photo = await compressImage(f); drawCart(); } });
  const rp = $('#rmphoto', el); if (rp) rp.onclick = () => { state.photo = null; drawCart(); };
  $$('[data-pay]', el).forEach((b) => b.onclick = () => payFlow(b.dataset.pay));
  const pl = $('#printlast', el); if (pl) pl.onclick = () => printReceipt('order', { id: lo.id });
  $$('[data-disc]', el).forEach((b) => b.onclick = () => {
    const v = b.dataset.disc;
    if (v !== 'custom') return setDiscount(v ? Number(v) : null);
    const m = modal(`<h3>其他折扣</h3><label class="f"><span>打几折（例如 7.5 表示 7.5 折）</span><input id="z" inputmode="decimal"></label>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确定</button></div>`);
    $('#ok', m.el).onclick = () => {
      const pct = Math.round(parseFloat($('#z', m.el).value) * 10);
      if (!(pct >= 1 && pct <= 99)) return toast('请填 0.1 到 9.9 之间的数', true);
      m.close(); setDiscount(pct);
    };
  });
  const da = $('#discall', el);
  if (da) da.onchange = () => act(async () => {
    if (da.checked) {
      const pct = state.discount || state.me.discount.presets[0];
      state.me.discount = await api('POST', '/api/discount-all', { pct });
      state.discount = pct;
      toast(`已开启：每一单都打 ${zhe(pct)}`);
    } else {
      state.me.discount = await api('POST', '/api/discount-all', { pct: null });
      state.discount = null;
      toast('已关闭全部打折');
    }
    drawCart();
  });
  const mb = $('#mbar');
  if (mb) {
    const n = state.cart.reduce((s, l) => s + l.qty, 0);
    mb.innerHTML = n ? `<span>${n} 件　<b class="num">¥${yuan(total)}</b></span><button class="btn primary" id="tocart">去结账</button>` : '';
    mb.classList.toggle('hidden', !n);
    const tc = $('#tocart'); if (tc) tc.onclick = () => el.scrollIntoView({ behavior: 'smooth' });
  }
}

async function submitOrder(payments, m) {
  return act(async () => {
    const r = await api('POST', '/api/orders', {
      items: state.cart.map((l) => ({ product_id: l.product_id, name: l.name, price_cents: l.price_cents, qty: l.qty })),
      payments, photo: state.photo, discount_pct: state.discount || null,
    });
    m && m.close();
    state.cart = []; state.photo = null; state.lastOrder = r; state.discount = state.me.discount.all; drawCart();
    refreshProdStats();
    toast(r.overpay_cents ? `已收款：餐票 ¥${yuan(r.paid_cents)}，多出 ¥${yuan(r.overpay_cents)} 不找零` : `已收款 ¥${yuan(r.total_cents)}`);
    const auto = state.me.print.auto;
    if (canPrint() && (auto === 'all' || (auto === 'stored' && r.has_stored))) printReceipt('order', { id: r.id });
  });
}
const supplementSelect = () => `<select id="sup"><option value="cash">现金</option><option value="pos">收银机</option></select>`;

function payFlow(method) {
  const total = cartTotal();
  if (method === 'pos') {
    const m = modal(`<h3>学校收银机收款</h3><p>请在学校收银机上收 <b class="num">¥${yuan(total)}</b>，刷卡成功后点确认。</p>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">已刷卡，确认</button></div>`);
    $('#ok', m.el).onclick = () => submitOrder([{ method: 'pos', amount_cents: total }], m);
    return;
  }
  if (method === 'cash') {
    const m = modal(`<h3>现金收款 <span class="num">¥${yuan(total)}</span></h3>
      <label class="f"><span>实收（元，可不填）</span><input id="got" inputmode="decimal"></label>
      <p id="chg" class="muted">找零：—</p>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确认收款</button></div>`);
    $('#got', m.el).oninput = (e) => { const g = toCents(e.target.value); $('#chg', m.el).textContent = g >= total ? `找零：¥${yuan(g - total)}` : '找零：—'; };
    $('#ok', m.el).onclick = () => submitOrder([{ method: 'cash', amount_cents: total }], m);
    return;
  }
  if (method === 'ticket') {
    const faces = state.me.ticket_faces.length ? state.me.ticket_faces : [1000];
    const counts = Object.fromEntries(faces.map((f) => [f, 0]));
    const m = modal(`<h3>临时用票 · 应付 <span class="num">¥${yuan(total)}</span></h3>
      <p class="muted" style="font-size:13px">票面超过应付时不找零，多出的部分记为餐票溢收。</p>
      <div id="faces">${faces.map((f) => `<div class="counter"><b>${faceText(f)} 元票</b><span class="qty"><button data-d="${f}">−</button><span class="num" id="c${f}">0</span><button data-i="${f}">+</button></span></div>`).join('')}</div>
      <p id="tsum"></p>
      <div id="supwrap" class="hidden"><label class="f"><span>差额用什么补</span>${supplementSelect()}</label></div>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok" disabled>确认收款</button></div>`);
    const upd = () => {
      const t = faces.reduce((s, f) => s + f * counts[f], 0);
      faces.forEach((f) => { $('#c' + f, m.el).textContent = counts[f]; });
      const diff = t - total;
      const used = faces.filter((f) => counts[f] > 0);
      const minFace = used.length ? Math.min(...used) : 0;
      const tooMany = diff > 0 && diff >= minFace;
      $('#tsum', m.el).innerHTML = t === 0 ? '<span class="muted">请选择收到的餐票</span>'
        : tooMany ? `票面 <b class="num">¥${yuan(t)}</b>，<b class="warn">多了一张 ${faceText(minFace)} 元票，少收一张也够付</b>`
        : diff > 0 ? `票面 <b class="num">¥${yuan(t)}</b>，多出 <b class="num">¥${yuan(diff)}</b> 不找零（记为餐票溢收）`
        : diff === 0 ? `票面 <b class="num">¥${yuan(t)}</b>，刚好`
        : `票面 <b class="num">¥${yuan(t)}</b>，还差 <b class="num warn">¥${yuan(-diff)}</b>`;
      $('#supwrap', m.el).classList.toggle('hidden', !(t > 0 && diff < 0));
      $('#ok', m.el).disabled = t === 0 || tooMany;
    };
    $$('[data-i]', m.el).forEach((b) => b.onclick = () => { counts[b.dataset.i]++; upd(); });
    $$('[data-d]', m.el).forEach((b) => b.onclick = () => { if (counts[b.dataset.d] > 0) counts[b.dataset.d]--; upd(); });
    $('#ok', m.el).onclick = () => {
      const tickets = faces.filter((f) => counts[f] > 0).map((f) => ({ face_cents: f, count: counts[f] }));
      const t = tickets.reduce((s, k) => s + k.face_cents * k.count, 0);
      const pays = [{ method: 'ticket', tickets }];
      if (t < total) pays.push({ method: $('#sup', m.el).value, amount_cents: total - t });
      submitOrder(pays, m);
    };
    upd();
    return;
  }
  if (method === 'stored') {
    let picked = null;
    const m = modal(`<h3>存票余额 · 应付 <span class="num">¥${yuan(total)}</span></h3>
      <label class="f"><span>输入 5 位查询码或姓名</span><input id="q" autocomplete="off"></label>
      <div class="results" id="res"></div>
      <div id="info"></div>
      ${state.photo ? '' : '<p class="muted" style="font-size:13px">提示：可以先关掉这个窗口，在购物车里拍照再结账。</p>'}
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok" disabled>确认扣款</button></div>`);
    let timer;
    const search = async () => {
      const q = $('#q', m.el).value.trim();
      if (!q) { $('#res', m.el).innerHTML = ''; return; }
      const rows = await api('GET', '/api/accounts?q=' + encodeURIComponent(q)).catch((e) => { toast(e.message, true); return []; });
      const act_ = rows.filter((a) => a.status === 'active');
      $('#res', m.el).innerHTML = act_.map((a) => `<button class="result" data-aid="${a.id}"><span><b>${esc(a.name)}</b>　<span class="muted">${esc(a.note || '')}</span><br><span class="muted mono">码 ***${a.code.slice(3)}</span></span><span class="num">¥${yuan(a.balance_cents)}</span></button>`).join('')
        || '<p class="muted">没有找到</p>';
      $$('[data-aid]', m.el).forEach((b) => b.onclick = () => { picked = act_.find((a) => a.id === Number(b.dataset.aid)); $$('.result', m.el).forEach((x) => x.classList.toggle('on', x === b)); pick(); });
      if (act_.length === 1) { picked = act_[0]; $('.result', m.el).classList.add('on'); pick(); }
    };
    const pick = () => {
      const use = Math.min(picked.balance_cents, total);
      const rest = total - use;
      $('#info', m.el).innerHTML = `<p>${esc(picked.name)} 余额 <b class="num">¥${yuan(picked.balance_cents)}</b>，本次扣 <b class="num" style="color:var(--stored)">¥${yuan(use)}</b>${rest > 0 ? `，余额不足还差 <b class="num warn">¥${yuan(rest)}</b>` : `，扣后剩 <b class="num">¥${yuan(picked.balance_cents - use)}</b>`}</p>
        ${rest > 0 ? `<label class="f"><span>差额用什么补</span>${supplementSelect()}</label>` : ''}`;
      $('#ok', m.el).disabled = use <= 0;
    };
    $('#q', m.el).oninput = () => { clearTimeout(timer); picked = null; $('#ok', m.el).disabled = true; $('#info', m.el).innerHTML = ''; timer = setTimeout(search, 250); };
    $('#ok', m.el).onclick = () => {
      const use = Math.min(picked.balance_cents, total);
      const pays = [{ method: 'stored', amount_cents: use, account_id: picked.id }];
      if (total > use) pays.push({ method: $('#sup', m.el).value, amount_cents: total - use });
      submitOrder(pays, m);
    };
  }
}

// ---------- 存票 ----------
function ticketInputs(prefix) {
  const faces = state.me.ticket_faces.length ? state.me.ticket_faces : [1000];
  return `<div>${faces.map((f) => `<div class="counter"><b>${faceText(f)} 元票</b><span class="qty"><button type="button" data-${prefix}d="${f}">−</button><span class="num" data-${prefix}c="${f}">0</span><button type="button" data-${prefix}i="${f}">+</button></span></div>`).join('')}</div>
    <label class="f"><span>或直接填金额（元，没有纸票明细时用）</span><input data-${prefix}amt inputmode="decimal"></label>
    <label class="f"><span>餐票有效期（可不填）</span><input type="date" data-${prefix}exp></label>
    <p data-${prefix}sum class="muted">合计：¥0.00</p>`;
}
function bindTicketInputs(el, prefix) {
  const faces = state.me.ticket_faces.length ? state.me.ticket_faces : [1000];
  const counts = Object.fromEntries(faces.map((f) => [f, 0]));
  const sum = () => {
    const t = faces.reduce((s, f) => s + f * counts[f], 0);
    faces.forEach((f) => { el.querySelector(`[data-${prefix}c="${f}"]`).textContent = counts[f]; });
    const amt = toCents(el.querySelector(`[data-${prefix}amt]`).value);
    el.querySelector(`[data-${prefix}sum]`).textContent = `合计：¥${yuan(t || (amt > 0 ? amt : 0))}`;
  };
  $$(`[data-${prefix}i]`, el).forEach((b) => b.onclick = () => { counts[b.getAttribute(`data-${prefix}i`)]++; sum(); });
  $$(`[data-${prefix}d]`, el).forEach((b) => b.onclick = () => { const k = b.getAttribute(`data-${prefix}d`); if (counts[k] > 0) counts[k]--; sum(); });
  el.querySelector(`[data-${prefix}amt]`).oninput = sum;
  return () => {
    const tickets = faces.filter((f) => counts[f] > 0).map((f) => ({ face_cents: f, count: counts[f] }));
    const amt = toCents(el.querySelector(`[data-${prefix}amt]`).value);
    return { tickets, amount_cents: tickets.length ? undefined : amt, expire_date: el.querySelector(`[data-${prefix}exp]`).value || undefined };
  };
}
function showCode(name, code, accountId) {
  const m = modal(`<h3>${esc(name)} 的查询码</h3><div class="bigcode">${code}</div>
    <p>请顾客拍照或记下这个号码。连上店里 WiFi 后打开 <b class="mono">${esc(state.me.query_url)}</b> 输入号码即可查询余额和消费记录。</p>
    <p class="muted" style="font-size:13px">号码只告诉本人，不要写名字一起贴出来。</p>
    <div class="acts">${canPrint() ? '<button class="btn" id="pc">打印凭条</button>' : ''}<button class="btn primary" data-close>好的</button></div>`);
  const pc = $('#pc', m.el); if (pc) pc.onclick = () => printReceipt('account_code', { id: accountId });
}
async function renderAccounts(main) {
  const sum = await api('GET', '/api/accounts/summary').catch(() => ({ active_accounts: 0, liability_cents: 0 }));
  main.innerHTML = `<div class="stack">
    <div class="stats"><div class="stat"><span class="k">存票账户</span><span class="v">${sum.active_accounts}</span></div>
      <div class="stat m-stored"><span class="k">存票余额合计（店里欠顾客的）</span><span class="v">¥${yuan(sum.liability_cents)}</span></div></div>
    <div class="row"><input id="aq" placeholder="搜索姓名、备注或 5 位码" style="flex:1;min-width:200px"><button class="btn primary" id="newacc">+ 存票开户</button></div>
    <div class="card tbl"><table><thead><tr><th>姓名</th><th>备注</th><th>查询码</th><th class="r">余额</th><th>状态</th><th>开户时间</th></tr></thead><tbody id="alist"></tbody></table></div>
  </div>`;
  const load = async () => {
    const rows = await api('GET', '/api/accounts?q=' + encodeURIComponent($('#aq').value.trim())).catch((e) => { toast(e.message, true); return []; });
    $('#alist').innerHTML = rows.map((a) => `<tr data-aid="${a.id}" style="cursor:pointer"><td><b>${esc(a.name)}</b></td><td>${esc(a.note)}</td><td class="mono">***${a.code.slice(3)}</td>
      <td class="r num">${yuan(a.balance_cents)}</td><td>${a.status === 'active' ? '<span class="pill m-stored">正常</span>' : '<span class="pill">已销户</span>'}</td><td class="muted">${esc(a.created_at.slice(0, 10))}</td></tr>`).join('')
      || '<tr><td colspan="6" class="empty">还没有存票账户</td></tr>';
    $$('[data-aid]').forEach((tr) => tr.onclick = () => accountDetail(Number(tr.dataset.aid), load));
  };
  tableTools(main, '存票账户', () => ($('#aq').value.trim() ? `搜索：${$('#aq').value.trim()}` : dateStr()));
  let t; $('#aq').oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  $('#newacc').onclick = () => {
    const m = modal(`<h3>存票开户</h3>
      <label class="f"><span>姓名</span><input id="nn"></label>
      <label class="f"><span>备注（店员可见，例如学院、手机尾号）</span><input id="nt"></label>
      ${ticketInputs('n')}
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">开户并生成查询码</button></div>`);
    const read = bindTicketInputs(m.el, 'n');
    $('#ok', m.el).onclick = () => act(async () => {
      const r = await api('POST', '/api/accounts', { name: $('#nn', m.el).value, note: $('#nt', m.el).value, ...read() });
      m.close(); load(); showCode($('#nn', m.el).value, r.code, r.id);
    });
  };
  load();
}
async function accountDetail(id, reload) {
  const a = await api('GET', '/api/accounts/' + id).catch((e) => toast(e.message, true));
  if (!a) return;
  const owner = state.me.role === 'owner';
  const m = modal(`<div class="row between"><h3>${esc(a.name)} <span class="muted" style="font-weight:400">${esc(a.note)}</span></h3>${a.status === 'active' ? '' : '<span class="pill">已销户</span>'}</div>
    <div class="row between"><span>余额 <b class="num" style="font-size:24px;color:var(--stored)">¥${yuan(a.balance_cents)}</b></span>
      <span class="muted">查询码 <span class="mono" id="codev">***${a.code.slice(3)}</span> <button class="btn small" id="showcode">显示</button></span></div>
    <div class="row">${canPrint() ? '<button class="btn" id="pbal">打印余额凭条</button>' : ''}${a.status === 'active' ? `<button class="btn primary" id="dep">续存</button>${owner ? '<button class="btn" id="adj">调整余额</button><button class="btn" id="reset">重置查询码</button><button class="btn danger" id="closeacc">销户</button>' : ''}` : ''}</div>
    <div class="tbl"><table><thead><tr><th>时间</th><th>类型</th><th class="r">金额</th><th>明细</th><th>照片</th></tr></thead><tbody>
    ${a.txs.map((t) => `<tr><td class="muted">${esc(t.created_at.slice(5, 16))}</td><td>${TX[t.type] || t.type}</td><td class="r num ${t.amount_cents < 0 ? '' : 'ok'}">${t.amount_cents > 0 ? '+' : ''}${yuan(t.amount_cents)}</td>
      <td>${esc(t.items || t.note || '')}<br><span class="muted" style="font-size:12px">${esc(t.operator_name || '')}</span></td><td>${t.photo ? `<img class="thumb sm" src="/photos/${esc(t.photo)}" alt="照片">` : ''}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">没有记录</td></tr>'}
    </tbody></table></div>
    <div class="acts"><button class="btn" data-close>关闭</button></div>`);
  const again = () => { m.close(); reload && reload(); accountDetail(id, reload); };
  $('#showcode', m.el).onclick = () => { $('#codev', m.el).textContent = a.code; };
  const pb = $('#pbal', m.el); if (pb) pb.onclick = () => printReceipt('account_balance', { id });
  const dep = $('#dep', m.el);
  if (dep) dep.onclick = () => {
    const d = modal(`<h3>${esc(a.name)} 续存</h3>${ticketInputs('d')}<div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确认存入</button></div>`);
    const read = bindTicketInputs(d.el, 'd');
    $('#ok', d.el).onclick = () => act(async () => { await api('POST', `/api/accounts/${id}/deposit`, read()); d.close(); toast('已存入'); again(); });
  };
  const adj = $('#adj', m.el);
  if (adj) adj.onclick = () => {
    const d = modal(`<h3>调整余额</h3><label class="f"><span>调整金额（元，减少填负数）</span><input id="v" inputmode="decimal"></label>
      <label class="f"><span>原因</span><input id="r"></label><div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确认</button></div>`);
    $('#ok', d.el).onclick = () => act(async () => { await api('POST', `/api/accounts/${id}/adjust`, { amount_cents: toCents($('#v', d.el).value), note: $('#r', d.el).value }); d.close(); again(); });
  };
  const reset = $('#reset', m.el);
  if (reset) reset.onclick = () => act(async () => {
    if (!confirm('重置后旧码立即失效，确定吗？')) return;
    const r = await api('POST', `/api/accounts/${id}/reset-code`); m.close(); reload && reload(); showCode(a.name, r.code, id);
  });
  const cl = $('#closeacc', m.el);
  if (cl) cl.onclick = () => act(async () => {
    if (!confirm(`销户后余额 ¥${yuan(a.balance_cents)} 记为已退还顾客，确定吗？`)) return;
    await api('POST', `/api/accounts/${id}/close`, {}); toast('已销户'); again();
  });
}

// ---------- 订单 ----------
async function renderOrders(main) {
  const owner = state.me.role === 'owner';
  main.innerHTML = `<div class="stack"><div class="row"><input type="date" id="od" value="${dateStr()}" style="max-width:200px" ${owner ? '' : 'max="' + dateStr() + '"'}></div><div id="ostats"></div><div id="owrap"><div class="card tbl" id="olist"></div></div></div>`;
  const load = async () => {
    const d = $('#od').value;
    const rows = await api('GET', `/api/orders?from=${d}&to=${d}`).catch((e) => { toast(e.message, true); return []; });
    const by = { cash: 0, pos: 0, ticket: 0, stored: 0 };
    const done = rows.filter((o) => o.status === 'done');
    done.forEach((o) => o.payments.forEach((p) => { by[p.method] += p.amount_cents; }));
    const over = done.reduce((s, o) => s + (o.overpay_cents || 0), 0);
    $('#ostats').innerHTML = `<div class="stats">${Object.entries(METHOD).map(([k, v]) => `<div class="stat m-${k}"><span class="k">${v}${k === 'ticket' && over ? `（含溢收 ${yuan(over)}）` : ''}</span><span class="v">¥${yuan(by[k])}</span></div>`).join('')}
      <div class="stat"><span class="k">有效单数</span><span class="v">${done.length}</span></div></div>`;
    const actions = owner || canPrint();
    $('#owrap').innerHTML = '<div class="card tbl" id="olist"></div>';
    $('#olist').innerHTML = `<table><thead><tr><th>时间</th><th>商品</th><th class="r">金额</th><th>收款</th><th>照片</th><th>收银员</th>${actions ? '<th></th>' : ''}</tr></thead><tbody>
      ${rows.map((o) => `<tr class="${o.status === 'void' ? 'void' : ''}"><td class="muted">${esc(o.created_at.slice(11, 16))}</td>
        <td>${o.items.map((i) => `${esc(i.name)}×${i.qty}`).join('、')}${o.status === 'void' ? `<br><span class="pill bad">已撤销：${esc(o.void_reason)}</span>` : ''}</td>
        <td class="r num">${yuan(o.total_cents)}${o.discount_cents ? `<br><span class="pill">${zhe(o.discount_pct)} −${yuan(o.discount_cents)}</span>` : ''}</td>
        <td>${o.payments.map((p) => `<span class="pill m-${p.method}">${p.detail === '餐票找零' ? '找零' : METHOD[p.method]} ${yuan(p.amount_cents)}${p.account_name ? ' · ' + esc(p.account_name) : ''}</span>`).join(' ')}${o.overpay_cents ? ` <span class="pill">溢收 ${yuan(o.overpay_cents)}</span>` : ''}</td>
        <td>${o.photo ? `<img class="thumb sm" src="/photos/${esc(o.photo)}" alt="照片">` : ''}</td><td class="muted">${esc(o.cashier_name)}</td>
        ${actions ? `<td><div class="row" style="gap:4px;flex-wrap:nowrap">${canPrint() ? `<button class="btn small" data-print="${o.id}">打印</button>` : ''}${owner && o.status === 'done' ? `<button class="btn small danger" data-void="${o.id}">撤单</button>` : ''}</div></td>` : ''}</tr>`).join('') || `<tr><td colspan="7" class="empty">这天没有订单</td></tr>`}
      </tbody></table>`;
    tableTools($('#ostats').parentNode, '订单', () => d);
    $$('[data-print]').forEach((b) => b.onclick = () => printReceipt('order', { id: Number(b.dataset.print) }));
    $$('[data-void]').forEach((b) => b.onclick = () => {
      const m = modal(`<h3>撤销订单</h3><p class="muted">存票扣款会退回账户，这单不再计入统计。</p><label class="f"><span>原因</span><input id="r"></label>
        <div class="acts"><button class="btn" data-close>取消</button><button class="btn danger" id="ok">确认撤单</button></div>`);
      $('#ok', m.el).onclick = () => act(async () => { await api('POST', `/api/orders/${b.dataset.void}/void`, { reason: $('#r', m.el).value }); m.close(); toast('已撤单'); load(); });
    });
  };
  $('#od').onchange = load;
  load();
}

// ---------- 日结 ----------
async function renderClose(main) {
  main.innerHTML = `<div class="stack"><div class="row"><input type="date" id="cd" value="${dateStr()}" style="max-width:200px"></div><div id="cbody"></div></div>`;
  const load = async () => {
    const r = await api('GET', '/api/dayclose?date=' + $('#cd').value).catch((e) => toast(e.message, true));
    if (!r) return;
    const s = r.system; const sv = r.saved;
    // 店内余票：今天按面额点张数，合计和票据库存比；以前的日期看当时保存的记录
    const isToday = r.date === r.today;
    const savedTk = sv && sv.tickets ? sv.tickets : null;
    const tkSystem = isToday ? r.ticket_stock_cents : savedTk ? savedTk.system_cents : null;
    const faces = isToday ? r.faces : savedTk ? savedTk.rows.map((x) => x.face_cents) : [];
    const tk = tkSystem === null ? null : faces.map((f) => ({ face_cents: f, count: savedTk ? (savedTk.rows.find((x) => x.face_cents === f) || {}).count ?? null : null }));
    $('#cbody').innerHTML = `
      <div class="stats">${Object.entries(METHOD).map(([k, v]) => `<div class="stat m-${k}"><span class="k">${v} · ${s.orders_by_method[k]} 单</span><span class="v">¥${yuan(s.amounts[k])}</span></div>`).join('')}
        <div class="stat"><span class="k">四种来源合计 · ${s.orders} 单</span><span class="v">¥${yuan(s.paid_cents)}</span></div></div>
      <p class="muted">商品金额 ¥${yuan(s.total_cents)}${s.discount_cents ? `（打折优惠 ¥${yuan(s.discount_cents)}）` : ''}${s.overpay_cents ? `，餐票溢收 ¥${yuan(s.overpay_cents)}（已算在临时用票里）` : ''}。当天另有存票存入 ¥${yuan(s.deposits_cents)}（不算营业额）${s.voided ? `，撤销 ${s.voided} 单` : ''}。</p>
      <div class="card"><h3>对账</h3><div class="grid2">
        <label class="f"><span>实点现金（元）· 系统 ¥${yuan(s.amounts.cash)}</span><input id="ca" inputmode="decimal" value="${sv ? yuan(sv.cash_actual_cents) : ''}"></label>
        <label class="f"><span>学校收银机小票合计（元）· 系统 ¥${yuan(s.amounts.pos)}</span><input id="pa" inputmode="decimal" value="${sv ? yuan(sv.pos_actual_cents) : ''}"></label></div>
        <h3 style="margin-top:4px">店内余票</h3>
        ${tk ? `<div class="tbl"><table id="tktbl"><thead><tr><th>面额</th><th class="r">实点（张）</th><th class="r">金额</th></tr></thead><tbody>
          ${tk.map((t) => `<tr><td>${faceText(t.face_cents)} 元票</td>
            <td class="r">${isToday ? `<input data-tk="${t.face_cents}" inputmode="numeric" value="${t.count ?? ''}" style="width:90px;text-align:right">` : `<span class="num">${t.count ?? '—'}</span>`}</td>
            <td class="r num" data-tkd="${t.face_cents}"></td></tr>`).join('')}
          <tr><td><b>实点合计</b></td><td></td><td class="r num" id="tkact"></td></tr>
          <tr><td><b>票据库存（系统应有）</b></td><td></td><td class="r num">¥${yuan(tkSystem)}</td></tr></tbody></table></div>
          <p class="muted" style="font-size:13px">票据库存 = 收进来的临时用票和存票纸票，减去去学校兑换和自由出库的金额。${isToday ? '' : '这是当天日结时的记录。'}</p>`
          : '<p class="muted">这天日结时没有清点余票。</p>'}
        <p id="diff"></p>
        <label class="f"><span>差额原因（有差额时必填）</span><input id="cn" value="${esc(sv ? sv.note : '')}"></label>
        <div class="row between"><span class="muted">${sv ? `已于 ${esc(sv.closed_at)} 由 ${esc(sv.closed_by)} 日结` : '今天还没日结'}</span>
          <span class="row"><button class="btn" id="cexp">导出 Excel</button><button class="btn" id="ca4">打印（A4）</button>${canPrint() ? '<button class="btn" id="cprint">打印小票</button>' : ''}<button class="btn primary" id="save">${sv ? '更新日结' : '保存日结'}</button></span></div>
        <p class="muted" style="font-size:13px">若钱箱里有备用零钱，请先减去再填实点现金。</p></div>`;
    const diff = () => {
      const c = toCents($('#ca').value); const p = toCents($('#pa').value);
      const parts = [];
      if (Number.isFinite(c)) parts.push(`现金差额 <b class="num ${c - s.amounts.cash ? 'warn' : 'ok'}">${yuan(c - s.amounts.cash)}</b>`);
      if (Number.isFinite(p)) parts.push(`收银机差额 <b class="num ${p - s.amounts.pos ? 'warn' : 'ok'}">${yuan(p - s.amounts.pos)}</b>`);
      if (tk) {
        let filled = false; let actSum = 0;
        tk.forEach((t) => {
          const inp = $(`[data-tk="${t.face_cents}"]`);
          const v = inp ? (inp.value.trim() === '' ? null : parseInt(inp.value, 10)) : t.count;
          const cell = $(`[data-tkd="${t.face_cents}"]`);
          if (v === null || Number.isNaN(v)) { cell.textContent = ''; return; }
          filled = true; actSum += v * t.face_cents;
          cell.textContent = yuan(v * t.face_cents);
        });
        $('#tkact').textContent = filled ? '¥' + yuan(actSum) : '';
        const dd = actSum - tkSystem;
        if (filled) parts.push(`余票差额 <b class="num ${dd ? 'warn' : 'ok'}">${yuan(dd)}</b>`);
      }
      $('#diff').innerHTML = parts.join('　');
    };
    $('#ca').oninput = diff; $('#pa').oninput = diff; $$('[data-tk]').forEach((i) => { i.oninput = diff; }); diff();
    const cp = $('#cprint'); if (cp) cp.onclick = () => printReceipt('dayclose', { date: $('#cd').value });
    // 日结单（A4 / Excel）：按页面上现在填的数
    const closeTables = () => {
      const c = toCents($('#ca').value); const p = toCents($('#pa').value);
      const t1 = { name: '收款', head: ['项目', '单数', '金额'], rows: [
        ...Object.entries(METHOD).map(([k, v]) => [v, s.orders_by_method[k], yuan(s.amounts[k])]),
        ['四种来源合计', s.orders, yuan(s.paid_cents)], ['商品金额', '', yuan(s.total_cents)],
        ...(s.discount_cents ? [['打折优惠', '', yuan(s.discount_cents)]] : []), ...(s.overpay_cents ? [['餐票溢收（含在临时用票里）', '', yuan(s.overpay_cents)]] : []),
        ['当天存票存入（不算营业额）', '', yuan(s.deposits_cents)], ...(s.voided ? [['撤销单数', s.voided, '']] : [])] };
      const t2 = { name: '对账', head: ['项目', '系统', '实际', '差额'], rows: [
        ['现金', yuan(s.amounts.cash), Number.isFinite(c) ? yuan(c) : '', Number.isFinite(c) ? yuan(c - s.amounts.cash) : ''],
        ['学校收银机', yuan(s.amounts.pos), Number.isFinite(p) ? yuan(p) : '', Number.isFinite(p) ? yuan(p - s.amounts.pos) : '']] };
      const out = [t1, t2];
      if ($('#tktbl')) { const d = tableData($('#tktbl')); out.push({ name: '店内余票', ...d }); }
      if ($('#cn').value.trim()) out.push({ name: '备注', head: ['差额原因'], rows: [[$('#cn').value.trim()]] });
      return out;
    };
    $('#ca4').onclick = () => printTables(`日结单 ${r.date}`, `${state.me.shop_name}　${sv ? `${sv.closed_by} 于 ${sv.closed_at} 日结` : '还没保存日结'}`, closeTables());
    $('#cexp').onclick = () => {
      const rows = [];
      closeTables().forEach((t) => { rows.push([`【${t.name}】`], t.head, ...t.rows, []); });
      downloadCsv(`日结单_${r.date}`, [`${state.me.shop_name} 日结单 ${r.date}`], rows);
    };
    $('#save').onclick = () => act(async () => {
      const tickets_actual = $$('[data-tk]').map((i) => ({ face_cents: Number(i.dataset.tk), count: i.value.trim() === '' ? null : parseInt(i.value, 10) }));
      if (tickets_actual.some((t) => t.count !== null && !(t.count >= 0))) throw new Error('余票张数要填整数');
      await api('POST', '/api/dayclose', { date: $('#cd').value, cash_actual_cents: toCents($('#ca').value), pos_actual_cents: toCents($('#pa').value), note: $('#cn').value, tickets_actual });
      toast('日结已保存'); load();
    });
  };
  $('#cd').onchange = load;
  load();
}

// ---------- 出品 ----------
async function renderProduction(main) {
  const prods = (await api('GET', '/api/products').catch(() => [])).filter((p) => p.active);
  main.innerHTML = `<div class="stack">
    <div class="row"><input type="date" id="pd" value="${dateStr()}" style="max-width:200px"><span class="muted">收银和出品暂不关联，这里单独登记后厨数据。</span></div>
    <div class="card"><h3>登记出品</h3><div class="grid2">
      <label class="f"><span>商品</span><select id="pp">${prods.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}<option value="new">＋ 新品（还没有这个商品）</option></select></label>
      <label class="f newp hidden"><span>新品名称</span><input id="nn"></label>
      <label class="f newp hidden"><span>售价（元）</span><input id="np" inputmode="decimal"></label>
      <label class="f newp hidden"><span>分类（可不填）</span><input id="nc" placeholder="新品"></label>
      <label class="f"><span>类型</span><select id="pt"><option value="output">出炉</option><option value="loss">报损</option><option value="leftover">收档剩余</option></select></label>
      <label class="f"><span>数量</span><input id="pq" inputmode="numeric"></label>
      <label class="f"><span>备注</span><input id="pn" placeholder="报损原因等"></label></div>
      <p class="muted newp hidden" style="font-size:13px">新品登记后会自动加到"设置 → 商品"里，收银页面也能直接卖。</p>
      <div><button class="btn primary" id="padd">登记</button></div></div>
    <div id="pbody"></div></div>`;
  const newShow = () => $$('.newp').forEach((el) => el.classList.toggle('hidden', $('#pp').value !== 'new'));
  $('#pp').onchange = newShow;
  const load = async () => {
    const d = $('#pd').value;
    const r = await api('GET', '/api/production?date=' + d).catch((e) => toast(e.message, true));
    if (!r) return;
    // 出品表：前一天保存的生产计划 + 当天登记过的其他商品
    const rows = new Map();
    for (const p of r.plan) rows.set(p.product_id, { id: p.product_id, name: p.name, plan: p.qty, output: 0, loss: 0, leftover: 0 });
    for (const l of r.logs) {
      if (!rows.has(l.product_id)) rows.set(l.product_id, { id: l.product_id, name: l.name, plan: null, output: 0, loss: 0, leftover: 0 });
      rows.get(l.product_id)[l.type] += l.qty;
    }
    const list = [...rows.values()];
    const tot = (k) => list.reduce((a, x) => a + (x[k] || 0), 0);
    $('#pbody').innerHTML = `<div class="card tbl"><h3>出品表 <span class="muted" style="font-weight:400;font-size:13px">${r.plan.length ? '计划数来自前一天保存的生产计划' : '这天没有生产计划，在"生产计划"页保存后会自动列在这里'}</span></h3>
      <table><thead><tr><th>商品</th><th class="r">计划</th><th class="r">出炉</th><th class="r">还差</th><th class="r">报损</th><th class="r">收档剩余</th><th></th></tr></thead><tbody>
      ${list.map((x) => `<tr><td><b>${esc(x.name)}</b>${x.plan === null ? ' <span class="pill">计划外</span>' : ''}</td><td class="r num">${x.plan ?? '—'}</td><td class="r num">${x.output}</td>
        <td class="r num">${x.plan === null ? '—' : x.plan - x.output > 0 ? `<span class="warn">${x.plan - x.output}</span>` : '<span class="ok">0</span>'}</td><td class="r num">${x.loss}</td><td class="r num">${x.leftover}</td>
        <td><div class="row" style="gap:4px;flex-wrap:nowrap"><input data-q="${x.id}" inputmode="numeric" placeholder="数量" style="width:72px;min-height:32px;padding:4px 8px">
          <button class="btn small" data-add="${x.id}" data-type="output">出炉</button><button class="btn small" data-add="${x.id}" data-type="loss">报损</button><button class="btn small" data-add="${x.id}" data-type="leftover">剩余</button></div></td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">还没有计划，也还没有登记</td></tr>'}
      ${list.length ? `<tr><td><b>合计</b></td><td class="r num">${tot('plan')}</td><td class="r num">${tot('output')}</td><td></td><td class="r num">${tot('loss')}</td><td class="r num">${tot('leftover')}</td><td></td></tr>` : ''}
      </tbody></table></div>
      <div class="card tbl"><h3>登记明细</h3><table><thead><tr><th>时间</th><th>商品</th><th>类型</th><th class="r">数量</th><th>备注</th><th>登记人</th><th></th></tr></thead><tbody>
      ${r.logs.map((l) => `<tr><td class="muted">${esc(l.created_at.slice(11, 16))}</td><td>${esc(l.name)}</td><td>${PROD_TYPE[l.type]}</td><td class="r num">${l.qty}</td><td>${esc(l.note)}</td><td class="muted">${esc(l.operator_name)}</td><td><button class="btn small" data-del="${l.id}">删除</button></td></tr>`).join('') || '<tr><td colspan="7" class="empty">—</td></tr>'}
      </tbody></table></div>`;
    tableTools($('#pbody'), '出品', d);
    $$('[data-add]').forEach((b) => b.onclick = () => act(async () => {
      const inp = $(`[data-q="${b.dataset.add}"]`);
      const qty = parseInt(inp.value, 10);
      if (!(qty > 0)) { inp.focus(); throw new Error('请先在这一行填数量'); }
      await api('POST', '/api/production', { date: d, product_id: Number(b.dataset.add), type: b.dataset.type, qty });
      toast(`已登记${PROD_TYPE[b.dataset.type]} ${qty}`); load();
    }));
    $$('[data-del]').forEach((b) => b.onclick = () => act(async () => { if (!confirm('删除这条记录？')) return; await api('POST', `/api/production/${b.dataset.del}/delete`); load(); }));
  };
  $('#padd').onclick = () => act(async () => {
    const base = { date: $('#pd').value, type: $('#pt').value, qty: Number($('#pq').value), note: $('#pn').value };
    if ($('#pp').value === 'new') {
      const r = await api('POST', '/api/production/new-product', { ...base, name: $('#nn').value, price_cents: toCents($('#np').value), category: $('#nc').value });
      // 新品加到下拉框里
      const o = document.createElement('option'); o.value = r.product_id; o.textContent = $('#nn').value.trim();
      $('#pp').insertBefore(o, $('#pp option[value=new]')); $('#pp').value = String(r.product_id); newShow();
      $('#nn').value = ''; $('#np').value = ''; $('#nc').value = '';
      toast('新品已登记，并加到了商品里');
    } else {
      await api('POST', '/api/production', { ...base, product_id: Number($('#pp').value) });
      toast('已登记');
    }
    $('#pq').value = ''; $('#pn').value = ''; load();
  });
  $('#pd').onchange = load;
  load();
}

// ---------- 生产计划 ----------
async function renderPlan(main) {
  const owner = state.me.role === 'owner';
  const wd = '日一二三四五六';
  main.innerHTML = `<div class="stack">
    <div class="row"><input type="date" id="ld" value="${addDays(dateStr(), 1)}" style="max-width:200px"><span id="lw" class="muted"></span></div>
    <p class="muted">建议数 = 近 4 周同一天平均销量 × 0.6 + 近 7 天平均销量 × 0.4，再按前 7 天的剩余和报损比例加 0–10% 余量。数据越多越准，${owner ? '你可以改数后保存，后厨在这里和出品页都能看到。' : '最终数量以店主保存的计划为准。'}</p>
    <div class="card tbl" id="lbody"></div>
    <div class="card tbl" id="ppcard"><h3>原材料订购计划</h3>
      <div class="row"><span>从</span><input type="date" id="ppf" value="${addDays(dateStr(), 1)}" style="max-width:180px"><span>起</span>
        <select id="ppd" style="max-width:110px">${[1, 2, 3, 4, 5, 6, 7].map((n) => `<option value="${n}" ${n === 3 ? 'selected' : ''}>${n} 天</option>`).join('')}</select><span class="muted">按这几天的生产计划和产品配方（BOM）算要用多少原料</span></div>
      <div id="ppbody"></div></div></div>`;
  const loadPP = async () => {
    const r = await api('GET', `/api/purchase-plan?from=${$('#ppf').value}&days=${$('#ppd').value}`).catch((e) => toast(e.message, true));
    if (!r) return;
    const total = r.items.reduce((a, x) => a + x.cost_cents, 0);
    $('#ppbody').innerHTML = `<p class="muted" style="font-size:13px;margin:0">${r.day_info.map((d) => `${d.date.slice(5)} ${d.source === 'saved' ? '计划' : '<span class="warn">系统建议</span>'} ${d.total} 个`).join('，')}。没保存计划的日子按系统建议数算。
      ${r.no_bom.length ? `<br><span class="warn">还没设配方的商品不会算进来：${r.no_bom.map(esc).join('、')}。请店主到"设置 → 产品配方"里设置。</span>` : ''}</p>
      <table><thead><tr><th>原料</th><th>类别</th><th class="r">这几天要用</th><th class="r">现有库存</th><th class="r">预警量</th><th class="r">建议采购</th><th class="r">预计金额</th></tr></thead><tbody>
      ${r.items.map((x) => `<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.kind)}</td><td class="r num">${x.need} ${esc(x.unit)}</td><td class="r num">${x.stock} ${esc(x.unit)}</td><td class="r num">${x.low_qty || 0}</td>
        <td class="r num">${x.short ? `<b class="warn">${x.packs ? `${x.packs} ${esc(x.pack_unit)}（${x.buy_qty} ${esc(x.unit)}）` : `${x.buy_qty} ${esc(x.unit)}`}</b>` : '<span class="ok">够用</span>'}</td><td class="r num">${x.short ? yuan(x.cost_cents) : ''}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">没有需要的原料（可能还没设置产品配方）</td></tr>'}
      ${r.items.length ? `<tr><td><b>合计</b></td><td></td><td></td><td></td><td></td><td></td><td class="r num"><b>${yuan(total)}</b></td></tr>` : ''}
      </tbody></table>
      <p class="muted" style="font-size:13px;margin:0">建议采购 = 这几天要用的 + 预警量 − 现有库存，设置了规格的按整包装（例如整袋）向上取整。金额按库存品的单价估算。</p>`;
    tableTools(main, '原材料订购计划', `${$('#ppf').value} 起 ${$('#ppd').value} 天`);
  };
  $('#ppf').onchange = loadPP; $('#ppd').onchange = loadPP; loadPP();
  const load = async () => {
    const d = $('#ld').value;
    $('#lw').textContent = '星期' + wd[new Date(d + 'T12:00:00').getDay()];
    const r = await api('GET', '/api/plan?date=' + d).catch((e) => toast(e.message, true));
    if (!r) return;
    $('#lbody').innerHTML = `<h3>生产计划</h3><table><thead><tr><th>商品</th><th class="r">同星期均销</th><th class="r">近7天均销</th><th class="r">剩余+报损率</th><th class="r">建议</th><th class="r">计划</th></tr></thead><tbody>
      ${r.rows.map((x) => `<tr><td>${esc(x.name)}</td><td class="r num">${x.avg_same_weekday ?? '—'}</td><td class="r num">${x.avg_7d}</td><td class="r num">${x.waste_rate}%</td><td class="r num"><b>${x.suggest}</b></td>
        <td class="r">${owner ? `<input data-plan="${x.product_id}" inputmode="numeric" value="${x.planned ?? x.suggest}" style="width:90px;text-align:right">` : `<b class="num">${x.planned ?? '未定'}</b>`}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">没有在售商品</td></tr>'}
      </tbody></table>${owner ? '<div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" id="lsave">保存为计划</button></div>' : ''}`;
    $('#lbody').querySelector('.ttools')?.remove();
    tableTools(main, '生产计划', `${d} 星期${wd[new Date(d + 'T12:00:00').getDay()]}`);
    const s = $('#lsave');
    if (s) s.onclick = () => act(async () => {
      const rows = $$('[data-plan]').map((i) => ({ product_id: Number(i.dataset.plan), qty: parseInt(i.value, 10) || 0 }));
      await api('POST', '/api/plan', { date: d, rows }); toast('计划已保存'); load(); loadPP();
    });
  };
  $('#ld').onchange = load;
  load();
}

// ---------- 盘存 ----------
const q3 = (n) => Math.round(n * 1000) / 1000;
const specText = (it) => (it.pack_qty ? `${it.pack_qty}${it.unit}/${it.pack_unit}` : '');
// 粘贴或 CSV 文件的表格文本 → 行数组（Excel 复制出来是制表符分隔）
function parseTable(text) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim());
  const sep = lines.some((l) => l.includes('\t')) ? '\t' : ',';
  return lines.map((l) => {
    if (sep === '\t') return l.split('\t').map((c) => c.trim());
    const out = []; let cur = ''; let q = false;
    for (let i = 0; i < l.length; i++) {
      const c = l[i];
      if (q) { if (c === '"' && l[i + 1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
      else if (c === '"') q = true; else if (c === ',') { out.push(cur.trim()); cur = ''; } else cur += c;
    }
    out.push(cur.trim());
    return out;
  });
}
const IMPORT_HEAD = ['名称', '类别', '主单位', '规格数量', '包装单位', '单价（元/主单位）', '预警量', '期初库存'];
async function renderStock(main) {
  main.innerHTML = `<div class="stack"><div class="row between"><span class="muted">出炉时按产品配方自动扣原料和包材；成品库存 = 出炉 − 售出 − 报损。</span>
      <span class="row"><button class="btn" id="simp">批量导入</button><button class="btn primary" id="sadd">+ 新增库存品</button></span></div>
    <p class="muted" style="font-size:13px;margin:0">盘点：照着"理论库存"清点，把实际数量填在"实盘"一栏（没清点的留空），再点最下面的"保存盘点"，系统按实盘数修正库存。可以先点每张表下面的"打印"，打一张盘存表拿去清点。</p>
    <div id="sbody"></div></div>`;
  const itemForm = (it = {}) => {
    const m = modal(`<h3>${it.id ? '修改' : '新增'}库存品</h3><div class="grid2">
      <label class="f"><span>名称</span><input id="n" value="${esc(it.name || '')}"></label>
      <label class="f"><span>类别</span><select id="k">${['原料', '包材'].concat(it.kind === '成品' ? ['成品'] : []).map((k) => `<option ${it.kind === k ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
      <label class="f"><span>主单位（库存和配方都按这个算）</span><input id="u" value="${esc(it.unit || '')}" placeholder="kg、个、卷"></label>
      <label class="f"><span>规格：每个包装多少主单位（可不填）</span><span class="row" style="flex-wrap:nowrap;gap:6px"><input id="pq" inputmode="decimal" value="${it.pack_qty || ''}" placeholder="25"><span id="pu1" class="muted">${esc(it.unit || '主单位')}/</span><input id="pu" value="${esc(it.pack_unit || '')}" placeholder="袋" style="max-width:90px"></span></label>
      <label class="f"><span>单价（元/主单位）</span><input id="c" inputmode="decimal" value="${it.cost_cents ? q3(it.cost_cents / 100) : ''}"></label>
      <label class="f"><span>低于多少提醒（主单位）</span><input id="l" inputmode="decimal" value="${it.low_qty || ''}"></label>
      ${it.id ? `<label class="f"><span>状态</span><select id="a"><option value="1">启用</option><option value="0" ${it.active ? '' : 'selected'}>停用</option></select></label>` : ''}</div>
      <p class="muted" style="font-size:13px" id="specn">例如面粉：主单位 kg，规格 25 kg/袋。入库时选"按袋"填 1，库存就加 25 kg。</p>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">保存</button></div>`);
    $('#u', m.el).oninput = () => { $('#pu1', m.el).textContent = ($('#u', m.el).value || '主单位') + '/'; };
    $('#ok', m.el).onclick = () => act(async () => {
      const pq = parseFloat($('#pq', m.el).value);
      await api('POST', '/api/stock/items', { id: it.id, name: $('#n', m.el).value, kind: $('#k', m.el).value, unit: $('#u', m.el).value, pack_qty: pq > 0 ? pq : null, pack_unit: $('#pu', m.el).value,
        cost_cents: (parseFloat($('#c', m.el).value) || 0) * 100, low_qty: parseFloat($('#l', m.el).value) || 0, active: it.id ? $('#a', m.el).value === '1' : true });
      m.close(); load();
    });
  };
  const moveForm = (it, type) => {
    const m = modal(`<h3>${esc(it.name)} · ${MOVE[type]}</h3><p class="muted">当前理论库存 ${q3(it.qty)} ${esc(it.unit)}${it.pack_qty ? `（规格 ${esc(specText(it))}）` : ''}</p>
      <div class="row" style="flex-wrap:nowrap"><label class="f" style="flex:1"><span>数量</span><input id="q" inputmode="decimal"></label>
        ${it.pack_qty ? `<label class="f" style="width:130px"><span>单位</span><select id="bp"><option value="1">按${esc(it.pack_unit)}</option><option value="0">按${esc(it.unit)}</option></select></label>` : `<span style="padding-top:22px">${esc(it.unit)}</span>`}</div>
      <p class="muted" id="qn" style="margin:0"></p>
      ${type === 'in' ? '<label class="f"><span>这批总金额（元，可不填；填了会更新单价）</span><input id="c" inputmode="decimal"></label>' : ''}
      <label class="f"><span>备注</span><input id="n"></label>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确认</button></div>`);
    const byPack = () => { const bp = $('#bp', m.el); return bp ? bp.value === '1' : false; };
    const note = () => { const v = parseFloat($('#q', m.el).value); $('#qn', m.el).textContent = byPack() && v > 0 ? `= ${q3(v * it.pack_qty)} ${it.unit}` : ''; };
    $('#q', m.el).oninput = note; const bp = $('#bp', m.el); if (bp) bp.onchange = note;
    $('#ok', m.el).onclick = () => act(async () => {
      const c = $('#c', m.el);
      const r = await api('POST', '/api/stock/moves', { item_id: it.id, type, qty: parseFloat($('#q', m.el).value), by_pack: byPack(), cost_cents: c && c.value.trim() ? toCents(c.value) : undefined, note: $('#n', m.el).value });
      m.close(); toast(`已登记 ${r.qty_main} ${it.unit}`); load();
    });
  };
  const importForm = () => {
    const m = modal(`<h3>批量导入库存品</h3>
      <p class="muted" style="font-size:13px;margin:0">在 Excel 里按下面的列排好，选中整块（含表头）复制，粘贴到下面的框里；也可以选一个 CSV 文件。同名的库存品会更新资料，填了期初库存的会记一笔入库。</p>
      <p class="mono" style="font-size:12px;margin:0">${IMPORT_HEAD.join(' | ')}</p>
      <div class="row"><button class="btn small" id="tpl">下载模板</button><label class="btn small" style="display:inline-flex;align-items:center;cursor:pointer">选择 CSV 文件<input type="file" accept=".csv,.txt" id="f" hidden></label></div>
      <textarea id="t" rows="8" placeholder="名称	类别	主单位	规格数量	包装单位	单价（元/主单位）	预警量	期初库存
高筋面粉	原料	kg	25	袋	4.8	25	50"></textarea>
      <div id="pv" class="tbl"></div>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok" disabled>导入</button></div>`);
    let rows = [];
    const preview = () => {
      let data = parseTable($('#t', m.el).value);
      if (data.length && data[0][0] && data[0][0].includes('名称')) data = data.slice(1);
      rows = data.filter((r) => r[0]).map((r) => ({ name: r[0], kind: r[1] === '包材' ? '包材' : '原料', unit: r[2] || '个', pack_qty: parseFloat(r[3]) || null, pack_unit: r[4] || '', cost_cents: (parseFloat(r[5]) || 0) * 100, low_qty: parseFloat(r[6]) || 0, init_qty: r[7] || '' }));
      $('#pv', m.el).innerHTML = rows.length ? `<p style="margin:4px 0">识别到 <b>${rows.length}</b> 行：</p><table><thead><tr><th>名称</th><th>类别</th><th>主单位</th><th>规格</th><th class="r">单价</th><th class="r">期初</th></tr></thead><tbody>
        ${rows.slice(0, 50).map((r) => `<tr><td>${esc(r.name)}</td><td>${r.kind}</td><td>${esc(r.unit)}</td><td>${r.pack_qty ? `${r.pack_qty}${esc(r.unit)}/${esc(r.pack_unit || '包')}` : ''}</td><td class="r num">${yuan(r.cost_cents)}</td><td class="r num">${esc(r.init_qty)}</td></tr>`).join('')}</tbody></table>${rows.length > 50 ? '<p class="muted">只显示前 50 行</p>' : ''}` : '';
      $('#ok', m.el).disabled = !rows.length;
    };
    $('#t', m.el).oninput = preview;
    $('#f', m.el).onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const buf = await f.arrayBuffer();
      let text = new TextDecoder('utf-8').decode(buf);
      if (text.includes('�')) text = new TextDecoder('gbk').decode(buf); // Excel 另存的 CSV 常是 GBK
      $('#t', m.el).value = text; preview();
    };
    $('#tpl', m.el).onclick = () => downloadCsv('库存品导入模板', IMPORT_HEAD, [['高筋面粉', '原料', 'kg', '25', '袋', '4.8', '25', '50'], ['黄油', '原料', 'kg', '25', '箱', '60', '5', ''], ['蛋挞托', '包材', '个', '1000', '箱', '0.12', '500', '2000']]);
    $('#ok', m.el).onclick = () => act(async () => {
      const r = await api('POST', '/api/stock/import', { rows });
      m.close(); toast(`导入完成：新增 ${r.added} 项，更新 ${r.updated} 项`); load();
    });
  };
  const load = async () => {
    const r = await api('GET', '/api/stock').catch((e) => toast(e.message, true));
    if (!r) return;
    const act_ = r.items.filter((it) => it.active);
    const itemRows = (list) => list.map((it) => `<tr><td><b>${esc(it.name)}</b> ${it.low_qty && it.qty <= it.low_qty ? '<span class="pill bad">该补货了</span>' : ''}</td><td>${esc(it.unit)}</td><td>${esc(specText(it))}</td>
        <td class="r num">${q3(it.qty)}</td><td class="r"><input data-cnt="${it.id}" data-sys="${it.qty}" inputmode="decimal" class="cntin"></td><td class="r num" data-cd="c${it.id}"></td>
        <td class="r num">${q3(it.cost_cents / 100)}</td><td class="r num">${yuan(it.qty * it.cost_cents)}</td>
        <td><div class="row" style="gap:4px;flex-wrap:nowrap">${['in', 'use', 'loss'].map((k) => `<button class="btn small" data-mv="${k}" data-id="${it.id}">${MOVE[k]}</button>`).join('')}<button class="btn small" data-edit="${it.id}">修改</button></div></td></tr>`).join('');
    const itemCard = (kind) => {
      const list = act_.filter((it) => it.kind === kind);
      const sum = list.reduce((a, it) => a + it.qty * it.cost_cents, 0);
      return `<div class="card tbl"><h3>${kind} <span class="muted" style="font-weight:400;font-size:13px">${list.length} 项，库存金额 ¥${yuan(sum)}</span></h3><table><thead><tr><th>名称</th><th>主单位</th><th>规格</th><th class="r">理论库存</th><th class="r">实盘</th><th class="r">差异</th><th class="r">单价</th><th class="r">金额</th><th></th></tr></thead><tbody>
        ${itemRows(list) || `<tr><td colspan="9" class="empty">还没有${kind}，点右上角新增或批量导入</td></tr>`}</tbody></table></div>`;
    };
    // 成品：按商品分类
    const cats = [...new Set(r.products.map((p) => p.category))];
    const oldFinished = act_.filter((it) => it.kind === '成品');
    const finished = `<div class="card tbl"><h3>成品 <span class="muted" style="font-weight:400;font-size:13px">理论库存 = 出炉 − 售出 − 报损（含盘点调整）；"—"表示还没登记过出炉</span></h3><table><thead><tr><th>商品</th><th class="r">理论库存</th><th class="r">实盘</th><th class="r">差异</th><th class="r">今日计划</th><th class="r">单个成本</th><th class="r">售价</th></tr></thead><tbody>
      ${cats.map((c) => `<tr class="grp"><td colspan="7">${esc(c)}</td></tr>${r.products.filter((p) => p.category === c).map((p) => `<tr><td>${esc(p.name)}</td><td class="r num">${p.qty === null ? '—' : `<span class="${p.qty < 0 ? 'warn' : ''}">${p.qty}</span>`}</td>
        <td class="r"><input data-pcnt="${p.id}" data-sys="${p.qty ?? 0}" inputmode="numeric" class="cntin"></td><td class="r num" data-cd="p${p.id}"></td><td class="r num">${p.plan_today ?? '—'}</td>
        <td class="r num">${p.unit_cost === null ? '<span class="muted">未设配方</span>' : yuan(p.unit_cost)}</td><td class="r num">${yuan(p.price_cents)}</td></tr>`).join('')}`).join('') || '<tr><td colspan="7" class="empty">没有在售商品</td></tr>'}
      </tbody></table>${oldFinished.length ? `<p class="muted" style="font-size:13px">以前手动建的成品库存品：${oldFinished.map((it) => `${esc(it.name)} ${q3(it.qty)}${esc(it.unit)}`).join('、')}（可以在"修改"里停用）</p>` : ''}</div>`;
    $('#sbody').innerHTML = `${itemCard('原料')}${itemCard('包材')}${finished}
      <div class="card"><div class="row between"><label class="f" style="flex:1;min-width:200px"><span>盘点备注（可不填）</span><input id="cntnote" placeholder="例如：月底盘点"></label><button class="btn primary" id="cntsave">保存盘点</button></div></div>
      <div class="card tbl"><h3>最近进出</h3><table><thead><tr><th>时间</th><th>名称</th><th>类型</th><th class="r">变化</th><th>备注</th><th>登记人</th></tr></thead><tbody>
      ${r.moves.map((mv) => `<tr><td class="muted">${esc(mv.created_at.slice(5, 16))}</td><td>${esc(mv.name)}</td><td>${MOVE[mv.type] || mv.type}</td><td class="r num">${mv.qty > 0 ? '+' : ''}${q3(mv.qty)} ${esc(mv.unit)}</td><td>${esc(mv.note)}</td><td class="muted">${esc(mv.operator_name)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">—</td></tr>'}
      </tbody></table></div>
      ${r.adjs.length ? `<div class="card tbl"><h3>成品盘点调整</h3><table><thead><tr><th>时间</th><th>商品</th><th class="r">调整</th><th>备注</th><th>登记人</th></tr></thead><tbody>
      ${r.adjs.map((x) => `<tr><td class="muted">${esc(x.created_at.slice(5, 16))}</td><td>${esc(x.name)}</td><td class="r num">${x.qty > 0 ? '+' : ''}${x.qty}</td><td>${esc(x.note)}</td><td class="muted">${esc(x.operator_name)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      ${r.items.some((it) => !it.active) ? `<p class="muted" style="font-size:13px">已停用：${r.items.filter((it) => !it.active).map((it) => `<a href="#" data-edit="${it.id}">${esc(it.name)}</a>`).join('、')}</p>` : ''}`;
    tableTools($('#sbody'), '盘存', dateStr());
    $$('[data-mv]').forEach((b) => b.onclick = () => moveForm(r.items.find((x) => x.id === Number(b.dataset.id)), b.dataset.mv));
    $$('[data-edit]').forEach((b) => b.onclick = (e) => { e.preventDefault(); itemForm(r.items.find((x) => x.id === Number(b.dataset.edit))); });
    $$('[data-cnt],[data-pcnt]').forEach((inp) => inp.oninput = () => {
      const c = $(`[data-cd="${inp.dataset.cnt ? 'c' + inp.dataset.cnt : 'p' + inp.dataset.pcnt}"]`);
      const v = parseFloat(inp.value);
      if (inp.value.trim() === '' || !Number.isFinite(v)) { c.textContent = ''; return; }
      const d = q3(v - Number(inp.dataset.sys));
      c.innerHTML = `<span class="${d ? 'warn' : 'ok'}">${d > 0 ? '+' : ''}${d}</span>`;
    });
    $('#cntsave').onclick = () => act(async () => {
      const rows = $$('[data-cnt]').filter((i) => i.value.trim() !== '').map((i) => ({ item_id: Number(i.dataset.cnt), qty: parseFloat(i.value) }));
      const products = $$('[data-pcnt]').filter((i) => i.value.trim() !== '').map((i) => ({ product_id: Number(i.dataset.pcnt), qty: Number(i.value) }));
      if (!rows.length && !products.length) throw new Error('还没有填实盘数');
      if (rows.some((x) => !(x.qty >= 0)) || products.some((x) => !Number.isInteger(x.qty) || x.qty < 0)) throw new Error('实盘数要填数字，成品填整数');
      const res = await api('POST', '/api/stock/count', { rows, products, note: $('#cntnote').value });
      const diffs = res.rows.filter((x) => x.diff);
      toast(`盘点已保存：${res.rows.length} 项，${diffs.length ? `${diffs.length} 项有差异，库存已按实盘修正` : '全部相符'}`);
      load();
    });
  };
  $('#sadd').onclick = () => itemForm();
  $('#simp').onclick = importForm;
  load();
}

// ---------- 餐票（票据） ----------
async function renderTickets(main) {
  const r = await api('GET', '/api/tickets').catch((e) => toast(e.message, true));
  if (!r) return;
  main.innerHTML = `<div class="stack">
    <div class="stats"><div class="stat m-ticket"><span class="k">票据库存（店里现有餐票）</span><span class="v">¥${yuan(r.stock_cents)}</span></div>
      <div class="stat"><span class="k">今天收票</span><span class="v">¥${yuan(r.today_in_cents)}</span></div>
      <div class="stat"><span class="k">本月收票</span><span class="v">¥${yuan(r.month.in)}</span></div>
      <div class="stat"><span class="k">本月学校兑换</span><span class="v">¥${yuan(r.month.school)}</span></div>
      <div class="stat"><span class="k">本月自由出库</span><span class="v">¥${yuan(r.month.free)}</span></div>
      <div class="stat m-stored"><span class="k">存票余额合计（欠顾客）</span><span class="v">¥${yuan(r.liability_cents)}</span></div></div>
    <div class="card"><h3>票据出库</h3>
      <p class="muted" style="margin:0">收银时收到的临时用票、存票时收的纸票会自动进票据库存。拿去学校兑换或者自由出库（例如拿去其他档口用），填金额就行，从票据库存里扣，都会记在票据记录里。</p>
      <div class="row"><button class="btn primary" data-out="school">去学校兑换</button><button class="btn" data-out="free">自由出库</button>
        <button class="btn badge-btn" id="recs">票据记录 <span class="n">查看</span></button></div></div></div>`;
  $$('[data-out]').forEach((b) => b.onclick = () => {
    const kind = b.dataset.out;
    const m = modal(`<h3>${kind === 'school' ? '去学校兑换' : '自由出库'}</h3><p class="muted">票据库存 ¥${yuan(r.stock_cents)}</p>
      <label class="f"><span>票据金额（元）</span><input id="v" inputmode="decimal"></label>
      <label class="f"><span>${kind === 'school' ? '备注（可不填）' : '用在哪里（例如：二楼面档买面粉）'}</span><input id="n"></label>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">确认出库</button></div>`);
    $('#ok', m.el).onclick = () => act(async () => {
      await api('POST', '/api/tickets/out', { kind, amount_cents: toCents($('#v', m.el).value), note: $('#n', m.el).value });
      m.close(); toast('已出库'); renderTickets(main);
    });
  });
  $('#recs').onclick = () => {
    const m = modal(`<div class="row between"><h3>票据记录</h3><span class="row"><input type="date" id="rf" value="${addDays(r.today, -30)}" style="max-width:160px"><span>至</span><input type="date" id="rt" value="${r.today}" style="max-width:160px"></span></div>
      <div class="card tbl" id="rlist" style="padding:0;border:0"></div><div class="acts"><button class="btn" data-close>关闭</button></div>`);
    m.el.style.width = 'min(900px,100%)';
    const loadR = async () => {
      const x = await api('GET', `/api/tickets/records?from=${$('#rf', m.el).value}&to=${$('#rt', m.el).value}`).catch((e) => toast(e.message, true));
      if (!x) return;
      const inSum = x.rows.filter((y) => y.dir === 'in').reduce((a, y) => a + y.amount_cents, 0);
      const outSum = x.rows.filter((y) => y.dir === 'out').reduce((a, y) => a - y.amount_cents, 0);
      $('#rlist', m.el).innerHTML = `<p class="muted" style="margin:0">这段时间收票 ¥${yuan(inSum)}，出库 ¥${yuan(outSum)}</p><table><thead><tr><th>时间</th><th>类型</th><th class="r">金额</th><th>明细</th><th>经办</th></tr></thead><tbody>
        ${x.rows.map((y) => `<tr><td class="muted">${esc(y.created_at.slice(0, 16))}</td><td><span class="pill ${y.dir === 'in' ? 'm-ticket' : 'm-cash'}">${esc(y.kind)}</span></td><td class="r num ${y.dir === 'in' ? 'ok' : ''}">${y.amount_cents > 0 ? '+' : ''}${yuan(y.amount_cents)}</td><td>${esc(y.detail)}</td><td class="muted">${esc(y.operator_name)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">这段时间没有记录</td></tr>'}
        </tbody></table>`;
      tableTools(m.el, '票据记录', `${$('#rf', m.el).value} 至 ${$('#rt', m.el).value}`);
    };
    $('#rf', m.el).onchange = loadR; $('#rt', m.el).onchange = loadR; loadR();
  };
}

// ---------- 报表 ----------
async function renderReports(main) {
  const to = dateStr(); const from = addDays(to, -6);
  main.innerHTML = `<div class="stack">
    <div class="row"><input type="date" id="rf" value="${from}" style="max-width:180px"><span>至</span><input type="date" id="rt" value="${to}" style="max-width:180px">
      <button class="btn small" data-range="0">今天</button><button class="btn small" data-range="6">近7天</button><button class="btn small" data-range="29">近30天</button></div>
    <div id="rbody"></div>
    <div class="card"><h3>导出 Excel（CSV）</h3><div class="row"><a class="btn" id="ex0">订单汇总</a><a class="btn" id="ex1">销售明细</a><a class="btn" id="ex2">收款明细</a><a class="btn" id="ex3">存票账户</a></div></div></div>`;
  const load = async () => {
    const f = $('#rf').value; const t = $('#rt').value;
    $('#ex0').href = `/api/export?type=orders&from=${f}&to=${t}`;
    $('#ex1').href = `/api/export?type=items&from=${f}&to=${t}`;
    $('#ex2').href = `/api/export?type=payments&from=${f}&to=${t}`;
    $('#ex3').href = `/api/export?type=accounts`;
    const [r, pf] = await Promise.all([api('GET', `/api/reports?from=${f}&to=${t}`), api('GET', `/api/profit?from=${f}&to=${t}`)]).catch((e) => { toast(e.message, true); return []; });
    if (!r) return;
    const by = { cash: 0, pos: 0, ticket: 0, stored: 0 };
    r.methods.forEach((m) => { by[m.method] = m.amount; });
    const sumM = Object.values(by).reduce((a, b) => a + Math.max(b, 0), 0) || 1;
    const days = {};
    r.days.forEach((d) => { days[d.day] = days[d.day] || { cash: 0, pos: 0, ticket: 0, stored: 0 }; days[d.day][d.method] = d.amount; });
    const prodMap = Object.fromEntries(r.produced.map((p) => [p.name, p]));
    const maxH = Math.max(1, ...r.hours.map((h) => h.amount));
    const T = pf.today; const P = pf.range;
    const pct = (a, b) => (b ? Math.round(a / b * 100) + '%' : '—');
    $('#rbody').innerHTML = `
      <div class="card"><h3>今天赚了多少</h3>
        <div class="stats"><div class="stat"><span class="k">营业收入</span><span class="v">¥${yuan(T.revenue)}</span></div>
          <div class="stat"><span class="k">出炉用掉的原料</span><span class="v">¥${yuan(T.material)}</span></div>
          <div class="stat"><span class="k">原料损耗</span><span class="v">¥${yuan(T.raw_loss)}</span></div>
          <div class="stat ${T.profit < 0 ? 'lossy' : 'm-cash'}"><span class="k">今天${T.profit < 0 ? '亏了' : '赚了'}（毛利 ${pct(T.profit, T.revenue)}）</span><span class="v">¥${yuan(T.profit)}</span></div></div>
        <p class="muted" style="font-size:13px;margin:0">赚了 = 营业收入 − 今天出炉用掉的原料成本（按产品配方）− 原料损耗。成品报损的原料成本已经算在出炉成本里${T.product_loss ? `（今天报损约 ¥${yuan(T.product_loss)}）` : ''}。不算房租、人工、水电。${T.no_bom.length ? `<br><span class="warn">还没设配方的商品成本按 0 算：${T.no_bom.map(esc).join('、')}</span>` : ''}</p></div>
      <div class="card tbl"><h3>利润（${esc(f)} 至 ${esc(t)}）</h3>
        <div class="stats"><div class="stat"><span class="k">营业收入</span><span class="v">¥${yuan(P.revenue)}</span></div>
          <div class="stat"><span class="k">出炉原料成本</span><span class="v">¥${yuan(P.material)}</span></div>
          <div class="stat"><span class="k">原料损耗</span><span class="v">¥${yuan(P.raw_loss)}</span></div>
          <div class="stat ${P.profit < 0 ? 'lossy' : 'm-cash'}"><span class="k">${P.profit < 0 ? '亏了' : '赚了'}（毛利 ${pct(P.profit, P.revenue)}）</span><span class="v">¥${yuan(P.profit)}</span></div></div>
        <table><thead><tr><th>分类</th><th class="r">售出</th><th class="r">销售额</th><th class="r">配方成本</th><th class="r">毛利</th><th class="r">毛利率</th></tr></thead><tbody>
        ${P.categories.map((c) => `<tr><td><b>${esc(c.category)}</b>${c.no_cost ? ' <span class="pill">部分未设配方</span>' : ''}</td><td class="r num">${c.qty}</td><td class="r num">${yuan(c.sales)}</td>${c.no_cost >= c.sales ? '<td class="r num">—</td><td class="r num">—</td><td class="r num">—</td>' : `<td class="r num">${yuan(c.cost)}</td><td class="r num"><b>${yuan(c.gross)}</b></td><td class="r num">${pct(c.gross, c.sales - c.no_cost)}</td>`}</tr>`).join('') || '<tr><td colspan="6" class="empty">没有数据</td></tr>'}
        </tbody></table>
        <p class="muted" style="font-size:13px;margin:0">分类和商品按售出数量算成本（售出 × 单个配方成本），销售额已扣除打折。上面的"赚了"按出炉算成本，剩下没卖掉、报损的也算进去，所以两者会有差别。${P.overpay ? `餐票溢收 ¥${yuan(P.overpay)} 算在营业收入里，不分到商品。` : ''}${P.count_loss ? `盘点盘亏 ¥${yuan(P.count_loss)} 没有算进成本，可以对照看。` : ''}</p></div>
      <div class="card tbl"><h3>商品利润</h3><table><thead><tr><th>商品</th><th>分类</th><th class="r">售出</th><th class="r">销售额</th><th class="r">单个成本</th><th class="r">成本</th><th class="r">毛利</th><th class="r">毛利率</th></tr></thead><tbody>
        ${P.products.map((x) => `<tr><td>${esc(x.name)}</td><td>${esc(x.category)}</td><td class="r num">${x.qty}</td><td class="r num">${yuan(x.sales)}</td><td class="r num">${x.unit_cost === null ? '<span class="muted">未设</span>' : yuan(x.unit_cost)}</td>
          <td class="r num">${x.cost === null ? '—' : yuan(x.cost)}</td><td class="r num">${x.gross === null ? '—' : `<b>${yuan(x.gross)}</b>`}</td><td class="r num">${x.gross === null ? '—' : pct(x.gross, x.sales)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">没有数据</td></tr>'}
        </tbody></table></div>
      <div class="stats"><div class="stat"><span class="k">四种来源合计 · ${r.totals.orders} 单</span><span class="v">¥${yuan(Object.values(by).reduce((a, b) => a + b, 0))}</span></div>
        ${Object.entries(METHOD).map(([k, v]) => `<div class="stat m-${k}"><span class="k">${v} · ${Math.round(Math.max(by[k], 0) / sumM * 100)}%</span><span class="v">¥${yuan(by[k])}</span></div>`).join('')}</div>
      <p class="muted" style="font-size:13px">商品金额 ¥${yuan(r.totals.amount)}${r.totals.discount ? `（已减去打折优惠 ¥${yuan(r.totals.discount)}；下面商品销量的金额按原价算）` : ''}${r.totals.overpay ? `，餐票溢收 ¥${yuan(r.totals.overpay)}（票面多出不找零的部分，已算在临时用票里）` : ''}。存票余额消费是顾客预存的餐票，不是当天新收的钱。${by.cash < 0 ? '现金为负数是因为第一版曾经用现金给餐票找零。' : ''}</p>
      <div class="card tbl"><h3>每日分来源</h3><table><thead><tr><th>日期</th>${Object.values(METHOD).map((v) => `<th class="r">${v}</th>`).join('')}<th class="r">合计</th></tr></thead><tbody>
        ${Object.entries(days).map(([d, v]) => `<tr><td>${d}</td>${Object.keys(METHOD).map((k) => `<td class="r num">${yuan(v[k])}</td>`).join('')}<td class="r num"><b>${yuan(Object.values(v).reduce((a, b) => a + b, 0))}</b></td></tr>`).join('') || '<tr><td colspan="6" class="empty">没有数据</td></tr>'}
      </tbody></table></div>
      <div class="card tbl"><h3>商品销量</h3><table><thead><tr><th>商品</th><th class="r">售出</th><th class="r">金额</th><th class="r">出炉</th><th class="r">报损</th></tr></thead><tbody>
        ${r.products.map((p) => `<tr><td>${esc(p.name)}</td><td class="r num">${p.qty}</td><td class="r num">${yuan(p.amount)}</td><td class="r num muted">${prodMap[p.name] ? prodMap[p.name].output : '—'}</td><td class="r num muted">${prodMap[p.name] ? prodMap[p.name].loss : '—'}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">没有数据</td></tr>'}
      </tbody></table><p class="muted" style="font-size:13px">出炉、报损来自出品页登记，仅作对照。</p></div>
      <div class="card tbl"><h3>时段分布</h3><table class="hidden"><thead><tr><th>时段</th><th class="r">单数</th><th class="r">金额</th></tr></thead><tbody>${r.hours.map((h) => `<tr><td>${h.hour}点</td><td>${h.orders}</td><td>${yuan(h.amount)}</td></tr>`).join('')}</tbody></table>${r.hours.map((h) => `<div class="row" style="flex-wrap:nowrap"><span class="num" style="width:48px">${h.hour}点</span><div class="bar" style="flex:1"><i style="width:${h.amount / maxH * 100}%;background:var(--accent)"></i></div><span class="num muted" style="width:120px;text-align:right">${h.orders}单 ¥${yuan(h.amount)}</span></div>`).join('') || '<p class="muted">没有数据</p>'}</div>`;
    tableTools($('#rbody'), '报表', `${f} 至 ${t}`);
  };
  $$('[data-range]').forEach((b) => b.onclick = () => { $('#rt').value = dateStr(); $('#rf').value = addDays(dateStr(), -Number(b.dataset.range)); load(); });
  $('#rf').onchange = load; $('#rt').onchange = load;
  load();
}

// ---------- 设置 ----------
async function renderSettings(main) {
  const [settings, products, users, logs, bomData, stock] = await Promise.all([api('GET', '/api/settings'), api('GET', '/api/products'), api('GET', '/api/users'), api('GET', '/api/logs'), api('GET', '/api/bom'), api('GET', '/api/stock')]).catch((e) => { toast(e.message, true); return []; });
  if (!settings) return;
  main.innerHTML = `<div class="stack">
    <div class="card"><h3>店铺</h3><div class="grid2">
      <label class="f"><span>店名</span><input id="sn" value="${esc(settings.shop_name || '')}"></label>
      <label class="f"><span>餐票面额（元，用逗号分隔）</span><input id="sf" value="${esc((settings.ticket_faces || '').split(',').filter(Boolean).map((c) => Number(c) / 100).join(','))}"></label>
      <label class="f"><span>顾客查询地址（印在存票凭条上，不填自动识别）</span><input id="sq" value="${esc(settings.query_url || '')}" placeholder="${esc(state.me.query_url)}"></label></div>
      <div><button class="btn primary" id="ssave">保存</button></div></div>
    <div class="card"><h3>打折</h3>
      <label class="row" style="gap:8px;cursor:pointer"><input type="checkbox" id="don" style="width:20px;min-height:20px" ${settings.discount_on === '1' ? 'checked' : ''}> 开启打折（开启后收银页面会出现打折按钮）</label>
      <div class="grid2">${(settings.discount_presets || '90,85,80').split(',').map((v, i) => `<label class="f"><span>打折按钮 ${i + 1}（几折）</span><input data-dp inputmode="decimal" value="${Number(v) / 10}"></label>`).join('')}</div>
      <p class="muted" style="font-size:13px">例如填 9 就是 9 折、8.5 就是 8.5 折。收银时点一下按钮这一单就打折；勾选"全部订单打折"后，每一单都自动按这个折扣，直到取消。</p>
      <div><button class="btn primary" id="dsave">保存</button></div></div>
    <div class="card"><h3>小票打印机</h3>
      <div class="grid2">
        <label class="f"><span>打印方式</span><select id="pm">
          <option value="none">不使用打印机</option>
          <option value="network">网络打印机（网口或 WiFi）</option>
          <option value="local">USB 打印机（连在这台电脑上）</option>
          <option value="browser">浏览器打印（弹出打印窗口）</option></select></label>
        <label class="f" data-pm="network"><span>打印机 IP 地址</span><input id="ph" value="${esc(settings.print_host || '')}" placeholder="例如 192.168.1.200"></label>
        <label class="f" data-pm="network"><span>端口</span><input id="pport" inputmode="numeric" value="${esc(settings.print_port || '')}" placeholder="9100"></label>
        <label class="f" data-pm="local"><span>打印机共享名</span><input id="pname" value="${esc(settings.print_name || '')}" placeholder="例如 POS58"></label>
        <label class="f" data-pm="network local browser"><span>纸宽</span><select id="ppaper"><option value="58">58 毫米</option><option value="80">80 毫米</option></select></label>
        <label class="f" data-pm="network local"><span>每行字数（不填按纸宽自动）</span><input id="pcols" inputmode="numeric" value="${esc(settings.print_cols || '')}" placeholder="58 毫米 32，80 毫米 48"></label>
        <label class="f" data-pm="network local browser"><span>结账后自动打印</span><select id="pauto">
          <option value="off">不自动，需要时点"打印小票"</option><option value="all">每单都打印</option><option value="stored">只打存票消费的单</option></select></label>
        <label class="f" data-pm="network local browser"><span>小票底部文字</span><input id="pfoot" maxlength="40" value="${esc(settings.print_footer ?? '谢谢惠顾，欢迎再来')}"></label>
      </div>
      <p class="muted" id="phelp" style="font-size:13px;max-width:70ch"></p>
      <div class="row"><button class="btn primary" id="psave">保存</button><button class="btn" id="ptest" data-pm="network local browser">保存并测试打印</button></div></div>
    <div class="card tbl"><div class="row between"><h3>商品</h3><button class="btn primary" id="padd">+ 新增商品</button></div>
      <table><thead><tr><th>排序</th><th>名称</th><th>分类</th><th class="r">售价</th><th>状态</th><th></th></tr></thead><tbody>
      ${products.map((p) => `<tr style="${p.active ? '' : 'opacity:.5'}"><td class="num">${p.sort}</td><td>${esc(p.name)}</td><td>${esc(p.category)}</td><td class="r num">${yuan(p.price_cents)}</td><td>${p.active ? '在售' : '下架'}</td><td><button class="btn small" data-p="${p.id}">修改</button></td></tr>`).join('')}
      </tbody></table></div>
    <div class="card tbl"><h3>产品配方（BOM）</h3>
      <p class="muted" style="font-size:13px;margin:0">设置每做 1 个商品要用多少原料和包材（按库存品的主单位）。设好后：出炉时自动扣库存，生产计划页能算原材料订购计划，报表能算成本和利润。</p>
      <table><thead><tr><th>商品</th><th>分类</th><th>配方</th><th class="r">单个成本</th><th class="r">售价</th><th class="r">成本占比</th><th></th></tr></thead><tbody>
      ${products.filter((p) => p.active).map((p) => { const b = bomData.bom[p.id] || []; const uc = bomData.unit_costs[p.id]; return `<tr><td>${esc(p.name)}</td><td>${esc(p.category)}</td>
        <td style="font-size:13px">${b.length ? b.map((x) => `${esc(x.name)} ${q3(x.qty)}${esc(x.unit)}`).join('、') : '<span class="warn">未设置</span>'}</td>
        <td class="r num">${uc === undefined ? '—' : yuan(uc)}</td><td class="r num">${yuan(p.price_cents)}</td><td class="r num">${uc === undefined || !p.price_cents ? '—' : Math.round(uc / p.price_cents * 100) + '%'}</td>
        <td><button class="btn small" data-bom="${p.id}">设置</button></td></tr>`; }).join('') || '<tr><td colspan="7" class="empty">没有在售商品</td></tr>'}
      </tbody></table></div>
    <div class="card tbl"><div class="row between"><h3>员工</h3><button class="btn primary" id="uadd">+ 新增员工</button></div>
      <table><thead><tr><th>姓名</th><th>角色</th><th>状态</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr><td>${esc(u.name)}</td><td>${ROLE[u.role]}</td><td>${u.active ? '启用' : '停用'}</td><td><button class="btn small" data-u="${u.id}">修改</button></td></tr>`).join('')}
      </tbody></table></div>
    <div class="card"><h3>我的密码</h3><div class="grid2"><label class="f"><span>原密码</span><input id="op" type="password" inputmode="numeric"></label><label class="f"><span>新密码（4–8 位数字）</span><input id="np" type="password" inputmode="numeric"></label></div><div><button class="btn primary" id="pwsave">修改密码</button></div></div>
    <div class="card"><h3>数据备份</h3><p class="muted">系统每 6 小时自动备份一次，保留最近 60 份，放在收银系统文件夹的 data/backups 里。建议每周把整个 data 文件夹复制到 U 盘。</p><div><button class="btn" id="bk">立即备份</button></div></div>
    <p class="muted" style="font-size:12px">版本 ${esc(state.me.version)}</p>
    <div class="card tbl"><h3>操作日志</h3><table><thead><tr><th>时间</th><th>人员</th><th>操作</th><th>内容</th></tr></thead><tbody>
      ${logs.map((l) => `<tr><td class="muted">${esc(l.created_at.slice(5, 16))}</td><td>${esc(l.user_name)}</td><td>${esc(l.action)}</td><td class="muted" style="font-size:12px;word-break:break-all">${esc(l.detail)}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  tableTools(main, '设置', dateStr());
  $('#dsave').onclick = () => act(async () => {
    const ps = $$('[data-dp]').map((i) => Math.round(parseFloat(i.value) * 10));
    if (ps.some((x) => !(x >= 1 && x <= 99))) throw new Error('折扣要填 0.1 到 9.9 之间的数');
    await api('POST', '/api/settings', { discount_on: $('#don').checked ? '1' : '0', discount_presets: ps.join(',') });
    state.me = await api('GET', '/api/me'); toast('打折设置已保存');
  });
  $('#ssave').onclick = () => act(async () => {
    const faces = $('#sf').value.split(/[,，\s]+/).map(toCents).filter((n) => n > 0).join(',');
    await api('POST', '/api/settings', { shop_name: $('#sn').value.trim() || '桃喜团子', ticket_faces: faces, query_url: $('#sq').value.trim() });
    state.me = await api('GET', '/api/me'); toast('已保存'); render();
  });
  // 小票打印机
  const PHELP = {
    none: '店里有小票打印机的话，选一种连接方式。',
    network: '打印机用网线接到路由器（或连上店里 WiFi）。多数打印机关机后按住走纸键再开机，会打出一张自检页，上面有 IP 地址。建议在路由器里给打印机固定 IP。平板和手机收银时也能出小票。',
    local: 'USB 线插在运行收银系统的这台电脑上。先在 Windows 里共享打印机：设置 → 打印机和扫描仪 → 点这台打印机 → 打印机属性 → 共享 → 勾选"共享这台打印机"，共享名填英文，例如 POS58，再把共享名填到这里。Mac 填系统里显示的打印机名称。平板和手机收银时也能出小票。',
    browser: '每次打印会弹出打印窗口，只适合直接在这台电脑上收银时用，平板和手机一般用不了。想跳过打印窗口，见使用说明里的"免确认打印"。',
  };
  $('#pm').value = settings.print_mode || 'none';
  $('#ppaper').value = settings.print_paper || '58';
  $('#pauto').value = settings.print_auto || 'off';
  const pmShow = () => {
    const v = $('#pm').value;
    $$('[data-pm]').forEach((el) => el.classList.toggle('hidden', !el.dataset.pm.split(' ').includes(v)));
    $('#phelp').textContent = PHELP[v];
  };
  $('#pm').onchange = pmShow; pmShow();
  const savePrinter = async () => {
    await api('POST', '/api/settings', {
      print_mode: $('#pm').value, print_host: $('#ph').value.trim(), print_port: $('#pport').value.trim(), print_name: $('#pname').value.trim(),
      print_paper: $('#ppaper').value, print_cols: $('#pcols').value.trim(), print_auto: $('#pauto').value, print_footer: $('#pfoot').value.trim(),
    });
    state.me = await api('GET', '/api/me');
  };
  $('#psave').onclick = () => act(async () => { await savePrinter(); toast('打印机设置已保存'); });
  $('#ptest').onclick = () => act(async () => { await savePrinter(); await printReceipt('test'); });
  const pForm = (p = { active: 1, sort: products.length }) => {
    const m = modal(`<h3>${p.id ? '修改' : '新增'}商品</h3><div class="grid2">
      <label class="f"><span>名称</span><input id="n" value="${esc(p.name || '')}"></label>
      <label class="f"><span>分类</span><input id="c" value="${esc(p.category || '')}" placeholder="面包、蛋糕、饮品"></label>
      <label class="f"><span>售价（元）</span><input id="pr" inputmode="decimal" value="${p.id ? yuan(p.price_cents) : ''}"></label>
      <label class="f"><span>排序（小的在前）</span><input id="s" inputmode="numeric" value="${p.sort ?? 0}"></label>
      ${p.id ? `<label class="f"><span>状态</span><select id="a"><option value="1">在售</option><option value="0" ${p.active ? '' : 'selected'}>下架</option></select></label>` : ''}</div>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">保存</button></div>`);
    $('#ok', m.el).onclick = () => act(async () => {
      await api('POST', '/api/products', { id: p.id, name: $('#n', m.el).value, category: $('#c', m.el).value, price_cents: toCents($('#pr', m.el).value), sort: parseInt($('#s', m.el).value, 10) || 0, active: p.id ? $('#a', m.el).value === '1' : true });
      m.close(); renderSettings(main);
    });
  };
  $('#padd').onclick = () => pForm();
  $$('[data-p]').forEach((b) => b.onclick = () => pForm(products.find((p) => p.id === Number(b.dataset.p))));
  const uForm = (u = { role: 'cashier', active: 1 }) => {
    const m = modal(`<h3>${u.id ? '修改' : '新增'}员工</h3><div class="grid2">
      <label class="f"><span>姓名</span><input id="n" value="${esc(u.name || '')}"></label>
      <label class="f"><span>角色</span><select id="r">${Object.entries(ROLE).map(([k, v]) => `<option value="${k}" ${u.role === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
      <label class="f"><span>${u.id ? '新密码（不改留空）' : '登录密码（4–8 位数字）'}</span><input id="p" inputmode="numeric"></label>
      ${u.id ? `<label class="f"><span>状态</span><select id="a"><option value="1">启用</option><option value="0" ${u.active ? '' : 'selected'}>停用</option></select></label>` : ''}</div>
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">保存</button></div>`);
    $('#ok', m.el).onclick = () => act(async () => {
      await api('POST', '/api/users', { id: u.id, name: $('#n', m.el).value, role: $('#r', m.el).value, pin: $('#p', m.el).value || undefined, active: u.id ? $('#a', m.el).value === '1' : true });
      m.close(); renderSettings(main);
    });
  };
  // 产品配方
  const mats = stock.items.filter((it) => it.active && it.kind !== '成品');
  $$('[data-bom]').forEach((btn) => btn.onclick = () => {
    const p = products.find((x) => x.id === Number(btn.dataset.bom));
    let rows = (bomData.bom[p.id] || []).map((x) => ({ item_id: x.item_id, qty: x.qty }));
    if (!rows.length) rows.push({ item_id: '', qty: '' });
    const m = modal(`<h3>${esc(p.name)} 的配方</h3><p class="muted" style="margin:0">做 1 个${esc(p.name)}要用：</p><div id="brows" class="stack" style="gap:8px"></div>
      <div class="row between"><button class="btn small" id="badd">+ 加一行</button><span>单个成本 <b class="num" id="bcost">0.00</b> 元 · 售价 ${yuan(p.price_cents)} 元</span></div>
      ${mats.length ? '' : '<p class="warn">还没有原料和包材，请先到"盘存"页新增或批量导入。</p>'}
      <div class="acts"><button class="btn" data-close>取消</button><button class="btn primary" id="ok">保存</button></div>`);
    const draw = () => {
      $('#brows', m.el).innerHTML = rows.map((r, i) => `<div class="row" style="flex-wrap:nowrap;gap:6px">
        <select data-bi="${i}" style="flex:2"><option value="">选择原料/包材</option>${mats.map((it) => `<option value="${it.id}" ${it.id === Number(r.item_id) ? 'selected' : ''}>${esc(it.kind)} · ${esc(it.name)}</option>`).join('')}</select>
        <input data-bq="${i}" inputmode="decimal" value="${r.qty}" placeholder="用量" style="flex:1;min-width:70px"><span class="muted" style="min-width:32px">${esc((mats.find((it) => it.id === Number(r.item_id)) || {}).unit || '')}</span>
        <button class="btn small" data-bd="${i}" aria-label="删除">✕</button></div>`).join('');
      $$('[data-bi]', m.el).forEach((el) => el.onchange = () => { rows[el.dataset.bi].item_id = el.value; draw(); });
      $$('[data-bq]', m.el).forEach((el) => el.oninput = () => { rows[el.dataset.bq].qty = el.value; cost(); });
      $$('[data-bd]', m.el).forEach((el) => el.onclick = () => { rows.splice(Number(el.dataset.bd), 1); draw(); });
      cost();
    };
    const cost = () => { $('#bcost', m.el).textContent = yuan(rows.reduce((a, r) => { const it = mats.find((x) => x.id === Number(r.item_id)); return a + (it ? (parseFloat(r.qty) || 0) * it.cost_cents : 0); }, 0)); };
    $('#badd', m.el).onclick = () => { rows.push({ item_id: '', qty: '' }); draw(); };
    $('#ok', m.el).onclick = () => act(async () => {
      const out = rows.filter((r) => r.item_id).map((r) => ({ item_id: Number(r.item_id), qty: parseFloat(r.qty) }));
      if (out.some((r) => !(r.qty > 0))) throw new Error('每一行都要填用量');
      await api('POST', '/api/bom', { product_id: p.id, rows: out });
      m.close(); toast('配方已保存'); renderSettings(main);
    });
    draw();
  });
  $('#uadd').onclick = () => uForm();
  $$('[data-u]').forEach((b) => b.onclick = () => uForm(users.find((u) => u.id === Number(b.dataset.u))));
  $('#pwsave').onclick = () => act(async () => { await api('POST', '/api/me/pin', { old_pin: $('#op').value, new_pin: $('#np').value }); state.me = await api('GET', '/api/me'); toast('密码已修改'); render(); });
  $('#bk').onclick = () => act(async () => { const r = await api('POST', '/api/backup'); toast('已备份：' + r.file); });
}

boot();
