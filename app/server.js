'use strict';
// 桃喜团子收银系统 · 本地服务
// 零依赖：只用 Node.js 自带模块（需要 Node.js 22.13 或更高版本）

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');
let DatabaseSync;
try { ({ DatabaseSync } = require('node:sqlite')); } catch {
  console.error(`\n  Node.js 版本太旧（现在是 ${process.version}），请到 https://nodejs.org/zh-cn 安装最新的 LTS 版本（22.13 或更高）。\n`);
  process.exit(1);
}
const printer = require('./printer');

const VERSION = require('./package.json').version;
const DEFAULT_SHOP = '桃喜团子';

const PORT = Number(process.env.PORT) || 3000;
const ROOT = __dirname;
const DATA = process.env.DATA_DIR || path.join(ROOT, 'data');
const PHOTOS = path.join(DATA, 'photos');
const BACKUPS = path.join(DATA, 'backups');
const PUBLIC = path.join(ROOT, 'public');
for (const d of [DATA, PHOTOS, BACKUPS]) fs.mkdirSync(d, { recursive: true });

const db = new DatabaseSync(path.join(DATA, 'shop.db'));
db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`);
db.exec(fs.readFileSync(path.join(ROOT, 'schema.sql'), 'utf8'));
// 旧版数据升级：补上新加的字段
function addColumn(table, col, decl) {
  if (!db.prepare(`PRAGMA table_info(${table})`).all().some((c) => c.name === col)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${decl}`);
}
addColumn('orders', 'overpay_cents', 'INTEGER NOT NULL DEFAULT 0');
addColumn('orders', 'subtotal_cents', 'INTEGER'); // 打折前金额（旧数据为空，等于 total_cents）
addColumn('orders', 'discount_pct', 'INTEGER'); // 90 表示 9 折
addColumn('orders', 'discount_cents', 'INTEGER NOT NULL DEFAULT 0');
addColumn('redemptions', 'kind', "TEXT NOT NULL DEFAULT 'school'"); // school 去学校兑换现金 / stall 拿去食堂其他档口用
addColumn('day_closes', 'tickets_json', 'TEXT'); // 日结时清点的店内余票

// ---------- 工具 ----------
const now = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
const today = () => now().slice(0, 10);
const addDays = (dateStr, n) => {
  const d = new Date(dateStr + 'T12:00:00');
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const isDate = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);
const isInt = (n) => Number.isInteger(n);

class HttpError extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}
const bad = (msg) => { throw new HttpError(400, msg); };

function tx(fn) {
  db.exec('BEGIN');
  try { const r = fn(); db.exec('COMMIT'); return r; }
  catch (e) { db.exec('ROLLBACK'); throw e; }
}
const all = (sql, ...a) => db.prepare(sql).all(...a);
const get = (sql, ...a) => db.prepare(sql).get(...a);
const run = (sql, ...a) => db.prepare(sql).run(...a);

function hashPin(pin, salt = crypto.randomBytes(16).toString('hex')) {
  const h = crypto.scryptSync(String(pin), salt, 32).toString('hex');
  return `${salt}:${h}`;
}
function checkPin(pin, stored) {
  const [salt, h] = String(stored).split(':');
  const test = crypto.scryptSync(String(pin), salt, 32);
  return crypto.timingSafeEqual(test, Buffer.from(h, 'hex'));
}

function log(user, action, detail) {
  run(`INSERT INTO logs (created_at, user_id, user_name, action, detail) VALUES (?,?,?,?,?)`,
    now(), user ? user.id : null, user ? user.name : null, action, typeof detail === 'string' ? detail : JSON.stringify(detail));
}

function getSetting(key, def) {
  const r = get(`SELECT value FROM settings WHERE key=?`, key);
  return r ? r.value : def;
}

// ---------- 初始数据 ----------
if (!get(`SELECT id FROM users LIMIT 1`)) {
  run(`INSERT INTO users (name, role, pin_hash, active) VALUES (?,?,?,1)`, '店主', 'owner', hashPin('123456'));
  run(`INSERT OR IGNORE INTO settings (key, value) VALUES ('default_pin','1')`);
  const sample = [
    ['面包', '肉松小贝', 600], ['面包', '全麦吐司', 1200], ['面包', '可颂', 700], ['面包', '毛毛虫', 500],
    ['西点', '蛋挞', 450], ['西点', '泡芙', 500], ['蛋糕', '切块蛋糕', 1000], ['饮品', '豆浆', 300],
  ];
  sample.forEach(([c, n, p], i) => run(`INSERT INTO products (category, name, price_cents, active, sort) VALUES (?,?,?,1,?)`, c, n, p, i));
  run(`INSERT OR IGNORE INTO settings (key, value) VALUES ('shop_name',?)`, DEFAULT_SHOP);
  run(`INSERT OR IGNORE INTO settings (key, value) VALUES ('ticket_faces','500,1000,2000')`);
}
// 第一版默认店名是"药大烘焙"，没改过的话换成正式店名
run(`UPDATE settings SET value=? WHERE key='shop_name' AND value='药大烘焙'`, DEFAULT_SHOP);
process.title = `${getSetting('shop_name', DEFAULT_SHOP)}收银系统`; // Windows 黑色窗口的标题

// 打折：店主在设置里开启，预设 3 个折扣；"全部打折"打开后每一单都按这个折扣
function discountCfg() {
  const presets = getSetting('discount_presets', '90,85,80').split(',').map(Number);
  const on = getSetting('discount_on', '0') === '1';
  const allPct = Number(getSetting('discount_all', '')) || null;
  return { on, presets, all: on ? allPct : null };
}
const zhe = (pct) => `${pct / 10}折`;

// ---------- 照片 ----------
function savePhoto(dataUrl) {
  if (!dataUrl) return null;
  const m = /^data:image\/(jpeg|png|webp);base64,(.+)$/.exec(dataUrl);
  if (!m) bad('照片格式不对');
  const buf = Buffer.from(m[2], 'base64');
  if (buf.length > 5 * 1024 * 1024) bad('照片太大');
  const name = `${today()}-${crypto.randomBytes(12).toString('hex')}.${m[1] === 'jpeg' ? 'jpg' : m[1]}`;
  fs.writeFileSync(path.join(PHOTOS, name), buf);
  return name;
}

// ---------- 存票账户 ----------
function weakCode(c) {
  if (/^(\d)\1{4}$/.test(c)) return true;
  const d = c.split('').map(Number);
  const asc = d.every((x, i) => i === 0 || x === d[i - 1] + 1);
  const desc = d.every((x, i) => i === 0 || x === d[i - 1] - 1);
  return asc || desc || /(\d)\1{3}/.test(c);
}
function newCode() {
  for (let i = 0; i < 1000; i++) {
    const c = String(crypto.randomInt(10000, 100000));
    if (weakCode(c)) continue;
    if (get(`SELECT 1 FROM accounts WHERE code=?`, c)) continue;
    if (get(`SELECT 1 FROM retired_codes WHERE code=?`, c)) continue;
    return c;
  }
  throw new HttpError(500, '生成查询码失败，请重试');
}
const balanceOf = (id) => get(`SELECT COALESCE(SUM(amount_cents),0) AS b FROM account_tx WHERE account_id=?`, id).b;
const maskName = (n) => (n ? n[0] + '*'.repeat(Math.min(Math.max(n.length - 1, 1), 3)) : '');

// tickets: [{face_cents, count}]，返回票面合计
function ticketsTotal(tickets) {
  if (!Array.isArray(tickets) || !tickets.length) return 0;
  let t = 0;
  for (const k of tickets) {
    if (!isInt(k.face_cents) || k.face_cents <= 0 || !isInt(k.count) || k.count <= 0) bad('餐票面额或张数不对');
    t += k.face_cents * k.count;
  }
  return t;
}
function addTicketBatches(tickets, source, refType, refId, expire) {
  for (const k of tickets || []) {
    run(`INSERT INTO ticket_batches (created_at, face_cents, count, expire_date, source, ref_type, ref_id) VALUES (?,?,?,?,?,?,?)`,
      now(), k.face_cents, k.count, isDate(expire) ? expire : null, source, refType, refId);
  }
}

// ---------- 会话 ----------
// 会话存在数据库里，重启程序不用重新登录
function currentUser(req) {
  const m = /(?:^|;\s*)sid=([a-f0-9]+)/.exec(req.headers.cookie || '');
  if (!m) return null;
  const s = get(`SELECT user_id FROM sessions WHERE token=?`, m[1]);
  if (!s) return null;
  const u = get(`SELECT id, name, role, active FROM users WHERE id=?`, s.user_id);
  if (!u || !u.active) return null;
  return u;
}

// 顾客查询限流：同一来源连续输错 5 次锁 15 分钟；全店每分钟最多 60 次查询
const lookupFails = new Map();
let lookupWindow = { start: Date.now(), count: 0 };
function clientIp(req) { return req.socket.remoteAddress || 'unknown'; }

// ---------- 路由 ----------
const routes = [];
function route(method, pattern, roles, handler) {
  const keys = [];
  const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; }) + '$');
  routes.push({ method, re, keys, roles, handler });
}
const STAFF = ['owner', 'cashier'];
const KITCHEN = ['owner', 'kitchen'];
const OWNER = ['owner'];
const ANY = ['owner', 'cashier', 'kitchen'];

