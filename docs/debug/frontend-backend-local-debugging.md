# Glomi AI 前后端本地调试说明

本文档面向当前 Glomi AI fork 的日常开发，重点覆盖 `web/` 前端和 `backend/` 后端。推荐的默认方式是：**外部依赖用 Docker 跑，本地源码只跑你正在改的服务**。这样热更新快、断点方便，也不会被完整容器栈拖慢。

## 0. 前置要求

- Docker Desktop 已启动。
- Python 3.13。
- `uv`。
- `bun`。
- Go 1.24+，仅当你调试 `cli/` 时需要。

Python 依赖在仓库根目录的 `.venv` 中：

```powershell
uv sync --frozen
.\.venv\Scripts\activate
```

如果你在 Git Bash / WSL 中：

```bash
uv sync --frozen
source .venv/bin/activate
```

如果需要真实 LLM 调用，先准备 `.vscode/.env`：

```powershell
Copy-Item .vscode\env_template.txt .vscode\.env
```

然后填入 `OPENAI_API_KEY` 等必要变量。测试真实 OpenAI 调用时，项目约定优先用 `gpt-5-mini`。

## 1. 推荐模式：Docker 依赖 + 本地前后端

适合改前端、API、i18n、登录页、主应用壳、FastAPI endpoint、数据库逻辑等。

### 1.1 启动外部依赖

进入 compose 目录：

```powershell
cd deployment\docker_compose
Copy-Item env.template .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d relational_db opensearch cache minio
```

这些服务分别是：

- `relational_db`: Postgres
- `opensearch`: 搜索 / 向量索引
- `cache`: Redis
- `minio`: S3 兼容文件存储

如果本次功能需要本地模型服务，也可以一起启动容器版：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d inference_model_server
```

### 1.2 跑数据库迁移

回到仓库根目录并激活虚拟环境：

```powershell
cd ..\..
.\.venv\Scripts\activate
cd backend
$env:POSTGRES_HOST = "localhost"
alembic upgrade head
```

多租户 / EE schema 只有在你明确调试相关功能时才需要：

```powershell
alembic -n schema_private upgrade head
```

### 1.3 启动后端 API

在 `backend/` 目录：

```powershell
$env:AUTH_TYPE = "basic"
$env:LOG_LEVEL = "DEBUG"
$env:POSTGRES_HOST = "localhost"
$env:OPENSEARCH_HOST = "localhost"
$env:REDIS_HOST = "localhost"
$env:MODEL_SERVER_HOST = "localhost"
$env:S3_ENDPOINT_URL = "http://localhost:9004"
$env:S3_AWS_ACCESS_KEY_ID = "minioadmin"
$env:S3_AWS_SECRET_ACCESS_KEY = "minioadmin"
uvicorn onyx.main:app --reload --port 8080
```

这些 `localhost` 环境变量只针对“本地源码跑后端 + Docker 跑依赖”的模式。后端进程不在 Docker 网络里，所以不能使用 compose 内部服务名 `relational_db`、`opensearch`、`cache`。

后端健康检查：

```powershell
Invoke-WebRequest http://localhost:8080/health
```

注意：开发时，前端应通过 `http://localhost:3000/api/...` 访问后端，不要直接在业务调试中绕到 `http://localhost:8080/api/...`。

### 1.4 启动后台任务

如果你调试 connector、索引、异步任务、文件处理等，需要跑后台任务：

```powershell
cd backend
$env:AUTH_TYPE = "basic"
$env:POSTGRES_HOST = "localhost"
$env:OPENSEARCH_HOST = "localhost"
$env:REDIS_HOST = "localhost"
$env:MODEL_SERVER_HOST = "localhost"
$env:S3_ENDPOINT_URL = "http://localhost:9004"
$env:S3_AWS_ACCESS_KEY_ID = "minioadmin"
$env:S3_AWS_SECRET_ACCESS_KEY = "minioadmin"
python .\scripts\dev_run_background_jobs.py
```

后台任务和 API 一样是本地 Python 进程；如果你在同一个终端里已经设置过这些环境变量，可以不用重复设置。

