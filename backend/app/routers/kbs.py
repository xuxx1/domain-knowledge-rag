"""知识库管理路由：CRUD + 统计聚合"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import Document, KnowledgeBase, get_db
from ..schemas import KBCreate, KBOut, KBUpdate

router = APIRouter(prefix="/kbs", tags=["知识库管理"])


def _kb_stats(db: Session, kb_id: int) -> dict:
    """聚合知识库下文档/分块/字符统计"""
    row = db.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.chunk_count), 0),
            func.coalesce(func.sum(Document.char_count), 0),
        ).where(Document.kb_id == kb_id)
    ).one()
    return {
        "doc_count": row[0],
        "chunk_count": row[1],
        "char_count": row[2],
    }


def _to_out(db: Session, kb: KnowledgeBase) -> KBOut:
    stats = _kb_stats(db, kb.id)
    data = KBOut.model_validate(kb)
    data.doc_count = stats["doc_count"]
    data.chunk_count = stats["chunk_count"]
    data.char_count = stats["char_count"]
    return data


@router.post("", response_model=KBOut)
def create_kb(body: KBCreate, db: Session = Depends(get_db)):
    if db.execute(
        select(KnowledgeBase).where(KnowledgeBase.name == body.name)
    ).scalar_one_or_none():
        raise HTTPException(400, f"知识库名称已存在：{body.name}")
    kb = KnowledgeBase(
        name=body.name, description=body.description, domains=body.domains
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _to_out(db, kb)


@router.get("", response_model=list[KBOut])
def list_kbs(db: Session = Depends(get_db)):
    kbs = db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id)).scalars().all()
    return [_to_out(db, kb) for kb in kbs]


@router.get("/{kb_id}", response_model=KBOut)
def get_kb(kb_id: int, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    return _to_out(db, kb)


@router.put("/{kb_id}", response_model=KBOut)
def update_kb(kb_id: int, body: KBUpdate, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if body.name is not None:
        dup = db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.name == body.name, KnowledgeBase.id != kb_id
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(400, f"知识库名称已存在：{body.name}")
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    if body.domains is not None:
        kb.domains = body.domains
    db.commit()
    db.refresh(kb)
    return _to_out(db, kb)


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, db: Session = Depends(get_db)):
    """删除知识库：级联删除文档/分块记录，并清除整个 Chroma collection"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    # 清除向量 collection
    try:
        from ..services.vector_store import get_vector_service

        get_vector_service().delete_collection(kb_id)
    except Exception:  # noqa: BLE001
        pass  # 向量清理失败不阻塞删除
    db.delete(kb)
    db.commit()
    return {"ok": True, "deleted_id": kb_id}
