"""索引流水线：文档分块 → 向量化 → Chroma 入库 → 回填 vector_id → 状态 ready"""

import uuid
from dataclasses import dataclass, field


@dataclass
class IndexResult:
    success: bool
    chunk_count: int = 0
    error: str = ""
    vector_ids: list[str] = field(default_factory=list)


def index_document(db, doc) -> IndexResult:
    """对单个文档做向量化入库。

    db: SQLAlchemy Session；doc: Document ORM 实例
    """
    from ..database import Chunk
    from .vector_store import get_vector_service

    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == doc.id)
        .order_by(Chunk.seq)
        .all()
    )
    if not chunks:
        return IndexResult(False, 0, "文档无分块数据")

    vs = get_vector_service()

    # 为每个 chunk 分配 vector_id（幂等：已有 vector_id 的复用）
    payload = []
    for c in chunks:
        if not c.vector_id:
            c.vector_id = f"doc{doc.id}_chunk{c.id}_{uuid.uuid4().hex[:8]}"
        payload.append(
            {
                "chunk_id": c.id,
                "vector_id": c.vector_id,
                "content": c.content,
                "document_id": doc.id,
                "doc_title": doc.title,
                "seq": c.seq,
            }
        )

    # 先删除旧向量（重索引场景），再批量插入
    vs.delete_vectors(doc.kb_id, [p["vector_id"] for p in payload])
    count = vs.add_chunks(doc.kb_id, payload)
    db.commit()

    doc.status = "ready"
    doc.error_msg = ""
    db.commit()
    return IndexResult(True, count, "", [p["vector_id"] for p in payload])


def remove_document_vectors(db, doc) -> int:
    """删除文档的全部向量（不删 chunk 记录，由数据库级联处理）"""
    from ..database import Chunk
    from .vector_store import get_vector_service

    vs = get_vector_service()
    vids = [
        c.vector_id
        for c in db.query(Chunk).filter(Chunk.document_id == doc.id).all()
        if c.vector_id
    ]
    if vids:
        vs.delete_vectors(doc.kb_id, vids)
    return len(vids)
