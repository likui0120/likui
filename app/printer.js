'use strict';
// 小票打印：中文 GBK 编码、ESC/POS 指令、发送到打印机
// 支持：网络打印机（网口/WiFi，端口 9100）、连在本机的 USB 打印机（Windows 共享打印机 / Mac 打印机名）

const net = require('node:net');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');

// 用 Node 自带的 GBK 解码器反向生成编码表（只在第一次打印时生成）
let GBK = null;
function gbkMap() {
  if (GBK) return GBK;
  GBK = new Map();
  const dec = new TextDecoder('gbk', { fatal: true });
  for (let a = 0x81; a <= 0xfe; a++) {
    for (let b = 0x40; b <= 0xfe; b++) {
      if (b === 0x7f) continue;
      try {
        const s = dec.decode(Uint8Array.of(a, b));
        if (s.length === 1 && !GBK.has(s)) GBK.set(s, (a << 8) | b);
      } catch { /* 不是有效的 GBK 字 */ }
    }
  }
  return GBK;
}

const SUB = { '¥': '￥', ' ': ' ', '\t': ' ' };
const chars = (s) => [...String(s ?? '')].map((c) => SUB[c] || c);
// 打印机上英文数字占 1 格，中文和全角符号占 2 格；打不出的字按 "?" 算 1 格
const charW = (c) => (c.codePointAt(0) < 0x80 ? 1 : gbkMap().has(c) ? 2 : 1);
const width = (s) => chars(s).reduce((n, c) => n + charW(c), 0);
const padL = (s, w) => ' '.repeat(Math.max(0, w - width(s))) + s;

function encode(s) {
  const m = gbkMap();
  const out = [];
  for (const c of chars(s)) {
    const code = c.codePointAt(0);
    if (code < 0x80) out.push(code);
    else if (m.has(c)) { const v = m.get(c); out.push(v >> 8, v & 0xff); }
    else out.push(0x3f);
  }
  return Buffer.from(out);
}

// 这些标点不放在行首，换行时带上前一个字一起换
const NO_START = new Set([...'，。、；：！？）》」』”’,.;:!?)']);
function wrap(s, w) {
  const lines = [];
  let cur = []; let cw = 0;
  for (const c of chars(s)) {
    const x = charW(c);
    if (cw + x > w && cur.length) {
      const carry = NO_START.has(c) && cur.length > 1 ? [cur.pop()] : [];
      lines.push(cur.join(''));
      cur = carry; cw = carry.reduce((n, k) => n + charW(k), 0);
    }
    cur.push(c); cw += x;
  }
  if (cur.length || !lines.length) lines.push(cur.join(''));
  return lines;
}

// 小票行格式：{t, a:'c'|'r', b, big} 文本 / {l, r, b, big} 左右两端 / {hr:true} 分隔线
// 排成每行固定字数的文本
function layout(lines, cols) {
  const rows = [];
  for (const ln of lines) {
    if (ln.hr) { rows.push({ text: '-'.repeat(cols) }); continue; }
    const w = ln.big ? Math.floor(cols / 2) : cols;
    if (ln.l !== undefined) {
      const l = String(ln.l ?? ''); const r = String(ln.r ?? '');
      if (!r) {
        for (const t of wrap(l, w)) rows.push({ text: t, bold: ln.b, big: ln.big });
      } else if (width(l) + width(r) + 1 <= w) {
        rows.push({ text: l + ' '.repeat(w - width(l) - width(r)) + r, bold: ln.b, big: ln.big });
      } else {
        for (const t of wrap(l, w)) rows.push({ text: t, bold: ln.b, big: ln.big });
        if (r) rows.push({ text: padL(r, w), bold: ln.b, big: ln.big });
      }
      continue;
    }
    for (const t of wrap(ln.t ?? '', w)) rows.push({ text: t, align: ln.a, bold: ln.b, big: ln.big });
  }
  return rows;
}

// 纯文本预览（测试和排查用）
function preview(lines, cols) {
  return layout(lines, cols).map((r) => {
    const w = r.big ? Math.floor(cols / 2) : cols;
    if (r.align === 'c') return ' '.repeat(Math.max(0, Math.floor((w - width(r.text)) / 2))) + r.text;
    if (r.align === 'r') return padL(r.text, w);
    return r.text;
  }).join('\n');
}

