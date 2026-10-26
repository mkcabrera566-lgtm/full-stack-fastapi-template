# FastAPI Project - Backend

## AI 工单业务演示（独立 SQLite，无需 Docker）

演示复用现有 FastAPI 路由、JWT、SQLModel 和 AI 服务，没有新增业务接口。
通过 TestClient 在进程内执行完整 HTTP 链路：

1. POST `/api/v1/login/access-token`，使用临时库中的虚构普通用户真实登录。
2. POST `/api/v1/tickets/`，创建“会员支付成功，但账户权益没有开通”虚构工单。
3. GET `/api/v1/tickets/{ticket_id}`，读取已持久化工单。
4. POST `/api/v1/tickets/{ticket_id}/ai-analysis`，展示四个 AI 字段及 Pydantic 校验结果。
5. 再次 GET，并通过全新 SQLite 连接核对全部 7 个工单字段保持不变。

每次运行使用新建临时目录中的文件 SQLite，NullPool 不复用物理连接，
每个 HTTP 请求独立创建并关闭 Session。脚本阻断应用原数据库引擎的连接/checkout，
临时用户和工单只写入本次临时库；结束后关闭引擎、删除该临时目录并恢复依赖覆盖。
不执行已有数据库迁移，不读取或清理现有数据库。

### PowerShell 默认 Mock 演示

在已安装 uv 的 PowerShell 中执行：

```powershell
Set-Location 'D:\python-job-plan\open-source\full-stack-fastapi-template\backend'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
uv run --frozen --package app python -X utf8 scripts/demo_ticket_ai.py
$LASTEXITCODE
```

默认模式即使环境中有真实密钥也不调用真实模型：仅在 SDK 的 HTTP 传输边界使用
MockTransport，实际服务层仍生成当前 System Prompt、调用真实 SDK 并执行 Pydantic 校验。
登录、JWT、工单路由和 SQLModel 操作均为真实执行，没有 Mock 掉业务层。
脚本仅输出脱敏 JSON，不输出密钥、JWT、登录密码、请求头或上游异常原文；
临时禁止第三方日志和警告，输出中精确替换本次 JWT 和传给 SDK 的密钥，
并额外替换疑似 JWT/`sk-` 字符串。密钥仅用于认证和内存中的脱敏，不写入报告或文件。

完整的实际 Mock 运行输出见 [脱敏运行样例](../docs/ticket-ai-demo.mock.json)。核心结果为：

```json
{
  "mode": "mock",
  "pydantic_validation": "passed",
  "quality": {"status": "no_flags", "flags": [], "requires_human_review": true},
  "checks": {"http_ticket_unchanged": true, "new_connection_ticket_unchanged": true},
  "ai_attempts": {"mock": 1, "real": 0, "limit": 1},
  "database_removed": true
}
```

### 显式开启一次真实千问尝试

只有决定进行真实调用时，才在已配置 `DASHSCOPE_API_KEY` 的同一终端单独执行：

```powershell
uv run --frozen --package app python -X utf8 scripts/demo_ticket_ai.py --real-ai
$LASTEXITCODE
```

沿用现有服务的模型、地域地址和超时设置，不修改已跟踪的 `.env`。
真实模式每次演示进程最多发起一次模型 HTTP 尝试：SDK 和传输层重试均为 0，
禁止跟随重定向，另有共享的一次调用预算，即使第一次失败也不自动补发。
缺少密钥时返回脱敏的 503 阶段结果、真实尝试数为 0。
重复执行带开关的命令属于新的真实尝试，不是跨进程的全局额度控制。
本次交付只实际运行 Mock 模式；真实模式的自动化测试也使用 MockTransport，不是真实联调。

### 回复质量检查及退出码

演示检查实际发出的 system 消息包含新版事实边界，并对返回的 summary、suggested_reply
做保守的中文措辞检查：无依据的支付成功断言、“已核实”、已退款/开通/转人工等操作或进度、
“5分钟生效”等时间承诺、人工开通/退款等结果承诺会被记录为质量失败。
演示不会重写、接受或执行这些建议，也不把质量检查加入产品 API。

| 退出码 | 含义 |
| --- | --- |
| 0 | HTTP 链路和不变性检查通过，质量规则未发现风险措辞 |
| 1 | 初始化、HTTP、结构校验或工单不变性失败 |
| 2 | 四字段结构可合法，但回复触发质量风险规则，`result=quality_failed` |

自动化测试注入含“已核实支付记录、5分钟生效、人工开通”的 Mock 回复，验证退出码 2，
同时工单仍保持不变；这些是模拟质量失败，不是真实千问输出。
文本规则有漏报和误报，也不能验证订单或权益状态；`no_flags` 不等于事实准确或模型完全遵守 Prompt。
Mock 演示通过不等于真实模型质量通过，所有建议仍需人工审核。

