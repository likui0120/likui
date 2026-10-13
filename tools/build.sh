#!/bin/bash
# 打包 Windows 免安装版：bash tools/build.sh <node.exe 所在文件夹> <输出文件夹>
# node.exe 用官方 node-v22 win-x64 版本（https://nodejs.org/dist/），解压后的文件夹里要有 node.exe 和 LICENSE
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_DIR="$1"; OUT="${2:-$ROOT/dist}"
VER=$(node -p "require('$ROOT/app/package.json').version")
PKG="$OUT/桃喜团子收银系统"
rm -rf "$PKG"; mkdir -p "$PKG/app/node"
cp -r "$ROOT/app/." "$PKG/app/"
cp "$NODE_DIR/node.exe" "$NODE_DIR/LICENSE" "$PKG/app/node/"
cp "$ROOT/启动收银系统.bat" "$ROOT/允许手机连接.bat" "$PKG/"
python3 "$ROOT/tools/md2html.py" "$ROOT/app/使用说明.md" "$PKG/使用说明.html"
python3 -I "$ROOT/tools/mkzip.py" "$PKG" "$OUT/桃喜团子收银系统-v$VER-免安装版.zip"