// 登录
route('GET', '/api/login-names', null, () => all(`SELECT name FROM users WHERE active=1 ORDER BY id`).map((r) => r.name));
route('POST', '/api/login', null, ({ body, res }) => {
  const u = get(`SELECT * FROM users WHERE name=? AND active=1`, String(body.name || ''));
  if (!u || !checkPin(body.pin || '', u.pin_hash)) throw new HttpError(401, '姓名或密码不对');
  const token = crypto.randomBytes(24).toString('hex');
  run(`INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)`, token, u.id, now());
  res.setHeader('Set-Cookie', `sid=${token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${60 * 60 * 24 * 30}`);
  log(u, '登录', '');
  return { id: u.id, name: u.name, role: u.role };
});
route('POST', '/api/logout', null, ({ req, res }) => {
  const m = /(?:^|;\s*)sid=([a-f0-9]+)/.exec(req.headers.cookie || '');
  if (m) run(`DELETE FROM sessions WHERE token=?`, m[1]);
  res.setHeader('Set-Cookie', 'sid=; Path=/; Max-Age=0');
  return { ok: true };
});
route('GET', '/api/me', ANY, ({ user, req }) => {
  const pc = printCfg();
  return {
    ...user, default_pin: user.role === 'owner' && getSetting('default_pin') === '1',
    shop_name: getSetting('shop_name', DEFAULT_SHOP), version: VERSION, query_url: queryUrl(req),
    ticket_faces: getSetting('ticket_faces', '500,1000,2000').split(',').map(Number).filter((n) => n > 0),
    print: { mode: pc.mode, auto: pc.auto, paper: pc.paper },
    discount: discountCfg(),
  };
});
route('POST', '/api/me/pin', ANY, ({ user, body }) => {
  const u = get(`SELECT * FROM users WHERE id=?`, user.id);
  if (!checkPin(body.old_pin || '', u.pin_hash)) bad('原密码不对');
  if (!/^\d{4,8}$/.test(String(body.new_pin || ''))) bad('新密码需为 4 到 8 位数字');
  run(`UPDATE users SET pin_hash=? WHERE id=?`, hashPin(body.new_pin), user.id);
  if (user.role === 'owner') run(`DELETE FROM settings WHERE key='default_pin'`);
  log(user, '修改密码', '');
  return { ok: true };
});

// 员工
route('GET', '/api/users', OWNER, () => all(`SELECT id, name, role, active FROM users ORDER BY id`));
route('POST', '/api/users', OWNER, ({ user, body }) => {
  const name = String(body.name || '').trim();
  if (!name) bad('请填写姓名');
  if (!['owner', 'cashier', 'kitchen'].includes(body.role)) bad('角色不对');
  if (body.pin && !/^\d{4,8}$/.test(String(body.pin))) bad('密码需为 4 到 8 位数字');
  if (body.id) {
    if (body.id === user.id && (body.role !== 'owner' || !body.active)) bad('不能停用或降级自己');
    run(`UPDATE users SET name=?, role=?, active=? WHERE id=?`, name, body.role, body.active ? 1 : 0, body.id);
    if (body.pin) run(`UPDATE users SET pin_hash=? WHERE id=?`, hashPin(body.pin), body.id);
    if (body.pin || !body.active) run(`DELETE FROM sessions WHERE user_id=?`, body.id);
    log(user, '修改员工', { id: body.id, name, role: body.role, active: !!body.active });
    return { id: body.id };
  }
  if (!body.pin) bad('新员工需要设置密码');
  if (get(`SELECT 1 FROM users WHERE name=?`, name)) bad('已有同名员工');
  const r = run(`INSERT INTO users (name, role, pin_hash, active) VALUES (?,?,?,1)`, name, body.role, hashPin(body.pin));
  log(user, '新增员工', { name, role: body.role });
  return { id: Number(r.lastInsertRowid) };
});

// 设置
route('GET', '/api/settings', OWNER, () => Object.fromEntries(all(`SELECT key, value FROM settings`).map((r) => [r.key, r.value])));
const SETTING_CHECK = {
  shop_name: (v) => v.trim().length > 0 && v.length <= 20 || '店名需要 1 到 20 个字',
  ticket_faces: (v) => /^(\d+)(,\d+)*$|^$/.test(v) || '餐票面额格式不对',
  query_url: (v) => v === '' || /^https?:\/\/\S+$/.test(v) || '顾客查询地址要以 http:// 开头',
  print_mode: (v) => ['none', 'network', 'local', 'browser'].includes(v) || '打印方式不对',
  print_host: (v) => v === '' || /^[\w.-]{1,64}$/.test(v) || '打印机 IP 地址格式不对',
  print_port: (v) => v === '' || (/^\d{1,5}$/.test(v) && Number(v) <= 65535) || '端口不对',
  print_name: (v) => v === '' || printer.validLocalName(v) || '打印机共享名不能有引号和特殊符号',
  print_paper: (v) => ['58', '80'].includes(v) || '纸宽只能是 58 或 80',
  print_cols: (v) => v === '' || (/^\d+$/.test(v) && Number(v) >= 16 && Number(v) <= 64) || '每行字数要在 16 到 64 之间',
  print_auto: (v) => ['off', 'all', 'stored'].includes(v) || '自动打印选项不对',
  print_footer: (v) => v.length <= 40 || '小票底部文字最多 40 个字',
  discount_on: (v) => ['0', '1'].includes(v) || '打折开关不对',
  discount_presets: (v) => (/^\d{1,2}(,\d{1,2}){2}$/.test(v) && v.split(',').every((x) => Number(x) >= 1 && Number(x) <= 99)) || '三个折扣要填 1 到 99 之间的数，例如 90,85,80',
};
route('POST', '/api/settings', OWNER, ({ user, body }) => {
  const changes = {};
  for (const [k, check] of Object.entries(SETTING_CHECK)) {
    if (body[k] === undefined) continue;
    const v = String(body[k]).trim();
    const ok = check(v);
    if (ok !== true) bad(ok);
    changes[k] = v;
  }
  tx(() => { for (const [k, v] of Object.entries(changes)) run(`INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, k, v); });
  log(user, '修改设置', changes);
  return { ok: true };
});

// 商品
route('GET', '/api/products', ANY, () => all(`SELECT p.*, COALESCE((SELECT SUM(i.qty) FROM order_items i JOIN orders o ON o.id=i.order_id
  WHERE i.product_id=p.id AND o.status='done' AND substr(o.created_at,1,10) >= ?),0) AS sold_30d FROM products p ORDER BY active DESC, sort, id`, addDays(today(), -29)));
route('POST', '/api/products', OWNER, ({ user, body }) => {
  const name = String(body.name || '').trim();
  if (!name) bad('请填写商品名');
  if (!isInt(body.price_cents) || body.price_cents < 0) bad('价格不对');
  const cat = String(body.category || '其他').trim() || '其他';
  const sort = isInt(body.sort) ? body.sort : 0;
  if (body.id) {
    run(`UPDATE products SET name=?, category=?, price_cents=?, active=?, sort=? WHERE id=?`, name, cat, body.price_cents, body.active ? 1 : 0, sort, body.id);
    log(user, '修改商品', { id: body.id, name, price_cents: body.price_cents, active: !!body.active });
    return { id: body.id };
  }
  const r = run(`INSERT INTO products (name, category, price_cents, active, sort) VALUES (?,?,?,1,?)`, name, cat, body.price_cents, sort);
  log(user, '新增商品', { name, price_cents: body.price_cents });
  return { id: Number(r.lastInsertRowid) };
});

// 收银下单
route('POST', '/api/orders', STAFF, ({ user, body }) => {
  const items = Array.isArray(body.items) ? body.items : [];
  if (!items.length) bad('购物车是空的');
  const lines = items.map((it) => {
    if (!isInt(it.qty) || it.qty <= 0) bad('数量不对');
    if (it.product_id) {
      const p = get(`SELECT * FROM products WHERE id=?`, it.product_id);
      if (!p) bad('商品不存在');
      const price = isInt(it.price_cents) && it.price_cents >= 0 ? it.price_cents : p.price_cents;
      return { product_id: p.id, name: p.name, qty: it.qty, price_cents: price };
    }
    const name = String(it.name || '').trim();
    if (!name || !isInt(it.price_cents) || it.price_cents < 0) bad('临时商品需要名称和价格');
    return { product_id: null, name, qty: it.qty, price_cents: it.price_cents };
  });
  const subtotal = lines.reduce((s, l) => s + l.qty * l.price_cents, 0);
  let pct = null;
  if (body.discount_pct !== undefined && body.discount_pct !== null && body.discount_pct !== 100) {
    if (!isInt(body.discount_pct) || body.discount_pct < 1 || body.discount_pct > 99) bad('折扣不对');
    if (!discountCfg().on) bad('打折功能没有开启，请店主到"设置"里开启');
    pct = body.discount_pct;
  }
  const discount = pct ? subtotal - Math.round(subtotal * pct / 100) : 0;
  const total = subtotal - discount;

  const pays = Array.isArray(body.payments) ? body.payments : [];
  if (!pays.length && total > 0) bad('请选择收款方式');
  let paid = 0; let ticketPaid = 0;
  const norm = pays.map((p) => {
    if (!['cash', 'pos', 'ticket', 'stored'].includes(p.method)) bad('收款方式不对');
    if (p.method === 'ticket') {
      const t = ticketsTotal(p.tickets);
      if (!t) bad('请填写餐票面额和张数');
      ticketPaid += t; paid += t;
      return { method: 'ticket', amount_cents: t, tickets: p.tickets };
    }
    if (!isInt(p.amount_cents) || p.amount_cents <= 0) bad('收款金额不对');
    paid += p.amount_cents;
    if (p.method === 'stored') {
      const a = get(`SELECT * FROM accounts WHERE id=?`, p.account_id);
      if (!a || a.status !== 'active') bad('存票账户不存在或已注销');
      return { method: 'stored', amount_cents: p.amount_cents, account_id: a.id };
    }
    return { method: p.method, amount_cents: p.amount_cents };
  });
  if (paid < total) bad(`还差 ${((total - paid) / 100).toFixed(2)} 元`);
  // 餐票票面超过应付时不找零，多出的部分记为"餐票溢收"
  const over = paid - total;
  if (over > 0) {
    if (norm.some((p) => p.method !== 'ticket')) bad('收款金额超过应付，请改一下金额（只有全用餐票时才能多收不找零）');
    const minFace = Math.min(...norm.flatMap((p) => p.tickets.map((k) => k.face_cents)));
    if (over >= minFace) bad(`餐票给多了，少收一张 ${(minFace / 100).toFixed(0)} 元票也够付`);
  }

  return tx(() => {
    // 同一账户多行合并检查余额
    const need = {};
    for (const p of norm) if (p.method === 'stored') need[p.account_id] = (need[p.account_id] || 0) + p.amount_cents;
    for (const [id, amt] of Object.entries(need)) {
      if (balanceOf(Number(id)) < amt) bad('存票余额不足');
    }
    const photo = savePhoto(body.photo);
    const o = run(`INSERT INTO orders (created_at, cashier_id, cashier_name, total_cents, overpay_cents, status, photo, note, subtotal_cents, discount_pct, discount_cents) VALUES (?,?,?,?,?, 'done', ?, ?, ?, ?, ?)`,
      now(), user.id, user.name, total, over, photo, String(body.note || ''), subtotal, pct, discount);
    const oid = Number(o.lastInsertRowid);
    for (const l of lines) run(`INSERT INTO order_items (order_id, product_id, name, qty, price_cents) VALUES (?,?,?,?,?)`, oid, l.product_id, l.name, l.qty, l.price_cents);
    for (const p of norm) {
      run(`INSERT INTO payments (order_id, method, amount_cents, account_id, detail) VALUES (?,?,?,?,?)`,
        oid, p.method, p.amount_cents, p.account_id || null, p.tickets ? JSON.stringify(p.tickets) : null);
      if (p.method === 'stored') {
        run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, order_id, operator_id, operator_name, note, photo) VALUES (?,?,'spend',?,?,?,?,?,?)`,
          p.account_id, now(), -p.amount_cents, oid, user.id, user.name, '', photo);
      }
      if (p.method === 'ticket') addTicketBatches(p.tickets, 'temp', 'order', oid, null);
    }
    return { id: oid, total_cents: total, subtotal_cents: subtotal, discount_cents: discount, paid_cents: paid, overpay_cents: over, has_stored: norm.some((p) => p.method === 'stored') };
  });
});

