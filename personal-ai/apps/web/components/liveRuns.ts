import type { AgentRunState, CitationSource, RunPostprocessStatus } from "@/lib/api";
import type { RunTraceItem, ToolStatus } from "@/components/runTrace";

export interface ToolActivity {
  key: string;
  tool: string;
  status: ToolStatus;
  result: string;
}

export interface ApprovalItem {
  approvalId: string;
  tool: string;
  argsSummary: string;
  state: "pending" | "approved" | "rejected" | "submitting" | "expired";
  error: string;
}

export interface ContextUsage {
  usedTokens: number;
  inputBudgetTokens: number;
  contextWindowTokens: number;
  maxOutputTokens: number;
  conversationTokens: number;
  breakdown: Record<string, number>;
}

export interface LiveRunSession {
  runId: string;
  controller: AbortController | null;
  currentRun: AgentRunState | null;
  streaming: string;
  streamingSources: CitationSource[];
  toolActivities: ToolActivity[];
  approvals: ApprovalItem[];
  isStopping: boolean;
  contextUsage: ContextUsage | null;
  contextLoading: boolean;
  runTrace: RunTraceItem[];
  startedAt: number;
  elapsedSeconds: number;
  error: string;
  running: boolean;
  postprocess: Record<string, RunPostprocessStatus>;
  /** 角色思考（内心独白）：直播文本与起止时间。 */
  thinking: string;
  thinkingActive: boolean;
  thinkingStartedAt: number | null;
  thinkingEndedAt: number | null;
}

type LiveRunListener = (session: LiveRunSession | null) => void;

// Run 属于会话而不是 ChatView 组件。切换会话或打开设置页只分离视图，
// 不能销毁流、停止后端任务，也不能让旧 Run 的事件污染新会话。
const LIVE_RUN_SESSIONS = new Map<string, LiveRunSession>();
const LIVE_RUN_LISTENERS = new Map<string, Set<LiveRunListener>>();
const POSTPROCESS_POLLS = new Set<string>();

export function postprocessPollRegistered(runId: string) {
  return POSTPROCESS_POLLS.has(runId);
}

export function registerPostprocessPoll(runId: string) {
  POSTPROCESS_POLLS.add(runId);
}

export function unregisterPostprocessPoll(runId: string) {
  POSTPROCESS_POLLS.delete(runId);
}

export function getLiveRunSession(conversationId: string) {
  return LIVE_RUN_SESSIONS.get(conversationId) ?? null;
}

export function listLiveRunSessionIds() {
  return [...LIVE_RUN_SESSIONS.keys()];
}

export function publishLiveRunSession(conversationId: string, session: LiveRunSession | null) {
  if (session) LIVE_RUN_SESSIONS.set(conversationId, session);
  else LIVE_RUN_SESSIONS.delete(conversationId);
  LIVE_RUN_LISTENERS.get(conversationId)?.forEach((listener) => listener(session));
}

export function updateLiveRunSession(
  conversationId: string,
  update: (session: LiveRunSession) => LiveRunSession,
) {
  const current = LIVE_RUN_SESSIONS.get(conversationId);
  if (!current) return null;
  const next = update(current);
  publishLiveRunSession(conversationId, next);
  return next;
}

export function subscribeLiveRunSession(conversationId: string, listener: LiveRunListener) {
  const listeners = LIVE_RUN_LISTENERS.get(conversationId) ?? new Set<LiveRunListener>();
  listeners.add(listener);
  LIVE_RUN_LISTENERS.set(conversationId, listeners);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) LIVE_RUN_LISTENERS.delete(conversationId);
  };
}
