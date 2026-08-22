"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  documentContentUrl,
  fetchAppSettings,
  fetchConversationPlans,
  fetchMessages,
  submitApproval,
  streamChat,
  uploadFile,
  type AppSettings,
  type ChatMessage,
  type CitationSource,
  type Plan,
  type PlanStep,
  type Project,
  type KnowledgeDocument,
} from "@/lib/api";
import PlanProgress from "@/components/PlanProgress";

interface ChatViewProps {
  conversationId: string | null;
  /** 无会话时点击发送自动创建，返回新会话 id */
  onAutoCreate: () => Promise<string>;
  /** 自动创建完成后立即激活侧栏，但保持当前流式组件不被卸载。 */
  onStarted: (conversationId: string) => void;
  /** 一次 Run 结束后刷新会话列表（标题可能变化） */
  onFinished: (conversationId: string) => void;
  onOpenSettings?: (view: "workspace" | "model") => void;
  projects: Project[];
  activeProjectId: string | null;
  onSelectProject: (id: string | null) => void;
  onCreateProject: () => void;
}

type ToolStatus = "running" | "completed" | "rejected" | "failed" | "timeout";

interface ToolActivity {
  key: string;
  tool: string;
  status: ToolStatus;
  result: string;
}

type TraceStatus = "running" | "completed" | "failed";

