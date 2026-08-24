/** 后端 API 封装：REST CRUD + SSE 流式聊天。 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8787/api";

export interface Conversation {
  id: string;
  title: string;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  workspace_dir: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: CitationSource[];
  run_id: string | null;
  status: "completed" | "interrupted";
  created_at: string;
  images: ChatImage[];
  token_estimate: number;
}

export interface ChatImage {
  id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  width: number;
  height: number;
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

export type ActivityStatus =
  | "scheduled"
  | "running"
  | "paused"
  | "completed"
  | "failed";

export interface Activity {
  id: string;
  conversation_id: string;
  title: string;
  prompt: string;
  execution_mode: "direct" | "planned";
  schedule_type: "once" | "interval";
  interval_minutes: number | null;
  next_run_at: string;
  status: ActivityStatus;
  last_run_id: string | null;
  last_error: string | null;
  last_started_at: string | null;
  last_completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlanStep {
  id: string;
  version: number;
  position: number;
  title: string;
  instruction: string;
  tool_hints: string[];
  status: "pending" | "running" | "interrupted" | "completed" | "blocked" | "failed" | "superseded" | "cancelled";
  output_summary: string | null;
  error: string | null;
}

export interface Plan {
  id: string;
  run_id: string;
  conversation_id: string;
  activity_id: string | null;
  goal: string;
  status: "planning" | "running" | "interrupted" | "completed" | "failed" | "cancelled";
  current_version: number;
  replan_count: number;
  error: string | null;
  steps: PlanStep[];
}

export interface Checkpoint {
  id: string;
  run_id: string;
  plan_id: string;
  step_id: string | null;
  sequence: number;
  state: {
    goal?: string;
    current_step?: { id?: string; position?: number; title?: string } | number | null;
    last_observation?: string;
  };
  workspace_snapshot: {
    files?: { path: string; sha256: string }[];
    git_head?: string | null;
  };
  capability_version: string | null;
  status: string;
  created_at: string;
}

export interface AgentRunState {
  id: string;
  conversation_id: string;
  execution_mode: "direct" | "planned";
  status: "running" | "interrupted";
  input_message: string;
  error: string | null;
  has_checkpoint: boolean;
  created_at: string;
}

export interface ConversationRunStats {
  eligible_run_count: number;
  input_tokens: number;
  cached_input_tokens: number;
  average_cache_hit_rate: number | null;
}

export interface RunHistoryTool {
  id: string;
  tool: string;
  args_summary: string;
  result_summary: string | null;
  risk_level: string;
  status: string;
  duration_ms: number | null;
}

export interface AgentRunHistory {
  id: string;
  conversation_id: string;
  execution_mode: "direct" | "planned";
  status: string;
  input_message: string;
  intent: Record<string, unknown> | null;
  context_stats: Record<string, unknown> | null;
  input_tokens: number;
  output_tokens: number;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  tools: RunHistoryTool[];
}

export interface Capability {
  kind: "tool" | "skill" | "mcp_server";
  name: string;
  description: string;
  source: string;
  risk_level: "low" | "medium" | "high" | null;
  required_tools: string[];
  enabled: boolean;
  available: boolean;
}

export type SkillStatus = "enabled" | "disabled" | "missing_dependencies" | "invalid";

export interface SkillItem {
  id: string;
  name: string;
  description: string;
  source: "builtin" | "local" | "online" | "demo";
  required_tools: string[];
  enabled: boolean;
  available: boolean;
  status: SkillStatus;
  error: string | null;
  instructions: string;
  deletable: boolean;
}

export type McpTransport = "stdio" | "streamable_http";

export interface McpServerItem {
  name: string;
  transport: McpTransport;
  command: string;
  args: string[];
  url: string;
  enabled: boolean;
  connected: boolean;
  status: "connected" | "disabled" | "error";
  error: string | null;
  source: string;
  default_risk_level: "low" | "medium" | "high";
  allowed_tools: string[];
  tool_risk_levels: Record<string, "low" | "medium" | "high">;
  env_keys: string[];
  header_keys: string[];
  server_info: Record<string, unknown> | null;
  tools: string[];
}

export interface McpServerInput {
  name: string;
  transport: McpTransport;
  command: string;
  args: string[];
  url: string;
  env: Record<string, string>;
  headers: Record<string, string>;
  enabled: boolean;
  default_risk_level: "low" | "medium" | "high";
  allowed_tools: string[];
  tool_risk_levels: Record<string, "low" | "medium" | "high">;
}

export interface McpTestResult {
  ok: boolean;
  server_info: Record<string, unknown> | null;
  tools: { name: string; description: string }[];
}

export interface PluginItem {
  id: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  skill_count: number;
  mcp_server_count: number;
  status: "enabled" | "disabled" | "needs_configuration" | "invalid";
  error: string | null;
  config_ready: boolean;
  settings: {
    key: string;
    label: string;
    description: string;
    secret: boolean;
    required: boolean;
    configured: boolean;
  }[];
  deletable: boolean;
}

export interface AgentSettings {
  name: string;
  role: string;
  language: string;
  tone: string;
  verbosity: string;
  humor: string;
  formality: string;
  proactivity: string;
  custom_instructions: string;
}

export interface AgentProfile extends AgentSettings {
  id: string;
  profile_name: string;
  is_active: boolean;
}

export interface AgentProfileInput extends AgentSettings {
  profile_name: string;
}

export interface ModelSettings {
  provider: "unconfigured" | "mock" | "openai-compatible";
  base_url: string;
  model: string;
  timeout_seconds: number;
  context_window_tokens: number;
  max_output_tokens: number;
  api_key_configured: boolean;
}

export interface ModelProfile extends ModelSettings {
  id: string;
  name: string;
  is_default: boolean;
}

export interface AppSettings {
  model: ModelSettings;
  model_control: {
    source: "environment" | "profiles" | "error";
    locked: boolean;
    error: string | null;
  };
  models: {
    default_model_id: string;
    items: ModelProfile[];
  };
  context: { max_tokens: number };
  workspace: { coding_workspace_dir: string };
  agent: AgentSettings;
  agents: {
    active_agent_id: string;
    items: AgentProfile[];
  };
}

export interface ModelSettingsInput {
  model_id?: string;
  provider: Exclude<ModelSettings["provider"], "unconfigured">;
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
  timeout_seconds: number;
  context_window_tokens: number;
  max_output_tokens: number;
}

export interface ModelProfileInput extends ModelSettingsInput {
  name: string;
}

export interface DirectoryListing {
  current_path: string | null;
  parent_path: string | null;
  directories: { name: string; path: string }[];
}

export type MemoryKind = "episodic" | "semantic" | "profile";

export interface Memory {
  id: string;
  kind: MemoryKind;
  content: string;
  importance: number;
  confidence: number;
  is_active: boolean;
  scope_type: "global" | "project" | "conversation";
  scope_key: string;
  status: "active" | "superseded" | "expired";
  supersedes_id: string | null;
  usage_count: number;
  last_used_at: string | null;
  source_conversation_id: string | null;
  created_at: string;
  updated_at: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const text = await resp.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      detail = parsed.detail ?? text;
    } catch {
      // 非 JSON 错误保留后端原文。
    }
    throw new Error(`请求失败 ${resp.status}: ${detail}`);
  }
  return resp.json();
}

export const fetchConversations = () =>
  req<Conversation[]>(`${API_URL}/conversations`);

export const createConversation = (projectId: string | null = null) =>
  req<Conversation>(`${API_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });

export const fetchProjects = () => req<Project[]>(`${API_URL}/projects`);

export const createProject = (body: { name: string; workspace_dir?: string | null }) =>
  req<Project>(`${API_URL}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

export const chatImageContentUrl = (id: string) =>
  `${API_URL}/chat/images/${encodeURIComponent(id)}/content`;

export const uploadChatImage = (file: File) => {
  const body = new FormData();
  body.append("file", file);
  return req<ChatImage>(`${API_URL}/chat/images`, { method: "POST", body });
};

export const deleteStagedChatImage = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/chat/images/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

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

export const cancelChatRun = (runId: string) =>
  req<{ ok: boolean; status: "cancelling" | "interrupted"; run_id: string }>(
    `${API_URL}/chat/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );

export const fetchActivities = () => req<Activity[]>(`${API_URL}/activities`);

export const createActivity = (body: {
  title: string;
  prompt: string;
  schedule_type: "once" | "interval";
  interval_minutes: number | null;
  next_run_at: string;
  execution_mode: "direct" | "planned";
}) =>
  req<Activity>(`${API_URL}/activities`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const pauseActivity = (id: string) =>
  req<Activity>(`${API_URL}/activities/${id}/pause`, { method: "POST" });

export const resumeActivity = (id: string) =>
  req<Activity>(`${API_URL}/activities/${id}/resume`, { method: "POST" });

export const runActivityNow = (id: string) =>
  req<Activity>(`${API_URL}/activities/${id}/run-now`, { method: "POST" });

export const deleteActivity = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/activities/${id}`, { method: "DELETE" });

export const fetchConversationPlans = (conversationId: string) =>
  req<Plan[]>(`${API_URL}/conversations/${conversationId}/plans`);

export const fetchConversationCheckpoints = (conversationId: string) =>
  req<Checkpoint[]>(`${API_URL}/conversations/${conversationId}/checkpoints`);

export const fetchCurrentConversationRun = (conversationId: string) =>
  req<AgentRunState | null>(`${API_URL}/conversations/${conversationId}/runs/current`);

export const fetchConversationRunStats = (conversationId: string) =>
  req<ConversationRunStats>(`${API_URL}/conversations/${conversationId}/runs/stats`);

export const fetchConversationRunHistory = (conversationId: string) =>
  req<AgentRunHistory[]>(`${API_URL}/conversations/${conversationId}/runs/history`);

export const fetchCapabilities = () => req<Capability[]>(`${API_URL}/capabilities`);

export const fetchSkills = () => req<SkillItem[]>(`${API_URL}/skills`);

export const refreshSkills = () =>
  req<SkillItem[]>(`${API_URL}/skills/refresh`, { method: "POST" });

export const updateSkill = (id: string, enabled: boolean) =>
  req<SkillItem>(`${API_URL}/skills/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });

export const importSkillFolder = (files: File[]) => {
  const body = new FormData();
  for (const file of files) {
    const relativePath = file.webkitRelativePath || file.name;
    body.append("paths", relativePath);
    body.append("files", file, file.name);
  }
  return req<SkillItem>(`${API_URL}/skills/import-folder`, { method: "POST", body });
};

export const createSkill = (body: {
  id: string;
  name: string;
  description: string;
  instructions: string;
  required_tools: string[];
}) =>
  req<SkillItem>(`${API_URL}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteSkill = (id: string) =>
  req<{ ok: boolean; recoverable: boolean }>(`${API_URL}/skills/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const fetchMcpServers = () => req<McpServerItem[]>(`${API_URL}/mcp-servers`);

export const refreshMcpServers = () =>
  req<McpServerItem[]>(`${API_URL}/mcp-servers/refresh`, { method: "POST" });

export const testMcpServer = (body: McpServerInput) =>
  req<McpTestResult>(`${API_URL}/mcp-servers/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const saveMcpServer = (body: McpServerInput) =>
  req<McpServerItem>(`${API_URL}/mcp-servers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateMcpServer = (name: string, enabled: boolean) =>
  req<McpServerItem>(`${API_URL}/mcp-servers/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });

export const deleteMcpServer = (name: string) =>
  req<{ ok: boolean }>(`${API_URL}/mcp-servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });

export const fetchPlugins = () => req<PluginItem[]>(`${API_URL}/plugins`);

export const refreshPlugins = () =>
  req<PluginItem[]>(`${API_URL}/plugins/refresh`, { method: "POST" });

export const updatePlugin = (id: string, enabled: boolean) =>
  req<PluginItem>(`${API_URL}/plugins/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });

export const updatePluginSettings = (
  id: string,
  body: { values: Record<string, string>; clear_keys: string[] },
) =>
  req<PluginItem>(`${API_URL}/plugins/${encodeURIComponent(id)}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deletePlugin = (id: string) =>
  req<{ ok: boolean; recoverable: boolean }>(`${API_URL}/plugins/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const importPluginFolder = (files: File[]) => {
  const body = new FormData();
  for (const file of files) {
    const relativePath = file.webkitRelativePath || file.name;
    body.append("paths", relativePath);
    body.append("files", file, file.name);
  }
  return req<PluginItem>(`${API_URL}/plugins/import-folder`, { method: "POST", body });
};

export const fetchAppSettings = () => req<AppSettings>(`${API_URL}/settings`);

export const updateAgentSettings = (body: AgentSettings) =>
  req<AgentSettings>(`${API_URL}/settings/agent`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const createAgentProfile = (body: AgentProfileInput) =>
  req<AgentProfile>(`${API_URL}/settings/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateAgentProfile = (id: string, body: AgentProfileInput) =>
  req<AgentProfile>(`${API_URL}/settings/agents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const setActiveAgentProfile = (agentId: string) =>
  req<AppSettings["agents"]>(`${API_URL}/settings/agents/selection`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId }),
  });

export const deleteAgentProfile = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/settings/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const updateModelSettings = (body: ModelSettingsInput) =>
  req<ModelSettings>(`${API_URL}/settings/model`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const createModelProfile = (body: ModelProfileInput) =>
  req<ModelProfile>(`${API_URL}/settings/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateModelProfile = (id: string, body: ModelProfileInput) =>
  req<ModelProfile>(`${API_URL}/settings/models/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const setDefaultModelProfile = (modelId: string) =>
  req<AppSettings["models"]>(`${API_URL}/settings/models/selection`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });

export const deleteModelProfile = (id: string) =>
  req<{ ok: boolean }>(`${API_URL}/settings/models/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const testModelSettings = (body: ModelSettingsInput) =>
  req<{ ok: boolean; message: string }>(`${API_URL}/settings/model/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const updateWorkspaceSettings = (codingWorkspaceDir: string) =>
  req<{ coding_workspace_dir: string }>(`${API_URL}/settings/workspace`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ coding_workspace_dir: codingWorkspaceDir }),
  });

export const fetchDirectories = (path?: string | null) =>
  req<DirectoryListing>(
    `${API_URL}/settings/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`,
  );

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
  executionMode: "direct" | "planned" = "direct",
  documentIds: string[] = [],
  modelId?: string | null,
  imageIds: string[] = [],
  runId?: string,
  requirePlanApproval = false,
): Promise<void> {
  const resp = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id: runId || null,
      conversation_id: convId,
      message,
      execution_mode: executionMode,
      document_ids: documentIds,
      model_id: modelId || null,
      image_ids: imageIds,
      require_plan_approval: requirePlanApproval,
    }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      // 保留非 JSON 错误原文。
    }
    throw new Error(`聊天失败 ${resp.status}: ${detail}`);
  }
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

export async function streamResumeRun(
  runId: string,
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_URL}/chat/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    signal,
  });
  if (!resp.ok || !resp.body) {
    const text = await resp.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      // 保留非 JSON 错误原文。
    }
    throw new Error(`恢复失败 ${resp.status}: ${detail}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const event = parseEventBlock(buffer.slice(0, index));
      buffer = buffer.slice(index + 2);
      if (event) onEvent(event);
    }
  }
}
