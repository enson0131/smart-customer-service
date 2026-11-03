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
| 意图识别 | `service/intent/` | 精确匹配完整指令；其他请求连同工具观察交给模型，每次校验一个动作。 |
| 模型编排 | `service/orchestration/` | LangGraph 调用意图识别，驱动 ReAct 循环，管理待选订单、任务恢复与回复汇总。 |
| 模型接入 | `service/model/` | 通过 LangChain 初始化 DeepSeek、绑定工具、发起工具选择和基于资料的回答生成。 |
| 领域能力 | `service/domain/` | 定义工具，查询模拟履约、物流轨迹与签收回执，检索政策并核验退款资格。 |
| 存储 | `service/storage/` | 通过 SQLite 或 Cloudflare D1 保存访客会话、对话记录、订单、退款申请和待续办任务。 |

### LangGraph 执行流程

![精确规则与可恢复的 ReAct 循环](docs/chat-flow.svg)

流程图由编译后的 LangGraph 直接导出，虚线表示条件边。修改节点或边后，在项目根目录重新生成 [Mermaid 源文件](docs/chat-flow.mmd)：

```sh
uv run python -m scripts.export_flow
mmdc -i docs/chat-flow.mmd -o docs/chat-flow.svg
```

第二条命令使用 Mermaid CLI 渲染 SVG。导出图结构无需启动服务或调用 DeepSeek。

1. `enter` 校验按钮或整句精确指令。例如“查看我的订单”直接进入 `act`，跳过模型决策。
2. 自由输入进入 `reason`。DeepSeek 根据原始请求、最近六轮对话、选中订单和已完成工具的观察，选择一个动作。每次 `act` 执行后带着新的事实回到 `reason`，所有诉求处理完毕后选择 `finish`。每个任务最多执行 8 次正常工具动作，重复动作、无效输出或模型异常会停止并提示未能继续核实。
3. 选单、澄清或需要用户重试时，`act` 调用 LangGraph 原生 `interrupt()` 返回提示。服务按访客身份设置 `thread_id`，下一条输入通过 `Command(resume=...)` 恢复同一执行。LangGraph 从被中断的节点开头重放，等待输入前的路径只读取业务数据。刷新后可用“查看我的订单”重新显示候选项；选单先校验候选范围和订单归属。
   本地使用官方 `SqliteSaver`，Cloudflare D1 使用同一 checkpointer 协议的 SQL 适配器。服务重启后仍可恢复；一轮完成后清理图检查点，对话摘要继续保存在 `chat_turns`。
4. `summarize` 根据已核实事实生成正文与页面卡片，`remember` 记录本轮对话。模型仅能预览退款；提交仍由独立确认接口执行。

| 在网页输入 | 可以观察到的行为 |
|---|---|
| 查一下这单的物流 | 选单后返回该单的模拟轨迹。 |
| 帮我查物流，再看看能不能退 | 指代不明时先选单，随后在同一次续办中展示物流及退款资格，符合条件时展示确认卡。 |
| 我的包裹为什么还没到 | 模型可先查轨迹，再根据观察查询仓库交运记录或签收回执。当前数据均为演示记录。 |

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

## Cloudflare Containers 与 D1

准备启用 Containers 的 Cloudflare 账户、Docker 引擎及 Wrangler 4.151.0。在项目根目录执行以下命令（也可使用 `npx wrangler@4.151.0` 代替 `wrangler`）：

```sh
wrangler login
wrangler d1 create spruce-aftercare-db
# 已部署的 D1 也需执行此幂等脚本，创建 graph_checkpoints 和 graph_writes 等表
wrangler d1 execute spruce-aftercare-db --remote --file service/storage/schema.sql
```

在 `wrangler.jsonc` 的 `vars` 中填写账户 ID 和创建命令返回的数据库 ID。容器通过 D1 HTTP API 使用同一份 SQL 表结构。创建仅授予目标账户 D1 编辑权限的 API Token，以 Worker Secret 保存。首次设置 Secret 若提示创建同名 Worker，可确认创建。

```sh
wrangler secret put D1_API_TOKEN
# 必填，更新密钥后重新启动容器以读取新值
wrangler secret put DEEPSEEK_API_KEY
wrangler deploy --dry-run
wrangler deploy
```

Worker 启动容器时传入数据库配置和 Secrets，等待 8080 端口就绪后转发同源请求。云端强制使用 D1，访客、选中订单和退款记录均跨容器重启保存。通过部署返回的 HTTPS 地址访问服务台，完成一次模拟退款，再次访问验证进度。容器本机文件仅存放静态网页与随镜像发布的知识库。

部署参考：[Cloudflare 容器与 Secrets](https://developers.cloudflare.com/containers/examples/env-vars-and-secrets/)、[D1 HTTP API](https://developers.cloudflare.com/d1/worker-api/rest-api/)。
