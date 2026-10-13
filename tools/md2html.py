# 把使用说明.md 转成可以双击打开的网页（只支持这份说明用到的写法）
import html, re, sys

src, out = sys.argv[1], sys.argv[2]
lines = open(src, encoding='utf-8').read().splitlines()

def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<![">])(https?://[^\s<，。）)]+)', r'<a href="\1">\1</a>', t)
    return t

body = []
stack = []  # [indent, tag]
para = []

def flush_para():
    if para:
        body.append('<p>' + '<br>'.join(inline(x) for x in para) + '</p>')
        para.clear()

def close_lists(to_indent=-1):
    while stack and stack[-1][0] > to_indent:
        body.append('</li></%s>' % stack.pop()[1])

i = 0
while i < len(lines):
    ln = lines[i]
    if ln.startswith('```'):
        flush_para(); close_lists()
        j = i + 1
        code = []
        while j < len(lines) and not lines[j].startswith('```'):
            code.append(lines[j]); j += 1
        body.append('<pre>' + html.escape('\n'.join(code), quote=False) + '</pre>')
        i = j + 1
        continue
    m = re.match(r'^(#{1,3})\s+(.*)', ln)
    if m:
        flush_para(); close_lists()
        n = len(m.group(1))
        body.append('<h%d>%s</h%d>' % (n, inline(m.group(2)), n))
        i += 1; continue
    if ln.startswith('|'):
        flush_para(); close_lists()
        rows = []
        while i < len(lines) and lines[i].startswith('|'):
            cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
            if not all(re.fullmatch(r':?-{3,}:?', c) for c in cells):
                rows.append(cells)
            i += 1
        h, *rest = rows
        body.append('<div class="tbl"><table><thead><tr>' + ''.join('<th>%s</th>' % inline(c) for c in h) + '</tr></thead><tbody>'
                    + ''.join('<tr>' + ''.join('<td>%s</td>' % inline(c) for c in r) + '</tr>' for r in rest) + '</tbody></table></div>')
        continue
    if ln.startswith('> '):
        flush_para(); close_lists()
        body.append('<blockquote>%s</blockquote>' % inline(ln[2:]))
        i += 1; continue
    m = re.match(r'^(\s*)([-*]|\d+\.)\s+(.*)', ln)
    if m:
        flush_para()
        ind = len(m.group(1)); tag = 'ol' if m.group(2)[0].isdigit() else 'ul'
        close_lists(ind)
        if stack and stack[-1][0] == ind:
            if stack[-1][1] == tag:
                body.append('</li><li>%s' % inline(m.group(3)))
            else:
                body.append('</li></%s>' % stack.pop()[1])
                stack.append([ind, tag]); body.append('<%s><li>%s' % (tag, inline(m.group(3))))
        else:
            stack.append([ind, tag]); body.append('<%s><li>%s' % (tag, inline(m.group(3))))
        i += 1; continue
    if ln.strip() == '':
        flush_para()
        # 列表后面的空行：下一行不是列表或缩进内容就结束列表
        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        if stack and not re.match(r'^(\s+\S|\s*([-*]|\d+\.)\s)', nxt):
            close_lists()
        i += 1; continue
    if stack and ln.startswith(' '):
        body.append('<br>' + inline(ln.strip()))
        i += 1; continue
    close_lists()
    para.append(ln)
    i += 1
flush_para(); close_lists()

title = '桃喜团子收银系统 · 使用说明'
page = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
:root{--bg:#f4f3ef;--paper:#fff;--ink:#1d2433;--muted:#5d6472;--line:#dcd9d0;--soft:#ecebe5;--accent:#b8862b;--accent-ink:#7a5410}
@media (prefers-color-scheme: dark){:root{--bg:#14171e;--paper:#1c2029;--ink:#e8e6e0;--muted:#a3a7b0;--line:#323846;--soft:#262b37;--accent:#e0b35a;--accent-ink:#f0cf8a;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 "Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif;padding:24px 16px 64px}
main{max-width:780px;margin:0 auto;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:28px clamp(16px,4vw,40px)}
h1{font-size:26px;margin:0 0 8px;line-height:1.35}
h2{font-size:20px;margin:36px 0 10px;padding-top:18px;border-top:1px solid var(--line);color:var(--accent-ink)}
h3{font-size:17px;margin:24px 0 6px}
p,li{max-width:68ch}
ul,ol{padding-left:1.5em;margin:8px 0}
li{margin:4px 0}
code{font-family:Consolas,"SF Mono",monospace;background:var(--soft);padding:1px 6px;border-radius:5px;font-size:.92em;word-break:break-all}
pre{font-family:Consolas,"SF Mono",monospace;background:var(--soft);padding:12px 14px;border-radius:10px;overflow-x:auto;font-size:14px;line-height:1.6}
blockquote{margin:12px 0;padding:10px 14px;border-left:3px solid var(--accent);background:var(--soft);border-radius:0 8px 8px 0}
.tbl{overflow-x:auto;margin:10px 0}
table{border-collapse:collapse;width:100%%;font-size:15px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--soft)}
a{color:var(--accent-ink)}
.start{background:var(--accent);color:#fff;border-radius:12px;padding:14px 18px;font-size:18px;font-weight:700;margin:16px 0 4px}
@media (prefers-color-scheme: dark){.start{color:#1d2433}}
</style></head><body><main>
%s
</main></body></html>
''' % (title, '\n'.join(body))
# 在标题后面加一行最醒目的提示
page = page.replace('</h1>', '</h1>\n<div class="start">开店时双击「启动收银系统.bat」，浏览器会自动打开收银页面。</div>', 1)
open(out, 'w', encoding='utf-8').write(page)
print('ok', out, len(page))
