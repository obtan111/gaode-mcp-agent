# 云端 RAG 多工具私人智能助手

基于 **LangGraph + FastAPI + Vue 3** 的前后端分离智能助手，支持知识库检索（RAG）、
外部工具调用（MCP）、多模态输入（文本/图片/语音）与语音播报，专为旅游场景设计，
可作为通用个人助手使用。

> 技术栈：Python 3.11 · FastAPI · LangGraph · Supabase(pgvector) · Vue 3 · Vite

## 功能特性

### 智能对话
- ✅ **Agent 工作流**：LangGraph 状态机编排「意图分析 → 工具调用 → 回答生成」三个节点，工具调用自动循环直到完成
- ✅ **RAG 检索增强**：密集向量 + 关键词（ILIKE）混合检索，RRF 融合 + Cross-Encoder 重排
- ✅ **MCP 工具集成**：高德地图（POI/路线/天气）、时间查询、文件读写、日程待办、网页抓取、知识库检索
- ✅ **长期记忆**：会话摘要与用户画像提取，跨会话保留
- ✅ **多模型可选**：DeepSeek / DeepSeek 视觉 / 智谱 GLM-4 / GLM-4V 视觉

### 交互能力
- ✅ **流式输出**：SSE 事件流（节点状态 + 增量文本），生成期间纯文本展示、完成后 Markdown 排版
- ✅ **多模态输入**：图片上传（缩略图随消息展示）、语音输入（浏览器录音自动转 WAV 后识别）
- ✅ **语音播报**：每条助手回答可一键 TTS 播放（按消息缓存）
- ✅ **会话管理**：多会话、历史持久化、重命名、删除、Markdown 导出

### 知识库
- ✅ 文档上传向量化（txt / md / pdf / json / csv，≤50MB）
- ✅ 入库幂等：基于内容 MD5 去重，重复文件自动跳过
- ✅ 分片查看（列表轻量预览 + 点击查看完整内容）
- ✅ 检索调试面板：不经过 LLM，直接测试混合检索效果

---

## 技术架构

```
┌────────────────┐   HTTP/SSE   ┌─────────────────────┐   直接复用    ┌──────────────────┐
│   Vue 3 前端    │ ───────────▶ │     FastAPI 后端     │ ───────────▶ │    src/ 业务层    │
│ (Vite :5173)   │  开发代理    │   (uvicorn :8100)   │               │ AgentGraph / RAG │
│ 聊天/会话/知识库 │  /api → 8100 │ routers/schemas/    │               │ / MCP / CRUD     │
└────────────────┘              │ services            │               └──────────────────┘
                                └─────────────────────┘
                                │
                                ▼
                        Supabase (PostgreSQL + pgvector)
```

设计要点：

- **业务层独立**：`src/` 下的工作流/检索/工具代码不感知 Web 框架，可被任何入口复用；
- **会话无状态化**：历史消息每次从数据库加载，后端不存内存态（重启不丢、可水平扩展）；
- **流式协议统一**：前端只面对 `start/status/token/tts/done/error` 六种事件，
  伪流与真流的切换是后端内部实现细节（见「流式模式」）。

---

## 项目结构

```
私人助手项目/
├── backend/                  # FastAPI Web 后端
│   ├── main.py               # 入口（CORS、lifespan 预热、路由注册）
│   ├── core/deps.py          # 重型组件懒加载单例（import 零副作用）
│   ├── schemas/              # pydantic 请求/响应模型
│   ├── routers/              # chat(SSE) / sessions / kb / voice 路由
│   └── services/agent_runner.py  # 会话服务层（事件流桥接 + 持久化）
├── frontend/                 # Vue 3 前端（Vite）
│   ├── vite.config.js        # 开发代理 /api → 127.0.0.1:8100
│   └── src/
│       ├── App.vue           # 根组件（状态管理）
│       ├── api/              # chat.js(SSE解析) / sessions / kb / voice(webm→WAV)
│       └── components/       # Sidebar / ChatWindow / MessageItem / KbPanel
├── src/                      # 业务层（与 Web 框架解耦）
│   ├── agent/                # LangGraph 工作流（graph/nodes/state/memory）
│   ├── config/settings.py    # 配置类（环境变量驱动）
│   ├── database/             # Supabase 客户端 + CRUD
│   ├── llm/                  # 模型工厂 / 嵌入 / 语音（ASR+TTS）
│   ├── mcp/                  # 工具注册与各 MCP 工具实现
│   ├── rag/                  # 文档解析 / 切分 / 混合检索管道
│   └── utils/                # 日志 / 重试 / 异常 / 导出
├── scripts/                  # SQL 初始化与迁移脚本
├── knowledge/                # 知识库源文档（结构化 Markdown，入库后向量化）
├── tests/                    # pytest 测试
├── run_backend.bat           # 后端启动脚本（固定 Python 3.11）
├── requirements.txt
└── .env.example              # 环境变量模板
```

