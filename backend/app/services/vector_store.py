"""向量服务：本地 Embedding + Chroma 向量库

设计要点：
- Embedding 模型懒加载（首次调用加载，进程内单例），避免拖慢服务启动
- 每个 KB 一个 Chroma collection（kb_{id}），天然隔离，删除即整集清除
- Chroma metadata 记录 chunk_id，检索时回查 SQLite 拿到文档标题等上下文
"""

import threading

from .. import config


class VectorService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._model = None
        self._chroma = None
        self._collections: dict[int, object] = {}

    # ---------- 单例 ----------
    @classmethod
    def instance(cls) -> "VectorService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------- Embedding ----------
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # 优先本地缓存目录，其次按模型名联网下载
            if (config.EMBEDDING_MODEL_PATH / "config.json").exists():
                source = str(config.EMBEDDING_MODEL_PATH)
            else:
                source = config.EMBEDDING_MODEL_NAME
            self._model = SentenceTransformer(
                source, device=config.EMBEDDING_DEVICE
            )
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """文本 → 向量（bge 建议对查询加指令，对文档不加）"""
        vecs = self.model.encode(
            texts,
            batch_size=config.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,  # 归一化后内积 = 余弦相似度
            show_progress_bar=False,
        )
        return vecs.tolist()

    def embed_query(self, query: str) -> list[float]:
        # bge 系列官方用法：query 前加检索指令
        instruction = "为这个句子生成表示以用于检索相关文章："
        return self.embed_texts([instruction + query])[0]

    def embedding_dim(self) -> int:
        """返回 embedding 向量的维度（触发模型加载）"""
        return len(self.embed_query("dimension check"))

    # ---------- Chroma ----------
    @property
    def chroma(self):
        if self._chroma is None:
            import chromadb

            self._chroma = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        return self._chroma

    def collection(self, kb_id: int):
        """每个知识库一个 collection"""
        if kb_id not in self._collections:
            self._collections[kb_id] = self.chroma.get_or_create_collection(
                name=f"kb_{kb_id}",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[kb_id]

    # ---------- 入库 ----------
    def add_chunks(self, kb_id: int, chunks: list[dict]) -> int:
        """chunks: [{chunk_id, vector_id, content}]，返回成功条数"""
        if not chunks:
            return 0
        col = self.collection(kb_id)
        vectors = self.embed_texts([c["content"] for c in chunks])
        col.add(
            ids=[c["vector_id"] for c in chunks],
            embeddings=vectors,
            documents=[c["content"] for c in chunks],
            metadatas=[
                {
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "doc_title": c["doc_title"],
                    "seq": c["seq"],
                }
                for c in chunks
            ],
        )
        return len(chunks)

    # ---------- 检索 ----------
    def search(self, kb_id: int, query: str, top_k: int) -> list[dict]:
        """返回 [{vector_id, document, chunk_id, document_id, doc_title, seq, score}]"""
        col = self.collection(kb_id)
        if col.count() == 0:
            return []
        qvec = self.embed_query(query)
        res = col.query(query_embeddings=[qvec], n_results=min(top_k, col.count()))
        hits = []
        for i, vid in enumerate(res["ids"][0]):
            dist = res["distances"][0][i]  # cosine distance
            meta = res["metadatas"][0][i] or {}
            hits.append(
                {
                    "vector_id": vid,
                    "content": res["documents"][0][i],
                    "chunk_id": meta.get("chunk_id"),
                    "document_id": meta.get("document_id"),
                    "doc_title": meta.get("doc_title", ""),
                    "seq": meta.get("seq", 0),
                    "score": 1.0 - dist,  # 转相似度
                }
            )
        return hits

    # ---------- 清理 ----------
    def delete_collection(self, kb_id: int):
        if self.chroma.list_collections() and f"kb_{kb_id}" in [
            c.name for c in self.chroma.list_collections()
        ]:
            self.chroma.delete_collection(f"kb_{kb_id}")
        self._collections.pop(kb_id, None)

    def delete_vectors(self, kb_id: int, vector_ids: list[str]):
        if not vector_ids:
            return
        col = self.collection(kb_id)
        col.delete(ids=vector_ids)


# 便捷入口
def get_vector_service() -> VectorService:
    return VectorService.instance()
