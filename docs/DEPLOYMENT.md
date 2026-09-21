# 部署、运行与备份恢复（T11）

负责人：王天一。本文描述 2.0 后端的启停、迁移、日志、健康检查与备份恢复。
服务器与域名尚未提供，因此本文交付**可验证的部署包与配置**，不声称公网已上线。

## 1. 依赖与环境

- Python 3.11+（仓库 `backend/pyproject.toml` 声明 `>=3.11`）。
- 默认数据库为 SQLite（`DATABASE_URL=sqlite:///./xunying.db`）；生产建议 PostgreSQL，
  需额外安装 `psycopg[binary]`（`pip install -e "backend[postgres]"`）。
- 智能导入与问答的本地模型（Ollama/Qwen）是**可选**组件：未启动时导入任务进入失败状态并可重试，
  问答返回结构化回答，不影响登录、档案、分析、方案与报告。

## 2. 首次部署

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env      # 按环境修改
python -m alembic upgrade head  # 建表/迁移
python -m app.cli create-admin --username admin   # 口令不回显
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

生产环境必须显式设置：

| 变量 | 生产值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | 关闭 `/docs`、`/redoc`、`/openapi.json` |
| `AUTH_REQUIRED` | `true` | 未登录访问业务接口返回 401 |
| `DATABASE_URL` | PostgreSQL 连接串 | 生产不建议 SQLite 文件 |
| `BACKEND_CORS_ORIGINS` | 实际站点域名 | 不要保留 `*` |
| `SESSION_TTL_MINUTES` | 按机构策略 | 会话过期时间 |
| `PASSWORD_HASH_ITERATIONS` | 留空或显式提高 | 留空使用默认 210000 |

`AUTH_REQUIRED=true` 后，前端必须先完成 C01 登录；切换时点与陈子正对齐（见
`docs/V2_API_CONTRACT.md` 第 6 节待确认项）。

### HTTPS 与会话边界

- 后端只监听 `127.0.0.1:8000`，由反向代理（Nginx/Caddy）终止 TLS 并转发；
  不要直接把 uvicorn 暴露到公网。
- 会话令牌放在 `Authorization: Bearer`，不要写入 URL 或日志；本服务的访问日志只记录
  `request_id`、方法、路径、状态码与耗时，不记录请求体与令牌。
- CORS 只允许实际站点域名；生产环境 `APP_ENV=production` 时交互式文档关闭。
- 数据库、日志与备份目录不放入 Git（`.gitignore` 已忽略 `.runtime`、`*.db`）。

## 3. 启停

```bash
# 启动（前台，便于观察日志）
uvicorn app.main:app --host 127.0.0.1 --port 8000
# 停止
Ctrl+C      # 或 systemctl stop xunying-api
```

systemd 单元示例（生产）：

```ini
[Unit]
Description=Xunying InsightCheck API
After=network.target

[Service]
WorkingDirectory=/srv/insightcheck/backend
EnvironmentFile=/srv/insightcheck/.env
ExecStart=/srv/insightcheck/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
User=xunying

[Install]
WantedBy=multi-user.target
```

## 4. 日志与健康检查

- 访问日志：每行一个 JSON 对象（`event=request`），字段 `request_id`、`method`、`path`、
  `status`、`duration_ms`；响应头回传 `X-Request-ID`，便于与前端问题对齐。
- 存活检查：`GET /health` 与 `GET /api/v1/health`（不需要登录）。
- 明细检查：`GET /api/v1/health/detail`（管理员），返回应用版本、环境、数据库可达性与迁移版本、
  账号/档案数量、`auth_required` 是否开启、导入临时目录是否可写、模型状态。

## 5. 迁移

```bash
python -m alembic upgrade head      # 应用迁移
python -m alembic current           # 当前版本
python -m app.cli backup-status     # 数据库位置与迁移版本（SQLite）
```

迁移前的常规顺序：备份 → 迁移 → 启动 → 抽查 `/health/detail`。
多实例部署时先停写再迁移，避免新旧代码同时写入。

## 6. 备份与恢复

```bash
# 备份（SQLite 在线备份 + SHA256 清单）
python -m app.cli backup --output /var/backups/xunying

# 查看数据库位置与迁移版本
python -m app.cli backup-status

# 恢复（默认先校验摘要与完整性，并保留覆盖前的安全副本）
python -m app.cli restore --input /var/backups/xunying/xunying-20260921T092633Z.db --force
```

规则：

- 备份使用 SQLite 在线备份 API，不会复制到写入中的半成品文件；同时生成
  `*.manifest.json`（摘要、大小、迁移版本、生成时间）。
- 恢复前会校验摘要与 `PRAGMA integrity_check`；目标库已存在时必须显式 `--force`，
  并自动生成 `*.pre-restore-<时间>` 安全副本。
- 备份迁移版本早于当前数据库时拒绝恢复，需要先确认迁移策略。
- PostgreSQL 请使用 `pg_dump` / `pg_restore`；内置备份只支持 SQLite，并会明确报错。
- 恢复后执行 `python -m alembic upgrade head`，再启动服务并检查 `/health/detail`。

## 7. 已知限制

- 未提供服务器与域名，因此没有公网部署证据；本文与 `/health/detail` 是可验证的交付内容。
- 备份未加密：备份目录需要单独的文件权限与传输加密措施。
- 解析为同步执行：单个后端进程按顺序处理导入任务；如需更高并发，参见 T03 未完成项。
