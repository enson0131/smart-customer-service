# 云杉生活 · AI 售后服务台

基于 FastAPI、LangGraph、LangChain 和 DeepSeek 的中文售后演示。每个浏览器会话有三笔虚构订单，分别覆盖可退款、超过期限和尚未签收。退款只登记为「已受理（模拟）」。

## 本地体验

需要 Python 3.12、uv 和非空的 DEEPSEEK_API_KEY。启动时从环境变量或项目根目录的 .env 读取密钥。在项目根目录运行：

```sh
uv sync --locked --python 3.12
uv run uvicorn service.app:app --host 127.0.0.1 --port 8000
```

打开 [服务台](http://127.0.0.1:8000/) 或 [交互式 API 文档](http://127.0.0.1:8000/docs)。点击「查看我的订单」，选择云杉阅读灯，输入「这单能退吗」，核对金额后点击「确认提交」。刷新页面，点击「查询退款进度」即可查看申请。清除访客 Cookie 会开始一个新的演示身份。

政策问答按标题和段落索引 `knowledge/` 下的 Markdown 和 TXT，以中文二元组 BM25 检索并展示原文。更新文件后重启服务。若修改实际退款期限，同时更新`constants/` 中的 `RETURN_WINDOW_DAYS`、知识库政策与测试。

在本地已忽略的 `.env` 中设置下列变量，然后重启：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

模型名由 `constants/__init__.py` 中的 `DEEPSEEK_MODEL` 指定。首次启动会初始化本地 SQLite。运行 `uv run python -m unittest discover -s tests -v` 可验证工具执行、跨轮续办和退款确认。

## 分层架构

![AI 售后客服系统五层架构，从上到下依次为意图识别层、模型编排层、模型层、领域能力层和存储层](docs/architecture.svg)

| 职责 | 代码入口 | 负责的决定 |
| --- | --- | --- |
| 意图识别 | `service/intent/` · `workers/intent/` | 精确匹配完整指令或按钮操作，其他请求进入客服 Agent。 |
| 模型编排 | `service/orchestration/` · `workers/orchestration/` | LangGraph 分流；LangChain create_agent 管理模型和工具之间的消息循环。 |
| 模型接入 | `service/model/` · `workers/model/` | 通过 LangChain 初始化 DeepSeek、绑定工具、发起工具选择和基于资料的回答生成。 |
| 领域能力 | `service/domain/` · `workers/domain/` | 定义工具，查询模拟履约、物流轨迹与签收回执，检索政策并核验退款资格。 |
| 存储 | `service/storage/` · `workers/storage/` | 通过 SQLite 或 Cloudflare D1 保存访客会话、对话记录、订单、退款申请和待续办任务。 |

本地 FastAPI 使用 Python。免费 Workers 使用 TypeScript 的 `createAgent`，由 HTTP 入口匹配按钮和完整指令，自由输入交给原生 Agent。两端共用网页、知识库和 SQL 表结构。以下流程图由 Python 实现导出。

### LangGraph 执行流程

![精确规则与可恢复的 ReAct 循环](docs/chat-flow.svg)

流程图由编译后的 LangGraph 直接导出，虚线表示条件边。修改节点或边后，在项目根目录重新生成 [Mermaid 源文件](docs/chat-flow.mmd)：

```sh
uv run python -m scripts.export_flow
mmdc -i docs/chat-flow.mmd -o docs/chat-flow.svg
```

第二条命令使用 Mermaid CLI 渲染 SVG。导出图结构无需启动服务或调用 DeepSeek。

1. 外层 LangGraph 在 `intent` 分流。精确命中规则走 `direct`，自由输入交给 `create_agent` 创建的子图。
2. Agent 接收系统提示和最近六轮对话的 `HumanMessage / AIMessage`。模型发起工具调用后，框架执行工具并追加 `ToolMessage`；模型根据实际结果继续调用工具或直接回答。工具返回的正文只含业务事实，订单卡片和确认票据保存在 `artifact` 中。一次提出多个工具时，每次放行一个，避免并发选择订单或生成多张退款卡。原生中间件限制每次运行的模型调用次数。
3. 缺订单或需要澄清时，工具调用 `interrupt()`。服务校验选单归属，通过同一访客的 `thread_id` 和 `Command(resume=...)` 继续这次工具调用，随后由 Agent 处理剩余诉求。未完成任务持久化到 SQLite 或 D1。
4. 外层将消息和业务结果组装成网页回复并保存本轮记录。退款确认仍使用独立 HTTP 接口，Agent 没有提交退款的工具。

| 在网页输入 | 可以观察到的行为 |
|---|---|
| 查一下这单的物流 | 选单后返回该单的模拟轨迹。 |
| 帮我查物流，再看看能不能退 | 指代不明时先选单，随后在同一次续办中展示物流及退款资格，符合条件时展示确认卡。 |
| 我的包裹为什么还没到 | 模型可先查轨迹，再根据观察查询仓库交运记录或签收回执。当前数据均为演示记录。 |

## 查看任务流转日志

本地每次聊天请求返回（含等待选单）或报错时，服务会将当前 `data/logs/tasks.jsonl` 自动格式化到 `data/logs/tasks.pretty.json`。阅读副本按时间顺序排列并沿用原日志的脱敏结果；轮转前的记录可从 `tasks.jsonl.1` 等备份查看。

开发人员可按问题发生时间和事件类型在服务端日志中定位请求，再用该行的 `task_id` 查询完整流程。用户选单、刷新候选项或重启服务后恢复中断时，沿用同一编号。

在项目根目录执行：

```sh
# 实时查看本地流转
tail -f data/logs/tasks.jsonl

# 将编号替换为服务端日志中的 task_id，同时搜索最近的轮转文件
rg --fixed-strings '粘贴任务日志编号' data/logs/
```

每行是一条 JSON 事件。`model.proposals` 是模型实际提出的工具；`tool.request` 给出实际执行的工具和参数；`tool.result` 是工具实际返回的状态。看到 `task.wait` 表示正在等人，`task.resume` 表示收到补充输入。LangGraph 恢复时会重放中断节点，因此同一任务中可能再次出现相同的工具观察。异常可查看 `decision.error` 或 `request.error` 的错误类型。

本地日志每个文件最大 5 MiB，保留 3 份备份。Cloudflare D1 模式下同样的 JSON 事件写到容器标准输出。详细日志包含聊天正文。`chat.request/response` 对应聊天接口输入和页面回复，`tool.request/result` 对应工具参数、事实和组件结果，`model.request` 包含实际发送给模型的消息批次（含 system Prompt）及模型、工具定义等调用参数，`model.response` 包含回复正文、工具调用、结束原因和返回的 token 用量。按 `call_id` 配对同一次模型请求和响应。详情仅写入开发日志，过往事件不会补录。认证头不参与采集，访客标识和退款票据在落盘前脱敏。

```sh
# 用 jq 展开一条任务的多行 Prompt 和结构化入参、出参
jq 'select(.task_id == "替换为任务编号" and (.event | startswith("model.")))' data/logs/tasks.jsonl
```

## HTTP 接口

除健康检查外，客户端需保存并回传服务端签发的 HttpOnly 访客 Cookie。

| 方法 | 路径 | 输入与结果 |
| --- | --- | --- |
| GET | /health | 进程就绪状态 |
| GET | /api/orders | 当前访客订单，金额以分为单位 |
| POST | /api/chat | 输入 `{"message":"查看我的订单"}`，返回正文、来源及可选的订单列表或确认卡 |
| POST | /api/refunds/confirm | 输入确认卡的 `{"ticket":"P-…"}`，返回申请编号和状态，重复确认返回原申请 |
| GET | /api/refunds/{id} | 当前访客的申请详情 |

提交取消消息或重新选择订单会作废旧确认卡。确认时数据库再次检查归属、签收日期和有效票据，每笔订单最多创建一个退款申请。演示访客身份仅适合虚构数据。

## Cloudflare Workers 免费版与 D1

正式环境使用 TypeScript Worker、静态资源绑定和 D1。Workers Builds 连接 GitHub 仓库，项目名填 `smart-customer-service`，生产分支为 `main`，根目录为仓库根目录。Build command 留空，Deploy command 填 `npx wrangler@4.151.0 deploy`。Wrangler 的构建钩子会用 Python 标准库读取 `knowledge/` 的 Markdown 和 TXT 并生成检索索引。

```sh
npm ci
python3 -m scripts.worker_knowledge
npm run check
npx wrangler@4.151.0 d1 execute smart-customer-service-db --remote --file service/storage/schema.sql
npx wrangler@4.151.0 secret put DEEPSEEK_API_KEY
npx wrangler@4.151.0 secret put DEEPSEEK_BASE_URL
npx wrangler@4.151.0 deploy
```

首次在其他账户部署时先创建 D1，在 Wrangler 配置中替换账户和数据库 ID。DeepSeek 使用 Worker 运行时 Secrets，模型名在 `workers/constants/`。订单、模拟退款和 LangGraph 检查点通过 D1 绑定读写。选单后继续同一访客线程，确认接口会重新核验订单与票据。[Cloudflare Workers Builds](https://developers.cloudflare.com/workers/ci-cd/builds/) · [D1 Workers Binding](https://developers.cloudflare.com/d1/worker-api/d1-database/)