route('POST', '/api/discount-all', STAFF, ({ user, body }) => {
  if (body.pct === null || body.pct === undefined || body.pct === '') {
    run(`DELETE FROM settings WHERE key='discount_all'`);
    log(user, '关闭全部打折', '');
    return discountCfg();
  }
  if (!discountCfg().on) bad('打折功能没有开启，请店主到"设置"里开启');
  if (!isInt(body.pct) || body.pct < 1 || body.pct > 99) bad('折扣不对');
  run(`INSERT INTO settings (key, value) VALUES ('discount_all',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, String(body.pct));
  log(user, '开启全部打折', zhe(body.pct));
  return discountCfg();
});

function ordersDetail(rows) {
  if (!rows.length) return rows;
  const ids = rows.map((r) => r.id);
  const q = ids.map(() => '?').join(',');
  const items = all(`SELECT * FROM order_items WHERE order_id IN (${q})`, ...ids);
  const pays = all(`SELECT p.*, a.code AS account_code, a.name AS account_name FROM payments p LEFT JOIN accounts a ON a.id=p.account_id WHERE order_id IN (${q})`, ...ids);
  for (const r of rows) {
    r.items = items.filter((i) => i.order_id === r.id);
    r.payments = pays.filter((p) => p.order_id === r.id);
  }
  return rows;
}
route('GET', '/api/orders', STAFF, ({ query }) => {
  const from = isDate(query.from) ? query.from : today();
  const to = isDate(query.to) ? query.to : from;
  return ordersDetail(all(`SELECT * FROM orders WHERE substr(created_at,1,10) BETWEEN ? AND ? ORDER BY id DESC LIMIT 2000`, from, to));
});
route('POST', '/api/orders/:id/void', OWNER, ({ user, params, body }) => {
  const o = get(`SELECT * FROM orders WHERE id=?`, Number(params.id));
  if (!o) bad('订单不存在');
  if (o.status === 'void') bad('这单已经撤销过了');
  const reason = String(body.reason || '').trim();
  if (!reason) bad('请填写撤单原因');
  return tx(() => {
    for (const p of all(`SELECT * FROM payments WHERE order_id=? AND method='stored'`, o.id)) {
      run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, order_id, operator_id, operator_name, note) VALUES (?,?,'refund',?,?,?,?,?)`,
        p.account_id, now(), p.amount_cents, o.id, user.id, user.name, `撤单退回：${reason}`);
    }
    const redeemed = get(`SELECT 1 FROM ticket_batches WHERE ref_type='order' AND ref_id=? AND redemption_id IS NOT NULL`, o.id);
    if (!redeemed) run(`DELETE FROM ticket_batches WHERE ref_type='order' AND ref_id=?`, o.id);
    run(`UPDATE orders SET status='void', void_reason=?, void_by=? WHERE id=?`, reason, user.name, o.id);
    log(user, '撤单', { order_id: o.id, total_cents: o.total_cents, reason });
    return { ok: true };
  });
});