---

## 环境要求与配置

### 依赖

| 环境 | 版本要求 | 说明 |
| ---- | ---- | ---- |
| Python | **≥ 3.9**（推荐 3.11） | 低于 3.8 无法导入 `typing.TypedDict` |
| Node.js | ≥ 18（推荐 22） | 前端构建 |
| Supabase 项目 | 免费档即可 | 需启用 pgvector 扩展 |

> ⚠️ 若 `python` 指向 conda base（常见为 Python 3.7），请改用
> `conda activate assistant` 或直接使用 `run_backend.bat`（已固定解释器路径）。

### 1. 安装依赖

```bash
pip install -r requirements.txt          # 后端
cd frontend && npm install               # 前端（首次）
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填入真实 Key：

```bash
cp .env.example .env
```

| 变量 | 必填 | 说明 |
| ---- | ---- | ---- |
| `SUPABASE_URL` / `SUPABASE_KEY` | ✅ | Supabase 项目地址与 **service role** Key |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek 大模型 |
| `ZHIPU_API_KEY` | ✅ | 智谱大模型 + 嵌入 + 语音（ASR/TTS） |
| `AMAP_API_KEY` | 可选 | 高德地图工具（未配则工具调用自动跳过） |
| `MODEL_TEMPERATURE` | 否 | 默认 0.7 |
| `MAX_TOOL_CALLS` | 否 | 单轮工具调用上限，默认 10 |
| `CHAT_STREAM_MODE` | 否 | 流式模式，`updates`（默认）/ `multi`（见「流式模式」） |
| `LOG_LEVEL` | 否 | 默认 INFO |

其余切块/连接池等参数均有默认值，见 `.env.example` 注释。

### 3. 初始化数据库

在 Supabase Dashboard → SQL Editor 中依次执行：

1. `scripts/init_tables.sql` —— 建表（chat_session / documents / mcp_call_log / travel_plan）
2. 确认 `documents.vector` 列为 `vector(1024)`（与智谱 embedding-2 输出维度一致）。
   若表曾被重建为其他维度（如 1536），执行 `scripts/migrate_vector_to_1024.sql` 迁移，
   再运行 `python scripts/reembed_documents.py` 重嵌入存量分片。

---

## 快速开始

### 1. 启动后端

**Windows 一键启动**（推荐）：双击 `run_backend.bat`（自动检查解释器与依赖，
也可用 `run_backend.bat check` 做环境自检）。

**手动启动**：

```bash
python -m uvicorn backend.main:app --reload --port 8100
```

启动后验证：

- 接口文档：http://127.0.0.1:8100/docs （可在线调试所有接口）
- 健康检查：http://127.0.0.1:8100/api/health 应返回 `{"status":"ok"}`

### 2. 启动前端

```bash
cd frontend
npm install        # 首次
npm run dev
```

访问 http://localhost:5173 。开发期由 Vite 将 `/api` 请求代理到 8100 端口，
无需配置跨域。

### 3. 功能验证清单

按顺序验证，每条都对应可独立排查的链路：

| # | 操作 | 预期 | 排查入口 |
| - | ---- | ---- | ---- |
| 1 | 侧栏加载历史会话 | 出现数据库中的会话列表 | `/api/sessions` |
| 2 | 发一条消息 | 先「正在思考…」→ 流式文字 → 完成后 Markdown 排版 | `/api/chat/stream` |
| 3 | 问知识库相关的问题（如「长沙有什么好吃的」） | 回答引用知识库内容 | 知识库面板「检索调试」 |
| 4 | 上传一份文档到知识库 | 上传成功统计、分片出现在列表 | `/api/kb/{name}/documents` |
| 5 | 点助手消息的 🔊 | 播放语音、按钮变 ⏸ | `/api/voice/tts` |
| 6 | 点 🎤 说话 | 识别文本自动填入输入框 | `/api/voice/asr` |
| 7 | 上传图片后提问 | 用户气泡显示图片缩略图 | 请求体 `images` 字段 |

### 4. 命令行直接验证（可选）

```bash
# 流式对话
curl -N -X POST http://127.0.0.1:8100/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 上传文档到知识库
curl -X POST http://127.0.0.1:8100/api/kb/长沙攻略/documents \
  -F "files=@./长沙旅游.txt"

