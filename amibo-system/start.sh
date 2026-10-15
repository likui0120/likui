#!/bin/bash
# Mac / Linux 启动脚本
cd "$(dirname "$0")/backend" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "第一次运行，正在安装依赖……"
  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
[ -f ../data/amibo.db ] || .venv/bin/python -m app.seed
echo "系统已启动：http://127.0.0.1:8000（平板用这台电脑的局域网 IP 访问）"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
