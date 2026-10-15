# 车间出率与成本核算系统

按 BOM 和车间称重数据，每天算出每种原料、每道工序的实际出率，逐级推出半成品和成品的实际成本与标准成本，偏差超限自动提醒；同时用抄表数据算出电、水、燃气的吨能耗。需求见项目文件夹里的《Amibo系统制作.md》，使用方法见 [使用说明.md](使用说明.md)。

## 结构

```
backend/            Python + FastAPI + SQLite
  app/models.py       数据表（基础资料带生效日期版本、每日录入、计算结果）
  app/calc/engine.py  计算引擎：出率、实际/标准成本、差额归因、跨天取价、异常
  app/calc/energy.py  能耗：单表用量、全厂/车间合计、吨能耗、费用
  app/api/            接口：基础资料、每日录入、Excel 导入、报表与导出
  app/seed.py         初始化（计量表、能源单价、包装规格、附录 BOM），--demo 加示例数据
  tests/              计算公式手算核对 + 接口冒烟测试
frontend/           Vue 3 + Element Plus（dist/ 是已打包的页面，后端直接托管）
data/amibo.db       数据库（不进版本管理）
```

## 开发

```bash
cd backend
pip install -r requirements.txt pytest httpx
python -m app.seed --demo          # 初始化并加示例数据
uvicorn app.main:app --reload      # http://127.0.0.1:8000
python -m pytest -q                # 测试

cd ../frontend
npm install
npm run dev                        # 前端开发，接口代理到 8000
npm run build                      # 打包到 frontend/dist
```

重算策略：任何录入或资料改动后，从受影响的最早日期起往后全部重算（半成品油取之前最近一天的价、麻油取前 7 天，依赖会一直往后传）。每天数据量很小，全量往后算最稳妥。
