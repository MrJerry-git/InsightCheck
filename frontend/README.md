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

核心页面已连接工作流：创建档案、录入指标、查看历史与病灶、合成模型分析、规则检查、方案保存回看、证据导出与本地模板说明。项目和规则管理支持新增，规则可启停。操作及范围见 [1.0 工程预览](../docs/V1_WORKFLOW.md)。

`/health-records` 保留合成导入包校验、幂等导入与历史查看，见 [导入说明](../docs/SYNTHETIC_IMPORT.md)。前端需要同时运行后端；默认 API 为 `http://127.0.0.1:8000/api/v1`，可通过 `NEXT_PUBLIC_API_BASE_URL` 配置。