**SQLite 演示不能替代 PostgreSQL 验收。** 真实迁移、UUID/时区/约束差异、行锁、事务隔离、
并发及原 PostgreSQL 测试仍待专用测试库验证；本演示没有访问该库，也未改变 CI 90% 门槛。

演示测试：`uv run --frozen --package app pytest tests_offline/test_ticket_demo.py -q`。

2026-10-26 实际验证：默认 Mock 演示的 HTTP 状态依次为 `200/201/200/200/200`，
五次请求各用独立 Session，新连接核对工单未变，真实模型尝试数为 0，临时库已清理。
全量 pytest 为 **169 passed、58 skipped**，演示新增 13 项；Ruff 和格式检查通过，
mypy（28 个文件）、ty 通过，保留一条原有 TestClient 弃用警告。
真实模式护栏测试同样使用 MockTransport，本轮没有执行真实千问演示。

## Requirements

* [Docker](https://www.docker.com/).
* [uv](https://docs.astral.sh/uv/) for Python package and environment management.

## Local Development

Run the backend locally and connect it to PostgreSQL in Docker Compose.

From the project root, start PostgreSQL and Mailpit:

```console
$ docker compose up -d db mailpit
```

Then, from `./backend/`, install the dependencies, prepare the database, and start the development server:

```console
$ uv sync
$ uv run bash scripts/prestart.sh
$ uv run fastapi dev
```

The API is available at `http://localhost:8000`, with automatic interactive docs at `http://localhost:8000/docs`.

## General Workflow

Run backend commands from `./backend/` with `uv run`. Make sure your editor uses the Python interpreter at `.venv/bin/python` in the project root.

Modify or add SQLModel models for data and SQL tables in `./backend/app/models.py`, API endpoints in `./backend/app/api/`, CRUD (Create, Read, Update, Delete) utils in `./backend/app/crud.py`.

## VS Code

There are already configurations in place to run the backend through the VS Code debugger, so that you can use breakpoints, pause and explore variables, etc.

The setup is also already configured so you can run the tests through the VS Code Python tests tab.

## Full Stack with Docker Compose

To run the backend and built frontend in Docker Compose:

```console
$ docker compose run --rm backend bash scripts/prestart.sh
$ docker compose watch
```

The application is available at `http://localhost:8000`.

### Docker Compose Override

The `compose.override.yml` file contains local settings for published ports, source synchronization, automatic image rebuilds, and backend reloads. Docker Compose applies it automatically when you run `docker compose` without an explicit file list.

To open a shell in the backend container:

```console
$ docker compose exec backend bash
```

## Backend Tests

To test the backend from the `backend` directory, run:

```console
$ uv run bash scripts/test.sh
```

The tests run with Pytest. Modify existing tests or add new ones in `./backend/tests/`.

If you use GitHub Actions, the tests will run automatically.

### Test a Running Stack

If your stack is already up and you just want to run the tests, you can use:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

The `/app/backend/scripts/tests-start.sh` script calls `pytest`. If you need to pass extra arguments to `pytest`, you can pass them to that command and they will be forwarded.

For example, to stop on first error:

```bash
docker compose exec backend bash scripts/tests-start.sh -x
```

### Test Coverage

When the tests run, they generate `htmlcov/index.html`. Open it in your browser to inspect the test coverage.

## Migrations

Make sure you create a revision of your models and upgrade the database with that revision every time you change them. From the `backend` directory, use `uv` to run Alembic against the PostgreSQL container:

* Alembic is already configured to import your SQLModel models from `./backend/app/models.py`.

* After changing a model (for example, adding a column), create a revision:

```console
$ uv run alembic revision --autogenerate -m "Add column last_name to User model"
```

* Commit to the git repository the files generated in the alembic directory.

* After creating the revision, run the migration in the database (this is what will actually change the database):

```console
$ uv run alembic upgrade head
```

If you don't want to use migrations at all, uncomment the lines in the file at `./backend/app/core/db.py` that end in:

```python
SQLModel.metadata.create_all(engine)
```

and comment the line in the file `scripts/prestart.sh` that contains:

```console
$ alembic upgrade head
```

If you don't want to start with the default models and want to remove them / modify them, from the beginning, without having any previous revision, you can remove the revision files (`.py` Python files) under `./backend/app/alembic/versions/`. And then create a first migration as described above.

## Email Templates

The email templates are written with [React Email](https://react.email) in `./packages/react-email/`. The `emails` directory holds one component per email and the `ui` directory holds the shared components (layout, heading, button, link, callout).

The rendered HTML in `./backend/app/email-templates/` is generated from those components. It is what the application sends and should not be edited by hand.

To preview the emails while editing them, start the dev server from the root of the project:

```console
$ bun run email:dev
```

Values coming from the backend are declared as Jinja placeholders in the component props, for example `username = "{{ username }}"`. The context for each email is built in `generate_*_email()` in `./backend/app/utils.py`, so a new placeholder needs to be added there too.

Once you are done, regenerate the templates used by the application:

```console
$ bun run email:export
```
