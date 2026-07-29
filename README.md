# 云端 RAG 多工具私人旅游智能助手

一个基于 LLM 的智能对话助手，支持多模态输入、知识库检索和外部工具调用，专为旅游场景设计。

**核心优化特性**：

- ✅ **RAG 入库幂等性**：基于内容 hash 的去重机制，避免重复文档
- ✅ **检索结果去重**：RRF 融合后自动去重，避免同一内容重复出现
- ✅ **智能切块策略**：针对 PDF、Markdown、JSON 等不同文档类型的专用切分规则
- ✅ **配置体系完善**：所有默认值统一走配置体系，支持环境变量覆盖
- ✅ **健壮的异常处理**：文件上传流程多层校验，提供详细的失败原因反馈
- ✅ **自适应 RAG 检索**：基于关键词快速判断是否需要知识库检索，避免不必要的 LLM 调用
- ✅ **会话缓存机制**：内存缓存 + 异步刷新，避免数据库操作阻塞 Gradio 队列
- ✅ **TTS 容错处理**：支持列表内容类型、空文本检测、绝对路径保存
- ✅ **电路断路器模式**：数据库连接失败时快速返回，不阻塞 UI
- ✅ **并发请求保护**：聊天请求加锁防止重复提交

---

## 目录

- [项目简介](#项目简介)
- [技术架构](#技术架构)
- [项目结构](#项目结构)
- [环境配置](#环境配置)
- [快速开始](#快速开始)
- [功能模块](#功能模块)
- [API 接口](#api-接口)
- [数据库设计](#数据库设计)
- [日志系统](#日志系统)
- [测试指南](#测试指南)
- [扩展开发](#扩展开发)
- [常见问题](#常见问题)

---

## 项目简介

本项目是一个模块化的智能旅游助手，具备以下核心能力：

1. **多模态交互**：支持文本、图片、语音输入输出
2. **RAG 检索增强**：基于向量数据库的知识库检索，支持密集向量和 BM25 混合检索
3. **外部工具调用**：集成高德地图、时间查询等外部服务
4. **智能行程规划**：结合多工具进行旅游行程规划
5. **会话管理**：支持多会话、历史记录持久化

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           前端层 (Gradio)                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ 聊天界面  │  │ 知识库管理│  │ 语音输入  │  │     图片上传         │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘  │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────┐
│                           应用层 (app.py)                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 界面组件    │  │ 会话管理    │  │ 多模态处理  │  │ 状态管理    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────┐
│                         智能代理层 (Agent)                             │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                      LangGraph 工作流                           │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌───────────────────┐   │  │
│  │  │ LLM推理节点 │───▶│ 工具执行节点 │───▶│   回答生成节点     │   │  │
│  │  │(意图识别)  │    │(MCP调用)    │    │(整合信息)         │   │  │
│  │  └─────────────┘    └─────────────┘    └───────────────────┘   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────┐
│                         工具层 (MCP)                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐   │
│  │ 高德地图 │  │ 时间查询 │  │ RAG检索  │  │    其他工具        │   │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────┘   │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────┐
│                         LLM 层                                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐    │
│  │  DeepSeek 模型   │  │   智谱 GLM-4     │  │  嵌入模型         │    │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘    │
└───────────────────────────┬───────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────┐
│                         数据层                                         │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    Supabase (PostgreSQL)                        │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────┐ │  │
│  │  │chat_session │  │  documents  │  │mcp_call_log│  │travel  │ │  │
│  │  │(会话记录)   │  │(向量文档)   │  │(调用日志)  │  │plan    │ │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────┘ │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 项目结构

```
私人助手项目/
├── app.py                    # Gradio 主应用入口
├── .env                      # 环境变量配置
├── requirements.txt          # Python 依赖列表
├── scripts/                  # SQL 初始化脚本
│   ├── init_tables.sql       # 创建所有表结构
│   ├── init_documents_table.sql        # 向量表结构
│   └── init_documents_table_fallback.sql  # JSONB 降级方案
├── src/                      # 源代码目录
│   ├── __init__.py
│   ├── agent/                # 智能代理模块
│   │   ├── __init__.py
│   │   ├── state.py          # 代理状态定义和操作函数
│   │   ├── graph.py          # LangGraph 工作流定义
│   │   ├── nodes.py          # 工作流节点实现
│   │   └── prompts.py        # 提示词模板
│   ├── config/               # 配置管理模块
│   │   ├── __init__.py
│   │   └── settings.py       # 配置类和验证逻辑
│   ├── database/             # 数据库模块
│   │   ├── __init__.py
│   │   ├── supabase_client.py # Supabase 连接池和断路器
│   │   ├── crud.py           # 数据库 CRUD 操作
│   │   ├── schema.py         # SQL 建表语句
│   │   └── pgvector_state.py # pgvector 可用性状态管理
│   ├── llm/                  # 大语言模型模块
│   │   ├── __init__.py
│   │   ├── model_factory.py  # 模型工厂（支持多种模型）
│   │   ├── embedding.py      # 嵌入模型工厂
│   │   └── speech.py         # 语音识别和合成
│   ├── mcp/                  # MCP 工具模块
│   │   ├── __init__.py
│   │   ├── mcp_client.py     # MCP 客户端框架
│   │   ├── amap_mcp.py       # 高德地图工具
│   │   ├── time_mcp.py       # 时间查询工具
│   │   └── rag_mcp.py        # RAG 检索工具
│   ├── rag/                  # RAG 检索模块
│   │   ├── __init__.py
│   │   ├── document_parser.py # 文档解析器工厂
│   │   ├── text_splitter.py  # 文本分割器
│   │   └── retrieval_pipeline.py # 检索管道（密集+BM25+RRF+重排）
│   └── utils/                # 工具函数模块
│       ├── __init__.py
│       ├── logger.py         # 日志配置
│       ├── retry.py          # 重试装饰器
│       ├── exception.py      # 自定义异常
│       └── formatter.py      # 格式化工具
├── tests/                    # 测试目录
│   ├── test_config.py        # 配置测试
│   ├── test_crud.py          # 数据库操作测试
│   ├── test_database.py      # 数据库连接测试
│   ├── test_llm.py           # LLM 调用测试
│   └── test_utils.py         # 工具函数测试
└── logs/                     # 日志输出目录
    ├── app.log               # 应用日志
    ├── agent_graph.log       # 代理图日志
    ├── supabase_client.log   # 数据库客户端日志
    └── ...                   # 其他模块日志
```

---

## 环境配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

创建 `.env` 文件，填写以下配置：

```env
# Supabase 数据库配置
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# 大语言模型 API Key
DEEPSEEK_API_KEY=your-deepseek-api-key
ZHIPU_API_KEY=your-zhipu-api-key

# 高德地图 API Key
AMAP_API_KEY=your-amap-api-key

# 模型参数
MODEL_TEMPERATURE=0.7

# RAG 参数
CHUNK_SIZE=512
CHUNK_OVERLAP=50
RETRIEVE_TOP_K=5
RRF_K=60
CROSS_ENCODER_THRESHOLD=0.5
MAX_TEXT_LENGTH=2000

# 按文档类型的切块参数
PDF_CHUNK_SIZE=1000
PDF_CHUNK_OVERLAP=100
MD_CHUNK_SIZE=800
MD_CHUNK_OVERLAP=80
TXT_CHUNK_SIZE=800
TXT_CHUNK_OVERLAP=80
CSV_CHUNK_SIZE=500
CSV_CHUNK_OVERLAP=0
JSON_CHUNK_SIZE=1000
JSON_CHUNK_OVERLAP=100

# 工具调用限制
MAX_TOOL_CALLS=10

# 日志级别
LOG_LEVEL=INFO

# 数据库连接配置
CONNECTION_POOL_SIZE=10
CONNECTION_TIMEOUT=30
HEARTBEAT_INTERVAL=60
```

### 3. 初始化数据库

在 Supabase Dashboard 的 SQL Editor 中执行 `scripts/init_tables.sql`：

```bash
# 或使用 psql 命令
psql -h your-project.supabase.co -U postgres -d postgres -f scripts/init_tables.sql
```

---

## 快速开始

### 启动应用

```bash
python app.py
```

访问 `http://localhost:7860` 即可使用界面。

### 测试 API

```bash
# 发送聊天消息
curl -X POST http://localhost:7860/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我规划一个去北京的三天行程",
    "session_id": null
  }'
```

---

## 功能模块

### 1. 聊天功能

- **实时对话**：支持与大模型实时对话
- **多模态输入**：文本、图片、语音
- **语音合成**：将回答转换为语音
- **会话管理**：新建、清空、删除会话
- **模型切换**：支持 DeepSeek 和智谱 GLM-4

### 2. 知识库管理

- **文档上传**：支持 PDF、Markdown、TXT、CSV、JSON，**自动去重**（基于内容 hash）
- **智能切块**：针对不同文档类型采用专用切分策略：
  - **PDF**：按页面切分，保持页面完整性
  - **Markdown**：按章节切分，保留标题信息
  - **JSON**：按结构切分，保持对象完整性
  - **CSV**：按行切分，保留表头信息
- **向量存储**：使用 pgvector 存储文档向量
- **知识库检索**：支持多知识库隔离
- **上传验证**：文件类型白名单、大小限制（50MB）、空文件检测、详细失败原因反馈

### 3. 外部工具调用

| 工具        | 功能                                  |
| ----------- | ------------------------------------- |
| **AmapMCP** | 地理编码、天气查询、路线规划、POI搜索 |
| **TimeMCP** | 获取当前时间、日期计算、时区转换      |
| **RagMCP**  | 知识库检索、文档查询                  |

### 4. RAG 检索管道

系统采用 **三级检索架构**，通过多路径检索和重排机制确保返回结果的准确性和相关性：

```
用户查询 "北京故宫门票价格"
    │
    ┌──────────────────────────────────────────────────────────────┐
    │                    第一级：多路径并行检索                      │
    ├─────────────────────────┬────────────────────────────────────┤
    │    DenseRetriever       │        BM25Retriever               │
    │    （向量检索）          │        （关键词检索）               │
    ├─────────────────────────┼────────────────────────────────────┤
    │ 1. query → embedding    │ 1. query → 关键词提取               │
    │ 2. 向量相似度计算       │ 2. ILIKE 模糊匹配                    │
    │ 3. 返回 top_k 结果      │ 3. 返回 top_k 结果                  │
    │    （语义相似）          │    （字面匹配）                    │
    └─────────────────────────┴────────────────────────────────────┘
    │
    ┌──────────────────────────────────────────────────────────────┐
    │                    第二级：RRF 融合排序                       │
    │       Reciprocal Rank Fusion (倒数排序融合)                   │
    ├──────────────────────────────────────────────────────────────┤
    │ 对每个文档计算: RRF = Σ(1/(k + rank))                        │
    │ k=60（超参数）                                                │
    │ 融合后重新排序                                                │
    └──────────────────────────────────────────────────────────────┘
    │
    ┌──────────────────────────────────────────────────────────────┐
    │                    第三级：Cross-Encoder 重排                 │
    │   cross-encoder/ms-marco-MiniLM-L-6-v2                       │
    ├──────────────────────────────────────────────────────────────┤
    │ 1. 输入 (query, document) 对                                 │
    │ 2. 模型预测相关性分数                                         │
    │ 3. 按分数重新排序                                            │
    │ 4. 应用阈值过滤                                               │
    └──────────────────────────────────────────────────────────────┘
    │
    返回最终结果列表（送入 LLM 生成回答）
```

#### 4.1 DenseRetriever（密集向量检索）

基于嵌入模型将查询转换为向量，通过余弦相似度匹配文档：

- **优势**：理解语义，能匹配同义词、近义词
- **适用场景**：自然语言查询、语义理解需求高的场景
- **底层实现**：调用 `search_documents_by_vector()`，使用 pgvector 或客户端计算余弦相似度

#### 4.2 BM25Retriever（关键词检索）

使用 PostgreSQL 的 `ILIKE` 进行模糊匹配：

- **优势**：精确匹配关键词，对专有名词、人名、地名效果好
- **适用场景**：精确查询、专有名词检索
- **底层实现**：调用 `search_documents_by_keyword()`，使用 SQL `ILIKE '%query%'`

#### 4.3 RRFFusion（RRF 融合）

**Reciprocal Rank Fusion** 公式：

$$RRF(d) = \sum_{i=1}^{n} \frac{1}{k + rank_i(d)}$$

- `k`：超参数，默认 60，控制排名对分数的影响程度
- `rank_i(d)`：文档 `d` 在第 `i` 个检索器中的排名
- **设计原理**：如果一个文档在多个检索器中都排名靠前，它的 RRF 分数会显著更高，避免单一检索器的局限性

#### 4.4 CrossEncoderReranker（精排）

使用 `cross-encoder/ms-marco-MiniLM-L-6-v2` 模型进行精排：

- **输入**：(query, document) 对
- **输出**：相关性分数（越高越相关）
- **优势**：相比 Bi-Encoder（向量检索），Cross-Encoder 可以看到 query 和 document 的交互信息，相关性判断更准确
- **性能优化**：只对 RRF 融合后的 top_k 结果进行精排，避免计算量过大

#### 4.5 结果去重与质量控制

检索管道在返回最终结果前，会执行以下质量控制步骤：

1. **内容去重**：基于 MD5 内容 hash 去重，避免同一内容重复出现在结果中
2. **阈值过滤**：应用 Cross-Encoder 分数阈值，过滤相关性较低的结果
3. **上下文裁剪**：超过 `MAX_TEXT_LENGTH` 的内容会被智能截断，保持语义完整性

#### 4.6 配置参数

```env
# 检索参数
RETRIEVE_TOP_K=5           # 每个检索器返回的数量
RRF_K=60                   # RRF 融合的 k 值
CROSS_ENCODER_THRESHOLD=0.5 # Cross-Encoder 分数阈值
MAX_TEXT_LENGTH=2000       # 返回文本的最大长度

# 按文档类型的切块参数（影响检索质量）
PDF_CHUNK_SIZE=1000        # PDF 切块大小
MD_CHUNK_SIZE=800          # Markdown 切块大小
TXT_CHUNK_SIZE=800         # TXT 切块大小
```

---

## API 接口

### 聊天接口

#### POST /api/chat

发送聊天消息

**请求体**：

```json
{
  "message": "用户消息",
  "session_id": "会话ID（可选）",
  "image_base64": "图片Base64（可选）",
  "audio_text": "语音转文字（可选）"
}
```

**响应**：

```json
{
  "success": true,
  "answer": "助手回答",
  "session_id": "会话ID",
  "response_time": "响应时间(秒)"
}
```

### 知识库接口

#### POST /api/kb/upload

上传文档到知识库

**请求体**：

```json
{
  "kb_name": "知识库名称",
  "file_path": "文件路径",
  "category": "文档类别（可选）"
}
```

#### GET /api/kb/list

获取知识库列表

#### DELETE /api/kb/delete

删除知识库

**请求体**：

```json
{
  "kb_name": "知识库名称"
}
```

---

## 数据库设计

### chat_session 表

存储聊天会话记录

| 字段       | 类型         | 说明           |
| ---------- | ------------ | -------------- |
| id         | UUID         | 主键，自动生成 |
| title      | VARCHAR(255) | 会话标题       |
| summary    | TEXT         | 会话摘要       |
| messages   | JSONB        | 消息列表       |
| created_at | TIMESTAMP    | 创建时间       |
| updated_at | TIMESTAMP    | 更新时间       |

### documents 表

存储向量文档

| 字段         | 类型         | 说明                                    |
| ------------ | ------------ | --------------------------------------- |
| id           | UUID         | 主键，自动生成                          |
| content      | TEXT         | 文档内容                                |
| vector       | vector(1536) | 向量表示（pgvector）                    |
| embeddings   | JSONB        | 向量表示（降级方案）                    |
| content_hash | VARCHAR(32)  | 内容 MD5 hash（用于去重，有索引）       |
| filename     | VARCHAR(255) | 文件名                                  |
| page_number  | INTEGER      | 页码                                    |
| category     | VARCHAR(100) | 类别                                    |
| metadata     | JSONB        | 元数据（包含 section、chunk_number 等） |
| source_text  | TEXT         | 原始文本                                |
| kb_name      | VARCHAR(255) | 知识库名称                              |
| created_at   | TIMESTAMP    | 创建时间                                |

**索引优化**：

- `idx_documents_content_hash`：content_hash 字段索引，加速去重查询
- `idx_documents_kb_name`：kb_name 字段索引，加速知识库隔离检索

### mcp_call_log 表

存储工具调用日志

| 字段        | 类型         | 说明           |
| ----------- | ------------ | -------------- |
| id          | UUID         | 主键，自动生成 |
| tool_name   | VARCHAR(255) | 工具名称       |
| parameters  | JSONB        | 调用参数       |
| result      | JSONB        | 返回结果       |
| call_time   | TIMESTAMP    | 调用时间       |
| token_usage | INTEGER      | 令牌使用量     |
| session_id  | UUID         | 会话ID         |

### travel_plan 表

存储行程规划

| 字段         | 类型          | 说明           |
| ------------ | ------------- | -------------- |
| id           | UUID          | 主键，自动生成 |
| title        | VARCHAR(255)  | 行程标题       |
| destination  | VARCHAR(255)  | 目的地         |
| days         | INTEGER       | 天数           |
| budget       | NUMERIC(12,2) | 预算           |
| plan_data    | JSONB         | 行程详情       |
| weather_info | JSONB         | 天气信息       |
| created_at   | TIMESTAMP     | 创建时间       |

---

## 日志系统

### 日志文件位置

所有日志输出到 `logs/` 目录：

| 日志文件               | 记录内容         |
| ---------------------- | ---------------- |
| app.log                | 应用级日志       |
| agent_graph.log        | 代理图执行日志   |
| agent_nodes.log        | 节点执行日志     |
| supabase_client.log    | 数据库连接日志   |
| crud.log               | 数据库操作日志   |
| mcp_client.log         | MCP 工具调用日志 |
| retrieval_pipeline.log | RAG 检索日志     |

### 日志级别

- **DEBUG**：详细调试信息
- **INFO**：一般运行信息（默认）
- **WARNING**：警告信息
- **ERROR**：错误信息
- **CRITICAL**：严重错误

---

## 测试指南

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行指定测试文件
pytest tests/test_config.py

# 运行 RAG 和 MCP 集成测试
python tests/test_rag_mcp.py

# 运行专业知识库测试
python tests/test_professional_kb.py

# 显示详细输出
pytest tests/ -v

# 生成测试报告
pytest tests/ --cov=src --cov-report=html
```

### 测试覆盖

| 测试文件         | 覆盖内容         |
| ---------------- | ---------------- |
| test_config.py   | 配置加载和验证   |
| test_database.py | 数据库连接和心跳 |
| test_crud.py     | CRUD 操作        |
| test_llm.py      | LLM 调用         |
| test_utils.py    | 工具函数         |

---

## 扩展开发

### 添加新模型

在 `src/llm/model_factory.py` 中添加新模型：

```python
def _create_new_model(self, model_name, temperature, max_tokens):
    api_key = self.config.NEW_API_KEY
    if not api_key:
        raise ServiceError("NEW_API_KEY is not configured")
    # 实现模型创建逻辑
    return CustomModel(...)
```

### 添加新 MCP 工具

在 `src/mcp/` 目录下创建新工具文件：

```python
from src.mcp.mcp_client import MCPClient

@MCPClient.register_tool("MyTool")
class MyTool(MCPClient):
    def my_method(self, param1: str, param2: int) -> Dict[str, Any]:
        """
        方法描述
        :param param1: 参数1说明
        :param param2: 参数2说明
        :return: 返回值说明
        """
        # 实现工具逻辑
        return {"result": "success"}
```

### 添加新文档解析器

在 `src/rag/document_parser.py` 中注册新解析器：

```python
@DocumentParserFactory.register_parser(".docx")
class DocxParser(DocumentParser):
    def parse(self, file_path: str) -> str:
        # 实现解析逻辑
        return content
```

---

## 常见问题

### Q1: 数据库连接失败

**原因**：

- Supabase URL 或 Key 配置错误
- 使用了 publishable key 而非 service role key

**解决**：

- 检查 `.env` 配置
- 使用 service role key（在 Supabase Dashboard → Settings → API 中获取）

### Q2: pgvector 扩展不可用

**原因**：

- Supabase 项目未启用 pgvector 扩展

**解决**：

- 在 Supabase SQL Editor 执行：`CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;`
- 系统会自动降级到 JSONB 存储方案

### Q3: Gradio 界面计时器一直显示

**原因**：

- `demo.launch()` 设置了 `debug=True`

**解决**：

- 将 `debug=True` 改为 `debug=False`

### Q4: 新建对话报错

**原因**：

- Gradio 6.x 不支持 `gr.Dropdown.update()`

**解决**：

- 使用字典形式返回更新值：`return {"choices": choices}`

### Q5: 文件上传失败

**常见错误原因**：

| 错误信息           | 原因                       | 解决                            |
| ------------------ | -------------------------- | ------------------------------- |
| 文件对象无效       | 文件未正确上传或已损坏     | 重新上传文件                    |
| 不支持的文件类型   | 文件扩展名不在白名单内     | 仅支持：txt、md、pdf、json、csv |
| 文件为空           | 文件内容为空               | 检查文件内容是否有效            |
| 文件大小超过限制   | 文件超过 50MB 限制         | 压缩文件或拆分上传              |
| 解析失败           | 文件格式错误或编码问题     | 检查文件格式是否正确            |
| 嵌入模型初始化失败 | API Key 配置错误或网络问题 | 检查 API Key 和网络连接         |

### Q6: 上传重复文件会怎样

**行为**：

- 系统会自动检测重复内容（基于 MD5 hash）
- 如果检测到重复，会跳过插入，不会产生重复文档
- 上传状态会显示成功，但实际未插入新数据

**设计原理**：

- 在 `crud.py` 中的 `insert_document()` 函数会先检查 `content_hash`
- 如果已存在相同 hash 的文档，会跳过插入并记录日志

---

## 技术栈

| 分类     | 技术                  | 版本  |
| -------- | --------------------- | ----- |
| 语言     | Python                | 3.11+ |
| 框架     | LangChain             | 最新  |
| 工作流   | LangGraph             | 最新  |
| 数据库   | Supabase (PostgreSQL) | 最新  |
| 向量扩展 | pgvector              | 最新  |
| 界面     | Gradio                | 6.x   |
| 嵌入     | sentence-transformers | 最新  |
| 重排序   | cross-encoder         | 最新  |

---

## 许可证

MIT License

---

## 贡献

欢迎提交 Issue 和 Pull Request！
