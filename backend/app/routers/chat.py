"""问答路由：会话管理 + SSE 流式问答 + 引用溯源

SSE 事件协议：
- event: refs     data: 命中片段列表（回答前推送）
- event: delta    data: 文本增量
- event: done     data: 消息 id / 耗时
- event: error    data: 错误信息
"""

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import ChatMessage, ChatSession, KnowledgeBase, SessionLocal, get_db
from ..schemas import ChatRequest, MessageOut, SessionCreate, SessionOut
from ..services import llm as llm_service
from ..services.rag import (
    build_context,
    build_messages,
    collect_debug_info,
    judge_answers,
    prepare_query,
    retrieve,
)

router = APIRouter(tags=["智能问答"])


# ---------- 会话管理 ----------
@router.post("/sessions", response_model=SessionOut)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    if not db.get(KnowledgeBase, body.kb_id):
        raise HTTPException(404, "知识库不存在")
    s = ChatSession(kb_id=body.kb_id, title=body.title)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/kbs/{kb_id}/sessions", response_model=list[SessionOut])
def list_sessions(kb_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(ChatSession)
        .where(ChatSession.kb_id == kb_id)
        .order_by(ChatSession.updated_at.desc())
    ).scalars().all()


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    ).scalars().all()


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---------- SSE 流式问答 ----------
@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    session = db.get(ChatSession, body.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    kb = db.get(KnowledgeBase, session.kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")

    question = body.question.strip()
    start = time.time()

    # ========== 1. 检索 ==========
    ret_query = prepare_query(session.kb_id, question)
    ret = retrieve(session.kb_id, ret_query)
    hits = ret["hits"]

    # ========== 2. DEBUG 日志：完整链路诊断 ==========
    from .. import config as _cfg
    print("\n" + "=" * 80)
    print("===== RAG DEBUG（完整链路）=====")
    print(f"[1] 用户原始问题: {question}")
    print(f"[2] 检索用 query（可能翻译）: {ret_query}")
    print(f"[3] Reranker 是否启用: {ret.get('reranked', False)}")
    print(f"[4] 当前配置阈值:")
    print(f"    SCORE_THRESHOLD（FAISS召回过滤）= {_cfg.SCORE_THRESHOLD}")
    print(f"    ANSWERABLE_MIN_SCORE（拒答硬门槛）= {_cfg.ANSWERABLE_MIN_SCORE}")
    print(f"    RETRIEVAL_TOP_K = {_cfg.RETRIEVAL_TOP_K}")
    print(f"    RERANK_TOP_K = {_cfg.RERANK_TOP_K}")
    print(f"    RANK_DOC_LIMIT = {_cfg.RANK_DOC_LIMIT}")

    # FAISS 原始召回（去重后，阈值过滤前）
    dedup = ret["dedup"]
    print(f"\n[5] FAISS 去重后召回（共 {len(dedup)} 条，阈值过滤前）:")
    for i, h in enumerate(dedup[:8], 1):
        preview = (h.get("content") or "")[:200].replace("\n", " ")
        print(f"  FAISS[{i}] chunk_id={h['chunk_id']} source={h.get('doc_title','')} faiss_score={round(h.get('score',0),4)}")
        print(f"         text: {preview}")

    # Reranker 排序后的 hits
    print(f"\n[6] Reranker 排序后 hits（共 {len(hits)} 条，进入 judge/LLM 的候选）:")
    for i, h in enumerate(hits, 1):
        preview = (h.get("content") or "")[:200].replace("\n", " ")
        faiss_s = round(h.get("faiss_score", h.get("score", 0)), 4)
        rerank_s = round(h.get("rerank_score", 0), 4)
        print(f"  RERANK[{i}] chunk_id={h['chunk_id']} faiss_score={faiss_s} rerank_score={rerank_s}")
        print(f"          text: {preview}")

    # ========== 3. 可回答性校验 ==========
    reject_reason = None
    if not hits:
        reject_reason = "FAISS召回不足（阈值过滤后无结果）"
        print(f"\n[7] 拒答原因: {reject_reason}")
    else:
        max_score = max(h.get("score", 0.0) for h in hits)
        print(f"\n[7] judge_answers 前检查:")
        print(f"    hits 中 max(score) = {round(max_score,4)}（此 score 是 FAISS 相似度，不是 rerank_score）")
        print(f"    ANSWERABLE_MIN_SCORE = {_cfg.ANSWERABLE_MIN_SCORE}")
        if max_score < _cfg.ANSWERABLE_MIN_SCORE:
            reject_reason = f"FAISS score 不足（max_score={round(max_score,4)} < ANSWERABLE_MIN_SCORE={_cfg.ANSWERABLE_MIN_SCORE}）"
            print(f"    >>> 触发硬门槛拒答: {reject_reason}")
        else:
            print(f"    硬门槛通过，进入 LLM judge...")

    if hits and reject_reason is None:
        # Judge 调试：输出 judge 看到的 chunk 数量和实际文本
        print(f"\n[8] LLM judge 输入详情:")
        print(f"    传入 judge 的 chunk 数量: {len(hits)}")
        print(f"    judge 看到的 chunk 内容（截取前400字，与 judge_answers 内一致）:")
        for i, h in enumerate(hits, 1):
            content = (h.get("content") or "").strip().replace("\n", " ")
            print(f"    [judge 片段{i}] chunk_id={h['chunk_id']} 来源={h.get('doc_title','')}")
            print(f"      text: {content[:400]}")
        judge_result = judge_answers(ret_query, hits)
        print(f"\n    judge 返回值: {judge_result}")
        if not judge_result:
            reject_reason = "LLM judge 判定为 NO（片段与问题不够相关）"
            print(f"    LLM judge 结果: NO → 拒答")
        else:
            print(f"    LLM judge 结果: YES → 进入生成")

    if reject_reason:
        print(f"\n[9] 最终决策: 不进入 LLM")
        print(f"    拒答原因: {reject_reason}")
    else:
        print(f"\n[9] 最终决策: 进入 LLM 生成")
    print("=" * 80 + "\n")

    # 拒答时清空 hits，让 gen() 走 no_hit 路径
    if reject_reason:
        hits = []

    # 历史消息（不含本问）
    history = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc())
        .limit(6)
    ).scalars().all()
    history = [
        {"role": m.role, "content": m.content} for m in reversed(history)
    ]

    context = build_context(hits) if hits else ""
    messages = build_messages(question, context, history)

    # 构造 SSE debug 信息（匹配前端 RagDebug 接口）
    from ..services.vector_store import get_vector_service as _vs
    _vs_inst = _vs()
    _dedup = ret["dedup"]
    debug_info = {
        "query": ret_query,
        "query_embedding_dim": _vs_inst.embedding_dim(),
        "retrieval_top_k": _cfg.RETRIEVAL_TOP_K,
        "raw_count": len(ret["raw"]),
        "dedup_count": len(_dedup),
        "topk": [
            {
                "vector_id": h.get("vector_id"),
                "chunk_id": h["chunk_id"],
                "doc_id": h["document_id"],
                "doc_title": h.get("doc_title", ""),
                "seq": h["seq"],
                "page": h.get("page"),
                "score": round(h.get("score", 0.0), 4),
                "source": h.get("doc_title", ""),
                "chunk_preview": (h.get("content") or "")[:300],
            }
            for h in _dedup
        ],
        "prompt": messages,
        # 额外字段（前端可选使用）
        "reranked": ret.get("reranked", False),
        "score_threshold": _cfg.SCORE_THRESHOLD,
        "answerable_min_score": _cfg.ANSWERABLE_MIN_SCORE,
        "reject_reason": reject_reason,
        "hits_count": len(hits),
    }

    # 3. 落库用户消息
    user_msg = ChatMessage(
        session_id=session.id, role="user", content=question
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # 首问自动生成会话标题
    if session.title == "新会话":
        session.title = llm_service.generate_title(question)
        db.commit()

    refs = [
        {
            "chunk_id": h["chunk_id"],
            "doc_id": h["document_id"],
            "doc_title": h["doc_title"],
            "seq": h["seq"],
            "score": round(h["score"], 4),
        }
        for h in hits
    ]

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    # 缓存为普通标量，避免 gen() 惰性执行时访问已失效的 ORM session 对象
    _sid = session.id

    # 无命中时的固定拒答文案（逻辑硬约束：不调用 LLM，杜绝编造）
    NO_HIT_TEXT = "根据现有知识库无法回答该问题，您可点击「补录」补充相关内容后再试。"

    def gen():
        answer_parts: list[str] = []
        answer_type = "normal"
        # 使用独立 session 落库，避免 StreamingResponse 时依赖已关闭
        _sdb = SessionLocal()
        try:
            # 推送调试信息（每次提问都会输出）
            yield sse("debug", debug_info)

            # 无命中：逻辑硬拒答，不调用 LLM，直接返回固定文案
            if not hits:
                answer_type = "no_hit"
                yield sse("refs", {"refs": [], "answer_type": answer_type})
                yield sse("delta", {"text": NO_HIT_TEXT})
                answer = NO_HIT_TEXT
                elapsed = round(time.time() - start, 2)
                # 落库助手消息（独立 session）
                a_msg = ChatMessage(
                    session_id=_sid,
                    role="assistant",
                    content=answer,
                    references=[],
                    answer_type=answer_type,
                )
                _sdb.add(a_msg)
                _sdb.commit()
                _sdb.refresh(a_msg)
                yield sse("done", {"message_id": a_msg.id, "elapsed": elapsed})
                return

            yield sse("refs", {"refs": refs, "answer_type": answer_type})

            for delta in llm_service.chat_stream(messages):
                answer_parts.append(delta)
                yield sse("delta", {"text": delta})

            answer = "".join(answer_parts)
            elapsed = round(time.time() - start, 2)

            # 落库助手消息（独立 session）
            a_msg = ChatMessage(
                session_id=_sid,
                role="assistant",
                content=answer,
                references=refs,
                answer_type=answer_type,
            )
            _sdb.add(a_msg)
            _sdb.commit()
            _sdb.refresh(a_msg)
            yield sse("done", {"message_id": a_msg.id, "elapsed": elapsed})
        except Exception as e:  # noqa: BLE001
            _sdb.rollback()
            msg = str(e)
            if "API_KEY" in msg:
                msg = "LLM API Key 未配置，请编辑 backend/.env 后重启服务"
            yield sse("error", {"message": msg[:300]})
        finally:
            _sdb.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
