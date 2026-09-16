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

多数业务页仍为架构占位。病灶页面连接后端演示接口，推荐详情当前渲染静态规则样例，不能视为真实方案联调完成。首版将按 [实施设计](../docs/IMPLEMENTATION_DESIGN.md) 收敛到导入、历史、复核与方案流程。
