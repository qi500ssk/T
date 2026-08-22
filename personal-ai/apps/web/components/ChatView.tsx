"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  documentContentUrl,
  fetchConversationPlans,
  fetchMessages,
  submitApproval,
  streamChat,
  type ChatMessage,
  type CitationSource,
  type Plan,
  type PlanStep,
} from "@/lib/api";
import PlanProgress from "@/components/PlanProgress";

interface ChatViewProps {
  conversationId: string | null;
  /** 无会话时点击发送自动创建，返回新会话 id */
  onAutoCreate: () => Promise<string>;
  /** 一次 Run 结束后刷新会话列表（标题可能变化） */
  onFinished: () => void;
}

type ToolStatus = "running" | "completed" | "rejected" | "failed" | "timeout";

interface ToolActivity {
  key: string;
  tool: string;
  status: ToolStatus;
  result: string;
}

interface ApprovalItem {
  approvalId: string;
  tool: string;
  argsSummary: string;
  state: "pending" | "submitting" | "approved" | "rejected" | "expired";
  error: string;
}

const TOOL_LABELS: Record<string, string> = {
  get_time: "查询时间",
  calculate: "执行计算",
  read_file: "读取文件",
  write_file: "写入文件",
  code_list_files: "列出项目文件",
  code_search: "搜索代码",
  code_read: "读取代码",
  code_create_file: "创建代码文件",
  code_edit: "修改代码",
  code_git_diff: "查看代码改动",
  code_run_check: "运行代码检查",
  "mcp_document-skills-generator_create_docx": "生成 Word 文档",
  "mcp_document-skills-generator_append_docx": "更新 Word 文档",
  "mcp_document-skills-generator_create_pdf": "生成 PDF",
  "mcp_document-skills-generator_create_pptx": "生成演示文稿",
  "mcp_document-skills-generator_create_xlsx": "生成工作簿",
};

const STATUS_LABELS: Record<ToolStatus, string> = {
  running: "执行中",
  completed: "已完成",
  rejected: "已拒绝",
  failed: "失败",
  timeout: "已超时",
};

