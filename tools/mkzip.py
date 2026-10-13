# 用 UTF-8 文件名标志打包，Windows 自带解压不会出现中文乱码
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
base = os.path.dirname(os.path.abspath(src))
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for root, dirs, files in os.walk(src):
        dirs.sort(); files.sort()
        rel = os.path.relpath(root, base)
        z.write(root, rel)
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.join(rel, f))
with zipfile.ZipFile(out) as z:
    bad = [i.filename for i in z.infolist() if any(ord(c) > 127 for c in i.filename) and not (i.flag_bits & 0x800)]
    print(out, 'entries', len(z.infolist()), 'non-utf8-flagged', bad, 'test', z.testzip())
