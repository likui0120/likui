'use strict';
// 电子秤：通过串口（RS232 或 USB 转串口）读重量。
// 大多数带串口的计重秤、计价秤都能设成"连续发送"，每秒发好几行类似 "ST,GS,+  0.326kg" 的数据；
// 这里不认具体型号，只从每一帧里找出数字和单位，再判断稳不稳。需要先发指令才回重量的秤，填"查询指令"。
// Windows 用系统自带的 PowerShell(.NET SerialPort) 读串口，不用装驱动以外的东西。
const { spawn, execFile } = require('node:child_process');
const fs = require('node:fs');

let cfg = { mode: 'off' };
let child = null, stream = null, pollTimer = null, simTimer = null;
let buf = '';
let last = null;            // { weight_g, stable, at, raw }
let recent = [];            // 最近几帧的读数，用来判断稳定
let error = '';

// 从一帧文字里取重量。返回 { g, stable } 或 null
function parseFrame(s, defUnit) {
  const t = s.replace(/[\x00-\x1f]/g, ' ').trim();
  if (!t) return null;
  const m = /([-+])?\s*(\d+(?:\.\d+)?)\s*(kg|g|lb|斤)?/i.exec(t.replace(/(ST|US|GS|NT|OL|MO)\s*,?/gi, ' '));
  if (!m) return null;
  let v = Number(m[2]);
  if (!Number.isFinite(v)) return null;
  if (m[1] === '-') v = -v;
  const unit = (m[3] || defUnit || 'kg').toLowerCase();
  const g = unit === 'g' ? v : unit === 'lb' ? v * 453.592 : unit === '斤' ? v * 500 : v * 1000;
  let stable = null;
  if (/\bUS\b|\bMO\b|unstable/i.test(t)) stable = false;
  else if (/\bST\b|stable/i.test(t)) stable = true;
  if (/\bOL\b/i.test(t)) return { g: NaN, stable: false, over: true };
  return { g: Math.round(g), stable };
}

function onFrame(frame) {
  const r = parseFrame(frame, cfg.unit);
  if (!r) return;
  if (r.over) { last = { weight_g: null, stable: false, at: Date.now(), raw: frame.trim(), over: true }; return; }
  const t = Date.now();
  recent.push({ g: r.g, at: t });
  recent = recent.filter((x) => t - x.at < 1500).slice(-6);
  // 秤自己报了稳定/不稳就听秤的；没报的话，连续 3 帧读数一样算稳定
  const same = recent.length >= 3 && recent.slice(-3).every((x) => x.g === r.g);
  last = { weight_g: r.g, stable: r.stable === null ? same : r.stable, at: t, raw: frame.trim().slice(0, 40) };
  error = '';
}

function onData(chunk) {
  buf += chunk;
  // 常见帧结尾：回车换行、STX/ETX、等号（有的秤用 "=" 分隔并倒序发送，这里不处理倒序）
  const parts = buf.split(/[\r\n\x02\x03]+/);
  buf = parts.pop();
  if (buf.length > 200) buf = buf.slice(-200);
  for (const p of parts) onFrame(p);
}

function hexBytes(s) {
  const h = String(s || '').replace(/[^0-9a-f]/gi, '');
  return h.length >= 2 && h.length % 2 === 0 ? Buffer.from(h, 'hex') : null;
}

function stop() {
  if (pollTimer) clearInterval(pollTimer);
  if (simTimer) clearInterval(simTimer);
  pollTimer = simTimer = null;
  if (child) { try { child.kill(); } catch {} child = null; }
  if (stream) { try { stream.destroy(); } catch {} stream = null; }
  buf = ''; recent = []; last = null; error = '';
}

const PS_SCRIPT = `
$ErrorActionPreference = 'Stop'
$p = New-Object System.IO.Ports.SerialPort $env:SCALE_PORT, ([int]$env:SCALE_BAUD), ([System.IO.Ports.Parity]$env:SCALE_PARITY), ([int]$env:SCALE_BITS), ([System.IO.Ports.StopBits]$env:SCALE_STOP)
$p.ReadTimeout = 500
$p.DtrEnable = $true
$p.RtsEnable = $true
try { $p.Open() } catch { [Console]::Error.WriteLine('OPENFAIL ' + $_.Exception.Message); exit 2 }
$cmd = $null
if ($env:SCALE_CMD) { $cmd = [byte[]]@(($env:SCALE_CMD -split '(..)' | Where-Object { $_ }) | ForEach-Object { [Convert]::ToByte($_, 16) }) }
$out = [Console]::OpenStandardOutput()
$last = [DateTime]::Now
while ($true) {
  if ($cmd -and ([DateTime]::Now - $last).TotalMilliseconds -ge 300) { $p.Write($cmd, 0, $cmd.Length); $last = [DateTime]::Now }
  $n = $p.BytesToRead
  if ($n -gt 0) { $b = New-Object byte[] $n; $r = $p.Read($b, 0, $n); $out.Write($b, 0, $r); $out.Flush() } else { Start-Sleep -Milliseconds 30 }
}
`;

