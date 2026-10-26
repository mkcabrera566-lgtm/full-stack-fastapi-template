# 工单管理 V1：实现说明与学习指南

## 本次交付

功能分支：`codex/ticket-management-v1`。本阶段只增加后端工单管理，保留认证、用户、Item 和原测试代码；未开发 AI 或前端，未使用 Docker，未连接或修改现有数据库，未执行在线 Alembic 升级。

沿用现有 FastAPI + SQLModel 架构、JWT 认证、`CurrentUser` 和 `SessionDep`。不增加依赖，不更改 Python 版本要求和锁文件。已用 uv 自动安装仓库要求的 Python 3.14.7 和锁定依赖，虚拟环境位于仓库根目录 `.venv`，Windows 下无需执行激活脚本。

## API

以下接口均要求 `Authorization: Bearer <access_token>`。

| 方法 | 路径 | 行为 | 成功状态 |
| --- | --- | --- | --- |
| POST | `/api/v1/tickets/` | 创建属于当前用户的工单 | 201 |
| GET | `/api/v1/tickets/` | 查询当前用户可访问工单，返回 `{data, count}` | 200 |
| GET | `/api/v1/tickets/{id}` | 查询单条工单 | 200 |
| PATCH | `/api/v1/tickets/{id}` | 部分更新和状态流转 | 200 |
| DELETE | `/api/v1/tickets/{id}` | 删除工单，返回消息 | 200 |

普通用户只能查看、修改、删除自己的工单；管理员可以操作全部工单。列表的 `count` 同样受权限过滤，按创建时间倒序、UUID 倒序稳定排序。参数：`skip >= 0`，`1 <= limit <= 100`，默认 `skip=0, limit=100`。

创建示例：

```json
{
  "title": "无法登录",
  "description": "申请重置密码后没有收到邮件，请协助排查。",
  "priority": "high"
}
```

创建时 `id`、`owner_id`、`created_at` 和初始 `status=open` 由服务端设置，不能由请求指定。标题去除首尾空白后长度为 1–255，描述去除首尾空白后长度为 1–10000。优先级为 `low / medium / high / urgent`，默认 `medium`。时间为带时区的 UTC，UUID 与原项目一致。

PATCH 可包含 `title`、`description`、`priority`、`status` 的任意子集。省略表示保留原值，显式 `null`、未知字段或只读字段返回 422；空对象为无操作更新。

业务默认状态规则由本次实现确定：

```text
open -> in_progress -> resolved -> closed
           ^             |
           +-------------+
```

允许 `resolved -> in_progress` 重开；允许提交相同状态。`closed` 是终态。其他流转返回 409，管理员同样遵守。先校验状态，再修改其他字段，避免非法流转同时写入其他编辑。更新和删除使用 PostgreSQL 行锁；真实并发行为仍需 PostgreSQL 验证。

错误约定：

| 情况 | 状态码 |
| --- | --- |
| 未提供令牌 | 401 |
| 令牌无效、过期，或 subject 不是 UUID | 403 |
| 非活跃用户 | 400，沿用原项目 |
| 工单不存在 | 404 |
| 工单存在但不属于当前普通用户 | 403 |
| 请求字段、UUID 或分页参数非法 | 422 |
| 状态流转不合法 | 409 |

## 修改文件

