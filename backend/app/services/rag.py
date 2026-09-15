"""RAG 核心：检索 → 过滤 → 上下文组装

检索链路：
1. 向量召回 Top-K（RETRIEVAL_TOP_K）
2. 阈值过滤（SCORE_THRESHOLD 以下丢弃）
3. 按文档去重截断到 RERANK_TOP_K 条，进入生成
   （Cross-Encoder 重排预留接口 rerank()，当前用向量分数排序，模块可后续替换）
"""

import re

from .. import config
from . import llm as llm_service
from .reranker import get_reranker
from .vector_store import get_vector_service

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(text: str) -> bool:
    """判断文本是否包含中文字符"""
    return bool(_CJK_RE.search(text or ""))


def kb_is_english(kb_id: int) -> bool:
    """判断知识库文档是否以英文为主：抽样该库 ready 文档的分块内容，计算中文字符占比。
    中文占比 < EN_KB_CJK_RATIO 即视为英文文档库。失败时保守返回 False（按中文处理，不翻译）。"""
    from ..database import SessionLocal
    from sqlalchemy import select

    with SessionLocal() as db:
        from ..database import Chunk, Document

        rows = db.execute(
            select(Chunk.content)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.kb_id == kb_id, Document.status == "ready")
            .limit(20)
        ).scalars().all()
    if not rows:
        return False
    sample = "".join(rows)
    if not sample.strip():
        return False
    cjk_chars = len(_CJK_RE.findall(sample))
    ratio = cjk_chars / len(sample)
    return ratio < getattr(config, "EN_KB_CJK_RATIO", 0.10)


def prepare_query(kb_id: int, question: str) -> str:
    """按知识库语言决定检索用查询词：
    - 文档为英文 且 问题为中文：先翻译成英文再检索；
    - 其余情况：使用原问题检索。"""
    if _has_cjk(question) and kb_is_english(kb_id):
        en_q = llm_service.translate_to_en(question)
        if en_q and en_q != question:
            return en_q
    return question


def retrieve(kb_id: int, query: str) -> dict:
    """返回 {hits: [...], hit: bool, raw: [...], dedup: [...], reranked: bool}

    query 由调用方按知识库语言处理（英文库+中文问题→翻译），此处直接检索。
    检索策略：
    1. 向量召回 RETRIEVAL_TOP_K（默认 8）条；
    2. 按 chunk_id 去重（保留 score 最高的一条），保证 Top-K 结果 chunk_id 唯一；
    3. 阈值过滤（SCORE_THRESHOLD，保留真实 score，不设固定 0.8 硬阈值）；
    4. 同一文档最多保留 RANK_DOC_LIMIT 条；
    5. 【二阶段重排】若 Reranker 可用，对候选按 rerank_score 降序，
       否则按原始 faiss score 排序；最终截断到 RERANK_TOP_K 条进入生成。
       重排仅改变顺序，不覆盖 score（score 仍为 FAISS 相似度，供 judge/后端兼容）。
    """
    vs = get_vector_service()
    raw = vs.search(kb_id, query, config.RETRIEVAL_TOP_K)

    # 调试：记录原始召回（含重复 chunk）供展示
    raw_records = list(raw)

    # 按 chunk_id 去重（保留 score 最高一条）
    seen: dict[int, dict] = {}
    for h in raw:
        cid = h["chunk_id"]
        if cid is None:
            continue
        if cid not in seen or h["score"] > seen[cid]["score"]:
            seen[cid] = h
    dedup = sorted(seen.values(), key=lambda x: -x["score"])

    # 阈值过滤（保留真实 score）
    hits = [h for h in dedup if h["score"] >= config.SCORE_THRESHOLD]

    # 同一文档最多保留 RANK_DOC_LIMIT 条
    by_doc: dict[int, int] = {}
    limited = []
    for h in sorted(hits, key=lambda x: -x["score"]):
        cnt = by_doc.get(h["document_id"], 0)
        if cnt >= config.RANK_DOC_LIMIT:
            continue
        by_doc[h["document_id"]] = cnt + 1
        limited.append(h)

    # 二阶段重排：Reranker 对候选精排，保留 faiss_score/rerank_score
    reranker = get_reranker()
    if reranker.enabled():
        reranked = reranker.rerank(query, limited)
    else:
        # Reranker 不可用：按 faiss score 降序（保持原排序），每个候选补 faiss_score 字段
        reranked = [dict(h, **{"faiss_score": round(h.get("score", 0.0), 4)}) for h in sorted(limited, key=lambda x: -x["score"])]

    return {
        "hits": reranked[: config.RERANK_TOP_K],
        "hit": len(reranked) > 0,
        "raw": raw_records,
        "dedup": dedup,
        "reranked": reranker.enabled(),
    }