# 检索调试（不经 LLM）
curl -X POST http://127.0.0.1:8100/api/kb/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "长沙美食", "top_k": 3}'
```

> 注：Windows 下 curl 传中文 JSON 易被 shell 编码破坏，建议用
> `--data-binary @file.json` 方式发送。

---

## Docker 部署

### 本地/服务器一键部署

前提：服务器已安装 Docker 与 Docker Compose（v2+）。

```bash
# 1. 获取代码
git clone https://github.com/obtan111/gaode-mcp-agent.git
cd gaode-mcp-agent

# 2. 配置密钥（与本地开发同一份模板）
cp .env.example .env
#    编辑 .env 填入 SUPABASE_URL/KEY、DEEPSEEK_API_KEY、ZHIPU_API_KEY 等

# 3. 构建并启动（首次构建约 5-10 分钟，主要耗时在 torch）
docker compose up -d --build

# 4. 访问
#    http://<服务器IP>:18080
```

常用运维命令：

```bash
docker compose ps                  # 容器状态（backend 应为 healthy）
docker compose logs -f backend     # 跟踪后端日志
docker compose down                # 停止
docker compose up -d --build       # 更新代码后重建
```

### 架构说明

| 容器 | 镜像 | 职责 |
| ---- | ---- | ---- |
| `frontend` | node 构建阶段 → nginx:alpine | 托管前端静态资源 + `/api` 反向代理 |
| `backend` | python:3.11-slim + uvicorn | FastAPI 业务服务（不对外暴露端口） |

- 唯一对外入口是 Nginx 的 **18080** 端口（8080 常被 Dify 等占用）；
- 前后端同源，生产环境天然无 CORS 问题；
- Nginx 已针对 SSE 关闭代理缓冲（`proxy_buffering off`）并放宽超时（300s），
  上传体积上限 60MB；
- 密钥通过 `env_file` 注入容器，**不进入镜像**（`.dockerignore` 已排除 `.env`）。

### 注意事项

1. **防火墙/安全组**：放行 18080 端口（云服务器还需在控制台安全组中配置）；
2. **HTTPS**：如需域名 + HTTPS，推荐在前面再叠一层 Caddy：
   ```
   your.domain.com {
       reverse_proxy 127.0.0.1:18080
   }
   ```
   Caddy 自动申请续期证书，两行配置完事；
3. **镜像加速**：Dockerfile 内已配置清华 PyPI 镜像与 HF 镜像
   （`HF_ENDPOINT=https://hf-mirror.com`，供 Cross-Encoder 首次下载）；
4. **数据持久化**：会话与知识库数据存于 Supabase 云端，容器本身无状态，
   重建/升级不丢数据。

---

## API 参考