| 文件 | 职责 |
| --- | --- |
| `backend/app/models.py` | Ticket 表、枚举、创建/更新/响应模型，以及 User 的 tickets 关系 |
| `backend/app/api/routes/tickets.py` | 五个接口、归属校验、分页、状态流转与写入行锁 |
| `backend/app/api/main.py` | 注册 tickets 路由 |
| `backend/app/api/deps.py` | 在原 JWT 认证中把 subject 转成 UUID，再查询用户；兼容 SQLite 并拒绝非法 subject |
| `backend/app/main.py` | 前端产物目录存在时才挂载，使未构建前端的后端可独立运行 |
| `backend/app/alembic/versions/a7b8c9d0e1f2_add_ticket.py` | 新增 ticket 表、外键级联、owner 索引及枚举 CHECK 约束 |
| `backend/conftest.py` | 离线测试配置、阻止应用 PostgreSQL 连接、原测试运行开关 |
| `backend/tests/conftest.py` | 保留原数据库夹具和清理代码，增加显式运行保护并延迟导入应用依赖 |
| `backend/tests_offline/conftest.py` | 每条测试独立内存 SQLite、外键启用、仅覆盖数据库依赖 |
| `backend/tests_offline/test_tickets.py` | CRUD、权限、校验、状态矩阵、级联与 Item 回归 |
| `backend/tests_offline/test_auth.py` | 原认证依赖的非法/不存在 UUID subject 回归 |
| `backend/tests_offline/test_backend_boot.py` | 无前端产物时后端加载及 404 回归 |
| `backend/tests_offline/test_ticket_migration.py` | 临时数据库迁移升降级、约束验证与 PostgreSQL SQL 离线生成 |
| `backend/tests_offline/test_test_safety.py` | 验证禁止应用 PostgreSQL 连接及集成测试专用 URL 保护 |
| `backend/scripts/test_backend.py` | Windows/Linux 共用测试入口，离线测试优先，显式测试库配置后追加集成测试覆盖率 |
| `backend/scripts/test.sh` | 原脚本委托给跨平台 Python 入口 |
| `backend/tests_offline/test_test_runner.py` | 测试入口选择测试集、追加覆盖率、失败立即停止的回归 |
| `.github/workflows/test-backend.yml` | 将 CI 临时库 URL 显式传给集成测试，保留原测试执行 |
| `backend/pyproject.toml` | 将 Alembic 脚本排除出 API 语句覆盖率统计，迁移用专门测试验证 |
| `docs/superpowers/plans/2026-10-25-ticket-management-v1.md` | 实施计划、约束与业务默认决策 |
| `docs/tickets-v1.md` | 本文档 |

## Windows 验证命令

在仓库根目录安装依赖：

```powershell
uv sync --frozen --package app --group dev
Set-Location backend
```

在 `backend` 目录执行：

```powershell
# 默认模式不会访问配置的 PostgreSQL；原集成测试会跳过。
uv run --frozen --package app pytest -q --tb=line

# 跨平台覆盖率入口；未设置 TEST_DATABASE_URL 时只运行离线测试。
uv run --frozen --package app python scripts/test_backend.py

uv run --frozen --package app ruff check .
uv run --frozen --package app ruff format app conftest.py tests_offline tests/conftest.py scripts/test_backend.py --check
uv run --frozen --package app mypy app scripts/test_backend.py
uv run --frozen --package app ty check app scripts/test_backend.py

# 项目默认排除 Alembic，单独检查新迁移。
uv run --frozen --package app ruff check --exclude '' app/alembic/versions/a7b8c9d0e1f2_add_ticket.py
uv run --frozen --package app ruff format --exclude '' app/alembic/versions/a7b8c9d0e1f2_add_ticket.py --check

# 只生成本次迁移的 PostgreSQL SQL，不连接数据库。
uv run --frozen --package app alembic upgrade fe56fa70289e:a7b8c9d0e1f2 --sql
```

2026-10-25 执行结果：默认 pytest **98 通过、58 跳过、0 失败**。98 项测试全部不依赖 PostgreSQL。API 测试使用真实 JWT/登录、真实 SQLModel 操作及真实 HTTP 请求，只把数据库依赖替换为临时 SQLite；测试入口的调度测试替换外部 coverage CLI，防止实际启动数据库测试。Ruff 检查和格式、mypy、ty 均通过。迁移 upgrade/downgrade 已在内存 SQLite 执行，并验证原有用户数据保留、非空/枚举/外键约束和索引；PostgreSQL 升降级 SQL 生成及单 head 迁移链已检查。

覆盖率运行中，`app/api/routes/tickets.py` 为 **100% 语句覆盖**，全后端为 **69%**，不代表已验证所有生产环境行为。单独执行整体 `coverage report --fail-under=90` 返回失败，原因是当前离线模式未覆盖原有 PostgreSQL 集成流程；未下调原 CI 的 90% 门槛。测试还有一条来自锁定 Starlette 的弃用警告：其 TestClient 建议使用 httpx2。暂未为消除警告改动上游锁定依赖。

