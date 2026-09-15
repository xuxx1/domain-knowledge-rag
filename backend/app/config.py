"""全局配置管理：从 .env 读取，支持环境变量覆盖"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 路径配置
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
MODELS_DIR = BASE_DIR / "models"

for d in (DATA_DIR, UPLOADS_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 数据库
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'knowledge.db').as_posix()}"

# Chroma 向量库
CHROMA_DIR = DATA_DIR / "chroma"

# 本地 Embedding 模型：优先读取本地目录，不存在则首次运行自动下载
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_MODEL_PATH = MODELS_DIR / EMBEDDING_MODEL_NAME.split("/")[-1]
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

# 本地 Reranker（Cross-Encoder 二阶段重排）模型：新增独立模型，不替换 Embedding
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-base")
# 是否启用 Reranker 二阶段重排（true=启用，false=只用向量召回排序）
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# LLM（OpenAI 兼容 API）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

# RAG 参数
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))          # 分块目标字符数（约500-800）
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))    # 块间重叠（约100-150）
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "8"))  # 召回数量
RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "4"))        # 重排后保留
# 同一文档最多保留的片段数：单文档场景（如整篇论文入库）需要让含明确答案的片段进入 judge/生成，
# 默认与 RERANK_TOP_K 一致；多文档库可调低避免单文档刷屏
RANK_DOC_LIMIT = int(os.getenv("RANK_DOC_LIMIT", "4"))
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.35"))  # 相似度阈值
# 可回答性判定兜底：即使 judge 判定可回答，若最高相似度低于此值也视为不可回答（拦截低质量命中）
ANSWERABLE_MIN_SCORE = float(os.getenv("ANSWERABLE_MIN_SCORE", "0.50"))
# 英文文档库判定：抽样的 ready 文档分块中中文字符占比低于此值即视为英文文档库（触发中文问题翻译）
EN_KB_CJK_RATIO = float(os.getenv("EN_KB_CJK_RATIO", "0.10"))

# 服务
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