如果你改了 Celery worker 相关代码，已有 worker 不会自动重启；需要手动重启对应 worker / dev background jobs。

### 1.5 启动模型服务

如果没有用容器版 `inference_model_server`，可以源码启动：

```powershell
cd backend
uvicorn model_server.main:app --reload --port 9000
```

### 1.6 启动前端

新开终端：

```powershell
cd web
bun install
bun run dev
```

访问：

```text
http://localhost:3000
```

如果本地访问异常，可以在 `web/.env.local` 中设置：

```text
WEB_DOMAIN=http://127.0.0.1:3000
```

默认登录可尝试：

```text
a@example.com
a
```

## 2. 只调前端：本地 web + 已运行后端

适合 i18n / UI rebrand / 页面组件 / layout / CSS 调试。

确认后端在 `localhost:8080` 可用后：

```powershell
cd web
bun run dev
```

前端开发服务器默认会把 `/api` 请求转到本地后端。浏览器里始终访问：

```text
http://localhost:3000
```

不要在前端代码里写死 `localhost:8080`。

### 调试 i18n / rebrand 的常用验证

```powershell
cd web
bun run test -- src/lib/i18n/config.test.ts
bun run test -- src/lib/i18n/messages.test.ts
bun run test -- src/lib/brand.test.ts
bun run types:check
bun run build
```

人工检查：

- `/auth/login` 默认中文。
- `/app` 主应用壳无用户可见的 `Onyx` 品牌残留。
- DevTools 设置 cookie `NEXT_LOCALE=en` 后刷新，界面可回英文。
- 标题 / metadata 显示 `Glomi AI`。

## 3. 只调后端：本地 API + Docker 依赖

适合 FastAPI endpoint、数据库操作、LLM 调用、工具执行、索引流程等。

启动依赖：

```powershell
cd deployment\docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d relational_db opensearch cache minio inference_model_server
```

启动 API：

```powershell
cd ..\..\backend
$env:AUTH_TYPE = "basic"
$env:LOG_LEVEL = "DEBUG"
$env:POSTGRES_HOST = "localhost"
$env:OPENSEARCH_HOST = "localhost"
$env:REDIS_HOST = "localhost"
$env:MODEL_SERVER_HOST = "localhost"
$env:S3_ENDPOINT_URL = "http://localhost:9004"
$env:S3_AWS_ACCESS_KEY_ID = "minioadmin"
$env:S3_AWS_SECRET_ACCESS_KEY = "minioadmin"
uvicorn onyx.main:app --reload --port 8080
```

启动前端来走真实调用链：

```powershell
cd ..\web
bun run dev
```

调试 API 时仍然优先从浏览器或前端路径发起请求，例如：

```text
http://localhost:3000/api/persona
```

数据库操作代码必须放在：

```text
backend/onyx/db
backend/ee/onyx/db
```

不要把 SQL 查询散落在 server route 或业务层里。

## 4. 全 Docker 模式

适合快速验证完整栈，或确认问题是否只出现在本地源码启动方式。

```powershell
cd deployment\docker_compose
Copy-Item env.template .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --wait
```

访问：

```text
http://localhost:3000
```

如果你要让 Docker 里的 web/backend 包含本地代码改动：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

注意：完整 Docker 模式里的 `nginx` 会占用 `localhost:3000`。如果你要本地跑 `web/bun run dev`，不要同时让 compose 的 `nginx` 占着 3000，或者改端口。

## 5. VS Code Debugger 模式

仓库已有 `.vscode/launch.json` 和 `.vscode/tasks.json`。第一次使用：

```powershell
Copy-Item .vscode\env_template.txt .vscode\.env
```

然后在 VS Code Debug 面板中：

1. 选择 `Clear and Restart External Volumes and Containers`，只在你接受清空本地 Postgres / OpenSearch 数据时运行。
2. 选择 `Run All Onyx Services`。
3. 打开 `http://localhost:3000`。
4. 在 Python / TypeScript 文件中打断点调试。

如果只是日常 UI 或 API 开发，推荐优先用第 1 节的混合模式；VS Code 全服务模式更适合需要集中断点和多服务一起跑的时候。