interface RunTraceItem {
  key: string;
  label: string;
  detail: string;
  status: TraceStatus;
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

function ChatComposer({
  input,
  setInput,
  submit,
  isStreaming,
  executionMode,
  setExecutionMode,
  settings,
  selectedModelId,
  setSelectedModelId,
  hero = false,
  uploadBusy,
  onUpload,
  onOpenSettings,
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
  attachments,
  onRemoveAttachment,
}: {
  input: string;
  setInput: (value: string) => void;
  submit: (event: React.FormEvent) => void;
  isStreaming: boolean;
  executionMode: "direct" | "planned";
  setExecutionMode: (mode: "direct" | "planned") => void;
  settings: AppSettings | null;
  selectedModelId: string;
  setSelectedModelId: (id: string) => void;
  hero?: boolean;
  uploadBusy: boolean;
  onUpload: (file: File) => void;
  onOpenSettings?: (view: "workspace" | "model") => void;
  projects: Project[];
  activeProjectId: string | null;
  onSelectProject: (id: string | null) => void;
  onCreateProject: () => void;
  attachments: KnowledgeDocument[];
  onRemoveAttachment: (id: string) => void;
}) {
  const [projectOpen, setProjectOpen] = useState(false);
  const activeProject = projects.find((project) => project.id === activeProjectId);
  const modelProfiles = settings?.models.items ?? [];
  const environmentLocked = Boolean(settings?.model_control.locked);
  const modelReady = environmentLocked || Boolean(selectedModelId);
  return (
    <form onSubmit={submit} className={`w-full overflow-visible rounded-[1.5rem] border border-zinc-200 bg-white shadow-[0_18px_55px_-28px_rgba(0,0,0,0.35)] ${hero ? "max-w-4xl" : "mx-auto max-w-4xl"}`}>
      <div className="relative flex min-h-12 items-center gap-2 border-b border-zinc-100 px-3 sm:px-4">
        <button type="button" onClick={() => setProjectOpen((value) => !value)} className="inline-flex min-h-9 min-w-0 items-center gap-2 rounded-xl px-2.5 text-left text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900" aria-expanded={projectOpen}>
          <span className="text-zinc-400" aria-hidden="true">▱</span>
          <span className="max-w-40 truncate sm:max-w-64">{activeProject?.name || "未分组"}</span>
          <span className="text-xs text-zinc-400" aria-hidden="true">⌄</span>
        </button>
        {projectOpen && <div className="absolute left-3 top-11 z-30 w-64 rounded-2xl border border-zinc-200 bg-white p-2 shadow-xl" role="menu">
          {projects.map((project) => <button key={project.id} type="button" onClick={() => { onSelectProject(project.id); setProjectOpen(false); }} className={`flex min-h-10 w-full items-center gap-2 rounded-xl px-3 text-left text-sm ${project.id === activeProjectId ? "bg-zinc-100 font-medium" : "hover:bg-zinc-50"}`}><span aria-hidden="true">▱</span><span className="min-w-0 flex-1 truncate">{project.name}</span>{project.id === activeProjectId && <span aria-hidden="true">✓</span>}</button>)}
          <button type="button" onClick={() => { setProjectOpen(false); onCreateProject(); }} className="mt-1 flex min-h-10 w-full items-center gap-2 rounded-xl border-t border-zinc-100 px-3 text-left text-sm font-medium hover:bg-zinc-50">＋ 新建项目</button>
        </div>}
        <span className="ml-auto hidden text-xs text-zinc-400 sm:block">当前对话上下文</span>
      </div>
      {attachments.length > 0 && <div className="flex flex-wrap gap-2 border-b border-zinc-100 px-4 py-2.5">{attachments.map((document) => <span key={document.id} className="inline-flex max-w-full items-center gap-2 rounded-xl bg-blue-50 px-3 py-1.5 text-xs text-blue-800"><span aria-hidden="true">▣</span><span className="max-w-56 truncate">{document.original_filename}</span><button type="button" onClick={() => onRemoveAttachment(document.id)} className="grid size-5 place-items-center rounded hover:bg-blue-100" aria-label={`移除附件 ${document.original_filename}`}>×</button></span>)}</div>}
      <textarea
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onInput={(event) => {
          const target = event.currentTarget;
          target.style.height = "auto";
          target.style.height = `${Math.min(target.scrollHeight, hero ? 190 : 140)}px`;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit(event);
          }
        }}
        rows={hero ? 3 : 1}
        placeholder={`向 ${settings?.agent.name || "Personal AI"} 提问，输入 @ 添加上下文`}
        className={`block min-h-16 w-full resize-none bg-transparent px-4 py-4 text-[15px] leading-6 text-zinc-900 outline-none placeholder:text-zinc-400 sm:px-5 ${hero ? "sm:min-h-24" : "max-h-36"}`}
      />
      <div className="flex min-h-14 items-center gap-1.5 border-t border-zinc-100 px-3 py-2 sm:gap-2 sm:px-4">
        <label className={`grid size-10 shrink-0 place-items-center rounded-xl text-xl text-zinc-500 hover:bg-zinc-100 ${uploadBusy ? "cursor-wait opacity-50" : "cursor-pointer"}`} title="选择文档并用于本次提问">
          <span aria-hidden="true">＋</span><span className="sr-only">选择文档并用于本次提问</span>
          <input type="file" accept=".pdf,.docx,.txt,.md" disabled={uploadBusy} className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.target.value = ""; }} />
        </label>
        <label className="relative shrink-0">
          <span className="sr-only">执行模式</span>
          <select value={executionMode} disabled={isStreaming} onChange={(event) => setExecutionMode(event.target.value as "direct" | "planned")} className="h-10 appearance-none rounded-xl bg-transparent py-0 pl-3 pr-8 text-sm font-medium text-zinc-700 outline-none hover:bg-zinc-100 focus:ring-2 focus:ring-zinc-300">
            <option value="direct">直接回答</option><option value="planned">规划执行</option>
          </select>
          <span className="pointer-events-none absolute right-2.5 top-2.5 text-xs text-zinc-400">⌄</span>
        </label>
        {environmentLocked ? <button type="button" onClick={() => onOpenSettings?.("model")} className="ml-auto min-h-10 max-w-44 truncate rounded-xl bg-zinc-100 px-3 text-xs font-medium text-zinc-700 sm:max-w-64 sm:text-sm" title=".env 环境模型具有最高优先级">{settings?.model.model} · 环境锁定</button> : modelProfiles.length > 0 ? <label className="relative ml-auto min-w-0"><span className="sr-only">本次对话使用的模型</span><select value={selectedModelId} disabled={isStreaming} onChange={(event) => setSelectedModelId(event.target.value)} className="h-10 max-w-28 appearance-none truncate rounded-xl bg-transparent py-0 pl-2 pr-6 text-xs text-zinc-600 outline-none hover:bg-zinc-100 focus:ring-2 focus:ring-zinc-300 sm:max-w-64 sm:pl-3 sm:pr-8 sm:text-sm">{modelProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.model || "Mock"}{profile.is_default ? "（默认）" : ""}</option>)}</select><span className="pointer-events-none absolute right-2 top-2.5 text-xs text-zinc-400 sm:right-2.5">⌄</span></label> : <button type="button" onClick={() => onOpenSettings?.("model")} className="ml-auto min-h-10 rounded-xl bg-amber-50 px-2 text-xs font-medium text-amber-800 hover:bg-amber-100 sm:px-3 sm:text-sm">配置模型</button>}
        <button type="submit" disabled={!input.trim() || isStreaming || !modelReady} className="grid size-10 shrink-0 place-items-center rounded-xl bg-zinc-900 text-lg font-medium text-white transition hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:bg-zinc-300" aria-label={modelReady ? "发送消息" : "请先配置模型"} title={modelReady ? "发送消息" : "请先配置并选择模型"}>↑</button>
      </div>
    </form>
  );
}

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

