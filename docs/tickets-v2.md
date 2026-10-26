# 工单 AI 分析 V2

## 范围与实现约定

从 V1 本地提交 `04811f5` 创建 `codex/ticket-ai-analysis-v2`；本轮按用户要求将完成检查的 V2 提交到本地，不推送或合并。只增加 `POST /api/v1/tickets/{ticket_id}/ai-analysis`。沿用 JWT、活跃用户检查、工单 owner/管理员权限；先鉴权和查工单，提取标题/描述快照并结束只读事务、释放数据库连接，再创建 SDK 客户端。只返回建议，不修改工单，不新增数据库表或迁移。

模型适配使用 OpenAI Python SDK 的 Chat Completions，对接千问兼容地址；独立服务负责提示词、JSON 输出、Pydantic 校验和错误转换。默认模型 `qwen-plus`，可配置模型、地域地址和超时。分类默认 `account / billing / technical / other`；建议优先级沿用 `low / medium / high / urgent`。固定响应字段：`category`、`summary`、`suggested_priority`、`suggested_reply`。

SDK 自动重试关闭，单次请求默认超时 15 秒。缺少服务密钥返回 503、上游超时 504、上游限流 429、其他上游错误或无效输出 502；响应不回传上游异常正文、密钥或内部 URL。模型只收到工单标题和描述。工单文本按不可信数据处理；提示词要求只输出 JSON、遵守指定字段，不执行工单中的指令。所有建议均须人工判断。

## 实施与验证计划

1. 新增服务配置与 SDK 锁定依赖；先写 API 权限、只读响应和服务异常的 Mock 测试并确认失败。
2. 实现独立 Pydantic 输出模型、服务适配与路由。测试 SDK 请求参数、输出字段/枚举/长度校验、空输出、错误 JSON、超时、限流、上游失败和缺少密钥。
3. 使用临时文件 SQLite 验证 AI 成功/失败均不修改工单；未授权、越权、工单不存在时 SDK 不调用。
4. 运行全量离线 pytest、Ruff、mypy、ty；记录真实 API 和 PostgreSQL 待验证项，不修改 CI 90% 门槛，不扩展覆盖率排除。

自动化测试不使用 Docker、真实数据库或真实模型调用；用户自行完成的真实千问联调另见下文。不开发前端，不修改 V1 行锁规则。

## 使用与配置

请求无需 body；沿用 `Authorization: Bearer <access_token>`。普通用户只能分析自己的工单，管理员可分析全部工单。

```http
POST /api/v1/tickets/工单UUID/ai-analysis
Authorization: Bearer <access_token>
```

示例响应：

```json
{
  "category": "technical",
  "summary": "用户无法登录，需要排查登录流程。",
  "suggested_priority": "high",
  "suggested_reply": "您好，请提供错误提示，我们会协助排查。"
}
```

通过进程环境或本地私有配置提供以下设置。仓库现有 `.env` 是已跟踪文件，**不要把真实密钥写入该文件或提交到 Git**；本次没有读取、写入或提交真实 API 密钥。

