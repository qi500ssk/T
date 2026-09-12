"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { fetchAgentRunHistory, type AgentRunHistory, type Conversation } from "@/lib/api";
import {
  RunStepsList,
  compactText,
  formatElapsed,
  historicalTraceItems,
  runElapsedSeconds,
} from "@/components/runTrace";
import {
  getLiveRunSession,
  listLiveRunSessionIds,
  subscribeLiveRunSession,
} from "@/components/liveRuns";

const RUN_STATUS: Record<string, { label: string; className: string }> = {
  completed: { label: "已完成", className: "bg-emerald-50 text-emerald-700" },
  running: { label: "运行中", className: "bg-blue-50 text-blue-700" },
  failed: { label: "失败", className: "bg-red-50 text-red-700" },
  interrupted: { label: "已中断", className: "bg-amber-50 text-amber-700" },
  cancelled: { label: "已停止", className: "bg-zinc-100 text-zinc-500" },
};

function RunStatusChip({ status }: { status: string }) {
  const value = RUN_STATUS[status] ?? { label: status, className: "bg-zinc-100 text-zinc-500" };
  return <span className={`rounded-md px-2 py-1 text-xs font-medium ${value.className}`}>{value.label}</span>;
}

/** 按角色隔离的处理步骤视图：实时 Run + 该好友全部会话的历史 Run。 */
export default function RunStepsView({
  agentId,
  agentName,
  conversations,
}: {
  agentId: string | null;
  agentName: string;
  conversations: Conversation[];
}) {
  const [history, setHistory] = useState<AgentRunHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const wasRunningRef = useRef(false);

  const agentConversations = useMemo(
    () => conversations.filter((conversation) => conversation.agent_id === agentId),
    [agentId, conversations],
  );
  const conversationTitles = useMemo(
    () => Object.fromEntries(agentConversations.map((conversation) => [conversation.id, conversation.title])),
    [agentConversations],
  );

  // 实时步骤来自各会话的 Live Session；进入视图时订阅既有会话，
  // 任何一条事件到达都让整个视图重算（本地 App，事件频率可接受）。
  useEffect(() => {
    const bump = () => setVersion((value) => value + 1);
    const unsubscribe = listLiveRunSessionIds().map((conversationId) =>
      subscribeLiveRunSession(conversationId, bump),
    );
    return () => unsubscribe.forEach((dispose) => dispose());
  }, []);

  const loadHistory = (quiet = false) => {
    if (!agentId) {
      setHistory([]);
      setHistoryLoading(false);
      return;
    }
    if (!quiet) setHistoryLoading(true);
    fetchAgentRunHistory(agentId)
      .then((rows) => setHistory(rows))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  };

  useEffect(() => {
    let cancelled = false;
    // 与 ChatView 一致：用微任务包裹重置，避免在 effect 里同步 setState。
    queueMicrotask(() => {
      if (cancelled) return;
      setExpanded(null);
      setHistoryLoading(true);
      if (!agentId) {
        setHistory([]);
        setHistoryLoading(false);
        return;
      }
      fetchAgentRunHistory(agentId)
        .then((rows) => { if (!cancelled) setHistory(rows); })
        .catch(() => { if (!cancelled) setHistory([]); })
        .finally(() => { if (!cancelled) setHistoryLoading(false); });
    });
    return () => { cancelled = true; };
  }, [agentId]);

  const liveSessions = useMemo(
    () => agentConversations
      .map((conversation) => ({ conversationId: conversation.id, session: getLiveRunSession(conversation.id) }))
      .filter((entry): entry is { conversationId: string; session: NonNullable<typeof entry.session> } => (
        entry.session != null
        && (entry.session.running || entry.session.runTrace.length > 0 || Boolean(entry.session.thinking.trim()))
      )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [agentConversations, history, version],
  );
  const anyRunning = liveSessions.some((entry) => entry.session.running);

  useEffect(() => {
    // 一场 Run 刚结束就刷新历史，完整步骤立即出现在下方列表。
    if (wasRunningRef.current && !anyRunning) loadHistory(true);
    wasRunningRef.current = anyRunning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyRunning]);

  useEffect(() => {
    // 运行中每秒走一格时钟，保证“正在处理”的耗时实时跳动。
    if (!anyRunning) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      setVersion((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [anyRunning]);

  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-7 lg:px-10">
        <header className="border-b border-zinc-200 pb-5">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-400">Agent pipeline</p>
          <div className="mt-1 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-zinc-950">处理步骤</h1>
              <p className="mt-1.5 max-w-2xl text-sm leading-6 text-zinc-500">
                每个 AI 好友的处理过程彼此独立。这里只显示 {agentName} 的记录：思考、意图、上下文装配、工具调用与回答生成的完整明细。
              </p>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-right shadow-sm">
              <p className="text-2xl font-semibold tabular-nums text-zinc-900">{history.length}</p>
              <p className="text-xs text-zinc-500">条历史运行</p>
            </div>
          </div>
        </header>

        {!agentId && (
          <p className="mt-6 rounded-2xl border border-dashed border-zinc-300 py-16 text-center text-sm text-zinc-400">
            请先选择一个 AI 好友。
          </p>
        )}

        {agentId && liveSessions.length > 0 && (
          <section className="mt-6 space-y-4" aria-label="实时处理步骤">
            {liveSessions.map(({ conversationId, session }) => (
              <div key={conversationId} className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm sm:p-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-zinc-800">{conversationTitles[conversationId] ?? "当前会话"}</h2>
                  <span className={`rounded-md px-2 py-1 text-xs ${session.running ? "bg-blue-50 text-blue-700" : "bg-zinc-100 text-zinc-500"}`}>
                    {session.running ? `正在处理 · ${formatElapsed(Math.max(0, Math.floor((now - session.startedAt) / 1000)))}` : "最近一次"}
                  </span>
                </div>
                <div className="ml-2 border-l border-zinc-200 pl-7">
                  <RunStepsList items={session.runTrace} />
                </div>
                {session.thinking.trim() && (
                  <div className="ml-2 mt-4 border-l border-zinc-200 pl-7">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">本次思考</h3>
                    <p className="mt-2 whitespace-pre-line break-words text-[13px] leading-6 text-zinc-500">{session.thinking}</p>
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        <section className="mt-8" aria-label="历史运行">
          <div className="mb-3 flex items-center gap-3">
            <h2 className="text-sm font-semibold text-zinc-800">{agentName}的历史运行</h2>
            <span className="text-xs tabular-nums text-zinc-400">{history.length} 条</span>
            <span className="h-px flex-1 bg-zinc-200" />
            <button
              type="button"
              onClick={() => loadHistory()}
              disabled={!agentId || historyLoading}
              className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
            >
              刷新
            </button>
          </div>
          {historyLoading ? (
            <p className="py-16 text-center text-sm text-zinc-400">正在读取运行记录…</p>
          ) : history.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-zinc-300 py-16 text-center text-sm text-zinc-400">
              还没有运行记录；和 {agentName} 聊一句后这里会出现完整的处理步骤。
            </p>
          ) : (
            <div className="space-y-3">
              {history.map((run) => {
                const open = expanded === run.id;
                return (
                  <article key={run.id} className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm sm:p-5">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                      <RunStatusChip status={run.status} />
                      <span>{new Date(run.created_at).toLocaleString("zh-CN")}</span>
                      <span className="text-zinc-300">·</span>
                      <span className="max-w-48 truncate">{run.conversation_title || "会话"}</span>
                      <span className="text-zinc-300">·</span>
                      <span>{run.execution_mode === "planned" ? "规划模式" : "自主模式"}</span>
                      <span className="text-zinc-300">·</span>
                      <span className="tabular-nums">{formatElapsed(runElapsedSeconds(run))}</span>
                      <span className="text-zinc-300">·</span>
                      <span className="tabular-nums">输入 {run.input_tokens || 0} / 输出 {run.output_tokens || 0} tokens</span>
                      <button
                        type="button"
                        onClick={() => setExpanded((value) => (value === run.id ? null : run.id))}
                        aria-expanded={open}
                        className="ml-auto rounded-md px-2 py-1 font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
                      >
                        {open ? "收起明细" : "查看完整步骤"}
                      </button>
                    </div>
                    <p className="mt-2 break-words text-sm leading-6 text-zinc-700">{compactText(run.input_message, 160)}</p>
                    {run.error && <p className="mt-1 break-words text-xs text-red-700">{run.error}</p>}
                    {open && (
                      <div className="ml-2 mt-4 border-l border-zinc-200 pl-7 pt-2">
                        <RunStepsList items={historicalTraceItems(run, true)} />
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
