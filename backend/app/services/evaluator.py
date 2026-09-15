"""RAG 检索效果评测服务

评测目标：衡量「基础向量检索」阶段的检索质量，不涉及 LLM 生成。
对每个测试问题：
1. 走与线上一致的基础检索链路（embedding 召回 → 按 chunk_id 去重 → 阈值过滤）
2. 记录每个问题的 Top-K 检索结果（score / chunk_id / source）
3. 按 ground truth 计算命中情况：
   - Top1 命中：Top1 结果所在 chunk（或文档）是否正确知识
   - Top3 命中：Top3 内是否包含正确知识
   - Top5 命中：Top5 内是否包含正确知识
4. 汇总整体检索效果统计（Top1 / Top3 / Top5 命中率、平均 Top1 score）

说明：
- 本模块【不】调用 Reranker，仅评估 Embedding 基础召回排序效果，
  用于作为后续引入 Reranker 前的基线（baseline）。
- 命中的判定支持两种粒度：
  a) 按 chunk_id（精确到块）—— 若 ground_truth_chunk_ids 提供，用它判定
  b) 按 document_id（精确到文档）—— 否则按 ground_truth_doc_ids 判定
  两种都提供时优先用 chunk_id 判定（更严格）。
"""

import time

from ..database import EvalQuestion, EvalRun, SessionLocal
from .rag import prepare_query, retrieve
from .reranker import get_reranker


def _ground_truth_doc_set(question: EvalQuestion) -> set[int]:
    return set(question.ground_truth_doc_ids or [])


def _ground_truth_chunk_set(question: EvalQuestion) -> set[int]:
    return set(question.ground_truth_chunk_ids or [])


def _hit_at(question: EvalQuestion, ranked: list[dict], top_n: int) -> bool:
    """判断 Top-N 中是否包含正确知识。
    优先按 chunk_id（更严格）；无 chunk ground truth 时按 doc_id。"""
    want_chunks = _ground_truth_chunk_set(question)
    want_docs = _ground_truth_doc_set(question)
    # 如果既有 chunk 又有 doc ground truth，且 chunk 非空，用 chunk 判定
    use_chunk = bool(want_chunks)
    for h in ranked[:top_n]:
        if use_chunk and h.get("chunk_id") in want_chunks:
            return True
        if not use_chunk and h.get("document_id") in want_docs:
            return True
    return False


def _top1_score(ranked: list[dict]) -> float:
    if not ranked:
        return 0.0
    return round(ranked[0]["score"], 4)