// 存票账户
function accountRow(a) { return { ...a, balance_cents: balanceOf(a.id) }; }
route('GET', '/api/accounts', STAFF, ({ query }) => {
  const q = String(query.q || '').trim();
  let rows;
  if (/^\d{5}$/.test(q)) rows = all(`SELECT * FROM accounts WHERE code=?`, q);
  else if (q) rows = all(`SELECT * FROM accounts WHERE name LIKE ? OR note LIKE ? ORDER BY status, id DESC LIMIT 50`, `%${q}%`, `%${q}%`);
  else rows = all(`SELECT * FROM accounts ORDER BY status, id DESC LIMIT 500`);
  return rows.map(accountRow);
});
route('GET', '/api/accounts/summary', STAFF, () => {
  const r = get(`SELECT COUNT(*) AS n, COALESCE(SUM(t.amount_cents),0) AS total FROM accounts a LEFT JOIN account_tx t ON t.account_id=a.id WHERE a.status='active'`);
  return { active_accounts: get(`SELECT COUNT(*) AS n FROM accounts WHERE status='active'`).n, liability_cents: r.total };
});
function accountTxs(id) {
  const txs = all(`SELECT * FROM account_tx WHERE account_id=? ORDER BY id DESC LIMIT 500`, id);
  const oids = [...new Set(txs.filter((t) => t.order_id).map((t) => t.order_id))];
  const items = oids.length ? all(`SELECT order_id, name, qty FROM order_items WHERE order_id IN (${oids.map(() => '?').join(',')})`, ...oids) : [];
  for (const t of txs) if (t.order_id) t.items = items.filter((i) => i.order_id === t.order_id).map((i) => `${i.name}×${i.qty}`).join('、');
  return txs;
}
route('GET', '/api/accounts/:id', STAFF, ({ params }) => {
  const a = get(`SELECT * FROM accounts WHERE id=?`, Number(params.id));
  if (!a) bad('账户不存在');
  return { ...accountRow(a), txs: accountTxs(a.id) };
});
function depositAmount(body) {
  const t = ticketsTotal(body.tickets);
  const amt = t || body.amount_cents;
  if (!isInt(amt) || amt <= 0) bad('请填写存入金额或餐票张数');
  return amt;
}
route('POST', '/api/accounts', STAFF, ({ user, body }) => {
  const name = String(body.name || '').trim();
  if (!name) bad('请填写姓名');
  const amt = depositAmount(body);
  return tx(() => {
    const code = newCode();
    const r = run(`INSERT INTO accounts (code, name, note, created_at, status) VALUES (?,?,?,?, 'active')`, code, name, String(body.note || ''), now());
    const id = Number(r.lastInsertRowid);
    const t = run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, operator_id, operator_name, note) VALUES (?,?,'deposit',?,?,?,?)`,
      id, now(), amt, user.id, user.name, '开户存入');
    addTicketBatches(body.tickets, 'stored', 'account_tx', Number(t.lastInsertRowid), body.expire_date);
    log(user, '存票开户', { id, name, amount_cents: amt });
    return { id, code };
  });
});
route('POST', '/api/accounts/:id/deposit', STAFF, ({ user, params, body }) => {
  const a = get(`SELECT * FROM accounts WHERE id=?`, Number(params.id));
  if (!a || a.status !== 'active') bad('账户不存在或已注销');
  const amt = depositAmount(body);
  return tx(() => {
    const t = run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, operator_id, operator_name, note) VALUES (?,?,'deposit',?,?,?,?)`,
      a.id, now(), amt, user.id, user.name, String(body.note || '续存'));
    addTicketBatches(body.tickets, 'stored', 'account_tx', Number(t.lastInsertRowid), body.expire_date);
    log(user, '存票续存', { id: a.id, amount_cents: amt });
    return { ok: true, balance_cents: balanceOf(a.id) };
  });
});
route('POST', '/api/accounts/:id/reset-code', OWNER, ({ user, params }) => {
  const a = get(`SELECT * FROM accounts WHERE id=?`, Number(params.id));
  if (!a) bad('账户不存在');
  return tx(() => {
    const code = newCode();
    run(`INSERT OR IGNORE INTO retired_codes (code) VALUES (?)`, a.code);
    run(`UPDATE accounts SET code=? WHERE id=?`, code, a.id);
    log(user, '重置查询码', { id: a.id, name: a.name });
    return { code };
  });
});
route('POST', '/api/accounts/:id/adjust', OWNER, ({ user, params, body }) => {
  const a = get(`SELECT * FROM accounts WHERE id=?`, Number(params.id));
  if (!a || a.status !== 'active') bad('账户不存在或已注销');
  if (!isInt(body.amount_cents) || body.amount_cents === 0) bad('调整金额不对');
  const note = String(body.note || '').trim();
  if (!note) bad('请填写调整原因');
  if (balanceOf(a.id) + body.amount_cents < 0) bad('调整后余额不能为负');
  run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, operator_id, operator_name, note) VALUES (?,?,'adjust',?,?,?,?)`,
    a.id, now(), body.amount_cents, user.id, user.name, note);
  log(user, '调整余额', { id: a.id, amount_cents: body.amount_cents, note });
  return { ok: true };
});
route('POST', '/api/accounts/:id/close', OWNER, ({ user, params, body }) => {
  const a = get(`SELECT * FROM accounts WHERE id=?`, Number(params.id));
  if (!a || a.status !== 'active') bad('账户不存在或已注销');
  return tx(() => {
    const b = balanceOf(a.id);
    if (b !== 0) {
      run(`INSERT INTO account_tx (account_id, created_at, type, amount_cents, operator_id, operator_name, note) VALUES (?,?,'close',?,?,?,?)`,
        a.id, now(), -b, user.id, user.name, String(body.note || '销户退还'));
    }
    run(`UPDATE accounts SET status='closed' WHERE id=?`, a.id);
    log(user, '销户', { id: a.id, name: a.name, refunded_cents: b });
    return { ok: true, refunded_cents: b };
  });
});

// 顾客查询（公开）
route('GET', '/api/public/info', null, () => ({ shop_name: getSetting('shop_name', DEFAULT_SHOP) }));
route('POST', '/api/public/lookup', null, ({ req, body }) => {
  const ip = clientIp(req);
  const t = Date.now();
  if (t - lookupWindow.start > 60000) lookupWindow = { start: t, count: 0 };
  if (++lookupWindow.count > 60) throw new HttpError(429, '查询太频繁，请稍后再试');
  const f = lookupFails.get(ip);
  if (f && f.until > t) throw new HttpError(429, `输错次数太多，请 ${Math.ceil((f.until - t) / 60000)} 分钟后再试`);
  const code = String(body.code || '');
  const a = /^\d{5}$/.test(code) ? get(`SELECT * FROM accounts WHERE code=?`, code) : null;
  if (!a) {
    const fails = (f && f.until === 0 ? f.fails : 0) + 1;
    lookupFails.set(ip, { fails, until: fails >= 5 ? t + 15 * 60000 : 0 });
    throw new HttpError(404, fails >= 5 ? '输错次数太多，请 15 分钟后再试' : `查询码不对，还可以试 ${5 - fails} 次`);
  }
  lookupFails.delete(ip);
  return {
    name: maskName(a.name), status: a.status, balance_cents: balanceOf(a.id),
    txs: accountTxs(a.id).slice(0, 200).map((x) => ({ created_at: x.created_at, type: x.type, amount_cents: x.amount_cents, items: x.items || '', photo: x.photo })),
  };
});

// 餐票库与兑换
route('GET', '/api/tickets', OWNER, () => {
  const pending = all(`SELECT * FROM ticket_batches WHERE redemption_id IS NULL ORDER BY COALESCE(expire_date,'9999'), id`);
  const groups = all(`SELECT face_cents, expire_date, SUM(count) AS count FROM ticket_batches WHERE redemption_id IS NULL GROUP BY face_cents, expire_date ORDER BY COALESCE(expire_date,'9999'), face_cents`);
  const pendingTotal = pending.reduce((s, b) => s + b.face_cents * b.count, 0);
  const liability = get(`SELECT COALESCE(SUM(t.amount_cents),0) AS v FROM account_tx t JOIN accounts a ON a.id=t.account_id WHERE a.status='active'`).v;
  const redemptions = all(`SELECT * FROM redemptions ORDER BY id DESC LIMIT 200`);
  const kinds = Object.fromEntries(all(`SELECT kind, COALESCE(SUM(face_total_cents),0) AS v FROM redemptions WHERE substr(created_at,1,7)=? GROUP BY kind`, today().slice(0, 7)).map((r) => [r.kind, r.v]));
  return { pending, groups, by_face: ticketsOnHand(), pending_total_cents: pendingTotal, liability_cents: liability, redemptions, month: { school: kinds.school || 0, stall: kinds.stall || 0 }, today: today() };
});
// 店里手上还有的纸质餐票（没去兑换、也没拿去其他档口用的），按面额
function ticketsOnHand() {
  return all(`SELECT face_cents, SUM(count) AS count FROM ticket_batches WHERE redemption_id IS NULL GROUP BY face_cents ORDER BY face_cents`);
}
// 拿店里收到的餐票去食堂其他档口用：按面额和张数，从最早到期的票开始扣
route('POST', '/api/ticket-use', OWNER, ({ user, body }) => {
  const want = Array.isArray(body.tickets) ? body.tickets.filter((k) => k && k.count) : [];
  const face = ticketsTotal(want);
  if (!face) bad('请选择要用的餐票');
  const note = String(body.note || '').trim();
  if (!note) bad('请填写用在哪个档口、买了什么');
  return tx(() => {
    const r = run(`INSERT INTO redemptions (created_at, face_total_cents, received_cents, note, operator_name, kind) VALUES (?,?,?,?,?, 'stall')`,
      now(), face, face, note, user.name);
    const rid = Number(r.lastInsertRowid);
    for (const k of want) {
      let need = k.count;
      const batches = all(`SELECT * FROM ticket_batches WHERE redemption_id IS NULL AND face_cents=? ORDER BY COALESCE(expire_date,'9999'), id`, k.face_cents);
      if (batches.reduce((s2, b) => s2 + b.count, 0) < need) bad(`店里的 ${(k.face_cents / 100)} 元票不够 ${k.count} 张`);
      for (const b of batches) {
        if (!need) break;
        if (b.count <= need) {
          run(`UPDATE ticket_batches SET redemption_id=? WHERE id=?`, rid, b.id);
          need -= b.count;
        } else {
          // 一批票只用掉一部分：拆成两批
          run(`UPDATE ticket_batches SET count=? WHERE id=?`, b.count - need, b.id);
          run(`INSERT INTO ticket_batches (created_at, face_cents, count, expire_date, source, ref_type, ref_id, redemption_id) VALUES (?,?,?,?,?,?,?,?)`,
            b.created_at, b.face_cents, need, b.expire_date, b.source, b.ref_type, b.ref_id, rid);
          need = 0;
        }
      }
    }
    log(user, '餐票档口使用', { id: rid, face_total_cents: face, note });
    return { id: rid, face_total_cents: face };
  });
});
route('POST', '/api/redemptions', OWNER, ({ user, body }) => {
  const ids = Array.isArray(body.batch_ids) ? body.batch_ids.filter(isInt) : [];
  if (!ids.length) bad('请选择要兑换的餐票');
  if (!isInt(body.received_cents) || body.received_cents < 0) bad('请填写实际换回金额');
  return tx(() => {
    const q = ids.map(() => '?').join(',');
    const rows = all(`SELECT * FROM ticket_batches WHERE id IN (${q}) AND redemption_id IS NULL`, ...ids);
    if (rows.length !== ids.length) bad('有餐票已经兑换过了，请刷新');
    const face = rows.reduce((s, b) => s + b.face_cents * b.count, 0);
    const r = run(`INSERT INTO redemptions (created_at, face_total_cents, received_cents, note, operator_name) VALUES (?,?,?,?,?)`,
      now(), face, body.received_cents, String(body.note || ''), user.name);
    const rid = Number(r.lastInsertRowid);
    run(`UPDATE ticket_batches SET redemption_id=? WHERE id IN (${q})`, rid, ...ids);
    log(user, '餐票兑换', { id: rid, face_total_cents: face, received_cents: body.received_cents });
    return { id: rid, face_total_cents: face };
  });
});

// 日结
function daySystem(date) {
  const by = all(`SELECT p.method, COALESCE(SUM(p.amount_cents),0) AS amount, COUNT(DISTINCT p.order_id) AS orders
    FROM payments p JOIN orders o ON o.id=p.order_id WHERE o.status='done' AND substr(o.created_at,1,10)=? GROUP BY p.method`, date);
  const m = { cash: 0, pos: 0, ticket: 0, stored: 0 };
  const n = { cash: 0, pos: 0, ticket: 0, stored: 0 };
  for (const r of by) { m[r.method] = r.amount; n[r.method] = r.orders; }
  const o = get(`SELECT COUNT(*) AS n, COALESCE(SUM(total_cents),0) AS total, COALESCE(SUM(overpay_cents),0) AS over, COALESCE(SUM(discount_cents),0) AS disc FROM orders WHERE status='done' AND substr(created_at,1,10)=?`, date);
  const voided = get(`SELECT COUNT(*) AS n FROM orders WHERE status='void' AND substr(created_at,1,10)=?`, date).n;
  const deposits = get(`SELECT COALESCE(SUM(amount_cents),0) AS v FROM account_tx WHERE type='deposit' AND substr(created_at,1,10)=?`, date).v;
  const paid = m.cash + m.pos + m.ticket + m.stored;
  return { amounts: m, orders_by_method: n, orders: o.n, total_cents: o.total, overpay_cents: o.over, discount_cents: o.disc, paid_cents: paid, voided, deposits_cents: deposits };
}
function ticketFaces() {
  const set = getSetting('ticket_faces', '500,1000,2000').split(',').map(Number).filter((n) => n > 0);
  return [...new Set([...set, ...ticketsOnHand().map((r) => r.face_cents)])].sort((a, b) => a - b);
}
route('GET', '/api/dayclose', STAFF, ({ query }) => {
  const date = isDate(query.date) ? query.date : today();
  const saved = get(`SELECT * FROM day_closes WHERE date=?`, date) || null;
  if (saved) { try { saved.tickets = JSON.parse(saved.tickets_json || 'null'); } catch { saved.tickets = null; } }
  const onHand = Object.fromEntries(ticketsOnHand().map((r) => [r.face_cents, r.count]));
  return { date, today: today(), system: daySystem(date), saved, tickets_now: ticketFaces().map((f) => ({ face_cents: f, count: onHand[f] || 0 })) };
});
route('POST', '/api/dayclose', STAFF, ({ user, body }) => {
  const date = isDate(body.date) ? body.date : today();
  if (!isInt(body.cash_actual_cents) || !isInt(body.pos_actual_cents)) bad('请填写实点现金和收银机小票合计');
  const s = daySystem(date);
  const cashDiff = body.cash_actual_cents - s.amounts.cash;
  const posDiff = body.pos_actual_cents - s.amounts.pos;
  const note = String(body.note || '').trim();
  // 店内余票：系统应有张数（按现在的餐票库）和实点张数
  let tickets = null; let ticketDiff = 0;
  if (Array.isArray(body.tickets_actual) && body.tickets_actual.some((k) => k && k.count !== null && k.count !== undefined)) {
    const onHand = Object.fromEntries(ticketsOnHand().map((r) => [r.face_cents, r.count]));
    const rows = ticketFaces().map((f) => {
      const k = body.tickets_actual.find((x) => x && x.face_cents === f);
      const actual = k && k.count !== null && k.count !== undefined ? k.count : null;
      if (actual !== null && (!isInt(actual) || actual < 0)) bad('余票张数不对');
      return { face_cents: f, system: onHand[f] || 0, actual };
    });
    for (const r of rows) if (r.actual !== null) ticketDiff += Math.abs(r.actual - r.system);
    tickets = { rows, at: now() };
  } else {
    const old = get(`SELECT tickets_json FROM day_closes WHERE date=?`, date);
    if (old && old.tickets_json) tickets = JSON.parse(old.tickets_json);
  }
  if ((cashDiff || posDiff || ticketDiff) && !note) bad('有差额，请填写原因');
  run(`INSERT INTO day_closes (date, cash_system_cents, cash_actual_cents, pos_system_cents, pos_actual_cents, ticket_cents, stored_cents, note, closed_by, closed_at, tickets_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET cash_system_cents=excluded.cash_system_cents, cash_actual_cents=excluded.cash_actual_cents,
    pos_system_cents=excluded.pos_system_cents, pos_actual_cents=excluded.pos_actual_cents, ticket_cents=excluded.ticket_cents, stored_cents=excluded.stored_cents,
    note=excluded.note, closed_by=excluded.closed_by, closed_at=excluded.closed_at, tickets_json=excluded.tickets_json`,
    date, s.amounts.cash, body.cash_actual_cents, s.amounts.pos, body.pos_actual_cents, s.amounts.ticket, s.amounts.stored, note, user.name, now(), tickets ? JSON.stringify(tickets) : null);
  log(user, '日结', { date, cashDiff, posDiff, ticketDiff });
  return { ok: true };
});

// 报表
route('GET', '/api/reports', OWNER, ({ query }) => {
  const to = isDate(query.to) ? query.to : today();
  const from = isDate(query.from) ? query.from : addDays(to, -6);
  const W = `o.status='done' AND substr(o.created_at,1,10) BETWEEN ? AND ?`;
  const methods = all(`SELECT p.method, SUM(p.amount_cents) AS amount FROM payments p JOIN orders o ON o.id=p.order_id WHERE ${W} GROUP BY p.method`, from, to);
  const products = all(`SELECT i.name, SUM(i.qty) AS qty, SUM(i.qty*i.price_cents) AS amount FROM order_items i JOIN orders o ON o.id=i.order_id WHERE ${W} GROUP BY i.name ORDER BY amount DESC`, from, to);
  const days = all(`SELECT substr(o.created_at,1,10) AS day, p.method, SUM(p.amount_cents) AS amount FROM payments p JOIN orders o ON o.id=p.order_id WHERE ${W} GROUP BY day, p.method ORDER BY day`, from, to);
  const hours = all(`SELECT substr(o.created_at,12,2) AS hour, COUNT(*) AS orders, SUM(o.total_cents) AS amount FROM orders o WHERE ${W} GROUP BY hour ORDER BY hour`, from, to);
  const totals = get(`SELECT COUNT(*) AS orders, COALESCE(SUM(total_cents),0) AS amount, COALESCE(SUM(overpay_cents),0) AS overpay, COALESCE(SUM(discount_cents),0) AS discount FROM orders o WHERE ${W}`, from, to);
  const produced = all(`SELECT p.name, SUM(CASE WHEN l.type='output' THEN l.qty ELSE 0 END) AS output, SUM(CASE WHEN l.type='loss' THEN l.qty ELSE 0 END) AS loss
    FROM production_logs l JOIN products p ON p.id=l.product_id WHERE l.date BETWEEN ? AND ? GROUP BY p.name`, from, to);
  return { from, to, methods, products, days, hours, totals, produced };
});

function csv(rows, cols) {
  const esc = (v) => { const s = v === null || v === undefined ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return '﻿' + [cols.map((c) => c[1]).join(','), ...rows.map((r) => cols.map((c) => esc(typeof c[0] === 'function' ? c[0](r) : r[c[0]])).join(','))].join('\r\n');
}
const yuan = (c) => (c / 100).toFixed(2);
const METHOD = { cash: '现金', pos: '学校收银机', ticket: '临时用票', stored: '存票余额' };
route('GET', '/api/export', OWNER, ({ query, res }) => {
  const to = isDate(query.to) ? query.to : today();
  const from = isDate(query.from) ? query.from : to;
  let body; let name;
  if (query.type === 'payments') {
    const rows = all(`SELECT o.id, o.created_at, o.status, o.cashier_name, p.method, p.amount_cents, a.code, a.name AS account_name FROM payments p JOIN orders o ON o.id=p.order_id LEFT JOIN accounts a ON a.id=p.account_id WHERE substr(o.created_at,1,10) BETWEEN ? AND ? ORDER BY o.id`, from, to);
    body = csv(rows, [['id', '订单号'], ['created_at', '时间'], [(r) => (r.status === 'void' ? '已撤销' : '正常'), '状态'], ['cashier_name', '收银员'], [(r) => METHOD[r.method], '收款方式'], [(r) => yuan(r.amount_cents), '金额'], ['code', '存票码'], ['account_name', '存票人']]);
    name = `收款明细_${from}_${to}.csv`;
  } else if (query.type === 'orders') {
    const rows = ordersDetail(all(`SELECT * FROM orders WHERE substr(created_at,1,10) BETWEEN ? AND ? ORDER BY id`, from, to));
    body = csv(rows, [['id', '订单号'], ['created_at', '时间'], [(r) => (r.status === 'void' ? '已撤销' : '正常'), '状态'], ['cashier_name', '收银员'],
      [(r) => r.items.map((i) => `${i.name}×${i.qty}`).join(' '), '商品'], [(r) => yuan(r.subtotal_cents ?? r.total_cents), '原价'],
      [(r) => (r.discount_pct ? `${r.discount_pct / 10}折` : ''), '折扣'], [(r) => yuan(r.discount_cents || 0), '优惠'], [(r) => yuan(r.total_cents), '应收'],
      [(r) => yuan(r.payments.reduce((s, p) => s + p.amount_cents, 0)), '实收'], [(r) => yuan(r.overpay_cents || 0), '餐票溢收'],
      [(r) => r.payments.map((p) => `${METHOD[p.method]}${yuan(p.amount_cents)}`).join(' '), '收款方式']]);
    name = `订单汇总_${from}_${to}.csv`;
  } else if (query.type === 'accounts') {
    const rows = all(`SELECT * FROM accounts ORDER BY id`).map(accountRow);
    body = csv(rows, [['code', '查询码'], ['name', '姓名'], ['note', '备注'], ['created_at', '开户时间'], [(r) => (r.status === 'active' ? '正常' : '已销户'), '状态'], [(r) => yuan(r.balance_cents), '余额']]);
    name = `存票账户_${today()}.csv`;
  } else {
    const rows = all(`SELECT o.id, o.created_at, o.status, o.cashier_name, i.name, i.qty, i.price_cents FROM order_items i JOIN orders o ON o.id=i.order_id WHERE substr(o.created_at,1,10) BETWEEN ? AND ? ORDER BY o.id`, from, to);
    body = csv(rows, [['id', '订单号'], ['created_at', '时间'], [(r) => (r.status === 'void' ? '已撤销' : '正常'), '状态'], ['cashier_name', '收银员'], ['name', '商品'], ['qty', '数量'], [(r) => yuan(r.price_cents), '单价'], [(r) => yuan(r.qty * r.price_cents), '小计']]);
    name = `销售明细_${from}_${to}.csv`;
  }
  res.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(name)}` });
  res.end(body);
  return undefined;
});