| 设置 | 默认/规则 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 可选，未配置时应用仍可启动，授权后的分析请求返回 503；以 SecretStr 保存 |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1`；可替换为对应地域/业务空间的兼容地址 |
| `QWEN_MODEL` | `qwen-plus`，1–128 字符，不能全为空白 |
| `QWEN_TIMEOUT_SECONDS` | 15，必须大于 0 且不超过 120，禁止 NaN/Infinity；这是 SDK 网络超时设置 |

只返回四个字段，额外字段、未知分类/优先级、缺失字段、空字符串、错误 JSON、Markdown 包裹 JSON、被截断或拒绝的响应均作为无效输出拒绝。summary 最大 2000 字符，suggested_reply 最大 5000 字符。模型最大输出 1500 tokens，SDK 自动重试为 0，避免隐式重复计费；客户端可以在适当时机手动重新请求。

401/403/404/422 沿用 V1 鉴权、工单权限和 UUID 校验；它们优先于模型配置与调用。上游异常只转换为固定公开消息，不返回上游正文、密钥或配置地址。模型返回内容只是文字建议，不执行工具、退款、发送消息或修改数据库。

实现参考 [OpenAI Python SDK 官方说明](https://developers.openai.com/api/reference/python) 与 [阿里云千问兼容 API 文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。默认经典域名仍被官方支持；新业务空间域名可通过 `QWEN_BASE_URL` 配置。JSON 模式显式使用 `response_format={"type":"json_object"}`、包含 JSON 指令的提示词和 `enable_thinking=false`。

## 修改文件

- `backend/app/api/routes/tickets.py`：新增 AI 分析路由，先复用工单权限检查，再调用服务并转换固定错误。
- `backend/app/core/config.py`：新增千问密钥、地址、模型、网络超时设置。
- `backend/app/services/__init__.py`、`backend/app/services/ticket_ai.py`：独立服务、Pydantic 输出模型、提示词、SDK 调用和错误分类。
- `backend/pyproject.toml`、`uv.lock`：只新增 OpenAI SDK 及其必要依赖，锁定 SDK 2.54.0；兼容当前 HTTPX，无需修改旧测试依赖。
- `backend/tests_offline/test_ticket_ai.py`：Mock SDK 与真实 SDK + MockTransport 测试，复用文件 SQLite 夹具。
- `docs/tickets-v2.md`：本说明。

## 可执行验证与限制

在 backend 目录执行：

```powershell
uv run --frozen --package app pytest -q --tb=short
uv run --frozen --package app ruff check .
uv run --frozen --package app ruff format app conftest.py tests_offline tests/conftest.py scripts/test_backend.py --check
uv run --frozen --package app mypy app scripts/test_backend.py tests_offline/conftest.py tests_offline/test_tickets.py tests_offline/test_ticket_ai.py
uv run --frozen --package app ty check app scripts/test_backend.py tests_offline/conftest.py tests_offline/test_tickets.py tests_offline/test_ticket_ai.py
```

2026-10-26 最终结果：**154 passed、58 skipped**，其中 V2 新增 **48 项**；Ruff 检查和格式（33 文件）、mypy（26 个源文件）、ty 均通过。独立 V2 审查发现推理期间不应占用数据库连接；新增真实连接池事件断言，确认修复前失败，复制文本后 rollback 只读事务释放连接，再调用模型，回归与全量测试通过。保留一条 V1 已存在的 Starlette TestClient 弃用警告。未改变 CI 90% 门槛或覆盖率排除。

## 2026-10-26 真实联调与回复事实边界改进

用户反馈已在 VS Code PowerShell 通过现有服务层完成一次真实千问调用，虚构工单为“会员支付成功，但账户权益没有开通”。`category`、`summary`、`suggested_priority`、`suggested_reply` 四字段通过 Pydantic 校验。这验证了当次配置下的真实 API 连通性和响应结构，不等于 HTTP 路由、全部模型/地域或回答事实准确性已经验证。未在仓库中保存密钥或包含敏感信息的原始日志。

本次发现：`suggested_reply` 编造了“已核实支付记录”“5分钟生效”和人工开通承诺。系统实际没有查询订单、支付或会员数据库，也没有执行这些操作的工具。原 Prompt 对“仅给建议”的约束不足以防止模型生成客服惯用的无依据承诺；Pydantic 校验仅约束结构、类型、长度和枚举，无法证明上述语义为真。

最小改进仅修改服务层 `SYSTEM_PROMPT`：

- 明确系统未查询相关数据库、没有退款/开通/派单工具；用户陈述不是已核实事实，摘要和回复都须保留这一边界。
- 禁止编造已完成操作、核实结果、处理进度、时效和人工处理结果承诺，不能用“预计”“通常”等词绕过。
- 使用中性可核实措辞，例如：“您反馈已支付但会员权益尚未开通。目前无法确认支付状态和权益状态；建议提供订单号，由具备查询权限的客服核查。”
- 不变更 API、数据库、输出结构、SDK 参数或业务流程，不增加输出重写/关键词拦截等新功能。

新增回归测试使用普通工单和要求编造承诺的对抗文本，检查实际 SDK 请求的 system 消息包含事实边界和回复约束，同时确保工单内容只出现在 user 消息中、JSON 输出模式不变。测试先失败，再随 Prompt 修改通过。Mock 响应不是模型遵守指令的证据。

本次改进后复验：**156 passed、58 skipped**，V2 共新增 50 项测试；Ruff 检查/格式、mypy（26 个文件）、ty 通过。仅新增两项 Prompt 传递回归用例，未修改 API、数据库和四字段输出结构。既有 TestClient 弃用警告继续保留。

**可靠性局限：** Prompt 是概率性约束，无法保证每次响应都遵守，也不能抵御所有提示注入。只要四字段格式合法，含虚假承诺的文本仍可能通过当前 Pydantic 模型。建议必须由具备实际信息的人员审核，不能视为已核实记录或处理结果。本轮未再次发起真实千问调用，因此新版 Prompt 的真实生成效果仍待验证；没有声称此问题已被确定性消除。

继续未验证：真实延迟/超时/限流、多次/对抗输入下的回答质量、真实 PostgreSQL 集成和既有 58 项测试；SDK Mock 与 MockTransport 不能代替这些验证。V1 的真实迁移、并发行锁、授权前行锁 Low 和整体 CI 覆盖率待验证项继续保留。V2 没有新增数据库表或迁移，不连接现有数据库。