## 6. 测试命令速查

### 前端

```powershell
cd web
bun run test
bun run types:check
bun run lint
bun run build
```

单测某个文件：

```powershell
bun run test -- src/app/auth/login/LoginText.test.tsx
```

E2E：

```powershell
cd web
bunx playwright test <TEST_NAME>
```

### 后端

单位测试，不依赖外部服务：

```powershell
pytest -xv backend/tests/unit
```

外部依赖单测，需要 Postgres / Redis / MinIO / Vespa 或 OpenSearch 等依赖可用：

```powershell
python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit
```

集成测试，需要完整 Onyx 部署正在运行：

```powershell
python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration
```

## 7. 日志与排障

本地源码启动时，优先看当前终端输出。Docker 服务日志：

```powershell
cd deployment\docker_compose
docker compose logs -f api_server
docker compose logs -f web_server
docker compose logs -f relational_db
docker compose logs -f opensearch
docker compose logs -f cache
```

项目也会把服务日志写到：

```text
backend/log/<service_name>_debug.log
```

调试数据库：

```powershell
docker exec -it onyx-relational_db-1 psql -U postgres
```

执行单条 SQL：

```powershell
docker exec -it onyx-relational_db-1 psql -U postgres -c "SELECT 1;"
```

查看容器状态：

```powershell
docker compose -f deployment/docker_compose/docker-compose.yml -f deployment/docker_compose/docker-compose.dev.yml ps
```

## 8. 常见坑

### 端口 3000 被占用

完整 compose 的 `nginx` 会监听 `localhost:3000`。如果你要本地跑前端：

```powershell
cd deployment\docker_compose
docker compose stop nginx web_server
```

然后：

```powershell
cd ..\..\web
bun run dev
```

### 后端改动没生效

确认你跑的是本地 `uvicorn --reload`，不是 Docker 里的 `api_server`。如果浏览器访问的是 `localhost:3000`，前端会代理到本地后端；如果完整 Docker 仍在运行，可能请求被 compose 的 nginx / web_server 接走。

### Celery 改动没生效

Celery worker 没有代码热更新保证。改 worker 后，重启：

```powershell
cd backend
python .\scripts\dev_run_background_jobs.py
```

### 搜索服务名不一致

当前 compose 服务名是 `opensearch`。如果看到旧文档中的 `index`，以当前 `deployment/docker_compose/docker-compose.yml` 为准。

### 前端请求直连 8080

除健康检查外，功能调试优先通过前端：

```text
http://localhost:3000/api/...
```

这样 cookies、auth、proxy、前后端真实边界都更接近用户路径。

## 9. 推荐日常启动顺序

前端 + 后端开发的最小闭环：

```powershell
# 终端 1：依赖
cd deployment\docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d relational_db opensearch cache minio inference_model_server

# 终端 2：API
cd backend
$env:AUTH_TYPE = "basic"
$env:LOG_LEVEL = "DEBUG"
$env:POSTGRES_HOST = "localhost"
$env:OPENSEARCH_HOST = "localhost"
$env:REDIS_HOST = "localhost"
$env:MODEL_SERVER_HOST = "localhost"
$env:S3_ENDPOINT_URL = "http://localhost:9004"
$env:S3_AWS_ACCESS_KEY_ID = "minioadmin"
$env:S3_AWS_SECRET_ACCESS_KEY = "minioadmin"
uvicorn onyx.main:app --reload --port 8080

# 终端 3：后台任务，按需
cd backend
$env:AUTH_TYPE = "basic"
$env:POSTGRES_HOST = "localhost"
$env:OPENSEARCH_HOST = "localhost"
$env:REDIS_HOST = "localhost"
$env:MODEL_SERVER_HOST = "localhost"
$env:S3_ENDPOINT_URL = "http://localhost:9004"
$env:S3_AWS_ACCESS_KEY_ID = "minioadmin"
$env:S3_AWS_SECRET_ACCESS_KEY = "minioadmin"
python .\scripts\dev_run_background_jobs.py

# 终端 4：Web
cd web
bun run dev
```

访问：

```text
http://localhost:3000
```