// 出品（后厨）
route('GET', '/api/production', KITCHEN, ({ query }) => {
  const date = isDate(query.date) ? query.date : today();
  const logs = all(`SELECT l.*, p.name FROM production_logs l JOIN products p ON p.id=l.product_id WHERE l.date=? ORDER BY l.id DESC`, date);
  // 计划表是前一天在"生产计划"页做好、保存到这一天的
  const plan = all(`SELECT pl.product_id, pl.qty, p.name, p.category FROM plans pl JOIN products p ON p.id=pl.product_id WHERE pl.date=? ORDER BY p.sort, p.id`, date);
  return { date, logs, plan };
});
route('POST', '/api/production', KITCHEN, ({ user, body }) => {
  const date = isDate(body.date) ? body.date : today();
  if (!['output', 'loss', 'leftover'].includes(body.type)) bad('类型不对');
  if (!get(`SELECT 1 FROM products WHERE id=?`, body.product_id)) bad('商品不存在');
  if (!isInt(body.qty) || body.qty <= 0) bad('数量不对');
  const r = run(`INSERT INTO production_logs (date, created_at, product_id, type, qty, note, operator_name) VALUES (?,?,?,?,?,?,?)`,
    date, now(), body.product_id, body.type, body.qty, String(body.note || ''), user.name);
  return { id: Number(r.lastInsertRowid) };
});
// 后厨登记新品：同时加到商品里（设置页能看到、收银能卖）
route('POST', '/api/production/new-product', KITCHEN, ({ user, body }) => {
  const name = String(body.name || '').trim();
  if (!name) bad('请填写新品名称');
  if (!isInt(body.price_cents) || body.price_cents <= 0) bad('请填写新品售价');
  if (get(`SELECT 1 FROM products WHERE name=?`, name)) bad('已经有这个商品了，请直接在商品里选');
  if (!['output', 'loss', 'leftover'].includes(body.type)) bad('类型不对');
  if (!isInt(body.qty) || body.qty <= 0) bad('数量不对');
  const date = isDate(body.date) ? body.date : today();
  const cat = String(body.category || '').trim() || '新品';
  return tx(() => {
    const sort = get(`SELECT COALESCE(MAX(sort),0)+1 AS s FROM products`).s;
    const pid = Number(run(`INSERT INTO products (name, category, price_cents, active, sort) VALUES (?,?,?,1,?)`, name, cat, body.price_cents, sort).lastInsertRowid);
    run(`INSERT INTO production_logs (date, created_at, product_id, type, qty, note, operator_name) VALUES (?,?,?,?,?,?,?)`,
      date, now(), pid, body.type, body.qty, String(body.note || ''), user.name);
    log(user, '后厨新增商品', { name, category: cat, price_cents: body.price_cents });
    return { product_id: pid };
  });
});
route('POST', '/api/production/:id/delete', KITCHEN, ({ user, params }) => {
  const l = get(`SELECT * FROM production_logs WHERE id=?`, Number(params.id));
  if (!l) bad('记录不存在');
  if (user.role !== 'owner' && l.date !== today()) bad('只能删除当天的记录');
  run(`DELETE FROM production_logs WHERE id=?`, l.id);
  log(user, '删除出品记录', l);
  return { ok: true };
});

