# 循影定检 Frontend

Next.js App Router 前端工程骨架，使用 TypeScript、Tailwind CSS、shadcn/ui 与 ECharts。

## 启动

```powershell
npm install
npm run dev
```

打开 `http://localhost:3000`。默认将根路径重定向到 `/dashboard`。

## 验证

```powershell
npm test
npm run lint
npm run typecheck
npm run build
```

多数业务页仍为架构占位。`/health-records` 已支持合成导入包校验、幂等导入与历史查看，操作见 [导入说明](../docs/SYNTHETIC_IMPORT.md)。病灶页面连接后端演示接口，推荐详情仍为静态规则样例，不能视为完整方案联调完成。后续按 [实施设计](../docs/IMPLEMENTATION_DESIGN.md) 推进。
