"""文档管理路由：上传解析、列表、详情、删除

上传流程：保存文件 → 解析 → 分块 → 落库（向量入库在模块 3 接入）
"""

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import Chunk, Document, KnowledgeBase, get_db
from ..schemas import DocumentOut
from ..services import parser
from ..services.cleaner import clean_text
from ..services.chunker import chunk_text
from ..services.indexer import index_document, remove_document_vectors
from ..services.vector_store import get_vector_service

router = APIRouter(prefix="/kbs/{kb_id}/documents", tags=["文档管理"])

_SAFE_NAME = re.compile(r"[^\w.\-\u4e00-\u9fa5]+")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name
    return _SAFE_NAME.sub("_", name)


@router.post("/upload", response_model=DocumentOut)
def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传单个文档：保存 → 解析 → 分块 → 落库"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")

    if not file.filename:
        raise HTTPException(400, "缺少文件名")

    try:
        file_type = parser.file_type_of(file.filename)
    except parser.ParseError as e:
        raise HTTPException(400, str(e))

    # 存储文件（重名冲突自动加后缀）
    safe_name = _safe_filename(file.filename)
    stored = config.UPLOADS_DIR / f"{uuid4().hex[:8]}_{safe_name}"
    content = file.file.read()
    stored.write_bytes(content)

    # 建文档记录（先 pending）
    doc = Document(
        kb_id=kb_id,
        title=Path(file.filename).stem,
        filename=safe_name,
        file_type=file_type,
        file_path=str(stored),
        file_size=len(content),
        status="parsing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 解析 + 分块（同步执行，出错标记 failed 并保留记录供排查）
    try:
        text = parser.parse_file(stored)
        text = clean_text(text)  # 清洗：过滤 AIGC 水印/UUID/HTML/乱码等
        chunks = chunk_text(text)
        if not chunks:
            raise parser.ParseError("解析后无有效内容（可能是扫描版 PDF）")

        doc.char_count = len(text)
        doc.chunk_count = len(chunks)
        doc.status = "parsed"  # 模块 3 接入向量入库后改为 ready
        doc.error_msg = ""

        for seq, c in enumerate(chunks):
            db.add(
                Chunk(
                    document_id=doc.id,
                    seq=seq,
                    content=c,
                    char_count=len(c),
                )
            )
        db.commit()
        db.refresh(doc)

        # 模块3：向量入库（失败不影响分块数据，状态留在 parsed 可重试）
        try:
            idx = index_document(db, doc)
            if not idx.success:
                doc.status = "parsed"
                doc.error_msg = f"向量入库未完成：{idx.error}"
                db.commit()
                db.refresh(doc)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            doc.status = "parsed"
            doc.error_msg = f"向量入库异常：{e}"
            db.commit()
            db.refresh(doc)
    except parser.ParseError as e:
        doc.status = "failed"
        doc.error_msg = str(e)
        db.commit()
        db.refresh(doc)
        # 解析失败不抛 500，返回文档记录让前端展示失败原因
    except Exception as e:  # noqa: BLE001
        doc.status = "failed"
        doc.error_msg = f"处理异常：{e}"
        db.commit()
        db.refresh(doc)

    return doc


class QuickAddRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source: str = ""  # 来源标注，如"盲区补录"


@router.post("/quick-add", response_model=DocumentOut)
def quick_add(
    kb_id: int, body: QuickAddRequest, db: Session = Depends(get_db)
):
    """快速补录：把一段文本直接作为文档加入知识库（无需文件上传）

    流程：文本 → 分块 → 落库 → 向量化 → ready
    适用于把未命中问题的答案/补充知识一键写入知识库。
    """
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if not body.content.strip():
        raise HTTPException(400, "内容不能为空")

    # 生成一个"虚拟文档"记录（file_type=txt，无实体文件）
    title = body.title.strip() or f"补录-{datetime.now():%Y%m%d%H%M}"
    safe = _safe_filename(f"{title}.txt") or "quick.txt"
    doc = Document(
        kb_id=kb_id,
        title=title,
        filename=safe,
        file_type="txt",
        file_path="",
        file_size=len(body.content.encode("utf-8")),
        status="parsing",
        error_msg=body.source or "",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        content = clean_text(body.content)
        if not content.strip():
            raise parser.ParseError("清洗后内容为空，无法分块")
        chunks = chunk_text(content)
        if not chunks:
            raise parser.ParseError("内容过短或为空，无法分块")
        doc.char_count = len(body.content)
        doc.chunk_count = len(chunks)
        for seq, c in enumerate(chunks):
            db.add(Chunk(document_id=doc.id, seq=seq, content=c, char_count=len(c)))
        db.commit()
        db.refresh(doc)

        # 向量化入库（失败留 parsed 可重试）
        try:
            idx = index_document(db, doc)
            if not idx.success:
                doc.status = "parsed"
                doc.error_msg = f"向量入库未完成：{idx.error}"
                db.commit()
                db.refresh(doc)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            doc.status = "parsed"
            doc.error_msg = f"向量入库异常：{e}"
            db.commit()
            db.refresh(doc)
    except parser.ParseError as e:
        doc.status = "failed"
        doc.error_msg = str(e)
        db.commit()
        db.refresh(doc)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        doc.status = "failed"
        doc.error_msg = f"处理异常：{e}"
        db.commit()
        db.refresh(doc)

    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(kb_id: int, db: Session = Depends(get_db)):
    if not db.get(KnowledgeBase, kb_id):
        raise HTTPException(404, "知识库不存在")
    docs = db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(Document.id.desc())
    ).scalars().all()
    return docs


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(kb_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "文档不存在")
    return doc


@router.post("/{doc_id}/reindex")
def reindex_document(kb_id: int, doc_id: int, db: Session = Depends(get_db)):
    """重新向量化（改分块参数后或入库失败时使用）"""
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "文档不存在")
    try:
        idx = index_document(db, doc)
        return {"ok": idx.success, "chunk_count": idx.chunk_count, "error": idx.error}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(500, f"重建索引失败：{e}")


@router.get("/{doc_id}/chunks")
def get_document_chunks(
    kb_id: int, doc_id: int, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    """分页查看文档分块（预览分块效果）"""
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "文档不存在")
    page = max(page, 1)
    total = doc.chunk_count
    chunks = db.execute(
        select(Chunk)
        .where(Chunk.document_id == doc_id)
        .order_by(Chunk.seq)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "chunks": [
            {"id": c.id, "seq": c.seq, "char_count": c.char_count, "content": c.content}
            for c in chunks
        ],
    }


@router.delete("/{doc_id}")
def delete_document(kb_id: int, doc_id: int, db: Session = Depends(get_db)):
    """删除文档：文件、分块记录、向量数据"""
    doc = db.get(Document, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(404, "文档不存在")
    # 模块3：清理向量
    try:
        remove_document_vectors(db, doc)
    except Exception:  # noqa: BLE001
        pass  # 向量清理失败不阻塞删除，残留由重索引/删库覆盖
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True, "deleted_id": doc_id}
