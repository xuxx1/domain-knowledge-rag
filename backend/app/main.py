"""FastAPI 应用入口

路由按模块逐步注册：
- kbs        知识库管理
- documents  文档上传与解析
- chat       RAG 问答
- stats      知识分析
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config  # noqa: F401  导入即完成目录初始化
from . import database  # noqa: F401  导入即完成建表

app = FastAPI(
    title="垂直领域知识智能服务平台",
    description="基于 RAG 的大模型知识应用系统：知识库管理 / 智能检索问答 / 知识分析",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "knowledge-platform", "version": "0.1.0"}


# ---- 模块路由注册（模块2起逐个启用） ----
try:
    from .routers import kbs

    app.include_router(kbs.router, prefix="/api")
except ImportError:
    pass

try:
    from .routers import documents

    app.include_router(documents.router, prefix="/api")
except ImportError:
    pass

try:
    from .routers import chat

    app.include_router(chat.router, prefix="/api")
except ImportError:
    pass

try:
    from .routers import stats

    app.include_router(stats.router, prefix="/api")
except ImportError:
    pass

try:
    from .routers import settings

    app.include_router(settings.router, prefix="/api")
except ImportError:
    pass

try:
    from .routers import eval

    app.include_router(eval.router, prefix="/api")
except ImportError:
    pass
