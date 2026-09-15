"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Doc, KB, docApi, kbApi } from "@/lib/api";

const STATUS_TEXT: Record<string, string> = {
  ready: "已入库",
  parsed: "待入库",
  failed: "解析失败",
  pending: "等待",
  parsing: "解析中",
  indexing: "向量化中",
};

export default function HomePage() {
  const [kbs, setKbs] = useState<KB[]>([]);
  const [selected, setSelected] = useState<KB | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  // 新建表单
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [domains, setDomains] = useState("");

  const fileRef = useRef<HTMLInputElement>(null);

  // 快速补录弹窗
  const [showQuick, setShowQuick] = useState(false);
  const [quickTitle, setQuickTitle] = useState("");
  const [quickContent, setQuickContent] = useState("");
  const [quickAdding, setQuickAdding] = useState(false);

  const openQuickAdd = () => {
    if (!selected) {
      setError("请先选择或创建一个知识库");
      return;
    }
    setQuickTitle("");
    setQuickContent("");
    setShowQuick(true);
  };

  const submitQuickAdd = async () => {
    if (!selected || !quickContent.trim()) return;
    setQuickAdding(true);
    setError("");
    try {
      await docApi.quickAdd(selected.id, {
        title: quickTitle.trim() || "快速补录",
        content: quickContent.trim(),
        source: "知识库-快速补录",
      });
      setShowQuick(false);
      await loadDocs(selected.id);
      await loadKbs();
    } catch (e: any) {
      setError(`添加失败：${e.message}`);
    } finally {
      setQuickAdding(false);
    }
  };

  const loadKbs = useCallback(async () => {
    try {
      const list = await kbApi.list();
      setKbs(list);
      setSelected((prev) => (prev ? list.find((k) => k.id === prev.id) || null : null));
    } catch (e: any) {
      setError(`加载知识库失败：${e.message}`);
    }
  }, []);

  const loadDocs = useCallback(async (kbId: number) => {
    setLoading(true);
    try {
      setDocs(await docApi.list(kbId));
    } catch (e: any) {
      setError(`加载文档失败：${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadKbs();
  }, [loadKbs]);

  useEffect(() => {
    if (selected) loadDocs(selected.id);
  }, [selected, loadDocs]);

  const createKb = async () => {
    if (!name.trim()) return;
    try {
      const kb = await kbApi.create({
        name: name.trim(),
        description: desc.trim(),
        domains: domains
          .split(/[,，\s]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setShowCreate(false);
      setName("");
      setDesc("");
      setDomains("");
      await loadKbs();
      setSelected(kb);
    } catch (e: any) {
      setError(`创建失败：${e.message}`);
    }
  };

  const removeKb = async (kb: KB) => {
    if (!confirm(`确定删除知识库「${kb.name}」？其下 ${kb.doc_count} 个文档与向量数据将一并删除。`)) return;
    try {
      await kbApi.remove(kb.id);
      if (selected?.id === kb.id) setSelected(null);
      await loadKbs();
    } catch (e: any) {
      setError(`删除失败：${e.message}`);
    }
  };

  const upload = async (file: File) => {
    if (!selected) return;
    setUploading(true);
    setError("");
    try {
      await docApi.upload(selected.id, file);
      await loadDocs(selected.id);
      await loadKbs();
    } catch (e: any) {
      setError(`上传失败：${e.message}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const removeDoc = async (doc: Doc) => {
    if (!selected) return;
    if (!confirm(`确定删除文档「${doc.title}」？`)) return;
    try {
      await docApi.remove(selected.id, doc.id);
      await loadDocs(selected.id);
      await loadKbs();
    } catch (e: any) {
      setError(`删除失败：${e.message}`);
    }
  };

  const reindex = async (doc: Doc) => {
    if (!selected) return;
    try {
      await docApi.reindex(selected.id, doc.id);
      await loadDocs(selected.id);
    } catch (e: any) {
      setError(`重建失败：${e.message}`);
    }
  };

  return (
    <div className="home">
      <div className="home-head">
        <h1 className="page-title">知识库管理</h1>
        <div className="head-ops">
          <button className="btn ghost" onClick={openQuickAdd}>
            ＋ 添加内容
          </button>
          <button className="btn" onClick={() => setShowCreate(true)}>
            ＋ 新建知识库
          </button>
        </div>
      </div>

      {error && <div className="alert-error" onClick={() => setError("")}>{error}</div>}

      <div className="home-layout">
        {/* 左：知识库列表 */}
        <aside className="kb-list">
          {kbs.length === 0 && !loading && (
            <div className="empty">暂无知识库，点击右上角创建</div>
          )}
          {kbs.map((kb) => (
            <div
              key={kb.id}
              className={`kb-item${selected?.id === kb.id ? " active" : ""}`}
              onClick={() => setSelected(kb)}
            >
              <div className="kb-item-name">{kb.name}</div>
              <div className="kb-item-meta">
                {kb.doc_count} 文档 · {kb.chunk_count} 块 · {(kb.char_count / 10000).toFixed(1)} 万字
              </div>
              {kb.domains?.length > 0 && (
                <div className="kb-item-tags">
                  {kb.domains.map((d) => (
                    <span key={d} className="tag">{d}</span>
                  ))}
                </div>
              )}
              <button
                className="kb-del"
                title="删除知识库"
                onClick={(e) => {
                  e.stopPropagation();
                  removeKb(kb);
                }}
              >
                删除
              </button>
            </div>
          ))}
        </aside>

        {/* 右：文档区 */}
        <section className="doc-panel card">
          {!selected ? (
            <div className="empty big">← 选择或创建一个知识库</div>
          ) : (
            <>
              <div className="doc-head">
                <div>
                  <h2 className="doc-title">{selected.name}</h2>
                  <p className="doc-desc">{selected.description || "（无描述）"}</p>
                </div>
                <div>
                  <label className="btn" style={{ cursor: uploading ? "not-allowed" : "pointer" }}>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".pdf,.docx,.txt,.md"
                      style={{ display: "none" }}
                      disabled={uploading}
                      onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
                    />
                    {uploading ? "上传处理中…" : "上传文档"}
                  </label>
                </div>
              </div>

              <table className="doc-table">
                <thead>
                  <tr>
                    <th>标题</th>
                    <th>类型</th>
                    <th>大小</th>
                    <th>分块</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty">暂无文档，支持 PDF / Word / TXT / Markdown</td>
                    </tr>
                  )}
                  {docs.map((d) => (
                    <tr key={d.id}>
                      <td title={d.error_msg || ""}>{d.title}</td>
                      <td>{d.file_type.toUpperCase()}</td>
                      <td>{(d.file_size / 1024).toFixed(0)} KB</td>
                      <td>{d.chunk_count}</td>
                      <td className={`st-${d.status}`}>
                        {STATUS_TEXT[d.status] || d.status}
                      </td>
                      <td className="doc-ops">
                        {d.status === "parsed" && (
                          <button className="btn small ghost" onClick={() => reindex(d)}>
                            重建索引
                          </button>
                        )}
                        <button className="btn small danger" onClick={() => removeDoc(d)}>
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>

      {/* 新建弹窗 */}
      {showCreate && (
        <div className="modal-mask" onClick={() => setShowCreate(false)}>
          <div className="modal card" onClick={(e) => e.stopPropagation()}>
            <h3>新建知识库</h3>
            <label>名称 *</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如：企业制度库" />
            <label>描述</label>
            <textarea className="textarea" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="知识库用途说明" />
            <label>领域标签（逗号分隔）</label>
            <input className="input" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="如：医疗, 制度, 产品" />
            <div className="modal-ops">
              <button className="btn ghost" onClick={() => setShowCreate(false)}>取消</button>
              <button className="btn" onClick={createKb} disabled={!name.trim()}>创建</button>
            </div>
          </div>
        </div>
      )}

      {/* 快速补录弹窗 */}
      {showQuick && (
        <div className="modal-mask" onClick={() => setShowQuick(false)}>
          <div className="modal card" onClick={(e) => e.stopPropagation()}>
            <h3>添加内容到「{selected?.name}」</h3>
            <label>标题</label>
            <input
              className="input"
              value={quickTitle}
              onChange={(e) => setQuickTitle(e.target.value)}
              placeholder="该条知识的标题"
            />
            <label>内容 *</label>
            <textarea
              className="textarea"
              value={quickContent}
              onChange={(e) => setQuickContent(e.target.value)}
              placeholder="粘贴要补充的知识内容，保存后自动分块并向量化，可被检索问答"
              rows={8}
            />
            <div className="modal-ops">
              <button className="btn ghost" onClick={() => setShowQuick(false)}>
                取消
              </button>
              <button
                className="btn"
                onClick={submitQuickAdd}
                disabled={quickAdding || !quickContent.trim()}
              >
                {quickAdding ? "处理中…" : "保存并入库"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .home {
          max-width: 1200px;
          margin: 0 auto;
          padding: 24px;
        }
        .home-head {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 18px;
        }
        .head-ops {
          display: flex;
          gap: 10px;
        }
        .btn.ghost {
          background: none;
          border: 1px solid var(--line);
          color: var(--ink);
        }
        .btn.ghost:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
        .page-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 22px;
          color: var(--ink);
        }
        .alert-error {
          background: #f9e8e5;
          color: var(--accent);
          border: 1px solid #e8c4bd;
          border-radius: 8px;
          padding: 10px 14px;
          margin-bottom: 14px;
          cursor: pointer;
          font-size: 13px;
        }
        .home-layout {
          display: grid;
          grid-template-columns: 280px 1fr;
          gap: 18px;
          align-items: start;
        }
        .kb-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .kb-item {
          background: var(--card);
          border: 1px solid var(--line);
          border-radius: 10px;
          padding: 14px 16px;
          cursor: pointer;
          position: relative;
          transition: border-color 0.15s;
        }
        .kb-item:hover {
          border-color: var(--accent-soft);
        }
        .kb-item.active {
          border-color: var(--accent);
          box-shadow: 0 0 0 1px var(--accent);
        }
        .kb-item-name {
          font-weight: 600;
          font-size: 15px;
          margin-bottom: 4px;
          padding-right: 44px;
        }
        .kb-item-meta {
          color: var(--ink-soft);
          font-size: 12px;
        }
        .kb-item-tags {
          margin-top: 8px;
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
        }
        .kb-del {
          position: absolute;
          top: 12px;
          right: 12px;
          border: none;
          background: none;
          color: var(--ink-soft);
          font-size: 12px;
        }
        .kb-del:hover {
          color: var(--accent);
        }
        .doc-panel {
          min-height: 400px;
        }
        .doc-head {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 16px;
          gap: 16px;
        }
        .doc-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 18px;
        }
        .doc-desc {
          color: var(--ink-soft);
          font-size: 13px;
          margin-top: 4px;
        }
        .doc-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .doc-table th {
          text-align: left;
          color: var(--ink-soft);
          font-weight: 500;
          border-bottom: 1px solid var(--line);
          padding: 8px 10px;
        }
        .doc-table td {
          border-bottom: 1px solid #f0ece2;
          padding: 10px;
        }
        .doc-ops {
          display: flex;
          gap: 6px;
        }
        .empty {
          color: var(--ink-soft);
          text-align: center;
          padding: 24px 0;
        }
        .empty.big {
          padding: 120px 0;
          font-size: 15px;
        }
        .modal-mask {
          position: fixed;
          inset: 0;
          background: rgba(43, 38, 32, 0.4);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
        }
        .modal {
          width: 420px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .modal h3 {
          font-family: "SimSun", "Songti SC", serif;
          margin-bottom: 8px;
        }
        .modal label {
          font-size: 12px;
          color: var(--ink-soft);
          margin-top: 6px;
        }
        .modal-ops {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          margin-top: 14px;
        }
      `}</style>
    </div>
  );
}