const ESC = 0x1b; const GS = 0x1d; const FS = 0x1c;
function escpos(lines, cols) {
  const parts = [Buffer.from([ESC, 0x40, FS, 0x26])]; // 初始化，进入中文模式
  for (const r of layout(lines, cols)) {
    parts.push(Buffer.from([
      ESC, 0x61, r.align === 'c' ? 1 : r.align === 'r' ? 2 : 0, // 对齐
      ESC, 0x45, r.bold ? 1 : 0, // 加粗
      GS, 0x21, r.big ? 0x11 : 0x00, // 倍宽倍高
    ]));
    parts.push(encode(r.text), Buffer.from([0x0a]));
  }
  parts.push(Buffer.from([ESC, 0x61, 0, ESC, 0x45, 0, GS, 0x21, 0, ESC, 0x64, 4, GS, 0x56, 0x42, 0x00])); // 走纸、切纸（没有切刀的打印机会忽略）
  return Buffer.concat(parts);
}

function sendNetwork(buf, host, port) {
  return new Promise((resolve, reject) => {
    let done = false;
    const sock = net.connect({ host, port });
    const finish = (err) => {
      if (done) return;
      done = true;
      if (err) { sock.destroy(); reject(err); } else { resolve(); setTimeout(() => sock.destroy(), 3000); }
    };
    sock.setTimeout(5000, () => finish(new Error(`连接打印机超时（${host}:${port}），请检查打印机电源、网线和 IP 地址`)));
    sock.on('error', (e) => finish(new Error(`连不上打印机（${host}:${port}）：${e.code || e.message}，请检查打印机电源、网线和 IP 地址`)));
    sock.on('connect', () => sock.end(buf));
    sock.on('finish', () => finish());
  });
}

const SHARE_RE = /^[^"&|<>^%\\/:*?]{1,64}$/;
const UNC_RE = /^\\\\[^"&|<>^%\\/:*?]{1,64}\\[^"&|<>^%\\/:*?]{1,64}$/;
function validLocalName(name) { return SHARE_RE.test(name) || UNC_RE.test(name); }

function sendLocal(buf, name) {
  if (!validLocalName(name)) return Promise.reject(new Error('打印机名称不对，只能用字母、数字、中文、横线等，不能有引号和特殊符号'));
  const tmp = path.join(os.tmpdir(), `taoxi-print-${process.pid}-${Date.now()}.bin`);
  fs.writeFileSync(tmp, buf);
  const cleanup = () => fs.unlink(tmp, () => {});
  return new Promise((resolve, reject) => {
    if (process.platform === 'win32') {
      const unc = name.startsWith('\\\\') ? name : `\\\\localhost\\${name}`;
      // 经典做法：把原始数据 copy /b 到共享打印机
      execFile('cmd.exe', ['/d', '/s', '/c', `"chcp 65001 >nul & copy /b "${tmp}" "${unc}""`],
        { windowsVerbatimArguments: true, windowsHide: true, timeout: 20000 }, (err, stdout, stderr) => {
          const out = `${stdout || ''}${stderr || ''}`.trim();
          if (!err && !/(^|\s)0\s*(个文件|file)/.test(out)) { cleanup(); return resolve(); }
          // 再试一次直接写入
          fs.writeFile(unc, buf, (e2) => {
            cleanup();
            if (!e2) return resolve();
            reject(new Error(`打印失败：${out || (err && err.message) || e2.message}。请确认打印机已开机，并且在 Windows 里共享了，共享名是 ${name}`));
          });
        });
    } else {
      execFile('lp', ['-d', name, '-o', 'raw', tmp], { timeout: 20000 }, (err, stdout, stderr) => {
        cleanup();
        if (err) return reject(new Error(`打印失败：${(stderr || err.message).trim()}。请确认打印机名称是 ${name}`));
        resolve();
      });
    }
  });
}

async function print(lines, cfg) {
  const buf = escpos(lines, cfg.cols);
  if (cfg.mode === 'network') {
    if (!cfg.host) throw new Error('还没有填写打印机 IP 地址');
    return sendNetwork(buf, cfg.host, cfg.port || 9100);
  }
  if (cfg.mode === 'local') {
    if (!cfg.name) throw new Error('还没有填写打印机共享名');
    return sendLocal(buf, cfg.name);
  }
  throw new Error('当前设置不是直连打印机');
}

module.exports = { print, escpos, preview, layout, width, padL, encode, validLocalName };
