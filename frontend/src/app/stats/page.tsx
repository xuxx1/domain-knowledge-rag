"use client";

import { useEffect, useState } from "react";
import {
  HotDoc,
  KBCompare,
  MissedItem,
  Overview,
  TrendItem,
  docApi,
  kbApi,
  statsApi,
} from "@/lib/api";

export default function StatsPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [trend, setTrend] = useState<TrendItem[]>([]);
  const [hot, setHot] = useState<HotDoc[]>([]);
  const [missed, setMissed] = useState<MissedItem[]>([]);
  const [cmp, setCmp] = useState<KBCompare[]>([]);
  const [error, setError] = useState("");
  const [kbs, setKbs] = useState<{ id: number; name: string }[]>([]);

  // 补录弹窗
  const [showAdd, setShowAdd] = useState(false);
  const [addKbId, setAddKbId] = useState<number>(0);
  const [addTitle, setAddTitle] = useState("");
  const [addContent, setAddContent] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    Promise.all([
      statsApi.overview(),
      statsApi.trend(14),
      statsApi.hotDocs(10),
      statsApi.missed(20),
      statsApi.comparison(),
      kbApi.list(),
    ])
      .then(([o, t, h, m, c, k]) => {
        setOv(o);
        setTrend(t);
        setHot(h);
        setMissed(m);
        setCmp(c);
        setKbs(k);
        if (k.length > 0) setAddKbId(k[0].id);
      })
      .catch((e) => setError(`加载统计数据失败：${e.message}`));
  }, []);

  const openAdd = (q?: string) => {
    if (kbs.length === 0) {
      setError("暂无知识库，请先在知识库页创建");
      return;
    }
    setAddTitle(q ? q.slice(0, 40) : "");
    setAddContent("");
    setShowAdd(true);
  };

  const submitAdd = async () => {
    if (!addKbId || !addContent.trim()) return;
    setAdding(true);
    setError("");
    try {
      await docApi.quickAdd(addKbId, {
        title: addTitle.trim() || "盲区补录",
        content: addContent.trim(),
        source: "知识分析-盲区补录",
      });
      setShowAdd(false);
      setAddContent("");
      // 刷新统计
      const [o, t, h, m] = await Promise.all([
        statsApi.overview(),
        statsApi.trend(14),
        statsApi.hotDocs(10),
        statsApi.missed(20),
      ]);
      setOv(o);
      setTrend(t);
      setHot(h);
      setMissed(m);
    } catch (e: any) {
      setError(`补录失败：${e.message}`);
    } finally {
      setAdding(false);
    }
  };

  const maxTotal = Math.max(1, ...trend.map((t) => t.total));

  return (
    <div className="stats">
      <h1 className="page-title">知识分析</h1>

      {error && <div className="alert-error" onClick={() => setError("")}>{error}</div>}

      {/* 指标卡 */}
      <div className="metric-grid">
        {[
          { label: "知识库", value: ov?.kb_count ?? "-", unit: "个" },
          { label: "文档", value: ov?.doc_count ?? "-", unit: "份" },
          { label: "知识块", value: ov?.chunk_count ?? "-", unit: "块" },
          {
            label: "提问总数",
            value: ov?.question_count ?? "-",
            unit: "次",
          },
          {
            label: "检索命中率",
            value: ov && ov.question_count > 0 ? (ov.hit_rate * 100).toFixed(1) : "-",
            unit: ov && ov.question_count > 0 ? "%" : "",
          },
          {
            label: "平均相似度",
            value: ov && ov.question_count > 0 ? (ov.avg_score * 100).toFixed(1) : "-",
            unit: ov && ov.question_count > 0 ? "%" : "",
          },
        ].map((m) => (
          <div key={m.label} className="card metric">
            <div className="metric-label">{m.label}</div>
            <div className="metric-value">
              {m.value}
              <span className="metric-unit">{m.unit}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        {/* 趋势 */}
        <div className="card panel">
          <h3 className="panel-title">近 14 天提问趋势</h3>
          {trend.length === 0 ? (
            <div className="empty">暂无问答数据</div>
          ) : (
            <div className="chart">
              {trend.map((t) => (
                <div key={t.date} className="bar-col" title={`${t.date}：${t.hit}/${t.total} 命中`}>
                  <div className="bar-stack">
                    <div
                      className="bar hit"
                      style={{ height: `${(t.hit / maxTotal) * 100}%` }}
                    />
                    <div
                      className="bar miss"
                      style={{ height: `${((t.total - t.hit) / maxTotal) * 100}%` }}
                    />
                  </div>
                  <div className="bar-label">{t.date.slice(5)}</div>
                </div>
              ))}
              <div className="legend">
                <span><i className="dot hit" />命中</span>
                <span><i className="dot miss" />未命中</span>
              </div>
            </div>
          )}
        </div>

        {/* 知识库对比 */}
        <div className="card panel">
          <h3 className="panel-title">知识库对比</h3>
          {cmp.length === 0 ? (
            <div className="empty">暂无知识库</div>
          ) : (
            <table className="stats-table">
              <thead>
                <tr>
                  <th>知识库</th>
                  <th>文档</th>
                  <th>知识块</th>
                  <th>提问数</th>
                </tr>
              </thead>
              <tbody>
                {cmp.map((c) => (
                  <tr key={c.kb_id}>
                    <td>{c.name}</td>
                    <td>{c.doc_count}</td>
                    <td>{c.chunk_count}</td>
                    <td>{c.question_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="grid-2">
        {/* 热门文档 */}
        <div className="card panel">
          <h3 className="panel-title">高频被引文档</h3>
          {hot.length === 0 ? (
            <div className="empty">暂无引用数据</div>
          ) : (
            <ol className="rank-list">
              {hot.map((h, i) => (
                <li key={h.doc_id}>
                  <span className={`rank-no${i < 3 ? " top" : ""}`}>{i + 1}</span>
                  <span className="rank-title">{h.title}</span>
                  <span className="rank-count">{h.citations} 次引用</span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {/* 知识盲区 */}
        <div className="card panel">
          <h3 className="panel-title">知识盲区（未命中问题）</h3>
          {missed.length === 0 && (
            <div className="empty">暂无未命中问题</div>
          )}
          {missed.length > 0 && (
            <>
              <ul className="miss-list">
                {missed.map((m, i) => (
                  <li key={i}>
                    <span className="miss-q">{m.question}</span>
                    <span className="miss-time">{m.asked_at.slice(5, 16)}</span>
                    <button
                      className="btn small ghost"
                      onClick={() => openAdd(m.question)}
                    >
                      补录
                    </button>
                  </li>
                ))}
              </ul>
              <p className="hint">提示：针对以上问题点击「补录」补充知识，可提升知识覆盖率。</p>
            </>
          )}
        </div>
      </div>

      {/* 补录弹窗 */}
      {showAdd && (
        <div className="modal-mask" onClick={() => setShowAdd(false)}>
          <div className="modal card" onClick={(e) => e.stopPropagation()}>
            <h3>补充知识内容</h3>
            <label>补入知识库</label>
            <select
              className="input"
              value={addKbId}
              onChange={(e) => setAddKbId(Number(e.target.value))}
            >
              {kbs.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
            <label>标题</label>
            <input
              className="input"
              value={addTitle}
              onChange={(e) => setAddTitle(e.target.value)}
              placeholder="该条知识的标题"
            />
            <label>内容 *</label>
            <textarea
              className="textarea"
              value={addContent}
              onChange={(e) => setAddContent(e.target.value)}
              placeholder="粘贴该问题的答案或相关知识内容，保存后将自动分块并向量化，可被检索问答"
              rows={6}
            />
            <div className="modal-ops">
              <button className="btn ghost" onClick={() => setShowAdd(false)}>
                取消
              </button>
              <button className="btn" onClick={submitAdd} disabled={adding || !addContent.trim()}>
                {adding ? "处理中…" : "保存并入库"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .stats {
          max-width: 1200px;
          margin: 0 auto;
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .page-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 22px;
        }
        .alert-error {
          background: #f9e8e5;
          color: var(--accent);
          border: 1px solid #e8c4bd;
          border-radius: 8px;
          padding: 10px 14px;
          font-size: 13px;
          cursor: pointer;
        }
        .metric-grid {
          display: grid;
          grid-template-columns: repeat(6, 1fr);
          gap: 14px;
        }
        @media (max-width: 1000px) {
          .metric-grid {
            grid-template-columns: repeat(3, 1fr);
          }
        }
        .metric-label {
          color: var(--ink-soft);
          font-size: 12px;
        }
        .metric-value {
          font-size: 26px;
          font-weight: 600;
          margin-top: 6px;
          color: var(--ink);
        }
        .metric-unit {
          font-size: 12px;
          font-weight: 400;
          color: var(--ink-soft);
          margin-left: 4px;
        }
        .grid-2 {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
        }
        @media (max-width: 900px) {
          .grid-2 {
            grid-template-columns: 1fr;
          }
        }
        .panel-title {
          font-size: 15px;
          margin-bottom: 14px;
        }
        .empty {
          color: var(--ink-soft);
          text-align: center;
          padding: 30px 0;
          font-size: 13px;
        }
        /* 趋势柱状图 */
        .chart {
          display: flex;
          align-items: flex-end;
          gap: 6px;
          height: 160px;
          padding-top: 10px;
          position: relative;
        }
        .bar-col {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
        }
        .bar-stack {
          width: 60%;
          display: flex;
          flex-direction: column-reverse;
          height: 130px;
        }
        .bar {
          width: 100%;
          border-radius: 3px 3px 0 0;
          min-height: 2px;
        }
        .bar.hit {
          background: var(--accent);
        }
        .bar.miss {
          background: var(--accent-soft);
          opacity: 0.5;
        }
        .bar-label {
          font-size: 10px;
          color: var(--ink-soft);
          margin-top: 6px;
          transform: scale(0.9);
        }
        .legend {
          position: absolute;
          top: -6px;
          right: 0;
          display: flex;
          gap: 12px;
          font-size: 12px;
          color: var(--ink-soft);
        }
        .dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 2px;
          margin-right: 4px;
        }
        .dot.hit { background: var(--accent); }
        .dot.miss { background: var(--accent-soft); opacity: 0.5; }
        /* 表格 */
        .stats-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .stats-table th {
          text-align: left;
          color: var(--ink-soft);
          font-weight: 500;
          border-bottom: 1px solid var(--line);
          padding: 8px 10px;
        }
        .stats-table td {
          border-bottom: 1px solid #f0ece2;
          padding: 9px 10px;
        }
        /* 排行 */
        .rank-list {
          list-style: none;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .rank-list li {
          display: flex;
          align-items: center;
          gap: 12px;
          font-size: 13px;
        }
        .rank-no {
          width: 22px;
          height: 22px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #f0ece2;
          border-radius: 6px;
          color: var(--ink-soft);
          font-size: 12px;
          flex-shrink: 0;
        }
        .rank-no.top {
          background: var(--accent);
          color: #fff;
        }
        .rank-title {
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .rank-count {
          color: var(--ink-soft);
          flex-shrink: 0;
        }
        /* 盲区 */
        .miss-list {
          list-style: none;
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 260px;
          overflow-y: auto;
        }
        .miss-list li {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          font-size: 13px;
          padding: 6px 10px;
          background: #faf6ee;
          border-radius: 6px;
        }
        .miss-q {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .miss-time {
          color: var(--ink-soft);
          font-size: 12px;
          flex-shrink: 0;
        }
        .hint {
          margin-top: 10px;
          font-size: 12px;
          color: var(--ink-soft);
        }
        .miss-list li {
          align-items: center;
        }
        .miss-list .miss-q {
          flex: 1;
        }
        .btn.small.ghost {
          padding: 2px 10px;
          font-size: 12px;
          border: 1px solid var(--line);
          background: none;
          color: var(--ink-soft);
          border-radius: 6px;
          cursor: pointer;
          flex-shrink: 0;
        }
        .btn.small.ghost:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
        /* 补录弹窗 */
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
          width: 480px;
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
        .modal .textarea {
          min-height: 120px;
          resize: vertical;
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