def run_eval(kb_id: int, question_ids: list[int]) -> dict:
    """执行一轮评测：遍历问题 → 检索 → 记录 Top-K → 计算命中 → 汇总。

    对比口径（对同一候选集分别排序）：
    - FAISS 排序：按向量相似度 score 降序（现有基线）
    - Reranker 排序：对同一候选集调 Cross-Encoder 重排，按 rerank_score 降序
    两者使用同一份候选（按 chunk_id 去重后的 dedup），仅排序依据不同，
    保证命中率对比是公平的。命中判定优先按 chunk_id，其次按 doc_id。

    返回评测结果 dict，由路由负责落库为 EvalRun。
    """
    from sqlalchemy import select

    started = time.time()
    if question_ids:
        questions = SessionLocal().scalars(
            select(EvalQuestion).where(EvalQuestion.id.in_(question_ids))
        ).all()
    else:
        # 默认跑该知识库下全部评测问题
        questions = SessionLocal().scalars(
            select(EvalQuestion).where(EvalQuestion.kb_id == kb_id)
        ).all()

    if not questions:
        return {
            "items": [],
            "summary": {
                "question_count": 0,
                "top1_rate": 0.0,
                "top3_rate": 0.0,
                "top5_rate": 0.0,
                "avg_top1_score": 0.0,
                "avg_recall_count": 0.0,
            },
            "elapsed_s": round(time.time() - started, 2),
        }

    reranker = get_reranker()
    reranker_available = reranker.enabled()

    items = []
    for q in questions:
        # 与线上一致的检索 query 处理（英文库+中文问题 → 翻译）
        ret_query = prepare_query(kb_id, q.question)
        ret = retrieve(kb_id, ret_query)
        dedup = ret["dedup"]  # 按 chunk_id 去重后的完整召回（阈值过滤前）
        # 统一候选集（FAISS 与 Reranker 用同一份，公平对比）
        candidate = sorted(dedup, key=lambda x: -x["score"])
        # 记录原始 FAISS score 到每个候选（幂等）
        for h in candidate:
            h.setdefault("faiss_score", round(h.get("score", 0.0), 4))

        # 1) FAISS 排序（基线）：按 score 降序
        faiss_ranked = candidate

        # 2) Reranker 排序：对同一候选集重排（rerank_score 降序）
        if reranker_available:
            rerank_ranked = reranker.rerank(ret_query, candidate)
        else:
            rerank_ranked = faiss_ranked

        # Top-K 评估窗口
        faiss_topk = faiss_ranked[:5]
        rerank_topk = rerank_ranked[:5]

        # 记录两个方法的 Top-K 结果
        faiss_topk_rec = [
            {
                "score": round(h.get("score", 0.0), 4),
                "faiss_score": round(h.get("faiss_score", h.get("score", 0.0)), 4),
                "rerank_score": round(h.get("rerank_score", 0.0), 4),
                "chunk_id": h["chunk_id"],
                "source": h["doc_title"],
                "doc_id": h["document_id"],
                "seq": h["seq"],
            }
            for h in faiss_topk
        ]
        rerank_topk_rec = [
            {
                "score": round(h.get("score", 0.0), 4),
                "faiss_score": round(h.get("faiss_score", h.get("score", 0.0)), 4),
                "rerank_score": round(h.get("rerank_score", 0.0), 4),
                "chunk_id": h["chunk_id"],
                "doc_id": h["document_id"],
                "doc_title": h["doc_title"],
                "seq": h["seq"],
            }
            for h in rerank_topk
        ]

        # 命中判定（FAISS 与 Reranker 各自独立）
        faiss_top1 = _hit_at(q, faiss_ranked, 1)
        faiss_top3 = _hit_at(q, faiss_ranked, 3)
        faiss_top5 = _hit_at(q, faiss_ranked, 5)
        rerank_top1 = _hit_at(q, rerank_ranked, 1)
        rerank_top3 = _hit_at(q, rerank_ranked, 3)
        rerank_top5 = _hit_at(q, rerank_ranked, 5)

        # 记录 FAISS 排名与 Reranker 排名（用于逐问对比）
        faiss_rank_of_gt = _rank_of_gt(q, faiss_ranked)
        rerank_rank_of_gt = _rank_of_gt(q, rerank_ranked)

        items.append(
            {
                "question_id": q.id,
                "question": q.question,
                "kb_id": kb_id,
                # FAISS 视角
                "faiss_top_k": faiss_topk_rec,
                "faiss_top1_hit": faiss_top1,
                "faiss_top3_hit": faiss_top3,
                "faiss_top5_hit": faiss_top5,
                "faiss_top1_score": _top1_score(faiss_ranked),
                # Reranker 视角
                "rerank_top_k": rerank_topk_rec,
                "rerank_top1_hit": rerank_top1,
                "rerank_top3_hit": rerank_top3,
                "rerank_top5_hit": rerank_top5,
                "rerank_top1_score": _top1_score(rerank_ranked),
                # 命中排名对比（ground truth 在两种排序下的位置，1 表示 Top1，-1 表示未命中）
                "faiss_rank_of_gt": faiss_rank_of_gt,
                "rerank_rank_of_gt": rerank_rank_of_gt,
                "raw_count": len(ret["raw"]),
                "dedup_count": len(dedup),
                "reranker_available": reranker_available,
                "ground_truth_doc_ids": q.ground_truth_doc_ids,
                "ground_truth_chunk_ids": q.ground_truth_chunk_ids,
            }
        )

    n = len(items)

    # ---- FAISS 整体统计 ----
    faiss_top1 = sum(1 for it in items if it["faiss_top1_hit"])
    faiss_top3 = sum(1 for it in items if it["faiss_top3_hit"])
    faiss_top5 = sum(1 for it in items if it["faiss_top5_hit"])
    faiss_top1_scores = [it["faiss_top1_score"] for it in items if it["faiss_top1_score"] > 0]

    # ---- Reranker 整体统计 ----
    rerank_top1 = sum(1 for it in items if it["rerank_top1_hit"])
    rerank_top3 = sum(1 for it in items if it["rerank_top3_hit"])
    rerank_top5 = sum(1 for it in items if it["rerank_top5_hit"])
    rerank_top1_scores = [it["rerank_top1_score"] for it in items if it["rerank_top1_score"] > 0]

    # 逐问对比：Reranker 相比 FAISS 提升/持平/回退
    top1_improve = sum(1 for it in items if it["rerank_top1_hit"] and not it["faiss_top1_hit"])
    top1_degrade = sum(1 for it in items if it["faiss_top1_hit"] and not it["rerank_top1_hit"])

    summary = {
        "question_count": n,
        # FAISS 基线
        "faiss_top1_rate": round(faiss_top1 / n, 4) if n else 0.0,
        "faiss_top3_rate": round(faiss_top3 / n, 4) if n else 0.0,
        "faiss_top5_rate": round(faiss_top5 / n, 4) if n else 0.0,
        "faiss_top1_hit_count": faiss_top1,
        "faiss_top3_hit_count": faiss_top3,
        "faiss_top5_hit_count": faiss_top5,
        "faiss_avg_top1_score": round(sum(faiss_top1_scores) / len(faiss_top1_scores), 4) if faiss_top1_scores else 0.0,
        # Reranker
        "rerank_top1_rate": rerank_top1 / n if n else 0.0,
        "rerank_top3_rate": rerank_top3 / n if n else 0.0,
        "rerank_top5_rate": rerank_top5 / n if n else 0.0,
        "rerank_top1_hit_count": rerank_top1,
        "rerank_top3_hit_count": rerank_top3,
        "rerank_top5_hit_count": rerank_top5,
        "rerank_avg_top1_score": round(sum(rerank_top1_scores) / len(rerank_top1_scores), 4) if rerank_top1_scores else 0.0,
        "reranker_available": reranker_available,
        # 对比增量
        "top1_improve_count": top1_improve,
        "top1_degrade_count": top1_degrade,
    }

    return {
        "items": items,
        "summary": summary,
        "elapsed_s": round(time.time() - started, 2),
    }


def _rank_of_gt(question: EvalQuestion, ranked: list[dict]) -> int:
    """返回 ground truth 在排序结果中的位置（1 起），若在 Top-N 外或未命中返回 -1。

    优先按 chunk_id 判定，无 chunk ground truth 时按 doc_id。"""
    want_chunks = _ground_truth_chunk_set(question)
    want_docs = _ground_truth_doc_set(question)
    use_chunk = bool(want_chunks)
    for idx, h in enumerate(ranked, 1):
        if use_chunk and h.get("chunk_id") in want_chunks:
            return idx
        if not use_chunk and h.get("document_id") in want_docs:
            return idx
    return -1


def save_run(kb_id: int, question_ids: list[int], result: dict) -> EvalRun:
    """把一轮评测结果落库为 EvalRun。"""
    with SessionLocal() as db:
        run = EvalRun(
            kb_id=kb_id,
            question_ids=question_ids or [],
            items=result.get("items", []),
            summary=result.get("summary", {}),
            status="done",
            elapsed_s=result.get("elapsed_s", 0.0),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run