def collect_debug_info(kb_id: int, query: str, messages: list[dict]) -> dict:
    """收集 RAG 调试信息（不参与检索逻辑，仅用于排查）。

    返回结构：
    {
      "query": 实际用于检索的 query 文本,
      "query_embedding_dim": query embedding 维度,
      "retrieval_top_k": 配置的召回数,
      "topk": [ {score, source, chunk_id, seq/page, chunk_preview, ...} ],  # 去重后的完整召回（阈值过滤前）
      "raw_count": 原始召回条数（去重前）,
      "prompt": 最终发送给 LLM 的完整 prompt（含 system + 历史 + user）
    }
    """
    vs = get_vector_service()
    raw = vs.search(kb_id, query, config.RETRIEVAL_TOP_K)
    # 按 chunk_id 去重（与检索逻辑一致），保证调试展示的 chunk_id 唯一
    seen: dict[int, dict] = {}
    for h in raw:
        cid = h["chunk_id"]
        if cid is not None and (cid not in seen or h["score"] > seen[cid]["score"]):
            seen[cid] = h
    dedup = sorted(seen.values(), key=lambda x: -x["score"])

    topk = [
        {
            "vector_id": h["vector_id"],
            "chunk_id": h["chunk_id"],
            "doc_id": h["document_id"],
            "doc_title": h["doc_title"],
            "seq": h["seq"],
            "page": h.get("page"),  # 页码（若解析时保留）
            "score": round(h["score"], 4),
            "source": h["doc_title"],  # 来源文件名
            "chunk_preview": (h["content"] or "")[:300],  # chunk 前300字
        }
        for h in dedup
    ]
    return {
        "query": query,
        "query_embedding_dim": vs.embedding_dim(),
        "retrieval_top_k": config.RETRIEVAL_TOP_K,
        "raw_count": len(raw),
        "dedup_count": len(dedup),
        "topk": topk,
        "prompt": messages,  # 最终发送给 LLM 的完整 prompt
    }


def rerank(query: str, hits: list[dict]) -> list[dict]:
    """重排入口：调用 Reranker 服务对候选精排（保留 faiss_score / rerank_score）。

    模型不可用时优雅降级为原顺序，不影响线上问答。"""
    reranker = get_reranker()
    if reranker.enabled():
        return reranker.rerank(query, hits)
    return hits


def build_context(hits: list[dict]) -> str:
    """把命中片段组装为编号上下文，供引用溯源"""
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"【片段{i}｜来源：{h['doc_title']} 第{h['seq'] + 1}块】\n{h['content']}")
    return "\n\n".join(parts)


SYSTEM_PROMPT = """你是垂直领域知识助手。请严格依据下面提供的「参考资料」回答用户问题，并遵守：

1. 优先使用参考资料作答，答案中用【片段N】标注引用来源，例如：RAG 分为三步【片段1】。
2. 若参考资料不足以回答，明确说明「根据现有知识库无法回答该问题」，不要编造。
3. 回答使用简体中文，条理清晰；能分点时用编号列表。
4. 若问题与知识库领域无关，礼貌说明并引导用户提出领域内问题。"""


def build_messages(question: str, context: str, history: list[dict] | None = None) -> list[dict]:
    """组装最终消息列表（含多轮历史，历史不含检索上下文以省 token）"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-6:]:  # 最近3轮
        messages.append({"role": h["role"], "content": h["content"][:1000]})
    if context:
        user = f"参考资料：\n{context}\n\n用户问题：{question}"
    else:
        user = question
    messages.append({"role": "user", "content": user})
    return messages


# 可回答性判断的系统提示词：判断检索片段是否与用户问题相关、能否作为回答依据
_JUDGE_SYSTEM_PROMPT = """你是一个知识检索质检员。你的任务是判断给定的「参考资料片段」是否与用户的问题具有足够的语义相关性，并且可以作为回答该问题的依据。

【判断原则】
你只能依据提供的检索片段进行判断，不允许使用模型自身知识补充判断。
但判断重点是"是否相关、是否能够作为回答依据"，而不是"这些片段能否单独、完整地回答问题"。

【判定规则】
- 如果片段包含与问题相关的核心概念、定义、流程、作用、方法等信息，即使不能完整覆盖所有细节，也判定为 YES。
- 不要因为信息不完整就直接判定 NO。最终回答是由多个检索片段共同提供上下文，再由 LLM 生成的，片段只需提供相关依据即可。
- 只有当检索片段与问题明显无关，或者无法从片段中找到任何回答依据时，才判定 NO。

【示例】
- 问题"什么是大语言模型（LLM）？"，片段包含 LLM 的定义和相关描述 → YES
- 问题"LLM 是什么意思？能做什么？"，片段包含 LLM 的定义、能力或相关描述 → YES
- 问题"RAG 如何结合向量检索和大模型来提升问答效果？"，片段包含 RAG、向量检索、上下文、LLM 生成等相关内容 → YES
- 问题"今天北京的天气怎么样？"，片段与天气完全无关 → NO

只输出 YES 或 NO，不要输出任何其他内容。"""


def judge_answers(question: str, hits: list[dict]) -> bool:
    """判断检索到的片段是否与用户问题相关、能否作为回答依据。

    返回 True=相关（进入 LLM 生成），False=不相关（拒答）。
    采用双保险：
    1) 片段最高相似度需 >= ANSWERABLE_MIN_SCORE，否则直接判不相关；
    2) 调用 LLM 做轻量二分类（判断相关性而非完整性），失败时保守返回 False。
    """
    if not hits:
        return False
    # 兜底 1：相似度硬门槛——检索片段最高相似度太低，直接视为不相关
    max_score = max((h.get("score") or 0.0) for h in hits)
    if max_score < config.ANSWERABLE_MIN_SCORE:
        return False
    # 组装片段内容（截断以免过长）
    ctx_parts = []
    for i, h in enumerate(hits, 1):
        content = (h.get("content") or "").strip().replace("\n", " ")
        ctx_parts.append(f"【片段{i}｜来源：{h.get('doc_title','')}】{content[:400]}")
    context = "\n\n".join(ctx_parts)
    user = f"用户问题：{question}\n\n参考资料：\n{context}"
    try:
        out = llm_service.chat(
            [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        verdict = (out or "").strip().upper()
        if verdict.startswith("YES"):
            return True
        if verdict.startswith("NO"):
            return False
        # 无法识别时保守返回 False
        return False
    except Exception:  # noqa: BLE001
        # 判定失败时保守返回 False
        return False
