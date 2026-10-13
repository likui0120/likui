-- 桃喜团子收银系统 数据表（金额单位：分）
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL, pin_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '其他', price_cents INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, cashier_id INTEGER, cashier_name TEXT, total_cents INTEGER NOT NULL,
  overpay_cents INTEGER NOT NULL DEFAULT 0, -- 餐票票面超过应付、不找零的部分
  status TEXT NOT NULL DEFAULT 'done', photo TEXT, note TEXT, void_reason TEXT, void_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_time ON orders(created_at);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), product_id INTEGER, name TEXT NOT NULL,
  qty INTEGER NOT NULL, price_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
-- method: cash 现金 / pos 学校收银机 / ticket 临时用票 / stored 存票余额
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), method TEXT NOT NULL, amount_cents INTEGER NOT NULL,
  account_id INTEGER, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_pay_order ON payments(order_id);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS retired_codes (code TEXT PRIMARY KEY);
-- type: deposit 存入 / spend 消费 / refund 撤单退回 / adjust 调整 / close 销户退还
CREATE TABLE IF NOT EXISTS account_tx (
  id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), created_at TEXT NOT NULL, type TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, order_id INTEGER, operator_id INTEGER, operator_name TEXT, note TEXT, photo TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_account ON account_tx(account_id);
CREATE TABLE IF NOT EXISTS redemptions (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, face_total_cents INTEGER NOT NULL, received_cents INTEGER NOT NULL, note TEXT, operator_name TEXT
);
-- source: temp 临时用票 / stored 存票
CREATE TABLE IF NOT EXISTS ticket_batches (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, face_cents INTEGER NOT NULL, count INTEGER NOT NULL, expire_date TEXT,
  source TEXT NOT NULL, ref_type TEXT, ref_id INTEGER, redemption_id INTEGER REFERENCES redemptions(id)
);
CREATE TABLE IF NOT EXISTS day_closes (
  date TEXT PRIMARY KEY, cash_system_cents INTEGER, cash_actual_cents INTEGER, pos_system_cents INTEGER, pos_actual_cents INTEGER,
  ticket_cents INTEGER, stored_cents INTEGER, note TEXT, closed_by TEXT, closed_at TEXT
);
-- type: output 出炉 / loss 报损 / leftover 收档剩余
CREATE TABLE IF NOT EXISTS production_logs (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, created_at TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
  type TEXT NOT NULL, qty INTEGER NOT NULL, note TEXT, operator_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_prod_date ON production_logs(date);
CREATE TABLE IF NOT EXISTS plans (date TEXT NOT NULL, product_id INTEGER NOT NULL, qty INTEGER NOT NULL, PRIMARY KEY (date, product_id));
-- kind: 原料 / 包材 / 成品
CREATE TABLE IF NOT EXISTS stock_items (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, unit TEXT NOT NULL, cost_cents INTEGER NOT NULL DEFAULT 0,
  low_qty REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
);
-- type: in 入库 / use 领用 / loss 损耗 / count 盘点调整；qty 为带符号变化量
CREATE TABLE IF NOT EXISTS stock_moves (
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES stock_items(id), created_at TEXT NOT NULL, type TEXT NOT NULL,
  qty REAL NOT NULL, cost_cents INTEGER, note TEXT, operator_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_moves_item ON stock_moves(item_id);
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_id INTEGER, user_name TEXT, action TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL);
-- 产品配方（BOM）：每做 1 个商品要用多少原料/包材（按库存品的主单位）
CREATE TABLE IF NOT EXISTS bom (
  product_id INTEGER NOT NULL REFERENCES products(id), item_id INTEGER NOT NULL REFERENCES stock_items(id), qty REAL NOT NULL,
  PRIMARY KEY (product_id, item_id)
);
-- 成品盘点调整：理论库存 = 出炉 − 售出 − 报损 + 调整
CREATE TABLE IF NOT EXISTS product_adj (
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), created_at TEXT NOT NULL, qty INTEGER NOT NULL, note TEXT, operator_name TEXT
);