原 58 项集成测试需要一个明确指定、可清理的专用 PostgreSQL 测试库才能运行：先设置 `TEST_DATABASE_URL`，再使用 `--run-postgres-tests`。未提供此变量时立即退出，默认 pytest 不执行原清理逻辑。这些测试会清理指定测试库的用户和 Item，不能对业务库运行。本次未执行该模式。

原 CI 测试脚本已接入新入口：先运行离线测试，再针对 CI 创建的临时库运行 `tests/ --run-postgres-tests` 并追加覆盖率。没有把业务逻辑排除出覆盖率；单独排除 `app/alembic/*`，因为离线迁移链解析会导入所有历史 revision，而迁移是否正确由专门的 SQL/结构测试验证。本地离线模式没有覆盖原 PostgreSQL 集成流程，不能宣称已通过 CI 的整体 90% 覆盖率门槛。

已完成独立只读代码审查。审查发现原 CI 入口需要接入新测试保护机制，已修正并补充先失败后通过的入口回归测试；离线连接保护测试也已按运行模式区分。审查未发现工单模型、权限或状态流转的阻塞问题。真实 PostgreSQL 与并发锁行为仍按下列待验证事项交付。

## 数据库待验证事项

V1 本地提交基线（2026-10-26）：已完成复验，**106 passed、58 skipped**；新增 8 项临时文件 SQLite 持久性测试使用 NullPool、每请求独立 Session 和请求后新连接。commit→flush 故障注入使 6 项 CRUD 持久性测试按预期失败，正常 commit 恢复后通过；Ruff、mypy（23 个文件）、ty 通过。本次提交不重复执行已完成的 V1 审查。

仍保留：真实 PostgreSQL 测试和并发/迁移验证未执行；整体 CI 90% 覆盖率门槛未验证通过；授权前行锁 Low 问题未改动；锁定 Starlette 的 TestClient 弃用警告未消除。

- 在专用 PostgreSQL 测试库中确认基线 revision 为 `fe56fa70289e`，再验证升级至 `a7b8c9d0e1f2` 及回滚。降级会删除工单表；仅在可丢弃测试库演练。
- 核对真实 PostgreSQL 的 UUID、TIMESTAMPTZ、VARCHAR 长度、CHECK 和外键级联行为，以及 Alembic 与 SQLModel 的结构差异。
- 两个并发 PATCH 的行锁和事务行为；SQLite 不提供 PostgreSQL 的行锁语义。
- 在专用测试库运行原 58 项测试和工单接口流程，确认旧认证、用户、Item 的 PostgreSQL 回归。
- SQLite 迁移测试从临时模拟的旧表结构开始，并未执行包含 PostgreSQL 专属语法的全部历史迁移。现有数据库的真实 revision、历史数据、权限和完整迁移链未核查。

## 建议重点学习的核心代码

1. **先看 `app/models.py` 的 TicketCreate、TicketUpdate、TicketPublic。** 学习为什么表模型和输入输出模型要分开；`Field` 限制、枚举、去空白、拒绝额外字段分别在解决什么问题。
2. **再看 `update_ticket()`。** `model_dump(exclude_unset=True)` 保留 PATCH 的“未提交”语义；显式 `null` 由校验器拒绝。状态规则在写入前检查，数据库事务在 `commit()` 时提交。
3. **看 `_get_ticket()` 和 `read_tickets()`。** 前者处理详情、修改、删除的 404/403，后者对查询和 count 同时加 owner 条件；owner 从登录用户获取而非请求输入。
4. **跟踪 `CurrentUser -> get_current_user -> get_db`。** 理解依赖注入如何组合 JWT、用户有效性检查和数据库会话；测试为什么只替换 get_db 而仍能验证真实认证。
5. **对照 `test_status_transition_matrix()` 与迁移测试。** 学习用矩阵固定所有合法/非法流转，用真实副作用断言“失败没有偷偷写入”，以及区分 SQLite 测试与 PostgreSQL 验证的证据边界。

测试隔离方式参考 [SQLModel 官方测试教程](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/)；依赖覆盖方式参考 [FastAPI 官方说明](https://fastapi.tiangolo.com/advanced/testing-dependencies/)。