function ToolActivityList({ items }: { items: ToolActivity[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex justify-start" aria-live="polite" aria-label="工具执行状态">
      <div className="w-full max-w-[80%] space-y-1.5 border-l-2 border-gray-200 pl-3 text-xs text-gray-600">
        {items.map((item) => {
          let artifact: { filename: string; download_url: string } | null = null;
          if (item.result.startsWith("ARTIFACT_JSON:")) {
            try {
              artifact = JSON.parse(item.result.split("\n", 1)[0].slice("ARTIFACT_JSON:".length));
            } catch {
              artifact = null;
            }
          }
          return <div key={item.key} className="py-0.5">
            <div className="flex min-w-0 items-center gap-2">
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${
                item.status === "completed"
                  ? "bg-emerald-500"
                  : item.status === "running"
                    ? "animate-pulse bg-blue-500 motion-reduce:animate-none"
                    : "bg-red-500"
              }`}
              aria-hidden="true"
            />
            <span className="truncate font-medium text-gray-700">
              {TOOL_LABELS[item.tool] ?? item.tool}
            </span>
            <span className="ml-auto shrink-0">{STATUS_LABELS[item.status]}</span>
            </div>
            {artifact && item.status === "completed" && (
              <a href={artifact.download_url} target="_blank" rel="noreferrer" className="mt-1 inline-flex min-h-8 items-center rounded-lg bg-blue-50 px-3 font-medium text-blue-700 hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
                下载 {artifact.filename}
              </a>
            )}
          </div>
        })}
      </div>
    </div>
  );
}

function ApprovalCard({
  item,
  onSubmit,
}: {
  item: ApprovalItem;
  onSubmit: (approvalId: string, approved: boolean) => void;
}) {
  const waiting = item.state === "pending";
  return (
    <div className="flex justify-start">
      <section
        className="w-full max-w-[80%] rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-gray-800"
        aria-label="写入操作确认"
      >
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">确认写入文件</h3>
          <span className="shrink-0 text-xs font-medium text-amber-800">高风险</span>
        </div>
        <p className="mt-1 break-words text-xs leading-5 text-gray-600">{item.argsSummary}</p>
        {item.error && (
          <p className="mt-2 text-xs text-red-700" role="alert">
            {item.error}
          </p>
        )}
        {waiting ? (
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => onSubmit(item.approvalId, true)}
              className="min-h-11 flex-1 rounded-md bg-blue-600 px-3 font-medium text-white hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              确认写入
            </button>
            <button
              type="button"
              onClick={() => onSubmit(item.approvalId, false)}
              className="min-h-11 flex-1 rounded-md border border-gray-300 bg-white px-3 font-medium text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 focus-visible:ring-offset-2"
            >
              拒绝
            </button>
          </div>
        ) : (
          <p className="mt-2 text-xs font-medium text-gray-700" aria-live="polite">
            {item.state === "submitting" && "正在提交决定…"}
            {item.state === "approved" && "已批准，正在执行"}
            {item.state === "rejected" && "已拒绝，未执行写入"}
            {item.state === "expired" && "审批已失效"}
          </p>
        )}
      </section>
    </div>
  );
}

function MessageBubble({
  role,
  content,
  streaming,
  citations = [],
}: {
  role: string;
  content: string;
  streaming?: boolean;
  citations?: CitationSource[];
}) {
  const isUser = role === "user";
  const usedCitations = citations.filter((source) =>
    content.toLowerCase().includes(`[${source.citation_id.toLowerCase()}]`),
  );
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
          isUser ? "bg-blue-600 text-white" : "border bg-white"
        }`}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm">{content}</div>
        ) : (
          <div className="text-sm">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
            {streaming && (
              <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-gray-400 align-middle" />
            )}
            {usedCitations.length > 0 && (
              <div className="mt-3 space-y-2 border-t border-gray-200 pt-3" aria-label="回答引用">
                {usedCitations.map((source) => (
                  <a
                    key={source.citation_id}
                    href={documentContentUrl(source.document_id, source.page_start)}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-md border border-gray-200 bg-gray-50 p-2.5 hover:border-blue-300 hover:bg-blue-50"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="shrink-0 font-medium text-blue-700">[{source.citation_id}]</span>
                      <span className="truncate font-medium text-gray-800">{source.filename}</span>
                      {source.page_start && <span className="ml-auto shrink-0 text-xs text-gray-500">第 {source.page_start} 页</span>}
                    </div>
                    <div className="mt-1 truncate text-xs text-gray-500">{source.section || "正文"}</div>
                    <p className="mt-1 line-clamp-3 text-xs leading-5 text-gray-600">{source.excerpt}</p>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatView({
  conversationId,
  onAutoCreate,
  onFinished,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [streamingSources, setStreamingSources] = useState<CitationSource[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(Boolean(conversationId));
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState("");
  const [toolActivities, setToolActivities] = useState<ToolActivity[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [executionMode, setExecutionMode] = useState<"direct" | "planned">("direct");
  const [plan, setPlan] = useState<Plan | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    fetchMessages(conversationId)
      .then((rows) => {
        if (!cancelled) {
          setMessages(rows);
          setToolActivities([]);
          setApprovals([]);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    fetchConversationPlans(conversationId)
      .then((rows) => { if (!cancelled) setPlan(rows[0] ?? null); })
      .catch(() => { if (!cancelled) setPlan(null); });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming, toolActivities, approvals]);

  const updateToolActivity = useCallback(
    (key: string, tool: string, status: ToolStatus, result = "") => {
      setToolActivities((items) => {
        const existing = items.findIndex((item) => item.key === key);
        const next = { key, tool, status, result };
        if (existing < 0) return [...items, next];
        return items.map((item, index) => (index === existing ? next : item));
      });
    },
    [],
  );

  const handleApproval = useCallback(async (approvalId: string, approved: boolean) => {
    setApprovals((items) =>
      items.map((item) =>
        item.approvalId === approvalId ? { ...item, state: "submitting", error: "" } : item,
      ),
    );
    try {
      await submitApproval(approvalId, approved);
    } catch (approvalError) {
      const message = String(approvalError);
      setApprovals((items) =>
        items.map((item) =>
          item.approvalId === approvalId
            ? {
                ...item,
                state: message.includes("404") ? "expired" : "pending",
                error: message.includes("404") ? "" : message,
              }
            : item,
        ),
      );
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      let convId = conversationId;
      if (!convId) {
        try {
          convId = await onAutoCreate();
        } catch (e) {
          setError(String(e));
          return;
        }
      }
      setError("");
      setStreaming("");
      setStreamingSources([]);
      setToolActivities([]);
      setApprovals([]);
      setPlan(null);
      setMessages((ms) => [
        ...ms,
        { id: `local-${Date.now()}`, role: "user", content: text, citations: [], created_at: "" },
      ]);
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);
      try {
        await streamChat(
          convId,
          text,
          (ev) => {
            if (ev.event === "message.delta") {
              setStreaming((s) => s + String(ev.data.content ?? ""));
            } else if (ev.event === "rag.retrieved") {
              setStreamingSources((ev.data.sources as CitationSource[]) ?? []);
            } else if (ev.event === "tool.started") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              updateToolActivity(key, String(ev.data.tool ?? "tool"), "running");
            } else if (ev.event === "tool.completed") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              updateToolActivity(
                key,
                String(ev.data.tool ?? "tool"),
                String(ev.data.status ?? "failed") as ToolStatus,
                String(ev.data.result_summary ?? ""),
              );
            } else if (ev.event === "approval.required") {
              setApprovals((items) => [
                ...items,
                {
                  approvalId: String(ev.data.approval_id),
                  tool: String(ev.data.tool ?? "write_file"),
                  argsSummary: String(ev.data.args_summary ?? ""),
                  state: "pending",
                  error: "",
                },
              ]);
            } else if (ev.event === "approval.completed") {
              const approvalId = String(ev.data.approval_id);
              const approved = Boolean(ev.data.approved);
              setApprovals((items) =>
                items.map((item) =>
                  item.approvalId === approvalId
                    ? { ...item, state: approved ? "approved" : "rejected" }
                    : item,
                ),
              );
            } else if (ev.event === "run.failed") {
              setError(String(ev.data.error ?? "运行失败"));
            } else if (ev.event === "plan.created") {
              setPlan({
                id: String(ev.data.plan_id),
                run_id: "",
                conversation_id: convId,
                activity_id: null,
                goal: String(ev.data.goal ?? text),
                status: "running",
                current_version: Number(ev.data.version ?? 1),
                replan_count: 0,
                error: null,
                steps: normalizePlanSteps(ev.data.steps),
              });
            } else if (ev.event.startsWith("plan.step.")) {
              const stepId = String(ev.data.step_id);
              setPlan((current) => current ? {
                ...current,
                steps: current.steps.map((step) => step.id === stepId ? {
                  ...step,
                  status: String(ev.data.status ?? step.status) as PlanStep["status"],
                  output_summary: ev.data.output_summary ? String(ev.data.output_summary) : step.output_summary,
                  error: ev.data.error ? String(ev.data.error) : step.error,
                } : step),
              } : current);
            } else if (ev.event === "plan.replanned") {
              setPlan((current) => current ? {
                ...current,
                current_version: Number(ev.data.version),
                replan_count: current.replan_count + 1,
                steps: [
                  ...current.steps.map((step) => ["pending", "blocked"].includes(step.status) ? { ...step, status: "superseded" as const } : step),
                  ...normalizePlanSteps(ev.data.steps),
                ],
              } : current);
            } else if (ev.event === "plan.completed") {
              setPlan((current) => current ? { ...current, status: "completed" } : current);
            } else if (ev.event === "plan.failed") {
              setPlan((current) => current ? { ...current, status: "failed", error: String(ev.data.error ?? "计划失败") } : current);
            }
          },
          controller.signal,
          executionMode,
        );
        const msgs = await fetchMessages(convId);
        setMessages(msgs);
        onFinished();
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError(String(e));
      } finally {
        setStreaming("");
        setStreamingSources([]);
        abortRef.current = null;
        setIsStreaming(false);
      }
    },
    [conversationId, executionMode, onAutoCreate, onFinished, updateToolActivity],
  );

  const stop = () => abortRef.current?.abort();

  const retry = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    send(text);
  };

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && !loading && (
          <div className="mt-16 text-center text-sm text-gray-400">
            {conversationId ? "开始对话吧" : "点击「+ 新对话」或直接输入消息开始"}
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} citations={m.citations} />
        ))}
        <PlanProgress plan={plan} />
        <ToolActivityList items={toolActivities} />
        {approvals.map((item) => (
          <ApprovalCard key={item.approvalId} item={item} onSubmit={handleApproval} />
        ))}
        {(streaming !== "" || (loading && conversationId)) && (
          <MessageBubble
            role="assistant"
            content={streaming || "…"}
            citations={streamingSources}
            streaming={streaming !== ""}
          />
        )}
        {error && (
          <div className="text-sm text-red-600" role="alert">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-gray-200 bg-white p-3">
        {isStreaming && (
          <div className="mb-2 flex items-center justify-between px-1 text-xs text-gray-500">
            <span>正在生成…</span>
            <button
              onClick={stop}
              className="min-h-11 rounded border px-3 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 focus-visible:ring-offset-2"
            >
              停止
            </button>
          </div>
        )}
        <div className="mb-2 flex items-center gap-1" aria-label="执行模式">
          {(["direct", "planned"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={executionMode === mode}
              disabled={isStreaming}
              onClick={() => setExecutionMode(mode)}
              className={`rounded-full px-3 py-1 text-xs ${executionMode === mode ? "bg-blue-100 font-medium text-blue-700" : "text-gray-500 hover:bg-gray-100"}`}
            >
              {mode === "direct" ? "直接回答" : "规划执行"}
            </button>
          ))}
        </div>
        <form onSubmit={submit} className="flex min-w-0 gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(e);
              }
            }}
            rows={1}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            className="min-h-11 min-w-0 max-h-40 flex-1 resize-none rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="min-h-11 shrink-0 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-40"
          >
            发送
          </button>
        </form>
        {!isStreaming && messages.some((m) => m.role === "assistant") && (
          <div className="mt-1 px-1 text-right">
            <button
              onClick={retry}
              className="text-xs text-gray-400 hover:text-blue-600"
            >
              重新生成最后回复
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

function normalizePlanSteps(value: unknown): PlanStep[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const step = item as Record<string, unknown>;
    return {
      id: String(step.step_id ?? step.id),
      version: Number(step.version ?? 1),
      position: Number(step.position ?? 0),
      title: String(step.title ?? "计划步骤"),
      instruction: String(step.instruction ?? ""),
      tool_hints: Array.isArray(step.tool_hints) ? step.tool_hints.map(String) : [],
      status: String(step.status ?? "pending") as PlanStep["status"],
      output_summary: step.output_summary ? String(step.output_summary) : null,
      error: step.error ? String(step.error) : null,
    };
  });
}
