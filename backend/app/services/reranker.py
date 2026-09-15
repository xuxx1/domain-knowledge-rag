"""Reranker Service：二阶段相关性重排（Cross-Encoder）

设计要点：
- 独立于 Embedding 模型，使用 CrossEncoder（默认 BAAI/bge-reranker-base）对
  (query, chunk) 对做精细相关性打分，比 bi-encoder 向量相似度更准。
- 懒加载 + 进程内单例（与 VectorService 一致），避免拖慢启动。
- 只做重排打分，不修改 Embedding / FAISS 基础检索逻辑。
- 提供 rerank()：对候选 chunk 按 reranker score 重新排序，同时保留原始 FAISS score 供对比。
- 若模型不可用（未下载/加载失败），优雅降级为按原 score 排序，不影响线上问答。
"""

import threading

from .. import config


class RerankerService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._model = None
        self._load_error = None

    # ---------- 单例 ----------
    @classmethod
    def instance(cls) -> "RerankerService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------- 模型 ----------
    @property
    def model(self):
        """懒加载 CrossEncoder 模型（进程内单例）。"""
        if self._model is None and self._load_error is None:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(config.RERANKER_MODEL_NAME, device="cpu")
            except Exception as e:  # noqa: BLE001
                # 记录错误，避免每次重试拉慢请求；后续调用走降级
                self._load_error = str(e)
        return self._model

    def enabled(self) -> bool:
        """Reranker 是否可用（配置启用且模型已加载成功）。"""
        return config.RERANKER_ENABLED and self.model is not None

    # ---------- 重排 ----------
    def rerank(self, query: str, candidates: list[dict], top_k: int | None = None) -> list[dict]:
        """对候选 chunk 进行二阶段相关性重排。

        入参 candidates: [{score(FAISS相似度), content, chunk_id, document_id, doc_title, seq, ...}]
        返回: 按 reranker score 降序的新列表，每个元素追加字段：
            - faiss_score: 原始 FAISS 相似度（保留供对比）
            - rerank_score: Reranker 相关性分（CrossEncoder logit，未归一化）
            - reranked: True（标记已重排）
        若模型不可用，返回候选但仅保留 faiss_score（降级，不改变顺序）。
        """
        if not candidates:
            return []

        # 记录原始 FAISS score（每个候选补一个 faiss_score 字段，幂等）
        prepared = []
        for c in candidates:
            item = dict(c)
            item.setdefault("faiss_score", item.get("score", 0.0))
            prepared.append(item)

        model = self.model
        if model is None:
            # 降级：模型不可用，返回原序（仅补字段），并标记未重排
            return prepared

        # 组装 (query, content) 对，批打分
        pairs = [(query, c.get("content") or "") for c in prepared]
        try:
            raw_scores = model.predict(pairs)
        except Exception:  # noqa: BLE001
            # 打分失败降级为原顺序
            return prepared

        for item, s in zip(prepared, raw_scores):
            item["rerank_score"] = round(float(s), 4)
            # 注意：不覆盖 score（保留原始 FAISS 相似度），
            # 因为 judge_answers 用 score 做相似度硬门槛（ANSWERABLE_MIN_SCORE），
            # 而 Reranker logit 与 FAISS 相似度量纲完全不同，覆盖会破坏判定。

        # 按 reranker score 降序
        ranked = sorted(prepared, key=lambda x: -x.get("rerank_score", 0.0))
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked


# 便捷入口
def get_reranker() -> RerankerService:
    return RerankerService.instance()