"use client";

import { useCallback, useEffect, useState } from "react";
import { SettingItem, settingsApi } from "@/lib/api";

export default function SettingsPage() {
  const [items, setItems] = useState<SettingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await settingsApi.get();
      setItems(res.items);
      setDirty(false);
    } catch (e: any) {
      setError(`加载参数失败：${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setValue = (key: string, raw: string) => {
    setItems((prev) =>
      prev.map((it) => {
        if (it.key !== key) return it;
        const v = it.type === "float" ? parseFloat(raw) : parseInt(raw, 10);
        return { ...it, value: Number.isNaN(v) ? 0 : v };
      })
    );
    setDirty(true);
  };

  const resetAll = () => {
    setItems((prev) => prev.map((it) => ({ ...it, value: it.default })));
    setDirty(true);
    setMsg("");
  };

  const save = async () => {
    setSaving(true);
    setError("");
    setMsg("");
    const values: Record<string, number> = {};
    for (const it of items) values[it.key] = it.value;
    try {
      await settingsApi.update(values);
      setMsg("已保存并立即生效");
      setDirty(false);
      // 保存后重新拉取一次，回显后端实际接受的值
      const fresh = await settingsApi.get();
      setItems(fresh.items);
    } catch (e: any) {
      setError(`保存失败：${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings">
      <div className="head">
        <h1 className="page-title">参数设置</h1>
        <p className="sub">调整 RAG 检索与回答判定参数，保存后立即生效，无需重启服务</p>
      </div>

      {error && <div className="alert-error" onClick={() => setError("")}>{error}</div>}
      {msg && <div className="alert-ok" onClick={() => setMsg("")}>{msg}</div>}

      {loading ? (
        <div className="empty">加载中…</div>
      ) : (
        <div className="panel card">
          <div className="hint">
            分块类参数（分块目标字符数、重叠字符数）影响<span>已入库</span>文档的切分，保存后需对相关文档重建索引才应用到存量数据；新上传文档直接用新值。其余参数保存后立即生效。
          </div>
          {items.map((it) => (
            <div className="row" key={it.key}>
              <div className="info">
                <div className="label">
                  {it.label}
                  <code className="key">{it.key}</code>
                </div>
                <div className="desc">{it.desc}</div>
                <div className="range">
                  范围 {it.min} ~ {it.max} · 默认 {it.default}
                </div>
              </div>
              <div className="ctrl">
                <input
                  className="input num"
                  type="number"
                  step={it.type === "float" ? "0.01" : "1"}
                  min={it.min}
                  max={it.max}
                  value={Number.isFinite(it.value) ? it.value : ""}
                  onChange={(e) => setValue(it.key, e.target.value)}
                />
                <span className="current">当前 {it.value}</span>
              </div>
            </div>
          ))}
          <div className="foot">
            <button className="btn ghost" onClick={resetAll}>
              恢复默认
            </button>
            <button className="btn" onClick={save} disabled={saving || !dirty}>
              {saving ? "保存中…" : "保存并生效"}
            </button>
          </div>
        </div>
      )}

      <style jsx>{`
        .settings {
          max-width: 880px;
          margin: 0 auto;
          padding: 24px;
        }
        .head {
          margin-bottom: 16px;
        }
        .page-title {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 22px;
          color: var(--ink);
        }
        .sub {
          color: var(--ink-soft);
          font-size: 13px;
          margin-top: 4px;
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
        .alert-ok {
          background: #eaf4ec;
          color: #3d7a4f;
          border: 1px solid #c3e2cb;
          border-radius: 8px;
          padding: 10px 14px;
          margin-bottom: 14px;
          cursor: pointer;
          font-size: 13px;
        }
        .panel {
          display: flex;
          flex-direction: column;
        }
        .hint {
          background: #f6f1e9;
          border-left: 3px solid var(--accent-soft);
          padding: 10px 14px;
          border-radius: 6px;
          font-size: 12.5px;
          color: var(--ink-soft);
          margin-bottom: 8px;
        }
        .hint span {
          color: var(--accent);
        }
        .row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 20px;
          padding: 14px 4px;
          border-bottom: 1px solid #f0ece2;
        }
        .row:last-of-type {
          border-bottom: none;
        }
        .info {
          flex: 1;
        }
        .label {
          font-weight: 600;
          font-size: 14px;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .key {
          font-family: "Consolas", monospace;
          font-size: 11px;
          color: var(--ink-soft);
          background: #f3ece4;
          padding: 1px 8px;
          border-radius: 4px;
          font-weight: 400;
        }
        .desc {
          color: var(--ink-soft);
          font-size: 12.5px;
          margin-top: 4px;
        }
        .range {
          color: #999;
          font-size: 11.5px;
          margin-top: 4px;
        }
        .ctrl {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 4px;
          width: 180px;
        }
        .input.num {
          width: 100%;
          text-align: right;
          font-family: "Consolas", monospace;
        }
        .current {
          color: var(--ink-soft);
          font-size: 11px;
        }
        .foot {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          margin-top: 16px;
        }
        .empty {
          color: var(--ink-soft);
          text-align: center;
          padding: 60px 0;
        }
      `}</style>
    </div>
  );
}