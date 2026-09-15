---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'de5762b8-7121-43a3-a7c6-7d34f5b9a8d3'
  PropagateID: 'de5762b8-7121-43a3-a7c6-7d34f5b9a8d3'
  ReservedCode1: '92b985ad-f27f-4ac4-9fb0-4a5d414fcf2c'
  ReservedCode2: '92b985ad-f27f-4ac4-9fb0-4a5d414fcf2c'
---

# 垂直领域知识智能服务平台

基于 RAG 的大模型知识应用系统：领域知识库管理、智能检索问答、知识分析。

## 技术栈

- **后端**：Python 3.12 + FastAPI + SQLAlchemy + SQLite
- **向量检索**：本地 Embedding（BAAI/bge-small-zh-v1.5）+ Chroma 向量库
- **LLM**：OpenAI 兼容 API（默认 DeepSeek，可配置通义/智谱/Kimi 等）
- **前端**：Next.js + React（模块 6）

## 目录结构

```
backend/                  # FastAPI 后端
├── app/
│   ├── main.py           # 入口：路由注册 + CORS
│   ├── config.py         # 配置管理（.env 驱动）
│   ├── database.py       # 数据表（知识库/文档/分块/会话/消息）
│   ├── schemas.py        # 请求/响应模型
│   ├── routers/
│   │   ├── kbs.py        # 知识库 CRUD
│   │   ├── documents.py  # 文档上传/解析/分块/入库
│   │   ├── chat.py       # SSE 流式问答
│   │   ├── stats.py      # 知识分析统计
│   │   └── eval.py       # RAG 检索效果评测
│   └── services/
│       ├── parser.py     # 多格式文档解析（PDF/Word/TXT/MD）
│       ├── chunker.py    # 智能分块（段落优先+滑动窗口）
│       ├── vector_store.py # Embedding + Chroma
│       ├── indexer.py    # 向量入库流水线
│       ├── rag.py        # 检索/提示词组装
│       ├── evaluator.py  # RAG 评测执行逻辑
│       └── llm.py        # LLM 封装（OpenAI 兼容）
├── data/                 # SQLite + Chroma（自动生成）
├── uploads/              # 上传的文档
├── models/               # 本地 Embedding 模型（可选）
└── .env

frontend/                 # Next.js 14 前端
└── src/
    ├── app/
    │   ├── page.tsx      # 知识库管理
    │   ├── chat/         # 智能问答（SSE 流式 + 引用溯源）
    │   └── stats/        # 知识分析看板
    ├── components/Nav.tsx
    └── lib/api.ts        # 后端 API 封装
```

## 快速启动

**后端**（端口 8000）：

```powershell
cd backend
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # 填入 LLM_API_KEY
python -m uvicorn app.main:app --port 8000
```

接口文档：http://127.0.0.1:8000/docs

**前端**（端口 3000，需先启动后端）：

```powershell
cd frontend
npm install
npm run dev
```

访问：http://127.0.0.1:3000

> 前端默认连接 http://127.0.0.1:8000/api，可通过环境变量 `NEXT_PUBLIC_API_BASE` 覆盖。
> 首次上传文档时后端会自动从 HuggingFace 下载 bge-small-zh-v1.5 模型（约 100MB），需要联网。

## API 总览

