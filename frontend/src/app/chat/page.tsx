"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  KB,
  Message,
  RagDebug,
  RefItem,
  Session,
  chatSSE,
  kbApi,
  sessionApi,
} from "@/lib/api";

interface ChatItem {
  role: string;
  content: string;
  refs?: RefItem[];
  answerType?: string;
  streaming?: boolean;
}

export default function ChatPage() {
  const [kbs, setKbs] = useState<KB[]>([]);
  const [kbId, setKbId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [debug, setDebug] = useState<RagDebug | null>(null);
  const [showDebug, setShowDebug] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  // 加载知识库
  useEffect(() => {
    kbApi
      .list()
      .then((list) => {
        setKbs(list);
        if (list.length > 0) setKbId((prev) => prev ?? list[0].id);
      })
      .catch((e) => setError(`加载知识库失败：${e.message}`));
  }, []);

  // 加载会话列表
  const loadSessions = useCallback(async (kid: number) => {
    try {
      const list = await sessionApi.list(kid);
      setSessions(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  // 切换知识库 → 默认选中最近会话
  useEffect(() => {
    if (!kbId) return;
    setSessionId(null);
    setItems([]);
    loadSessions(kbId).then((list) => {
      if (list.length > 0) setSessionId(list[0].id);
    });
  }, [kbId, loadSessions]);

  // 切换会话 → 加载历史
  useEffect(() => {
    if (!sessionId) {
      setItems([]);
      return;
    }
    sessionApi
      .messages(sessionId)
      .then((msgs: Message[]) =>
        setItems(
          msgs.map((m) => ({
            role: m.role,
            content: m.content,
            refs: m.references,
            answerType: m.answer_type,
          }))
        )
      )
      .catch((e) => setError(`加载历史失败：${e.message}`));
  }, [sessionId]);

  // 自动滚动到底
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items]);

  const newSession = async () => {
    if (!kbId) return;
    try {
      const s = await sessionApi.create(kbId);
      await loadSessions(kbId);
      setSessionId(s.id);
      setItems([]);
    } catch (e: any) {
      setError(`创建会话失败：${e.message}`);
    }
  };

  const send = async () => {
    const q = question.trim();
    if (!q || !sessionId || sending) return;
    setSending(true);
    setError("");
    setQuestion("");
    setDebug(null);

    // 乐观插入用户消息 + 流式助手占位
    setItems((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", streaming: true, refs: [] },
    ]);

    const aiIndex = items.length + 1;

    try {
      await chatSSE(sessionId, q, {
        onDebug: (d) => {
          setDebug(d);
          setShowDebug(true);
        },
        onRefs: (refs, answerType) => {
          setItems((prev) => {
            const next = [...prev];
            next[aiIndex] = { ...next[aiIndex], refs, answerType };
            return next;
          });
        },
        onDelta: (text) => {
          setItems((prev) => {
            const next = [...prev];
            next[aiIndex] = { ...next[aiIndex], content: next[aiIndex].content + text };
            return next;
          });
        },
        onDone: () => {
          setItems((prev) => {
            const next = [...prev];
            next[aiIndex] = { ...next[aiIndex], streaming: false };
            return next;
          });
          if (kbId) loadSessions(kbId);
        },
        onError: (msg) => {
          setItems((prev) => {
            const next = [...prev];
            next[aiIndex] = {
              ...next[aiIndex],
              content: next[aiIndex].content || `（出错了：${msg}）`,
              streaming: false,
            };
            return next;
          });
        },
      });
    } finally {
      setSending(false);
    }
  };

  const delSession = async (s: Session) => {
    if (!kbId) return;
    if (!confirm(`删除会话「${s.title}」？`)) return;
    try {
      await sessionApi.remove(s.id);
      const list = await loadSessions(kbId);
      if (sessionId === s.id) {
        setSessionId(list[0]?.id ?? null);
        setItems([]);
      }
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="chat">
      {/* 左侧栏：知识库 + 会话 */}
      <aside className="side">
        <div className="side-block">
          <div className="side-label">知识库</div>
          <select
            className="select"
            value={kbId ?? ""}
            onChange={(e) => setKbId(Number(e.target.value))}
          >
            {kbs.length === 0 && <option value="">（请先创建知识库）</option>}
            {kbs.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </div>
        <div className="side-block">
          <div className="side-label-row">
            <span className="side-label">会话</span>
            <button className="btn small ghost" onClick={newSession} disabled={!kbId}>
              ＋ 新会话
            </button>
          </div>
          <div className="session-list">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`session-item${sessionId === s.id ? " active" : ""}`}
                onClick={() => setSessionId(s.id)}
              >
                <span className="session-title">{s.title}</span>
                <button
                  className="session-del"
                  onClick={(e) => {
                    e.stopPropagation();
                    delSession(s);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
            {sessions.length === 0 && <div className="empty small">暂无会话</div>}
          </div>
        </div>
      </aside>

      {/* 对话区 */}
      <section className="main">
        <div className="msgs">
          {items.length === 0 && (
            <div className="welcome">
              <div className="welcome-mark">知</div>
              <div className="welcome-title">领域知识问答</div>
              <div className="welcome-sub">
                回答基于所选知识库检索生成，并标注引用片段
              </div>
            </div>
          )}
          {items.map((it, i) => (
            <div key={i} className={`msg ${it.role}`}>
              <div className="bubble">
                <div className="content">{it.content || (it.streaming ? "思考中…" : "")}</div>
                {it.streaming && it.content && <span className="cursor">▍</span>}
              </div>
              {/* 引用 */}
              {it.role === "assistant" && it.refs && it.refs.length > 0 && (
                <div className="refs">
                  <div className="refs-label">
                    引用 {it.refs.length} 个片段
                    {it.answerType === "no_hit" && "（未检索到相关知识）"}
                  </div>
                  {it.refs.map((r, j) => (
                    <div key={j} className="ref-item">
                      <span className="ref-no">【片段{j + 1}】</span>
                      {r.doc_title} · 第{r.seq + 1}块
                      <span className="ref-score">{(r.score * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {error && <div className="chat-error" onClick={() => setError("")}>{error}</div>}

        <div className="input-bar">
          <textarea
            className="ask-input"
            value={question}
            placeholder={kbId ? "输入问题，Enter 发送，Shift+Enter 换行" : "请先在左侧选择知识库"}
            disabled={!kbId || sending}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button className="btn send-btn" onClick={send} disabled={!question.trim() || sending || !sessionId}>
            {sending ? "回答中…" : "发送"}
          </button>
        </div>
      </section>

      {/* RAG 调试信息弹窗 */}
      {debug && showDebug && (
        <div className="debug-overlay" onClick={() => setShowDebug(false)}>
          <div className="debug-modal" onClick={(e) => e.stopPropagation()}>
            <div className="debug-modal-head">
              <span className="debug-modal-title">RAG 调试信息</span>
              <button className="debug-modal-close" onClick={() => setShowDebug(false)}>
                ×
              </button>
            </div>
            <div className="debug-modal-body">
              {debug.error ? (
                <div className="debug-err">（收集失败：{debug.error}）</div>
              ) : (
                <>
                  <div className="debug-meta">
                    query「{debug.query}」 · 维度 {debug.query_embedding_dim} · Top-{debug.retrieval_top_k} · 原始 {debug.raw_count} 条 / 去重后 {debug.dedup_count} 条
                  </div>
                  <div className="debug-sec">
                    <div className="debug-sec-title">检索 Top-K 结果</div>
                    {(debug.topk?.length ?? 0) === 0 ? (
                      <div className="debug-empty">无召回结果</div>
                    ) : (
                      (debug.topk ?? []).map((r, i) => (
                        <div className="debug-item" key={i}>
                          <div className="debug-item-head">
                            <span className="debug-idx">[{i + 1}]</span>
                            <span className="debug-score">score {r.score}</span>
                            <span className="debug-src">
                              {r.source} · 第{r.seq + 1}块 · chunk#{r.chunk_id}
                              {r.page != null ? ` · 第${r.page}页` : ""}
                            </span>
                          </div>
                          <div className="debug-chunk">{r.chunk_preview}</div>
                        </div>
                      ))
                    )}
                  </div>
                  <div className="debug-sec">
                    <div className="debug-sec-title">最终 Prompt</div>
                    <pre className="debug-prompt">{JSON.stringify(debug.prompt, null, 2)}</pre>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .chat {
          display: grid;
          grid-template-columns: 240px 1fr;
          height: calc(100vh - 58px);
        }
        .side {
          background: var(--paper);
          border-right: 1px solid var(--line);
          padding: 16px 14px;
          display: flex;
          flex-direction: column;
          gap: 18px;
          overflow-y: auto;
        }
        .side-label {
          font-size: 12px;
          color: var(--ink-soft);
          margin-bottom: 8px;
        }
        .side-label-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .session-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .session-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 10px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 13px;
        }
        .session-item:hover {
          background: #efe9de;
        }
        .session-item.active {
          background: #f3e3df;
          color: var(--accent);
        }
        .session-title {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .session-del {
          border: none;
          background: none;
          color: var(--ink-soft);
          font-size: 14px;
          padding: 0 2px;
        }
        .session-del:hover {
          color: var(--accent);
        }
        .main {
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .msgs {
          flex: 1;
          overflow-y: auto;
          padding: 28px 10%;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .welcome {
          margin: auto;
          text-align: center;
          color: var(--ink-soft);
        }
        .welcome-mark {
          width: 56px;
          height: 56px;
          margin: 0 auto 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--accent);
          color: #fff;
          border-radius: 14px;
          font-family: "SimSun", "Songti SC", serif;
          font-size: 28px;
        }
        .welcome-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 20px;
          color: var(--ink);
        }
        .welcome-sub {
          font-size: 13px;
          margin-top: 6px;
        }
        .msg {
          display: flex;
          flex-direction: column;
        }
        .msg.user {
          align-items: flex-end;
        }
        .bubble {
          max-width: 78%;
          padding: 10px 16px;
          border-radius: 12px;
          font-size: 14px;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .msg.user .bubble {
          background: var(--accent);
          color: #fff;
          border-bottom-right-radius: 4px;
        }
        .msg.assistant .bubble {
          background: var(--card);
          border: 1px solid var(--line);
          border-bottom-left-radius: 4px;
        }
        .cursor {
          color: var(--accent);
          animation: blink 0.9s infinite;
        }
        @keyframes blink {
          50% { opacity: 0; }
        }
        .refs {
          margin-top: 6px;
          max-width: 78%;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .refs-label {
          font-size: 12px;
          color: var(--ink-soft);
        }
        .ref-item {
          font-size: 12px;
          color: var(--ink-soft);
          background: #f6f1e8;
          border: 1px solid var(--line);
          border-radius: 6px;
          padding: 4px 10px;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .ref-no {
          color: var(--accent);
        }
        .ref-score {
          margin-left: auto;
          color: #3d7a4f;
        }
        .chat-error {
          margin: 0 10%;
          background: #f9e8e5;
          color: var(--accent);
          border: 1px solid #e8c4bd;
          border-radius: 8px;
          padding: 8px 14px;
          font-size: 13px;
          cursor: pointer;
          margin-bottom: 8px;
        }
        .input-bar {
          display: flex;
          gap: 12px;
          padding: 16px 10%;
          border-top: 1px solid var(--line);
          background: var(--paper);
        }
        .ask-input {
          flex: 1;
          padding: 10px 14px;
          border: 1px solid var(--line);
          border-radius: 10px;
          background: #fff;
          font-size: 14px;
          outline: none;
          resize: none;
          height: 44px;
          max-height: 120px;
        }
        .ask-input:focus {
          border-color: var(--accent-soft);
        }
        .send-btn {
          padding: 0 24px;
        }
        .empty.small {
          font-size: 12px;
          text-align: center;
          padding: 10px 0;
        }
        /* RAG 调试信息弹窗 */
        .debug-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.35);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 24px;
        }
        .debug-modal {
          background: #fff;
          border-radius: 12px;
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
          width: 720px;
          max-width: 100%;
          max-height: 86vh;
          display: flex;
          flex-direction: column;
        }
        .debug-modal-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 14px 18px;
          border-bottom: 1px solid var(--line);
          background: var(--paper);
          border-radius: 12px 12px 0 0;
        }
        .debug-modal-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 16px;
          color: var(--ink);
          font-weight: bold;
        }
        .debug-modal-close {
          border: none;
          background: none;
          font-size: 22px;
          line-height: 1;
          color: var(--ink-soft);
          cursor: pointer;
          padding: 0 4px;
        }
        .debug-modal-close:hover {
          color: var(--accent);
        }
        .debug-modal-body {
          overflow-y: auto;
          padding: 16px 18px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .debug-meta {
          font-size: 13px;
          color: var(--ink-soft);
          background: var(--paper);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 8px 12px;
          word-break: break-all;
        }
        .debug-sec-title {
          font-size: 13px;
          color: var(--ink);
          font-weight: bold;
          margin-bottom: 8px;
        }
        .debug-item {
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 8px 12px;
          margin-bottom: 8px;
          background: #fdfbf6;
        }
        .debug-item-head {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 12px;
          margin-bottom: 6px;
        }
        .debug-idx {
          color: var(--accent);
          font-weight: bold;
        }
        .debug-score {
          color: #3d7a4f;
          font-weight: bold;
        }
        .debug-src {
          color: var(--ink-soft);
        }
        .debug-chunk {
          font-size: 12px;
          color: var(--ink);
          line-height: 1.6;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .debug-empty {
          font-size: 13px;
          color: var(--ink-soft);
          padding: 8px 0;
        }
        .debug-err {
          font-size: 13px;
          color: var(--accent);
        }
        .debug-prompt {
          background: #1e1e1e;
          color: #d8d8d8;
          font-family: Consolas, Menlo, monospace;
          font-size: 11px;
          line-height: 1.5;
          padding: 12px 14px;
          border-radius: 8px;
          overflow: auto;
          white-space: pre-wrap;
          word-break: break-word;
          max-height: 240px;
        }
      `}</style>
    </div>
  );
}
