/** 后端 API 封装 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";

// ---------- 类型 ----------
export interface KB {
  id: number;
  name: string;
  description: string;
  domains: string[];
  doc_count: number;
  chunk_count: number;
  char_count: number;
  created_at: string;
  updated_at: string;
}

export interface Doc {
  id: number;
  kb_id: number;
  title: string;
  filename: string;
  file_type: string;
  file_size: number;
  char_count: number;
  chunk_count: number;
  status: string;
  error_msg: string;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: number;
  kb_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface RefItem {
  chunk_id: number;
  doc_id: number;
  doc_title: string;
  seq: number;
  score: number;
}

export interface Message {
  id: number;
  session_id: number;
  role: string;
  content: string;
  references: RefItem[];
  answer_type: string;
  created_at: string;
}

// ---------- 基础请求 ----------
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json; charset=utf-8" },
    ...init,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const j = await resp.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      /* ignore */
    }
    throw new Error(`请求失败 ${resp.status}: ${detail}`);
  }
  return resp.json();
}

// ---------- 知识库 ----------
export const kbApi = {
  list: () => request<KB[]>("/kbs"),
  get: (id: number) => request<KB>(`/kbs/${id}`),
  create: (data: { name: string; description?: string; domains?: string[] }) =>
    request<KB>("/kbs", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: Partial<{ name: string; description: string; domains: string[] }>) =>
    request<KB>(`/kbs/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  remove: (id: number) => request<{ ok: boolean }>(`/kbs/${id}`, { method: "DELETE" }),
};

// ---------- 文档 ----------
export const docApi = {
  list: (kbId: number) => request<Doc[]>(`/kbs/${kbId}/documents`),
  chunks: (kbId: number, docId: number, page = 1, pageSize = 20) =>
    request<{
      total: number;
      page: number;
      page_size: number;
      chunks: { id: number; seq: number; char_count: number; content: string }[];
    }>(`/kbs/${kbId}/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`),
  upload: (kbId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${API_BASE}/kbs/${kbId}/documents/upload`, {
      method: "POST",
      body: form,
    }).then(async (r) => {
      if (!r.ok) {
        let d = "";
        try {
          d = (await r.json()).detail || "";
        } catch {
          /* ignore */
        }
        throw new Error(d || `上传失败 ${r.status}`);
      }
      return r.json() as Promise<Doc>;
    });
  },
  reindex: (kbId: number, docId: number) =>
    request<{ ok: boolean; chunk_count: number; error: string }>(
      `/kbs/${kbId}/documents/${docId}/reindex`,
      { method: "POST" }
    ),
  remove: (kbId: number, docId: number) =>
    request<{ ok: boolean }>(`/kbs/${kbId}/documents/${docId}`, { method: "DELETE" }),
  quickAdd: (kbId: number, data: { title: string; content: string; source?: string }) =>
    request<Doc>(`/kbs/${kbId}/documents/quick-add`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// ---------- 会话 ----------
export const sessionApi = {
  list: (kbId: number) => request<Session[]>(`/kbs/${kbId}/sessions`),
  create: (kbId: number) =>
    request<Session>("/sessions", {
      method: "POST",
      body: JSON.stringify({ kb_id: kbId }),
    }),
  messages: (sessionId: number) => request<Message[]>(`/sessions/${sessionId}/messages`),
  remove: (sessionId: number) =>
    request<{ ok: boolean }>(`/sessions/${sessionId}`, { method: "DELETE" }),
};

// ---------- SSE 流式问答 ----------
export interface RagDebugTopk {
  score: number;
  source: string;
  chunk_id: number;
  seq: number;
  page?: number | null;
  chunk_preview: string;
}
export interface RagDebug {
  query: string;
  query_embedding_dim: number;
  retrieval_top_k: number;
  raw_count: number;
  dedup_count: number;
  topk: RagDebugTopk[];
  prompt: any;
  error?: string;
}
export interface SSEHandlers {
  onRefs?: (refs: RefItem[], answerType: string) => void;
  onDelta?: (text: string) => void;
  onDone?: (info: { message_id: number; elapsed: number }) => void;
  onError?: (message: string) => void;
  onDebug?: (debug: RagDebug) => void;
}

export async function chatSSE(
  sessionId: number,
  question: string,
  handlers: SSEHandlers,
  signal?: AbortSignal
) {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ session_id: sessionId, question }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    handlers.onError?.(`请求失败 ${resp.status}`);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  // SSE 解析
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // 按空行拆事件
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
      }
      if (!event || dataLines.length === 0) continue;
      let payload: any;
      try {
        payload = JSON.parse(dataLines.join(""));
      } catch {
        continue;
      }
      if (event === "refs") handlers.onRefs?.(payload.refs || [], payload.answer_type || "");
      else if (event === "delta") handlers.onDelta?.(payload.text || "");
      else if (event === "done") handlers.onDone?.(payload);
      else if (event === "error") handlers.onError?.(payload.message || "未知错误");
      else if (event === "debug") handlers.onDebug?.(payload as RagDebug);
    }
  }
}

// ---------- 统计 ----------
export interface Overview {
  kb_count: number;
  doc_count: number;
  chunk_count: number;
  question_count: number;
  hit_rate: number;
  avg_score: number;
}
export interface TrendItem {
  date: string;
  total: number;
  hit: number;
}
export interface HotDoc {
  doc_id: number;
  title: string;
  citations: number;
  kb_id?: number;
}
export interface MissedItem {
  question: string;
  asked_at: string;
  session_id: number;
  kb_id?: number;
}
export interface KBCompare {
  kb_id: number;
  name: string;
  doc_count: number;
  chunk_count: number;
  question_count: number;
}

export const statsApi = {
  overview: () => request<Overview>("/stats/overview"),
  trend: (days = 14) => request<TrendItem[]>(`/stats/trend?days=${days}`),
  hotDocs: (limit = 10) => request<HotDoc[]>(`/stats/hot-docs?limit=${limit}`),
  missed: (limit = 20) =>
    request<MissedItem[]>(`/stats/missed-questions?limit=${limit}`),
  comparison: () => request<KBCompare[]>("/stats/kb-comparison"),
};

// ---------- 参数设置 ----------
export interface SettingItem {
  key: string;
  label: string;
  desc: string;
  type: "int" | "float";
  min: number;
  max: number;
  default: number;
  value: number;
}

export const settingsApi = {
  get: () => request<{ items: SettingItem[] }>("/settings"),
  update: (values: Record<string, number>) =>
    request<{ ok: boolean; updated: Record<string, string> }>("/settings", {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),
};
