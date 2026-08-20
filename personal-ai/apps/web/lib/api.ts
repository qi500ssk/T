/** 后端 API 封装：REST CRUD + SSE 流式聊天。 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8787/api";

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: CitationSource[];
  created_at: string;
}

export interface CitationSource {
  citation_id: string;
  document_id: string;
  chunk_id: string;
  filename: string;
  section: string;
  page_start: number | null;
  page_end: number | null;
  char_start: number | null;
  char_end: number | null;
  chunk_index: number;
  excerpt: string;
}

export type DocumentStatus = "pending" | "indexing" | "indexed" | "needs_ocr" | "failed";

export interface KnowledgeDocument {
  id: string;
  original_filename: string;
  mime_type: string;
  file_type: string;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  embedding_model: string;
  embedding_dim: number;
  created_at: string;
  updated_at: string;
}

export interface ChunkPreview {
  id: string;
  chunk_index: number;
  section: string;
  content: string;
  page_start: number | null;
  page_end: number | null;
  char_start: number | null;
  char_end: number | null;
}

export interface DocumentDetail extends KnowledgeDocument {
  chunks: ChunkPreview[];
}

export interface SearchResult extends Omit<ChunkPreview, "id"> {
  chunk_id: string;
  document_id: string;
  filename: string;
  vector_score: number | null;
  bm25_score: number | null;
  rrf_score: number;
  retrieval_rank: number;
}

export interface AgentEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface ApprovalResponse {
  ok: boolean;
}

export type MemoryKind = "episodic" | "semantic" | "profile";

export interface Memory {
  id: string;
  kind: MemoryKind;
  content: string;
  importance: number;
  confidence: number;
  is_active: boolean;
  source_conversation_id: string | null;
  created_at: string;
  updated_at: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) throw new Error(`请求失败 ${resp.status}: ${await resp.text()}`);
  return resp.json();
}

export const fetchConversations = () =>
  req<Conversation[]>(`${API_URL}/conversations`);

export const createConversation = () =>
  req<Conversation>(`${API_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

export const deleteConversation = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/conversations/${id}`, { method: "DELETE" });

export const fetchMessages = (convId: string) =>
  req<ChatMessage[]>(`${API_URL}/conversations/${convId}/messages`);

export const fetchDocuments = () => req<KnowledgeDocument[]>(`${API_URL}/documents`);

export const fetchDocument = (id: string) =>
  req<DocumentDetail>(`${API_URL}/documents/${id}`);

export const documentContentUrl = (id: string, page?: number | null) =>
  `${API_URL}/documents/${id}/content${page ? `#page=${page}` : ""}`;

export const uploadFile = (file: File) => {
  const body = new FormData();
  body.append("file", file);
  return req<KnowledgeDocument>(`${API_URL}/files`, { method: "POST", body });
};

export const deleteDocument = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/documents/${id}`, { method: "DELETE" });

export const searchPreview = (query: string, limit = 5) =>
  req<SearchResult[]>(`${API_URL}/search?q=${encodeURIComponent(query)}&limit=${limit}`);

export const fetchMemories = () => req<Memory[]>(`${API_URL}/memories`);

export const createMemory = (body: {
  content: string;
  kind: MemoryKind;
  importance: number;
}) =>
  req<Memory>(`${API_URL}/memories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateMemory = (
  id: string,
  body: Partial<Pick<Memory, "content" | "kind" | "importance" | "is_active">>,
) =>
  req<Memory>(`${API_URL}/memories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteMemory = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/memories/${id}`, { method: "DELETE" });

export const submitApproval = (approvalId: string, approved: boolean) =>
  req<ApprovalResponse>(`${API_URL}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approval_id: approvalId, approved }),
  });

function parseEventBlock(block: string): AgentEvent | null {
  let event = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  if (!event) return null;
  return { event, data: data ? JSON.parse(data) : {} };
}

/** 流式聊天：解析 SSE 事件并回调，可被 AbortController 中止。 */
export async function streamChat(
  convId: string,
  message: string,
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: convId, message }),
    signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`聊天失败 ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const ev = parseEventBlock(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
      if (ev) onEvent(ev);
    }
  }
}