// 盘存（原料、包材、成品）
const stockQty = `COALESCE((SELECT SUM(qty) FROM stock_moves m WHERE m.item_id=s.id),0)`;
route('GET', '/api/stock', KITCHEN, () => ({
  items: all(`SELECT s.*, ${stockQty} AS qty FROM stock_items s ORDER BY s.active DESC, s.kind, s.name`),
  moves: all(`SELECT m.*, s.name, s.unit FROM stock_moves m JOIN stock_items s ON s.id=m.item_id ORDER BY m.id DESC LIMIT 200`),
}));
route('POST', '/api/stock/items', KITCHEN, ({ user, body }) => {
  const name = String(body.name || '').trim();
  if (!name) bad('请填写名称');
  const kind = ['原料', '包材', '成品'].includes(body.kind) ? body.kind : '原料';
  const unit = String(body.unit || '').trim() || '个';
  const cost = isInt(body.cost_cents) && body.cost_cents >= 0 ? body.cost_cents : 0;
  const low = typeof body.low_qty === 'number' && body.low_qty >= 0 ? body.low_qty : 0;
  if (body.id) {
    run(`UPDATE stock_items SET name=?, kind=?, unit=?, cost_cents=?, low_qty=?, active=? WHERE id=?`, name, kind, unit, cost, low, body.active ? 1 : 0, body.id);
    return { id: body.id };
  }
  const r = run(`INSERT INTO stock_items (name, kind, unit, cost_cents, low_qty, active) VALUES (?,?,?,?,?,1)`, name, kind, unit, cost, low);
  log(user, '新增库存品', { name, kind, unit });
  return { id: Number(r.lastInsertRowid) };
});
route('POST', '/api/stock/moves', KITCHEN, ({ user, body }) => {
  const item = get(`SELECT s.*, ${stockQty} AS qty FROM stock_items s WHERE s.id=?`, body.item_id);
  if (!item) bad('库存品不存在');
  const q = Number(body.qty);
  if (!Number.isFinite(q) || q < 0 || (q === 0 && body.type !== 'count')) bad('数量不对');
  let delta;
  if (body.type === 'in') delta = q;
  else if (body.type === 'use' || body.type === 'loss') delta = -q;
  else if (body.type === 'count') delta = Math.round((q - item.qty) * 1000) / 1000;
  else bad('类型不对');
  run(`INSERT INTO stock_moves (item_id, created_at, type, qty, cost_cents, note, operator_name) VALUES (?,?,?,?,?,?,?)`,
    item.id, now(), body.type, delta, isInt(body.cost_cents) ? body.cost_cents : null, String(body.note || ''), user.name);
  if (body.type === 'in' && isInt(body.cost_cents) && body.cost_cents > 0 && q > 0) {
    run(`UPDATE stock_items SET cost_cents=? WHERE id=?`, Math.round(body.cost_cents / q), item.id);
  }
  if (body.type === 'count') log(user, '盘点', { item: item.name, system: item.qty, actual: q, diff: delta });
  return { ok: true, delta };
});

// 盘点：按理论库存列出，一次填好所有实盘数
route('POST', '/api/stock/count', KITCHEN, ({ user, body }) => {
  const rows = (Array.isArray(body.rows) ? body.rows : []).filter((r) => r && r.qty !== null && r.qty !== undefined && r.qty !== '');
  if (!rows.length) bad('还没有填实盘数');
  const note = String(body.note || '').trim();
  return tx(() => {
    const out = [];
    for (const r of rows) {
      const item = get(`SELECT s.*, ${stockQty} AS qty FROM stock_items s WHERE s.id=?`, r.item_id);
      if (!item) bad('库存品不存在');
      const q = Number(r.qty);
      if (!Number.isFinite(q) || q < 0) bad(`${item.name} 的实盘数不对`);
      const delta = Math.round((q - item.qty) * 1000) / 1000;
      run(`INSERT INTO stock_moves (item_id, created_at, type, qty, cost_cents, note, operator_name) VALUES (?,?,'count',?,NULL,?,?)`,
        item.id, now(), delta, note || '盘点', user.name);
      out.push({ name: item.name, system: item.qty, actual: q, diff: delta });
    }
    log(user, '盘点', { n: out.length, diffs: out.filter((x) => x.diff).map((x) => `${x.name}${x.diff > 0 ? '+' : ''}${x.diff}`).join(' ') });
    return { ok: true, rows: out };
  });
});