| 模块 | 接口 | 说明 |
|---|---|---|
| 系统 | GET /api/health | 健康检查 |
| 知识库 | POST /api/kbs | 创建知识库 |
| 知识库 | GET /api/kbs | 知识库列表（含统计） |
| 知识库 | GET /api/kbs/{id} | 知识库详情 |
| 知识库 | PUT /api/kbs/{id} | 更新 |
| 知识库 | DELETE /api/kbs/{id} | 删除（级联删除文档与向量） |
| 文档 | POST /api/kbs/{id}/documents/upload | 上传（解析+分块+向量化一条龙） |
| 文档 | GET /api/kbs/{id}/documents | 文档列表 |
| 文档 | GET /api/kbs/{id}/documents/{doc_id}/chunks | 分块预览（分页） |
| 文档 | POST /api/kbs/{id}/documents/{doc_id}/reindex | 重建向量索引 |
| 文档 | DELETE /api/kbs/{id}/documents/{doc_id} | 删除文档（含向量） |
| 会话 | POST /api/sessions | 创建会话 |
| 会话 | GET /api/kbs/{id}/sessions | 会话列表 |
| 会话 | GET /api/sessions/{id}/messages | 消息历史 |
| 会话 | DELETE /api/sessions/{id} | 删除会话 |
| 问答 | POST /api/chat | SSE 流式问答（refs/delta/done/error） |
| 分析 | GET /api/stats/overview | 总览指标 |
| 分析 | GET /api/stats/trend | 提问/命中趋势 |
| 分析 | GET /api/stats/hot-docs | 热门被引文档 |
| 分析 | GET /api/stats/missed-questions | 未命中问题（知识盲区） |
| 分析 | GET /api/stats/kb-comparison | 知识库对比 |
| 评测 | GET /api/eval/questions | 评测问题集（可按 kb_id 过滤） |
| 评测 | POST /api/eval/questions | 新增评测问题（含 ground truth） |
| 评测 | PUT /api/eval/questions/{id} | 更新评测问题 |
| 评测 | DELETE /api/eval/questions/{id} | 删除评测问题 |
| 评测 | POST /api/eval/runs | 运行一轮检索评测 |
| 评测 | GET /api/eval/runs | 评测历史 |
| 评测 | GET /api/eval/runs/{id} | 单次评测详情（每问 Top-K 与命中） |

## RAG 检索评测

用于衡量**基础向量检索**阶段的召回与排序效果，不调用 LLM 生成，也不涉及 Reranker。
评测目标：作为后续引入 Reranker 前的基线（baseline），对比优化前后的检索质量。

**评测流程**（每个测试问题）：
1. 走与线上一致的基础检索链路（embedding 召回 → 按 chunk_id 去重 → 阈值过滤）
2. 记录 Top-K 检索结果：`score`、`chunk_id`、`source`（文档）、`seq`
3. 按 ground truth 计算命中：
   - **Top1 命中**：Top1 结果是否正确知识
   - **Top3 命中**：Top3 内是否包含正确知识
   - **Top5 命中**：Top5 内是否包含正确知识
4. 汇总整体统计：Top1 / Top3 / Top5 命中率、平均 Top1 score

命中判定支持两种粒度：优先按 `ground_truth_chunk_ids`（精确到块），否则按 `ground_truth_doc_ids`（精确到文档）。

### 使用方式

```powershell
# 1. 新增评测问题（可指定正确知识所在的 chunk 或文档）
curl -X POST http://127.0.0.1:8000/api/eval/questions \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question":"向量数据库有哪些常见产品？","ground_truth_doc_ids":[1],"ground_truth_chunk_ids":[9]}'

# 2. 运行评测（question_ids 为空则跑该知识库全部问题）
curl -X POST http://127.0.0.1:8000/api/eval/runs \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question_ids":[]}'

# 3. 查看最近一次评测整体统计
curl http://127.0.0.1:8000/api/eval/runs
```

## 开发进度

- [x] 模块 1：项目骨架（目录、配置、数据库、FastAPI 入口）
- [x] 模块 2：知识库管理（CRUD、文档上传、解析、分块）
- [x] 模块 3：向量化存储（本地 Embedding、Chroma、入库流水线）
- [x] 模块 4：RAG 问答（检索、重排、流式回答、引用溯源）
- [x] 模块 5：知识分析（统计看板、命中率、覆盖度）
- [x] 模块 6：Next.js 前端（对话、知识库管理、分析看板）
- [x] 模块 7：RAG 检索评测（问题集 + Top1/3/5 命中 + 整体统计）

## 待配置

- [ ] `backend/.env` 中的 `LLM_API_KEY`（当前为占位符，智能问答的生成环节需要真实 Key）

## 测试记录

各模块均有集成测试脚本（Python + urllib，存于 `.temp/`）：
- 模块 2：知识库 CRUD + 上传解析分块全链路（10/10）
- 模块 3：向量入库/检索/清理同步（10/10）
- 模块 4：会话 + SSE 通道 + 引用溯源（8/8，LLM 真实生成待 Key）
- 模块 5：统计指标构造验证（8/8）
- 模块 6：浏览器实测（建库→上传→问答→看板）

> AI生成