function startWindows() {
  const env = {
    ...process.env, SCALE_PORT: cfg.port, SCALE_BAUD: String(cfg.baud || 9600),
    SCALE_PARITY: { n: 'None', e: 'Even', o: 'Odd' }[cfg.parity] || 'None', SCALE_BITS: String(cfg.bits || 8),
    SCALE_STOP: cfg.stop === '2' ? 'Two' : 'One', SCALE_CMD: (hexBytes(cfg.cmd) || Buffer.alloc(0)).toString('hex'),
  };
  const encoded = Buffer.from(PS_SCRIPT, 'utf16le').toString('base64');
  child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded], { env, windowsHide: true });
  child.stdout.setEncoding('latin1');
  child.stdout.on('data', onData);
  let err = '';
  child.stderr.on('data', (d) => { err += d; });
  const me = child;
  child.on('exit', () => {
    if (child !== me) return;
    child = null;
    error = /OPENFAIL/.test(err) ? `打不开 ${cfg.port}：${err.replace(/.*OPENFAIL\s*/s, '').trim().slice(0, 120)}（看看端口选对没有、是不是被别的软件占用）` : `读秤程序停了${err ? '：' + err.trim().slice(0, 120) : ''}`;
    setTimeout(() => { if (!child && cfg.mode === 'serial') startWindows(); }, 3000); // 拔了线再插上能自己恢复
  });
}

// Linux / Mac：/dev/ttyUSB0 之类，用 stty 设波特率后直接读
function startUnix() {
  const args = [process.platform === 'darwin' ? '-f' : '-F', cfg.port, String(cfg.baud || 9600), 'raw', '-echo', cfg.bits === '7' ? 'cs7' : 'cs8',
    cfg.parity === 'e' ? 'parenb' : cfg.parity === 'o' ? 'parodd' : '-parenb', cfg.stop === '2' ? 'cstopb' : '-cstopb'];
  if (cfg.parity === 'o') args.splice(args.indexOf('parodd'), 0, 'parenb');
  execFile('stty', args, () => {
    if (cfg.mode !== 'serial') return;
    let fd;
    try { fd = fs.openSync(cfg.port, fs.constants.O_RDWR | fs.constants.O_NOCTTY); } catch (e) { error = `打不开 ${cfg.port}：${e.message}`; return; }
    stream = fs.createReadStream(null, { fd, encoding: 'latin1' });
    stream.on('data', onData);
    stream.on('error', (e) => { error = `读秤出错：${e.message}`; });
    const cmd = hexBytes(cfg.cmd);
    if (cmd) pollTimer = setInterval(() => { try { fs.writeSync(fd, cmd); } catch {} }, 300);
  });
}

// 模拟秤：没有秤的时候试用，读数在 0 和几百克之间变化
function startSim() {
  let target = 0, cur = 0, n = 0;
  simTimer = setInterval(() => {
    if (++n % 25 === 0) target = target ? 0 : Math.round(150 + Math.random() * 600);
    cur = Math.abs(cur - target) < 3 ? target : Math.round(cur + (target - cur) * 0.5);
    onData(`${cur === target ? 'ST' : 'US'},GS,+${(cur / 1000).toFixed(3).padStart(8)}kg\r\n`);
  }, 120);
}

function configure(c) {
  stop();
  cfg = { ...c };
  if (cfg.mode === 'sim') startSim();
  else if (cfg.mode === 'serial') {
    if (!cfg.port) { error = '还没选串口'; return; }
    try { process.platform === 'win32' ? startWindows() : startUnix(); } catch (e) { error = e.message; }
  }
}

function read() {
  if (cfg.mode === 'off') return { mode: 'off' };
  const age = last ? Date.now() - last.at : null;
  const fresh = age !== null && age < 2000;
  return {
    mode: cfg.mode, ok: fresh, weight_g: fresh ? last.weight_g : null, stable: fresh && last.stable, over: fresh && !!last.over,
    raw: last ? last.raw : '', error: fresh ? '' : (error || (last ? '秤没有数据了（线松了或秤关了？）' : '还没收到秤的数据')),
  };
}

// 列出电脑上的串口（Windows：COM3 这些）
function listPorts(cb) {
  if (process.platform === 'win32') {
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '[System.IO.Ports.SerialPort]::GetPortNames() -join ","'], { windowsHide: true, timeout: 8000 },
      (e, out) => cb(e ? [] : String(out).trim().split(',').filter(Boolean)));
  } else {
    fs.readdir('/dev', (e, names) => cb(e ? [] : names.filter((n) => /^(ttyUSB|ttyACM|ttyS[0-3]$|cu\.usb|tty\.usb)/.test(n)).map((n) => '/dev/' + n)));
  }
}

module.exports = { configure, read, listPorts, parseFrame, stop };
process.on('exit', stop); // 收银系统关掉时一起关掉读秤程序，免得占着串口
