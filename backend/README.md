# 循影定检 Backend

FastAPI 后端已包含体检数据模型、Alembic 迁移、基础 CRUD、指标标准化、病灶匹配、纵向指标特征，以及第六阶段的 PyTorch DeepFM 训练、评估、制品和匹配排名 API。DeepFM 分数不是疾病概率或最终推荐，当前不包含医疗规则执行。

```powershell
python -m alembic upgrade head
python -m app.seed
python -m uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` 可重复执行且不会重复创建 Demo 数据。所有 Demo 体检批次均为 `is_demo=true`。