// 生产计划：预测某天每种商品该做多少（初版算法）
function forecast(date) {
  const dow = new Date(date + 'T12:00:00').getDay();
  const products = all(`SELECT id, name, category FROM products WHERE active=1 ORDER BY sort, id`);
  const from28 = addDays(date, -28); const from7 = addDays(date, -7); const yest = addDays(date, -1);
  const sales = all(`SELECT i.product_id, substr(o.created_at,1,10) AS day, SUM(i.qty) AS qty FROM order_items i JOIN orders o ON o.id=i.order_id
    WHERE o.status='done' AND i.product_id IS NOT NULL AND substr(o.created_at,1,10) BETWEEN ? AND ? GROUP BY i.product_id, day`, from28, yest);
  const prod = all(`SELECT product_id, date, type, SUM(qty) AS qty FROM production_logs WHERE date BETWEEN ? AND ? GROUP BY product_id, date, type`, from7, yest);
  const saved = Object.fromEntries(all(`SELECT product_id, qty FROM plans WHERE date=?`, date).map((r) => [r.product_id, r.qty]));
  const openDays7 = new Set(all(`SELECT DISTINCT substr(created_at,1,10) AS d FROM orders WHERE status='done' AND substr(created_at,1,10) BETWEEN ? AND ?`, from7, yest).map((r) => r.d));
  const sameDowDays = new Set(all(`SELECT DISTINCT substr(created_at,1,10) AS d FROM orders WHERE status='done' AND substr(created_at,1,10) BETWEEN ? AND ?`, from28, yest)
    .map((r) => r.d).filter((d) => new Date(d + 'T12:00:00').getDay() === dow));
  return products.map((p) => {
    const ps = sales.filter((s) => s.product_id === p.id);
    const sum7 = ps.filter((s) => openDays7.has(s.day)).reduce((a, s) => a + s.qty, 0);
    const sumDow = ps.filter((s) => sameDowDays.has(s.day)).reduce((a, s) => a + s.qty, 0);
    const avg7 = openDays7.size ? sum7 / openDays7.size : 0;
    const avgDow = sameDowDays.size ? sumDow / sameDowDays.size : null;
    const base = avgDow === null ? avg7 : avgDow * 0.6 + avg7 * 0.4;
    const pp = prod.filter((x) => x.product_id === p.id);
    const leftover = pp.filter((x) => x.type === 'leftover').reduce((a, x) => a + x.qty, 0);
    const loss = pp.filter((x) => x.type === 'loss').reduce((a, x) => a + x.qty, 0);
    const output = pp.filter((x) => x.type === 'output').reduce((a, x) => a + x.qty, 0);
    // 前 7 天剩余+报损占产出比例高，说明做多了，建议少放余量
    const wasteRate = output ? (leftover + loss) / output : 0;
    const buffer = wasteRate > 0.15 ? 1.0 : wasteRate > 0.05 ? 1.05 : 1.1;
    const suggest = Math.ceil(base * buffer);
    return {
      product_id: p.id, name: p.name, category: p.category,
      avg_same_weekday: avgDow === null ? null : Math.round(avgDow * 10) / 10,
      avg_7d: Math.round(avg7 * 10) / 10, waste_rate: Math.round(wasteRate * 100),
      suggest, planned: saved[p.id] ?? null,
    };
  });
}
route('GET', '/api/plan', KITCHEN, ({ query }) => {
  const date = isDate(query.date) ? query.date : addDays(today(), 1);
  return { date, rows: forecast(date) };
});
route('POST', '/api/plan', OWNER, ({ user, body }) => {
  const date = isDate(body.date) ? body.date : bad('日期不对');
  const rows = Array.isArray(body.rows) ? body.rows : [];
  tx(() => {
    run(`DELETE FROM plans WHERE date=?`, date);
    for (const r of rows) if (isInt(r.product_id) && isInt(r.qty) && r.qty > 0) run(`INSERT INTO plans (date, product_id, qty) VALUES (?,?,?)`, date, r.product_id, r.qty);
  });
  log(user, '保存生产计划', { date, n: rows.length });
  return { ok: true };
});

// ---------- 小票打印 ----------
function printCfg() {
  const paper = getSetting('print_paper', '58');
  return {
    mode: getSetting('print_mode', 'none'),
    host: getSetting('print_host', ''),
    port: Number(getSetting('print_port', '9100')) || 9100,
    name: getSetting('print_name', ''),
    paper,
    cols: Number(getSetting('print_cols', '')) || (paper === '80' ? 48 : 32),
    auto: getSetting('print_auto', 'off'),
    footer: getSetting('print_footer', '谢谢惠顾，欢迎再来'),
  };
}
function lanIps() {
  return Object.values(os.networkInterfaces()).flat().filter((i) => i && i.family === 'IPv4' && !i.internal).map((i) => i.address);
}
// 顾客查询页地址：优先用店主填写的；否则用平板/手机访问时的地址；在电脑本机打开时猜一个局域网地址
function queryUrl(req) {
  const set = getSetting('query_url', '');
  if (set) return set;
  const host = req && req.headers.host;
  if (host && !/^(localhost|127\.|\[::1\])/.test(host)) return `http://${host}/q`;
  const ips = lanIps();
  const ip = ips.find((x) => /^192\.168\./.test(x)) || ips.find((x) => /^10\./.test(x)) || ips.find((x) => /^172\.(1[6-9]|2\d|3[01])\./.test(x)) || ips[0];
  return `http://${ip || 'localhost'}:${PORT}/q`;
}
const money = (c) => (c / 100).toFixed(2);
const faceText = (c) => (c % 100 ? (c / 100).toFixed(1) : String(c / 100));
const qtyAmt = (q, a) => printer.padL(q, 5) + printer.padL(a, 10);
const TX_LABEL = { deposit: '存入', spend: '消费', refund: '撤单退回', adjust: '调整', close: '销户退还' };
function receiptHead(title) {
  return [{ t: getSetting('shop_name', DEFAULT_SHOP), a: 'c', b: true, big: true }, { t: title, a: 'c' }, { hr: true }];
}
function receiptFoot() {
  const f = printCfg().footer;
  return f ? [{ hr: true }, { t: f, a: 'c' }] : [];
}
function orderReceipt(id) {
  const o = get(`SELECT * FROM orders WHERE id=?`, id);
  if (!o) bad('订单不存在');
  const items = all(`SELECT * FROM order_items WHERE order_id=? ORDER BY id`, id);
  const pays = all(`SELECT * FROM payments WHERE order_id=? ORDER BY id`, id);
  const L = receiptHead('销售小票');
  L.push({ l: `单号：${o.id}`, r: `收银：${o.cashier_name || ''}` }, { l: `时间：${o.created_at.slice(0, 16)}` }, { hr: true });
  L.push({ l: '商品', r: qtyAmt('数量', '金额') });
  for (const i of items) L.push({ l: i.name, r: qtyAmt('×' + i.qty, money(i.qty * i.price_cents)) });
  L.push({ hr: true });
  if (o.discount_cents > 0) L.push({ l: '小计', r: money(o.subtotal_cents) }, { l: `折扣（${zhe(o.discount_pct)}）`, r: '-' + money(o.discount_cents) });
  L.push({ l: '合计', r: '￥' + money(o.total_cents), b: true });
  for (const p of pays) {
    if (p.method === 'ticket') {
      let t = [];
      try { t = JSON.parse(p.detail || '[]'); } catch { /* 旧数据 */ }
      L.push({ l: `餐票 ${t.map((k) => `${faceText(k.face_cents)}元×${k.count}`).join(' ')}`, r: money(p.amount_cents) });
    } else if (p.detail === '餐票找零') {
      L.push({ l: '餐票找零', r: money(p.amount_cents) });
    } else {
      L.push({ l: METHOD[p.method], r: money(p.amount_cents) });
    }
    if (p.method === 'stored' && p.account_id) {
      const a = get(`SELECT name FROM accounts WHERE id=?`, p.account_id);
      const bal = get(`SELECT COALESCE(SUM(amount_cents),0) AS b FROM account_tx WHERE account_id=? AND id <= COALESCE((SELECT MAX(id) FROM account_tx WHERE account_id=? AND order_id=? AND type='spend'), 0)`,
        p.account_id, p.account_id, o.id).b;
      L.push({ l: `${maskName(a ? a.name : '')} 存票余额`, r: money(bal) });
    }
  }
  if (o.overpay_cents > 0) L.push({ l: '票面多出（不找零）', r: money(o.overpay_cents) });
  if (o.status === 'void') L.push({ hr: true }, { t: '*** 此单已撤销 ***', a: 'c', b: true });
  return [...L, ...receiptFoot()];
}
function accountCodeReceipt(id, req) {
  const a = get(`SELECT * FROM accounts WHERE id=?`, id);
  if (!a) bad('账户不存在');
  return [...receiptHead('存票凭条'),
    { l: '姓名', r: maskName(a.name) },
    { t: '查询码', a: 'c' }, { t: a.code.split('').join(' '), a: 'c', b: true, big: true },
    { hr: true }, { l: '当前余额', r: '￥' + money(balanceOf(a.id)), b: true }, { l: '打印时间', r: now().slice(0, 16) },
    { hr: true }, { t: '手机连上店里WiFi后打开：' }, { t: queryUrl(req) }, { t: '输入查询码就能查余额。' }, { t: '查询码请自己保管，不要告诉别人。' },
    ...receiptFoot()];
}
function accountBalanceReceipt(id) {
  const a = get(`SELECT * FROM accounts WHERE id=?`, id);
  if (!a) bad('账户不存在');
  const txs = all(`SELECT * FROM account_tx WHERE account_id=? ORDER BY id DESC LIMIT 6`, id);
  return [...receiptHead('存票余额'),
    { l: '姓名', r: maskName(a.name) }, { l: '查询码', r: '***' + a.code.slice(3) },
    { l: '当前余额', r: '￥' + money(balanceOf(a.id)), b: true }, { hr: true }, { t: '最近记录' },
    ...txs.map((t) => ({ l: `${t.created_at.slice(5, 16)} ${TX_LABEL[t.type] || t.type}`, r: (t.amount_cents > 0 ? '+' : '') + money(t.amount_cents) })),
    { hr: true }, { l: '打印时间', r: now().slice(0, 16) }, ...receiptFoot()];
}
function dayCloseReceipt(date) {
  const s = daySystem(date);
  const sv = get(`SELECT * FROM day_closes WHERE date=?`, date);
  const L = receiptHead(`日结单 ${date}`);
  for (const k of ['cash', 'pos', 'ticket', 'stored']) L.push({ l: `${METHOD[k]}（${s.orders_by_method[k]}单）`, r: money(s.amounts[k]) });
  if (s.overpay_cents) L.push({ l: '  其中餐票溢收', r: money(s.overpay_cents) });
  if (s.discount_cents) L.push({ l: '打折优惠', r: money(s.discount_cents) });
  L.push({ l: '四种来源合计', r: money(s.paid_cents), b: true }, { l: `商品金额（${s.orders}单）`, r: money(s.total_cents) });
  if (s.voided) L.push({ l: '撤销', r: `${s.voided}单` });
  L.push({ l: '当天存票存入', r: money(s.deposits_cents) }, { hr: true });
  if (sv) {
    L.push({ l: '实点现金', r: money(sv.cash_actual_cents) }, { l: '  现金差额', r: money(sv.cash_actual_cents - sv.cash_system_cents) });
    L.push({ l: '收银机小票', r: money(sv.pos_actual_cents) }, { l: '  收银机差额', r: money(sv.pos_actual_cents - sv.pos_system_cents) });
    let tk = null; try { tk = JSON.parse(sv.tickets_json || 'null'); } catch { /* 旧数据 */ }
    if (tk) {
      L.push({ t: '店内余票（实点/应有）' });
      for (const r of tk.rows) if (r.actual !== null || r.system) L.push({ l: `  ${faceText(r.face_cents)}元票`, r: `${r.actual ?? '-'}/${r.system}张` });
    }
    if (sv.note) L.push({ t: `备注：${sv.note}` });
    L.push({ l: '日结人', r: sv.closed_by || '' }, { l: '日结时间', r: (sv.closed_at || '').slice(0, 16) });
  } else {
    L.push({ t: '（这天还没有保存日结）', a: 'c' });
  }
  L.push({ l: '打印时间', r: now().slice(0, 16) });
  return L;
}
function testReceipt(cols) {
  return [...receiptHead('打印测试'),
    { t: '能看到这几行中文，' }, { t: '说明打印机连接正常。' },
    { l: '每行字数', r: String(cols) },
    { t: '下面这行数字应该刚好排满一行：' }, { t: '1234567890'.repeat(7).slice(0, cols) },
    { l: '商品', r: qtyAmt('数量', '金额') }, { l: '肉松小贝', r: qtyAmt('×2', '12.00') },
    { l: '合计', r: '￥12.00', b: true }, ...receiptFoot()];
}
function buildReceipt(q, req) {
  const id = Number(q.id);
  switch (q.type) {
    case 'order': return orderReceipt(id);
    case 'account_code': return accountCodeReceipt(id, req);
    case 'account_balance': return accountBalanceReceipt(id);
    case 'dayclose': return dayCloseReceipt(isDate(q.date) ? q.date : today());
    case 'test': return testReceipt(printCfg().cols);
    default: return bad('小票类型不对');
  }
}
route('GET', '/api/receipt', STAFF, ({ query, req }) => {
  const c = printCfg();
  return { paper: c.paper, cols: c.cols, lines: buildReceipt(query, req) };
});
route('POST', '/api/print', STAFF, async ({ body, req, user }) => {
  const c = printCfg();
  if (c.mode === 'none') bad('还没有设置小票打印机，请店主到"设置"里设置');
  if (c.mode === 'browser') bad('现在是浏览器打印模式，请在页面上打印');
  if (body.type === 'test' && user.role !== 'owner') throw new HttpError(403, '没有权限');
  const lines = buildReceipt(body, req);
  try { await printer.print(lines, c); } catch (e) { bad(e.message); }
  return { ok: true };
});

