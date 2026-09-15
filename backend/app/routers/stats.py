"""知识分析路由：总览、趋势、热门被引、未命中问题、知识库对比"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    KnowledgeBase,
    get_db,
)
from ..schemas import StatsOverview

router = APIRouter(prefix="/stats", tags=["知识分析"])


@router.get("/overview", response_model=StatsOverview)
def overview(db: Session = Depends(get_db)):
    """核心指标总览"""
    kb_count = db.execute(select(func.count(KnowledgeBase.id))).scalar() or 0
    doc_count = db.execute(select(func.count(Document.id))).scalar() or 0
    chunk_count = db.execute(select(func.count(Chunk.id))).scalar() or 0

    # 以助手消息数为提问数（每问必有一答，含拒答）
    answers = db.execute(
        select(ChatMessage.references, ChatMessage.answer_type).where(
            ChatMessage.role == "assistant"
        )
    ).all()
    question_count = len(answers)
    hit = sum(1 for r, _ in answers if r)  # references 非空即命中
    scores = []
    for r, _ in answers:
        if r:
            scores.extend(x.get("score", 0) for x in r)
    return StatsOverview(
        kb_count=kb_count,
        doc_count=doc_count,
        chunk_count=chunk_count,
        question_count=question_count,
        hit_rate=round(hit / question_count, 4) if question_count else 0.0,
        avg_score=round(sum(scores) / len(scores), 4) if scores else 0.0,
    )


@router.get("/trend")
def trend(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db)):
    """按天统计：提问数、命中数（用于趋势图）"""
    since = datetime.now() - timedelta(days=days)
    rows = db.execute(
        select(
            func.date(ChatMessage.created_at),
            ChatMessage.answer_type,
            func.count(ChatMessage.id),
        )
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        .group_by(func.date(ChatMessage.created_at), ChatMessage.answer_type)
    ).all()
    by_day: dict[str, dict] = {}
    for day, atype, cnt in rows:
        d = by_day.setdefault(day, {"date": day, "total": 0, "hit": 0})
        d["total"] += cnt
        if atype == "normal":
            d["hit"] += cnt
    return sorted(by_day.values(), key=lambda x: x["date"])


@router.get("/hot-docs")
def hot_docs(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    """被引用最多的文档（知识价值排名）"""
    answers = db.execute(
        select(ChatMessage.references).where(ChatMessage.role == "assistant")
    ).scalars().all()
    counter: dict[int, dict] = {}
    for refs in answers:
        if not refs:
            continue
        seen = set()
        for r in refs:
            doc_id = r.get("doc_id")
            if doc_id is None or doc_id in seen:
                continue
            seen.add(doc_id)
            counter.setdefault(doc_id, {"doc_id": doc_id, "citations": 0, "title": r.get("doc_title", "")})
            counter[doc_id]["citations"] += 1
    top = sorted(counter.values(), key=lambda x: -x["citations"])[:limit]
    # 回查最新标题（可能改名）
    for t in top:
        doc = db.get(Document, t["doc_id"])
        if doc:
            t["title"] = doc.title
            t["kb_id"] = doc.kb_id
    return top


@router.get("/missed-questions")
def missed_questions(
    limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
):
    """未命中（拒答）的问题清单 → 知识盲区"""
    # 未命中 = 回答消息无 references 或 answer_type == no_hit
    msgs = db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(500)
    ).scalars().all()
    missed = [m for m in msgs if m.answer_type == "no_hit" or not m.references]
    # 找对应问题（前一条 user 消息）
    result = []
    for m in missed[:limit]:
        q = db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == m.session_id,
                ChatMessage.id < m.id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        result.append(
            {
                "question": q.content if q else "(未知)",
                "asked_at": m.created_at.isoformat(),
                "session_id": m.session_id,
                "kb_id": m.session.kb_id if m.session else None,
            }
        )
    return result


@router.get("/kb-comparison")
def kb_comparison(db: Session = Depends(get_db)):
    """各知识库规模对比（文档数/分块数/提问数）"""
    kbs = db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id)).scalars().all()
    out = []
    for kb in kbs:
        docs = db.execute(
            select(func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.kb_id == kb.id
            )
        ).one()
        qs = db.execute(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.kb_id == kb.id, ChatMessage.role == "assistant")
        ).scalar() or 0
        out.append(
            {
                "kb_id": kb.id,
                "name": kb.name,
                "doc_count": docs[0],
                "chunk_count": docs[1],
                "question_count": qs,
            }
        )
    return out
