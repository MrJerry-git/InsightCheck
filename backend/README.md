# 循影定检 Backend

FastAPI 后端包含体检数据模型、Alembic 迁移、基础 CRUD、指标标准化、病灶匹配、纵向指标特征、PyTorch DeepFM 训练与排名，以及独立医疗规则引擎。DeepFM 分数不是疾病概率或最终推荐；LightGBM、真实数据实验和完整方案生成编排尚未完成。后续以 [实施设计](../docs/IMPLEMENTATION_DESIGN.md) 为准。

```powershell
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` 可重复执行且不会重复创建 Demo 数据。所有 Demo 体检批次均为 `is_demo=true`。

研究工具通过 `pip install -e '.[dev,research]'` 安装可选依赖。新增 NLST 固定版本下载审计和三种离线风险基线，详见 [研究程序说明](../docs/RISK_EXPERIMENTS.md)。在线 LightGBM Adapter 与真实数据验证尚未完成；离线程序不自动进入医疗推荐链路。