function formatElapsed(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return remainingSeconds > 0 ? `${minutes} 分 ${remainingSeconds} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours} 小时 ${remainingMinutes} 分` : `${hours} 小时`;
}

function traceIcon(key: string) {
  if (key === "analysis") return "◉";
  if (key === "context") return "⌕";
  if (key === "planning") return "≣";
  if (key === "model") return "◌";
  if (key.startsWith("tool-")) return "⌘";
  return "✓";
}

function RunTracePanel({
  items,
  open,
  active,
  elapsedSeconds,
  onToggle,
}: {
  items: RunTraceItem[];
  open: boolean;
  active: boolean;
  elapsedSeconds: number;
  onToggle: () => void;
}) {
  if (items.length === 0) return null;
  const failed = items.some((item) => item.status === "failed");
  const heading = failed ? "处理失败" : active ? "正在处理" : "已处理";
  return <section className="py-1" aria-label="Agent 工作记录">
    <button type="button" onClick={onToggle} className="group flex min-h-11 w-full items-center gap-3 text-left text-sm text-zinc-500 focus-visible:rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900" aria-expanded={open}>
      <span className="shrink-0 font-medium">{heading} {formatElapsed(elapsedSeconds)}</span>
      <span className="h-px min-w-6 flex-1 bg-zinc-200" aria-hidden="true" />
      <span className={`grid size-7 shrink-0 place-items-center rounded-full text-xs text-zinc-400 transition group-hover:bg-zinc-100 group-hover:text-zinc-700 ${open ? "rotate-180" : ""}`} aria-hidden="true">⌄</span>
    </button>
    {open && <div className="ml-2 border-l border-zinc-200 pb-2 pl-7 pt-3">
      <ol className="space-y-6">{items.map((item) => <li key={item.key} className="relative text-sm">
        <span className={`absolute -left-[35px] top-0 grid size-4 place-items-center bg-[#fcfcfc] text-xs ${item.status === "failed" ? "text-red-500" : item.status === "running" ? "animate-pulse text-blue-500 motion-reduce:animate-none" : "text-zinc-400"}`} aria-hidden="true">{traceIcon(item.key)}</span>
        <p className={`flex items-center gap-2 text-sm ${item.status === "failed" ? "text-red-600" : "text-zinc-400"}`}>
          <span>{item.label}</span>
          {item.status === "running" && <span className="text-xs">进行中</span>}
        </p>
        {item.detail && <p className="mt-2 break-words text-[15px] leading-7 text-zinc-700">{item.detail}</p>}
      </li>)}</ol>
    </div>}
  </section>;
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
  onStarted,
  onFinished,
  onOpenSettings,
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
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
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [composerNotice, setComposerNotice] = useState("");
  const [attachments, setAttachments] = useState<KnowledgeDocument[]>([]);
  const [runTrace, setRunTrace] = useState<RunTraceItem[]>([]);
  const [traceOpen, setTraceOpen] = useState(true);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const runStartedAtRef = useRef<number | null>(null);
  const locallyCreatedConversationRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAppSettings().then((value) => {
      if (cancelled) return;
      setAppSettings(value);
      setSelectedModelId((current) => value.models.items.some((item) => item.id === current) ? current : value.models.default_model_id);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const resetConversationState = () => {
      if (cancelled) return;
      setMessages([]);
      setStreaming("");
      setStreamingSources([]);
      setToolActivities([]);
      setApprovals([]);
      setPlan(null);
      setRunTrace([]);
      setElapsedSeconds(0);
      runStartedAtRef.current = null;
      setError("");
    };
    if (!conversationId) {
      queueMicrotask(() => {
        resetConversationState();
        if (!cancelled) setLoading(false);
      });
      return () => { cancelled = true; };
    }
    if (locallyCreatedConversationRef.current === conversationId) {
      locallyCreatedConversationRef.current = null;
      queueMicrotask(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }
    queueMicrotask(() => {
      resetConversationState();
      if (!cancelled) setLoading(true);
    });
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
    if (!isStreaming || runStartedAtRef.current === null) return;
    const timer = window.setInterval(() => {
      if (runStartedAtRef.current !== null) {
        setElapsedSeconds(Math.floor((Date.now() - runStartedAtRef.current) / 1000));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isStreaming]);

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

  const updateTrace = useCallback((key: string, label: string, status: TraceStatus, detail = "") => {
    setRunTrace((items) => {
      const next = { key, label, status, detail };
      return items.some((item) => item.key === key)
        ? items.map((item) => item.key === key ? next : item)
        : [...items, next];
    });
  }, []);

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
    async (text: string, documentIds: string[] = []) => {
      let convId = conversationId;
      if (!convId) {
        try {
          convId = await onAutoCreate();
          locallyCreatedConversationRef.current = convId;
          onStarted(convId);
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
      setRunTrace([{ key: "analysis", label: "分析请求", detail: "识别任务类型并准备可用能力", status: "running" }]);
      setTraceOpen(true);
      runStartedAtRef.current = Date.now();
      setElapsedSeconds(0);
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
            if (ev.event === "run.started") {
              updateTrace("analysis", "分析请求", "completed", `已进入${executionMode === "planned" ? "规划执行" : "直接回答"}模式`);
            } else if (ev.event === "context.started") {
              updateTrace("context", "装配上下文", "running", "正在读取会话、记忆和相关资料");
            } else if (ev.event === "context.completed") {
              const memories = Number(ev.data.memory_count ?? 0);
              const sources = Number(ev.data.source_count ?? 0);
              const selected = Number(ev.data.selected_document_count ?? 0);
              updateTrace("context", "装配上下文", "completed", selected > 0 ? `限定 ${selected} 个附件，选取 ${sources} 个资料片段` : `读取 ${memories} 条相关记忆，选取 ${sources} 个资料片段`);
            } else if (ev.event === "planning.started") {
              updateTrace("planning", "制定执行计划", "running", "正在拆分目标和安排步骤");
            } else if (ev.event === "model.started") {
              const phase = String(ev.data.phase ?? "response");
              updateTrace("model", phase === "synthesis" ? "汇总执行结果" : "生成回答", "running", phase === "synthesis" ? "正在整合各步骤的可验证结果" : "模型正在根据当前上下文组织回复");
            } else if (ev.event === "message.delta") {
              setStreaming((s) => s + String(ev.data.content ?? ""));
            } else if (ev.event === "rag.retrieved") {
              const sources = (ev.data.sources as CitationSource[]) ?? [];
              setStreamingSources(sources);
              updateTrace("context", "装配上下文", "completed", `最终使用并引用 ${sources.length} 个资料片段`);
            } else if (ev.event === "tool.started") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateToolActivity(key, tool, "running");
              updateTrace(`tool-${key}`, TOOL_LABELS[tool] ?? tool, "running", "工具正在执行");
            } else if (ev.event === "tool.completed") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              const status = String(ev.data.status ?? "failed") as ToolStatus;
              updateToolActivity(
                key,
                tool,
                status,
                String(ev.data.result_summary ?? ""),
              );
              updateTrace(`tool-${key}`, TOOL_LABELS[tool] ?? tool, status === "completed" ? "completed" : "failed", String(ev.data.result_summary ?? STATUS_LABELS[status]));
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
              setRunTrace((items) => items.map((item) => item.status === "running" ? { ...item, status: "failed" } : item));
              updateTrace("finished", "结束运行", "failed", String(ev.data.error ?? "运行失败"));
            } else if (ev.event === "run.completed") {
              const usage = (ev.data.token_usage ?? {}) as Record<string, unknown>;
              updateTrace("finished", "完成运行", "completed", `输入 ${Number(usage.prompt_tokens ?? 0)} tokens，输出 ${Number(usage.completion_tokens ?? 0)} tokens`);
            } else if (ev.event === "message.completed") {
              updateTrace("model", "生成回答", "completed", "回答已生成并保存到当前对话");
            } else if (ev.event === "plan.created") {
              updateTrace("planning", "制定执行计划", "completed", `已生成 ${Array.isArray(ev.data.steps) ? ev.data.steps.length : 0} 个步骤`);
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
          documentIds,
          selectedModelId,
        );
        const msgs = await fetchMessages(convId);
        setMessages(msgs);
        onFinished(convId);
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError(String(e));
          setRunTrace((items) => items.map((item) => item.status === "running" ? { ...item, status: "failed" } : item));
        }
      } finally {
        if (runStartedAtRef.current !== null) {
          setElapsedSeconds(Math.floor((Date.now() - runStartedAtRef.current) / 1000));
        }
        setStreaming("");
        setStreamingSources([]);
        abortRef.current = null;
        setIsStreaming(false);
      }
    },
    [conversationId, executionMode, onAutoCreate, onFinished, onStarted, selectedModelId, updateToolActivity, updateTrace],
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
    const documentIds = attachments.map((document) => document.id);
    setAttachments([]);
    send(text, documentIds);
  };

  const handleUpload = async (file: File) => {
    setUploadBusy(true);
    setComposerNotice("");
    setError("");
    try {
      const document = await uploadFile(file);
      setAttachments((items) => items.some((item) => item.id === document.id) ? items : [...items, document]);
      setComposerNotice(`${document.original_filename} 已就绪，发送时会限定检索所选附件`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "资料上传失败");
    } finally {
      setUploadBusy(false);
    }
  };

  const empty = messages.length === 0 && !streaming && toolActivities.length === 0 && approvals.length === 0 && !plan;
  const composerProps = { projects, activeProjectId, onSelectProject, onCreateProject, attachments, onRemoveAttachment: (id: string) => setAttachments((items) => items.filter((item) => item.id !== id)) };
  const completedRunMessage = runTrace.length > 0 && !isStreaming && messages.at(-1)?.role === "assistant" ? messages.at(-1)! : null;
  const visibleMessages = completedRunMessage ? messages.slice(0, -1) : messages;

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#fcfcfc]">
      {empty && !loading ? (
        <div className="flex min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8">
          <section className="m-auto w-full max-w-5xl py-6 sm:py-12" aria-label="新任务输入区">
            <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={isStreaming} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={setSelectedModelId} hero uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
            {(composerNotice || error) && <p className={`mt-3 text-center text-sm ${error ? "text-red-600" : "text-emerald-700"}`} role={error ? "alert" : "status"}>{error || composerNotice}</p>}
          </section>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto w-full max-w-4xl space-y-5">
            {visibleMessages.map((message) => <MessageBubble key={message.id} role={message.role} content={message.content} citations={message.citations} />)}
            <RunTracePanel items={runTrace} open={traceOpen} active={isStreaming} elapsedSeconds={elapsedSeconds} onToggle={() => setTraceOpen((value) => !value)} />
            <PlanProgress plan={plan} />
            <ToolActivityList items={toolActivities} />
            {approvals.map((item) => <ApprovalCard key={item.approvalId} item={item} onSubmit={handleApproval} />)}
            {completedRunMessage && <MessageBubble key={completedRunMessage.id} role={completedRunMessage.role} content={completedRunMessage.content} citations={completedRunMessage.citations} />}
            {(streaming !== "" || (loading && conversationId)) && <MessageBubble role="assistant" content={streaming || "…"} citations={streamingSources} streaming={streaming !== ""} />}
            {error && <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
            <div ref={bottomRef} />
          </div>
        </div>
      )}

      {!empty && <div className="border-t border-zinc-200 bg-white/95 px-3 py-3 backdrop-blur sm:px-6">
        {isStreaming && (
          <div className="mx-auto mb-2 flex max-w-4xl items-center justify-between px-1 text-xs text-gray-500">
            <span>正在生成…</span>
            <button
              onClick={stop}
              className="min-h-11 rounded border px-3 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 focus-visible:ring-offset-2"
            >
              停止
            </button>
          </div>
        )}
        <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={isStreaming} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={setSelectedModelId} uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
        {composerNotice && <p className="mx-auto mt-2 max-w-4xl px-1 text-xs text-emerald-700">{composerNotice}</p>}
        {!isStreaming && messages.some((m) => m.role === "assistant") && (
          <div className="mx-auto mt-1 max-w-4xl px-1 text-right">
            <button
              onClick={retry}
              className="text-xs text-gray-400 hover:text-blue-600"
            >
              重新生成最后回复
            </button>
          </div>
        )}
      </div>}
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
