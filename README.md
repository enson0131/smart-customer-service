# AI 售后服务

基于 FastAPI、LangGraph、LangChain 和 DeepSeek 的中文售后演示。每位访客有三笔虚构订单，分别覆盖可退款、超过期限和尚未签收。退款只登记为「已受理（模拟）」。

## 本地体验

需要 Python 3.12、uv 和非空的 DEEPSEEK_API_KEY。启动时从环境变量或项目根目录的 .env 读取密钥。在项目根目录运行：

```sh
uv sync --locked --python 3.12
uv run uvicorn service.app:app --host 127.0.0.1 --port 8000
```

打开 [服务台](http://127.0.0.1:8000/) 或 [交互式 API 文档](http://127.0.0.1:8000/docs)。点击「查看我的订单」，选择云杉阅读灯，输入「这单能退吗」，核对金额后点击「确认提交」。刷新页面，点击「查询退款进度」即可查看申请。左侧点击「开启新对话」进入空白页，发送首条消息时创建独立聊天；在「历史会话」列表中可切换并恢复之前的对话，刷新后恢复当前标签页选中的聊天。清除访客 Cookie 会开始一个新的演示身份。

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
| 意图识别 | `service/intent/` | 精确匹配完整指令或按钮操作，其他请求进入客服 Agent。 |
| 模型编排 | `service/orchestration/` | 按 chat_id 隔离 LangGraph 线程；LangChain create_agent 管理模型和工具之间的消息循环。 |
| 模型接入 | `service/model/` | 通过 LangChain 初始化 DeepSeek、绑定工具、发起工具选择和基于资料的回答生成。 |
| 领域能力 | `service/domain/` | 定义工具，查询模拟履约、物流轨迹与签收回执，检索政策并核验退款资格。 |
| 存储 | `service/storage/` | 通过 SQLite 保存访客、独立聊天及其消息与上下文；订单和退款归访客，检查点归聊天。 |

### 访客与聊天隔离

- `visitor_id`：由服务端签发，浏览器通过 HttpOnly Cookie 自动携带，仅用于识别访客及校验聊天、订单和申请归属。
- `chat_id`：由 `POST /api/chats` 创建，前端在聊天及退款确认请求中显式传入，作为 LangGraph 的 `thread_id`。后端校验归属后才读取或恢复检查点。
- `chats` 保存各聊天的选中订单、话题、退款原因和确认票据；`chat_messages` 保存各聊天的消息及页面回复。模型只读取本聊天最近六轮摘要，确认票据不进入模型历史。
- 同一访客可有多个聊天同时等待选单；恢复或取消其中一个，不改变其他聊天的消息、选单和检查点。订单及真实业务状态仍共享，同一订单最多生成一笔退款申请。
- 页面用 `sessionStorage` 保存当前标签页选中的 `chat_id`，新建聊天后不影响其他标签页。打开同一个聊天的两个标签页仍共享该聊天。

例如：聊天 A 发起“查物流，再看看能不能退”后等待选单，此时新建聊天 B 查询另一笔订单。切回 A 后仍显示 A 的候选项；选单恢复只向 A 的检查点提交 `Command(resume=...)`。

仅维护当前版本的数据结构，使用按当前 schema 初始化的 SQLite 数据库，不提供旧版本数据迁移或兼容逻辑。

### LangGraph 执行流程

![精确规则与可恢复的 ReAct 循环](docs/chat-flow.svg)

流程图由编译后的 LangGraph 直接导出，虚线表示条件边。修改节点或边后，在项目根目录重新生成 [Mermaid 源文件](docs/chat-flow.mmd)：

```sh
uv run python -m scripts.export_flow
mmdc -i docs/chat-flow.mmd -o docs/chat-flow.svg
```

第二条命令使用 Mermaid CLI 渲染 SVG。导出图结构无需启动服务或调用 DeepSeek。

1. 外层 LangGraph 在 `intent` 分流。精确命中规则走 `direct`，自由输入交给 `create_agent` 创建的子图。
2. Agent 接收系统提示和最近六轮对话的 `HumanMessage / AIMessage`。模型发起工具调用后，框架执行工具并追加 `ToolMessage`；模型根据实际结果继续调用工具或直接回答。工具返回的正文只含业务事实，订单卡片和确认票据保存在 `artifact` 中。当前 create_agent 原生 ToolNode 会分发同批的多个调用，因此按单一职责使用三个原生钩子：`after_model` 保存模型提出的新批次并放行首项，`before_model` 用 `jump_to="tools"` 续派剩余项，`wrap_model_call` 只处理模型异常与重试。剩余调用保存在 AIMessage 的 `additional_kwargs.pending_tool_calls` 中，随原生 checkpoint 持久化。工具执行、参数校验、中断和恢复仍由框架负责。批次未完成时，中间件直接放行下一项，不请求模型、不丢弃调用；全部完成后才将所有 ToolMessage 交给模型统一回答。用户取消、改变问题或工具出错时停止旧批次，由模型重新判断。原生 ModelCallLimitMiddleware 限制实际模型调用次数，续派工具会跳过模型及其计数。
3. 缺订单或需要澄清时，工具调用 `interrupt()`。服务校验选单归属，通过该聊天的 `thread_id=chat_id` 和 `Command(resume=...)` 继续这次工具调用，随后继续批次中的剩余工具，空订单号使用刚选中的会话订单。未完成任务持久化到 SQLite。
4. 外层采用模型的最终回复，订单、来源和确认卡仍从后端工具结果生成，并保存本轮记录。退款确认仍使用独立 HTTP 接口，Agent 没有提交退款的工具。

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

每行是一条 JSON 事件。`model.proposals` 是模型实际提出的工具；`tools.dispatch` 是本次放行的工具及剩余批次；`tool.request` 给出实际执行的工具和参数；`tool.result` 是工具实际返回的状态。看到 `task.wait` 表示正在等人，`task.resume` 表示收到补充输入。LangGraph 恢复时会重放中断节点，因此同一任务中可能再次出现相同的工具观察。异常可查看 `decision.error` 或 `request.error` 的错误类型。

本地日志每个文件最大 5 MiB，保留 3 份备份。详细日志包含聊天正文。`chat.request/response` 对应聊天接口输入和页面回复，`tool.request/result` 对应工具参数、事实和组件结果，`model.request` 包含实际发送给模型的消息批次（含 system Prompt）及模型、工具定义等调用参数，`model.response` 包含回复正文、工具调用、结束原因和返回的 token 用量。按 `call_id` 配对同一次模型请求和响应。详情仅写入开发日志，过往事件不会补录。认证头不参与采集，访客标识和退款票据在落盘前脱敏。

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
| POST | /api/chats | 创建聊天，返回 `{"id":"C-…"}` |
| GET | /api/chats | 列出当前访客的聊天 |
| GET | /api/chats/{chat_id} | 返回本聊天消息及页面回复，校验访客归属 |
| POST | /api/chat | 输入 `{"chat_id":"C-…","message":"查看我的订单"}`，返回正文、来源及可选的订单列表或确认卡 |
| POST | /api/refunds/confirm | 输入确认卡的 `{"chat_id":"C-…","ticket":"P-…"}`，返回申请编号和状态，重复确认返回原申请 |
| GET | /api/refunds/{id} | 当前访客的申请详情 |

提交取消消息或重新选择订单只作废当前聊天的旧确认卡。确认时数据库再次检查归属、签收日期和有效票据，每笔订单最多创建一个退款申请。演示访客身份仅适合虚构数据。