### 接口一览

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/api/chat` | 一次性完整回答（JSON，非流式兜底） |
| POST | `/api/chat/stream` | **SSE 流式回答（推荐）** |
| GET | `/api/sessions` | 会话列表（`include_messages=true` 可带消息体） |
| POST | `/api/sessions` | 新建会话 |
| GET | `/api/sessions/{id}` | 会话详情（含历史消息） |
| PATCH | `/api/sessions/{id}` | 重命名会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| GET | `/api/kb` | 知识库名称列表 |
| POST | `/api/kb/{kb_name}/documents` | 上传文档并向量化（multipart，多文件） |
| GET | `/api/kb/{kb_name}/documents` | 分片列表（300 字预览 + `content_len`，30s 缓存） |
| GET | `/api/kb/documents/{id}` | 单分片完整内容（按需加载） |
| DELETE | `/api/kb/{kb_name}` | 删除知识库 |
| POST | `/api/kb/retrieve` | 检索调试（直连混合检索管道） |
| POST | `/api/voice/tts` | 文本 → 语音（返回 data URI） |
| POST | `/api/voice/asr` | 音频文件 → 文本（multipart） |
| GET | `/api/health` | 健康检查 |

### SSE 事件协议（`/api/chat/stream`）

事件以 `event: <name>\ndata: <json>\n\n` 帧格式推送，协议定义见
`backend/services/agent_runner.py` 的 `iter_chat_events`：

| 事件 | 数据字段 | 含义 |
| ---- | ---- | ---- |
| `start` | `session_id` | 会话就绪（空 ID 自动新建） |
| `status` | `node` | 节点切换：`llm_inference` / `tool_execution` / `answer_generation` |
| `token` | `delta` | 回答增量文本 |
| `tts` | `audio` | 语音 data URI（请求体 `tts: true` 时） |
| `done` | `session_id, answer, elapsed_ms` | 生成完成（完整回答收尾，前端在此切 Markdown） |
| `error` | `message` | 出错信息 |

### 请求体格式（`/api/chat` 与 `/api/chat/stream` 一致）

```json
{
  "message": "用户消息",
  "session_id": null,
  "model_type": "deepseek",
  "images": ["data:image/jpeg;base64,..."],
  "tts": false
}
```

---

## 流式模式

由环境变量 `CHAT_STREAM_MODE` 控制（`.env`）：

| 模式 | 行为 | 适用 |
| ---- | ---- | ---- |
| `updates`（默认） | 节点状态事件 + 回答切片伪流 | 任何依赖版本组合，稳定 |
| `multi` | 尝试 messages 模式拿真实 token，失败自动降级重跑 | 等上游兼容修复后启用 |

> ⚠️ 已知问题：langgraph 1.2.x + langchain-core 1.4.x 组合下 messages 流模式存在
> 上游缺陷（`AIMessage.generation_info` 崩溃，升级至 1.6.0 亦复现）。
> 默认模式不受影响；`multi` 模式开启后每次请求会先失败再降级（多消耗一次调用），
> 建议暂不启用。前端协议不感知差异，未来切换无需改前端。

---

## 数据库设计

### chat_session 表

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| id | UUID | 主键 |
| title | VARCHAR(255) | 会话标题（首条用户消息自动生成） |
| summary | TEXT | 会话摘要 |
| messages | JSONB | 消息列表 |
| created_at / updated_at | TIMESTAMP | 时间戳 |

### documents 表

| 字段 | 类型 | 说明 |
| ---- | ---- | ---- |
| id | UUID | 主键 |
| content | TEXT | 分片内容 |
| vector | `vector(1024)` | 向量（智谱 embedding-2，**1024 维**） |
| content_hash | VARCHAR(32) | 内容 MD5（去重，有索引） |
| filename | VARCHAR(255) | 文件名 |
| page_number | INTEGER | 页码 |
| category | VARCHAR(100) | 类别 |
| metadata | JSONB | 分片元数据（含 `embedding_vector` 历史副本，API 返回时剔除） |
| source_text | TEXT | 原始文本 |
| kb_name | VARCHAR(255) | 知识库名称 |
| created_at | TIMESTAMP | 创建时间 |

索引：`idx_documents_content_hash`（去重查询）、`idx_documents_vector`（ivfflat 余弦）、`idx_documents_kb_name`（知识库隔离）。

### mcp_call_log 表

工具调用日志：`tool_name` / `parameters`(JSONB) / `result`(JSONB) / `call_time` / `token_usage` / `session_id`。

### travel_plan 表

行程规划：`title` / `destination` / `days` / `budget` / `plan_data`(JSONB) / `weather_info`(JSONB)。

---

## 日志系统

- 日志按模块落盘到 `logs/` 目录（app / agent_graph / agent_nodes / crud / supabase_client / mcp_client / retrieval_pipeline / voice 等），排查时按模块名定位；
- 级别由 `LOG_LEVEL` 控制，数据库层带有重试与熔断日志；
- 检索管道每路（dense / bm25）独立输出命中数——**观测单路静默失效的关键入口**。

---

## 测试指南

```bash
pytest tests/                      # 全量
pytest tests/test_backend_api.py   # 后端契约冒烟（无需 API Key，适合 CI）
pytest tests/test_unit.py          # 单元测试
```

| 测试文件 | 覆盖内容 |
| ---- | ---- |
| test_backend_api.py | 路由契约（OpenAPI 断言）与请求校验 |
| test_config.py | 配置加载与验证 |
| test_database.py | 建表 SQL 与 schema 一致性 |
| test_crud.py | 数据库 CRUD（mock） |
| test_llm.py | 模型工厂与嵌入 |
| test_utils.py | 工具函数 |

> 已知遗留：`test_crud.py` 部分 mock 用例与当前 CRUD 流程（去重检查调用次数）不一致，
> `test_rag_mcp.py` 依赖真实网络环境——这些用例的修复不在当前清理范围内，见 git 历史记录。

---

## 常见问题

### Q1: 启动报 `ImportError: cannot import name 'TypedDict' from 'typing'`

当前 `python` 是 Python 3.7（常见于 conda base）。改用 3.9+ 环境，或直接运行
`run_backend.bat`（已固定 Python 3.11 路径）。

### Q2: `run_backend.bat` 报乱码或 `'o' 不是内部或外部命令`

脚本含中文且编码与系统 GBK 代码页冲突。本仓库脚本已为纯 ASCII + CRLF，
若自行修改请保持同样规范。

### Q3: 知识库上传报 `expected 1536 dimensions, not 1024`

`documents.vector` 列维度与嵌入模型不符。执行 `scripts/migrate_vector_to_1024.sql`
（Supabase SQL Editor）→ `python scripts/reembed_documents.py` 重嵌入。

### Q4: TTS 按钮报「语音合成失败」

- 智谱 TTS 输入硬限制 **1024 字符**（超长自动截断，不影响播放）；
- 合成长文本需数十秒，接口超时为 120s，请耐心等待按钮从 ⏳ 变回 🔊；
- 返回「语音合成结果为空」时检查智谱账户余额与语音服务状态。

### Q5: 数据库连接失败

检查 `.env` 的 `SUPABASE_URL` / `SUPABASE_KEY`（需 service role key），
或 Supabase 项目网络可达性。

### Q6: 上传重复文件会怎样

基于内容 MD5 自动去重，重复分片跳过插入；对知识库查询无影响。

---

## 技术栈

| 层 | 技术 |
| ---- | ---- |
| 前端 | Vue 3（组合式 API）、Vite、markdown-it、原生 SSE 解析 |
| 后端 | FastAPI、uvicorn、pydantic v2 |
| Agent | LangGraph、LangChain、MCP 协议（自研客户端） |
| 检索 | pgvector（余弦）、ILIKE 关键词、RRF 融合、sentence-transformers 重排 |
| 数据库 | Supabase（PostgreSQL + pgvector） |
| 语音 | 智谱 GLM-ASR / GLM-TTS（PCM→WAV 容器化包装） |
| 测试 | pytest |

---

## 许可证

本项目仅用于学习交流，API Key 请自行申请。

## 贡献

欢迎提交 issue 与 PR。提交前请确保 `pytest tests/test_backend_api.py` 通过。