// 日志与备份
route('GET', '/api/logs', OWNER, () => all(`SELECT * FROM logs ORDER BY id DESC LIMIT 300`));
function backup() {
  const name = `shop-${now().replace(/[: ]/g, '-')}.db`;
  db.exec(`VACUUM INTO '${path.join(BACKUPS, name).replace(/'/g, "''")}'`);
  const files = fs.readdirSync(BACKUPS).filter((f) => f.endsWith('.db')).sort();
  while (files.length > 60) fs.unlinkSync(path.join(BACKUPS, files.shift()));
  return name;
}
route('POST', '/api/backup', OWNER, ({ user }) => { const n = backup(); log(user, '手动备份', n); return { file: n, dir: BACKUPS }; });

// ---------- HTTP ----------
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.json': 'application/json', '.ico': 'image/x-icon' };
function serveFile(res, file) {
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('找不到页面'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': file.startsWith(PHOTOS) ? 'private, max-age=86400' : 'no-cache' });
    fs.createReadStream(file).pipe(res);
  });
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    req.on('data', (c) => { size += c.length; if (size > 12 * 1024 * 1024) { reject(new HttpError(413, '提交内容太大')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => {
      if (!size) return resolve({});
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { reject(new HttpError(400, '数据格式不对')); }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const p = decodeURIComponent(url.pathname);
  try {
    if (p.startsWith('/api/')) {
      for (const r of routes) {
        if (r.method !== req.method) continue;
        const m = r.re.exec(p);
        if (!m) continue;
        const user = currentUser(req);
        if (r.roles) {
          if (!user) throw new HttpError(401, '请先登录');
          if (!r.roles.includes(user.role)) throw new HttpError(403, '没有权限');
        }
        if (req.method === 'POST') {
          // 防止其他网站伪造请求
          const origin = req.headers.origin;
          if (origin && new URL(origin).host !== req.headers.host) throw new HttpError(403, '来源不对');
        }
        const body = req.method === 'POST' ? await readBody(req) : {};
        const params = Object.fromEntries(r.keys.map((k, i) => [k, m[i + 1]]));
        const out = await r.handler({ req, res, body, user, params, query: Object.fromEntries(url.searchParams) });
        if (out !== undefined) { res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(out)); }
        return;
      }
      throw new HttpError(404, '接口不存在');
    }
    if (p.startsWith('/photos/')) {
      const name = path.basename(p);
      if (!/^[\w.-]+$/.test(name)) throw new HttpError(404, '');
      return serveFile(res, path.join(PHOTOS, name));
    }
    if (p === '/' ) return serveFile(res, path.join(PUBLIC, 'index.html'));
    if (p === '/q' || p === '/q/') return serveFile(res, path.join(PUBLIC, 'q.html'));
    const f = path.normalize(path.join(PUBLIC, p));
    if (!f.startsWith(PUBLIC)) throw new HttpError(404, '');
    return serveFile(res, f);
  } catch (e) {
    const status = e.status || 500;
    if (status === 500) console.error(e);
    if (!res.headersSent) res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: status === 500 ? '系统出错了：' + e.message : e.message }));
  }
});

// 双击"启动收银系统"时（启动脚本带 --open）自动用默认浏览器打开收银页面
const AUTO_OPEN = process.argv.includes('--open');
function openBrowser(url) {
  try {
    const { spawn } = require('node:child_process');
    const [cmd, args] = process.platform === 'win32' ? ['cmd.exe', ['/c', 'start', '', url]]
      : process.platform === 'darwin' ? ['open', [url]] : ['xdg-open', [url]];
    const child = spawn(cmd, args, { detached: true, stdio: 'ignore', windowsHide: true });
    child.on('error', () => {});
    child.unref();
  } catch { /* 打不开就算了，窗口里有地址 */ }
}
const LOCAL_URL = `http://localhost:${PORT}`;
server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    if (AUTO_OPEN) {
      openBrowser(LOCAL_URL);
      console.log(`\n  收银系统已经在运行了，已帮你打开收银页面（${LOCAL_URL}）。\n  这个窗口可以关掉。\n`);
      process.exit(0);
    }
    console.error(`\n  端口 ${PORT} 已被占用：收银系统可能已经在运行了（看看有没有另一个黑色窗口）。\n`);
  } else {
    console.error(e);
  }
  process.exit(1);
});
server.listen(PORT, () => {
  try { backup(); } catch (e) { console.error('备份失败', e.message); }
  setInterval(() => { try { backup(); } catch (e) { console.error('备份失败', e.message); } }, 6 * 60 * 60 * 1000);
  console.log('');
  console.log(`  ${getSetting('shop_name', DEFAULT_SHOP)}收银系统已启动（版本 ${VERSION}）`);
  console.log('');
  if (AUTO_OPEN) {
    openBrowser(LOCAL_URL);
    console.log(`  收银页面已经在浏览器里打开了。没打开的话，在浏览器地址栏输入 ${LOCAL_URL}`);
  } else {
    console.log(`  本机打开：      ${LOCAL_URL}`);
  }
  for (const ip of lanIps()) {
    console.log(`  平板/手机打开： http://${ip}:${PORT}`);
    console.log(`  顾客查询页：    http://${ip}:${PORT}/q`);
  }
  console.log(`  数据保存在：    ${DATA}`);
  console.log('');
  console.log('  收银期间不要关这个窗口，关掉收银系统就停了。');
  console.log('');
});
