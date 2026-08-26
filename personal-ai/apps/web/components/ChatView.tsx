"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import Avatar, { DEFAULT_USER_AVATAR, agentAvatarUrl } from "@/components/Avatar";
import {
  chatImageContentUrl,
  cancelChatRun,
  deleteStagedChatImage,
  documentContentUrl,
  fetchAppSettings,
  fetchConversationRunHistory,
  fetchConversationRunStats,
  fetchCurrentConversationRun,
  fetchMessages,
  submitApproval,
  streamChat,
  uploadFile,
  uploadChatImage,
  type AppSettings,
  type AgentSettings,
  type AgentRunHistory,
  type AgentRunState,
  type ChatMessage,
  type ChatImage,
  type CitationSource,
  type Project,
  type KnowledgeDocument,
  projectFolderName,
} from "@/lib/api";

interface ChatViewProps {
  conversationId: string | null;
  /** 无会话时点击发送自动创建，返回新会话 id */
  onAutoCreate: () => Promise<string>;
  /** 自动创建完成后立即激活侧栏，但保持当前流式组件不被卸载。 */
  onStarted: (conversationId: string) => void;
  /** 一次 Run 结束后刷新会话列表（标题可能变化） */
  onFinished: (conversationId: string) => void;
  /** 同步每个会话的侧栏运行状态；完成状态用于提示后台任务已经结束。 */
  onRunStatusChange: (conversationId: string, status: "running" | "completed" | "idle") => void;
  onOpenSettings?: (view: "model") => void;
  projects: Project[];
  activeProjectId: string | null;
  onSelectProject: (id: string | null) => void;
  onOpenFolder: () => void;
}

type ToolStatus = "running" | "completed" | "rejected" | "failed" | "timeout";

interface ToolActivity {
  key: string;
  tool: string;
  status: ToolStatus;
  result: string;
}

type TraceStatus = "running" | "completed" | "failed" | "cancelled";

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

interface ContextUsage {
  usedTokens: number;
  inputBudgetTokens: number;
  contextWindowTokens: number;
  maxOutputTokens: number;
  conversationTokens: number;
  breakdown: Record<string, number>;
}

interface LiveRunSession {
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
  traceOpen: boolean;
  startedAt: number;
  elapsedSeconds: number;
  error: string;
  running: boolean;
}

type LiveRunListener = (session: LiveRunSession | null) => void;

// Run 属于会话而不是 ChatView 组件。切换会话或打开设置页只分离视图，
// 不能销毁流、停止后端任务，也不能让旧 Run 的事件污染新会话。
const LIVE_RUN_SESSIONS = new Map<string, LiveRunSession>();
const LIVE_RUN_LISTENERS = new Map<string, Set<LiveRunListener>>();

function getLiveRunSession(conversationId: string) {
  return LIVE_RUN_SESSIONS.get(conversationId) ?? null;
}

function publishLiveRunSession(conversationId: string, session: LiveRunSession | null) {
  if (session) LIVE_RUN_SESSIONS.set(conversationId, session);
  else LIVE_RUN_SESSIONS.delete(conversationId);
  LIVE_RUN_LISTENERS.get(conversationId)?.forEach((listener) => listener(session));
}

function updateLiveRunSession(
  conversationId: string,
  update: (session: LiveRunSession) => LiveRunSession,
) {
  const current = LIVE_RUN_SESSIONS.get(conversationId);
  if (!current) return null;
  const next = update(current);
  publishLiveRunSession(conversationId, next);
  return next;
}

function subscribeLiveRunSession(conversationId: string, listener: LiveRunListener) {
  const listeners = LIVE_RUN_LISTENERS.get(conversationId) ?? new Set<LiveRunListener>();
  listeners.add(listener);
  LIVE_RUN_LISTENERS.set(conversationId, listeners);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) LIVE_RUN_LISTENERS.delete(conversationId);
  };
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
  "mcp_playwright_browser_navigate": "打开网页",
  "mcp_playwright_browser_snapshot": "读取页面结构",
  "mcp_playwright_browser_find": "查找页面内容",
  "mcp_playwright_browser_click": "点击页面元素",
  "mcp_playwright_browser_type": "输入文字",
  "mcp_playwright_browser_fill_form": "填写表单",
  "mcp_playwright_browser_select_option": "选择页面选项",
  "mcp_playwright_browser_press_key": "发送键盘按键",
  "mcp_playwright_browser_wait_for": "等待页面状态",
  "mcp_playwright_browser_tabs": "管理浏览器标签页",
  "mcp_playwright_browser_close": "关闭浏览器",
  "mcp_desktop-media_qqmusic_launch": "打开 QQ 音乐",
  "mcp_desktop-media_qqmusic_search_play": "搜索并播放歌曲",
  "mcp_desktop-media_media_play_pause": "播放或暂停音乐",
  "mcp_desktop-media_media_next": "播放下一首",
  "mcp_desktop-media_media_previous": "播放上一首",
  "mcp_desktop-media_media_get_current": "读取当前歌曲",
};

const STATUS_LABELS: Record<ToolStatus, string> = {
  running: "执行中",
  completed: "已完成",
  rejected: "已拒绝",
  failed: "失败",
  timeout: "已超时",
};

const RISK_LABELS: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

function compactText(value: string, maxLength = 180) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

function toolTraceDetail(data: Record<string, unknown>, stage: "proposed" | "running") {
  const args = String(data.args_summary ?? "未提供参数摘要");
  const effect = String(data.effect ?? "执行所选工具以推进当前任务");
  const risk = RISK_LABELS[String(data.risk_level ?? "")] ?? "未知风险";
  const approval = Boolean(data.requires_approval) || data.risk_level === "high";
  const state = stage === "running" ? "正在执行" : approval ? "确认后执行" : "即将执行";
  return `${state} · ${risk}\n目标与参数：${args}\n预期影响：${effect}`;
}

const CHAT_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function modelSupportsImages(model: string) {
  const name = model.trim().toLowerCase().replaceAll("_", "-");
  return ["qwen3.8-max", "qwen3-vl", "qwen2.5-vl", "qwen2-vl", "qwen-vl-max", "qwen-vl-plus"]
    .some((marker) => name.includes(marker));
}

function estimateTextTokens(text: string) {
  const characters = Array.from(text);
  const cjk = characters.filter((character) => character.codePointAt(0)! > 0x2e80).length;
  return cjk + Math.floor((characters.length - cjk) / 4) + 1;
}

function estimateMessageTokens(text: string, imageCount = 0) {
  return estimateTextTokens(text) + imageCount * 1_024;
}

function formatTokenCount(value: number) {
  if (value >= 10_000) {
    const digits = value >= 100_000 ? 1 : 2;
    return `${(value / 10_000).toFixed(digits).replace(/\.?0+$/, "")}万`;
  }
  return Math.max(0, Math.round(value)).toLocaleString("zh-CN");
}

function ContextMeter({
  usage,
  contextWindowTokens,
  maxOutputTokens,
  conversationTokens,
  cacheHitRate,
  loading,
}: {
  usage: ContextUsage | null;
  contextWindowTokens: number;
  maxOutputTokens: number;
  conversationTokens: number;
  cacheHitRate: number | null;
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const modelWindow = Math.max(1, usage?.contextWindowTokens || contextWindowTokens || 12_096);
  const outputReserve = Math.max(0, usage?.maxOutputTokens ?? maxOutputTokens ?? 4_096);
  const limit = Math.max(1, usage?.inputBudgetTokens || modelWindow - outputReserve);
  const totalConversationTokens = usage?.conversationTokens ?? conversationTokens;
  const usedTokens = usage?.usedTokens ?? Math.min(totalConversationTokens, limit);
  const remainingTokens = Math.max(0, limit - usedTokens);
  const percent = Math.min(100, Math.max(0, (usedTokens / limit) * 100));
  const remainingPercent = Math.min(100, Math.max(0, (remainingTokens / modelWindow) * 100));

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative ml-auto shrink-0">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="grid size-10 place-items-center rounded-xl text-zinc-500 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
        aria-label={`上下文容量，当前剩余 ${formatTokenCount(remainingTokens)}，模型窗口 ${formatTokenCount(modelWindow)}`}
        aria-expanded={open}
        aria-controls="context-capacity-popover"
        title="查看上下文容量"
      >
        <span className={`relative grid size-6 place-items-center rounded-full ${loading ? "animate-pulse motion-reduce:animate-none" : ""}`} aria-hidden="true">
          <svg viewBox="0 0 24 24" className="absolute inset-0 size-6 -rotate-90">
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" className="text-zinc-200" />
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" pathLength="100" strokeDasharray="100" strokeDashoffset={100 - percent} className="text-blue-500 transition-all motion-reduce:transition-none" />
          </svg>
          <span className="size-1.5 rounded-full bg-zinc-500" />
        </span>
      </button>
      {open && (
        <section
          id="context-capacity-popover"
          role="dialog"
          aria-modal="false"
          aria-labelledby="context-capacity-title"
          className="fixed inset-x-4 bottom-24 z-50 rounded-xl border border-zinc-200 bg-white p-4 shadow-xl sm:absolute sm:inset-x-auto sm:bottom-12 sm:right-0 sm:w-80"
        >
          <div className="flex items-center justify-between gap-4">
            <h2
              id="context-capacity-title"
              className="text-[15px] font-medium tracking-wide text-zinc-700"
              style={{ fontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif' }}
            >
              上下文容量
            </h2>
            <span className="whitespace-nowrap text-xs tabular-nums text-zinc-500">
              {formatTokenCount(remainingTokens)} / {formatTokenCount(modelWindow)}（{remainingPercent.toFixed(1)}%）
            </span>
          </div>
          <div
            className="mt-3 h-2.5 overflow-hidden rounded-full bg-zinc-100"
            role="progressbar"
            aria-label="上下文剩余容量"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(remainingPercent)}
            title={`剩余 ${formatTokenCount(remainingTokens)} / 模型窗口 ${formatTokenCount(modelWindow)} tokens`}
          >
            <div className="h-full rounded-full bg-zinc-950 transition-all motion-reduce:transition-none" style={{ width: `${remainingPercent}%` }} />
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-zinc-100 pt-3 text-sm">
            <span className="text-zinc-500">平均缓存命中率</span>
            <span className="font-medium tabular-nums text-zinc-800">
              {cacheHitRate === null ? "—" : `${cacheHitRate.toFixed(1)}%`}
            </span>
          </div>
        </section>
      )}
    </div>
  );
}

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
  contextUsage,
  conversationTokens,
  cacheHitRate,
  contextLoading,
  hero = false,
  uploadBusy,
  onStop,
  isStopping,
  onUpload,
  onOpenSettings,
  projects,
  activeProjectId,
  onSelectProject,
  onOpenFolder,
  attachments,
  onRemoveAttachment,
  images,
  onImageFiles,
  onRemoveImage,
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
  contextUsage: ContextUsage | null;
  conversationTokens: number;
  cacheHitRate: number | null;
  contextLoading: boolean;
  hero?: boolean;
  uploadBusy: boolean;
  onStop: () => void;
  isStopping: boolean;
  onUpload: (file: File) => void;
  onOpenSettings?: (view: "model") => void;
  projects: Project[];
  activeProjectId: string | null;
  onSelectProject: (id: string | null) => void;
  onOpenFolder: () => void;
  attachments: KnowledgeDocument[];
  onRemoveAttachment: (id: string) => void;
  images: ChatImage[];
  onImageFiles: (files: File[]) => void;
  onRemoveImage: (id: string) => void;
}) {
  const [projectOpen, setProjectOpen] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement>(null);
  const activeProject = projects.find((project) => project.id === activeProjectId);

  useEffect(() => {
    if (!projectOpen) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!projectMenuRef.current?.contains(event.target as Node)) setProjectOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setProjectOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [projectOpen]);
  const modelProfiles = settings?.models.items ?? [];
  const environmentLocked = Boolean(settings?.model_control.locked);
  const selectedProfile = modelProfiles.find((profile) => profile.id === selectedModelId);
  const modelReady = environmentLocked || Boolean(selectedModelId);
  const selectedModel = environmentLocked
    ? settings?.model.model || ""
    : selectedProfile?.model || "";
  const contextWindowTokens = environmentLocked
    ? settings?.model.context_window_tokens ?? 12_096
    : selectedProfile?.context_window_tokens ?? settings?.context.max_tokens ?? 12_096;
  const maxOutputTokens = environmentLocked
    ? settings?.model.max_output_tokens ?? 4_096
    : selectedProfile?.max_output_tokens ?? 4_096;
  const imageEnabled = modelSupportsImages(selectedModel);
  const canSubmitImages = images.length === 0 || imageEnabled;
  const imageTitle = imageEnabled
    ? "添加图片（JPG、PNG、WebP，最多 4 张，也可拖拽或粘贴）"
    : "当前模型不支持图片，请先选择 qwen3.8-max";
  return (
    <form
      onSubmit={submit}
      onDragOver={(event) => {
        if (Array.from(event.dataTransfer.items).some((item) => item.kind === "file")) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }
      }}
      onDrop={(event) => {
        const files = Array.from(event.dataTransfer.files);
        if (files.length) {
          event.preventDefault();
          onImageFiles(files);
        }
      }}
      className={`w-full overflow-visible rounded-[1.5rem] border border-zinc-200 bg-white shadow-[0_18px_55px_-28px_rgba(0,0,0,0.35)] ${hero ? "max-w-4xl" : "mx-auto max-w-4xl"}`}
    >
      <div className="relative flex min-h-12 items-center gap-2 border-b border-zinc-100 px-3 sm:px-4" ref={projectMenuRef}>
        <button type="button" disabled={isStreaming} onClick={() => setProjectOpen((value) => !value)} className="inline-flex min-h-9 min-w-0 items-center gap-2 rounded-xl px-2.5 text-left text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-not-allowed disabled:opacity-50" aria-expanded={projectOpen} aria-haspopup="menu" aria-controls="folder-menu">
          <span className="text-zinc-400" aria-hidden="true">▱</span>
          <span className="max-w-40 truncate sm:max-w-64">{activeProject ? projectFolderName(activeProject) : "不在项目中工作"}</span>
          <span className="text-xs text-zinc-400" aria-hidden="true">⌃</span>
        </button>
        {projectOpen && <div id="folder-menu" className="absolute bottom-11 left-3 z-30 max-h-[min(24rem,calc(100dvh-6rem))] w-[min(20rem,calc(100vw-3rem))] overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-2 shadow-xl" role="menu" aria-label="选择文件夹">
          <p className="px-3 pb-2 pt-1 text-xs font-medium text-zinc-400">已打开的文件夹</p>
          {projects.map((project) => <button key={project.id} type="button" role="menuitemradio" aria-checked={project.id === activeProjectId} onClick={() => { onSelectProject(project.id); setProjectOpen(false); }} className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm ${project.id === activeProjectId ? "bg-zinc-100 font-medium" : "hover:bg-zinc-50"}`}><span className="text-zinc-400" aria-hidden="true">▱</span><span className="min-w-0 flex-1 truncate">{projectFolderName(project)}</span>{project.id === activeProjectId && <span aria-hidden="true">✓</span>}</button>)}
          {projects.length === 0 && <p className="px-3 py-4 text-sm text-zinc-400">还没有打开过文件夹</p>}
          <div className="my-1 border-t border-zinc-100" />
          <button type="button" role="menuitem" onClick={() => { setProjectOpen(false); onOpenFolder(); }} className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium hover:bg-zinc-50"><span aria-hidden="true">⊞</span>打开文件夹</button>
          <button type="button" role="menuitemradio" aria-checked={activeProjectId === null} onClick={() => { onSelectProject(null); setProjectOpen(false); }} className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm ${activeProjectId === null ? "bg-zinc-100 font-medium" : "hover:bg-zinc-50"}`}><span aria-hidden="true">◯</span><span className="min-w-0 flex-1">不在项目中工作</span>{activeProjectId === null && <span aria-hidden="true">✓</span>}</button>
        </div>}
        <span className="ml-auto hidden text-xs text-zinc-400 sm:block">当前对话上下文</span>
      </div>
      {(attachments.length > 0 || images.length > 0) && <div className="flex flex-wrap gap-2 border-b border-zinc-100 px-4 py-2.5">
        {images.map((image) => <figure key={image.id} className="group relative h-20 w-20 overflow-hidden rounded-xl border border-zinc-200 bg-zinc-100">
          <img src={chatImageContentUrl(image.id)} alt={image.original_filename} className="h-full w-full object-cover" />
          <figcaption className="sr-only">{image.original_filename}</figcaption>
          <button type="button" onClick={() => onRemoveImage(image.id)} className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/65 text-sm text-white opacity-90 hover:bg-black focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-white" aria-label={`移除图片 ${image.original_filename}`}>×</button>
        </figure>)}
        {attachments.map((document) => <span key={document.id} className="inline-flex max-w-full items-center gap-2 rounded-xl bg-blue-50 px-3 py-1.5 text-xs text-blue-800"><span aria-hidden="true">▣</span><span className="max-w-56 truncate">{document.original_filename}</span><button type="button" onClick={() => onRemoveAttachment(document.id)} className="grid size-5 place-items-center rounded hover:bg-blue-100" aria-label={`移除附件 ${document.original_filename}`}>×</button></span>)}
      </div>}
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
        onPaste={(event) => {
          const files = Array.from(event.clipboardData.files).filter((file) => CHAT_IMAGE_TYPES.has(file.type));
          if (files.length) {
            event.preventDefault();
            onImageFiles(files);
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
        <label className={`grid size-10 shrink-0 place-items-center rounded-xl text-zinc-500 ${imageEnabled && !uploadBusy ? "cursor-pointer hover:bg-zinc-100" : "cursor-not-allowed opacity-40"}`} title={imageTitle}>
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 fill-none stroke-current" strokeWidth="1.8"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m5 18 4.5-4.5 3.2 3.2 2.1-2.1L19 18"/></svg>
          <span className="sr-only">{imageTitle}</span>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={uploadBusy || !imageEnabled || isStreaming} className="sr-only" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) onImageFiles(files); event.target.value = ""; }} />
        </label>
        <label className="relative shrink-0">
          <span className="sr-only">执行模式</span>
          <select value={executionMode} disabled={isStreaming} onChange={(event) => setExecutionMode(event.target.value as "direct" | "planned")} className="h-10 appearance-none rounded-xl bg-transparent py-0 pl-3 pr-8 text-sm font-medium text-zinc-700 outline-none hover:bg-zinc-100 focus:ring-2 focus:ring-zinc-300">
            <option value="direct">自主模式</option><option value="planned">规划模式</option>
          </select>
          <span className="pointer-events-none absolute right-2.5 top-2.5 text-xs text-zinc-400">⌄</span>
        </label>
        <ContextMeter usage={contextUsage} contextWindowTokens={contextWindowTokens} maxOutputTokens={maxOutputTokens} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} loading={contextLoading} />
        {environmentLocked ? <button type="button" onClick={() => onOpenSettings?.("model")} className="min-h-10 max-w-44 truncate rounded-xl bg-zinc-100 px-3 text-xs font-medium text-zinc-700 sm:max-w-64 sm:text-sm" title=".env 环境模型具有最高优先级">{settings?.model.model} · 环境锁定</button> : modelProfiles.length > 0 ? <label className="relative min-w-0"><span className="sr-only">本次对话使用的模型</span><select value={selectedModelId} disabled={isStreaming} onChange={(event) => setSelectedModelId(event.target.value)} className="h-10 max-w-28 appearance-none truncate rounded-xl bg-transparent py-0 pl-2 pr-6 text-xs text-zinc-600 outline-none hover:bg-zinc-100 focus:ring-2 focus:ring-zinc-300 sm:max-w-64 sm:pl-3 sm:pr-8 sm:text-sm">{modelProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.model || "Mock"}{profile.is_default ? "（默认）" : ""}</option>)}</select><span className="pointer-events-none absolute right-2 top-2.5 text-xs text-zinc-400 sm:right-2.5">⌄</span></label> : <button type="button" onClick={() => onOpenSettings?.("model")} className="min-h-10 rounded-xl bg-amber-50 px-2 text-xs font-medium text-amber-800 hover:bg-amber-100 sm:px-3 sm:text-sm">配置模型</button>}
        <button
          type={isStreaming ? "button" : "submit"}
          onClick={isStreaming ? onStop : undefined}
          disabled={isStreaming ? isStopping : (!input.trim() && images.length === 0) || uploadBusy || !modelReady || !canSubmitImages}
          className="grid size-10 shrink-0 place-items-center rounded-xl bg-zinc-900 text-lg font-medium text-white transition hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-not-allowed disabled:bg-zinc-300"
          aria-label={isStreaming ? isStopping ? "正在停止回答" : "停止回答" : modelReady ? "发送消息" : "请先配置模型"}
          title={isStreaming ? isStopping ? "正在停止…" : "停止回答" : !canSubmitImages ? "请切换到支持图片的模型" : modelReady ? "发送消息" : "请先配置并选择模型"}
        >
          {isStreaming ? <span className="size-3 rounded-[2px] bg-white" aria-hidden="true" /> : "↑"}
        </button>
      </div>
    </form>
  );
}

function ToolActivityList({ items }: { items: ToolActivity[] }) {
  const visibleItems = items.filter((item) => item.tool !== "memory_list");
  if (visibleItems.length === 0) return null;
  return (
    <div className="flex justify-start" aria-live="polite" aria-label="工具执行状态">
      <div className="w-full max-w-[80%] space-y-1.5 border-l-2 border-gray-200 pl-3 text-xs text-gray-600">
        {visibleItems.map((item) => {
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
  const stopped = items.some((item) => item.status === "cancelled");
  const heading = failed ? "处理失败" : stopped ? "已停止" : active ? "正在处理" : "已处理";
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
          {item.status === "cancelled" && <span className="text-xs">已停止</span>}
        </p>
        {item.detail && <p className="mt-2 whitespace-pre-line break-words text-[15px] leading-7 text-zinc-700">{item.detail}</p>}
      </li>)}</ol>
    </div>}
  </section>;
}

function historicalTraceItems(run: AgentRunHistory): RunTraceItem[] {
  const intent = run.intent ?? {};
  const context = run.context_stats ?? {};
  const memoryCount = Number(context.memory_count ?? 0);
  const memoryCandidates = Number(context.memory_candidate_count ?? memoryCount);
  const sourceCount = Number(context.source_count ?? 0);
  const knowledgeCandidates = Number(context.knowledge_candidate_count ?? sourceCount);
  const items: RunTraceItem[] = [
    {
      key: "analysis",
      label: "分析请求",
      status: "completed",
      detail: `当前理解：${compactText(run.input_message || "历史请求")}\n执行方式：${run.execution_mode === "planned" ? "规划模式" : "自主模式"}`,
    },
  ];
  if (Object.keys(intent).length > 0) {
    items.push({
      key: "intent",
      label: "识别意图",
      status: "completed",
      detail: `类型：${String(intent.intent ?? "conversation")} · 路由：${String(intent.source ?? "default")} · 置信度：${Math.round(Number(intent.confidence ?? 0) * 100)}%`,
    });
  }
  items.push({
    key: "context",
    label: "装配上下文",
    status: "completed",
    detail: Object.keys(context).length > 0
      ? `记忆候选 ${memoryCandidates}，使用 ${memoryCount}；资料候选 ${knowledgeCandidates}，使用 ${sourceCount}`
      : "上下文已装配；该历史 Run 未保存详细统计",
  });
  for (const [index, tool] of run.tools.entries()) {
    const status: TraceStatus = tool.status === "completed"
      ? "completed"
      : tool.status === "rejected"
        ? "cancelled"
        : "failed";
    items.push({
      key: `tool-${tool.id || index}`,
      label: TOOL_LABELS[tool.tool] ?? tool.tool,
      status,
      detail: `${tool.args_summary || "未记录参数"}${tool.result_summary ? `\n${tool.result_summary}` : ""}`,
    });
  }
  if (run.status === "completed") {
    items.push({
      key: "model",
      label: run.execution_mode === "planned" ? "生成规划文档" : "生成回答",
      status: "completed",
      detail: "内容已生成并保存到当前对话",
    });
  }
  const finalStatus: TraceStatus = run.status === "failed"
    ? "failed"
    : ["cancelled", "interrupted"].includes(run.status)
      ? "cancelled"
      : "completed";
  items.push({
    key: "finished",
    label: finalStatus === "failed" ? "结束运行" : finalStatus === "cancelled" ? "停止运行" : "完成运行",
    status: finalStatus,
    detail: run.error || `输入 ${run.input_tokens || 0} tokens，输出 ${run.output_tokens || 0} tokens`,
  });
  return items;
}

function runElapsedSeconds(run: AgentRunHistory) {
  if (!run.completed_at) return 0;
  return Math.max(0, Math.round((Date.parse(run.completed_at) - Date.parse(run.created_at)) / 1000));
}

function HistoricalRunTrace({ run }: { run: AgentRunHistory }) {
  const [open, setOpen] = useState(false);
  return (
    <RunTracePanel
      items={historicalTraceItems(run)}
      open={open}
      active={false}
      elapsedSeconds={runElapsedSeconds(run)}
      onToggle={() => setOpen((value) => !value)}
    />
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
  const toolLabel = TOOL_LABELS[item.tool] ?? item.tool;
  return (
    <div className="flex justify-start">
      <section
        className="w-full max-w-[80%] rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-gray-800"
        aria-label={`${toolLabel}操作确认`}
      >
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">确认执行：{toolLabel}</h3>
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
              确认执行
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
            {item.state === "rejected" && "已拒绝，未执行操作"}
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
  status = "completed",
  citations = [],
  images = [],
  agent,
}: {
  role: string;
  content: string;
  streaming?: boolean;
  status?: ChatMessage["status"];
  citations?: CitationSource[];
  images?: ChatImage[];
  agent?: AgentSettings;
}) {
  const isUser = role === "user";
  const usedCitations = citations.filter((source) =>
    content.toLowerCase().includes(`[${source.citation_id.toLowerCase()}]`),
  );
  return (
    <div className={`flex items-start gap-3 ${isUser ? "flex-row-reverse justify-start" : "justify-start"}`}>
      <Avatar
        src={isUser ? DEFAULT_USER_AVATAR : agentAvatarUrl(agent)}
        alt={isUser ? "用户头像" : `${agent?.name || "AI"}的头像`}
        className="mt-0.5 size-10 rounded-xl ring-1 ring-zinc-200"
      />
      <div
        className={`max-w-[calc(100%-3.25rem)] rounded-2xl px-4 py-2.5 sm:max-w-[80%] ${
          isUser ? "bg-blue-600 text-white" : "border border-zinc-300 bg-white"
        }`}
      >
        {images.length > 0 && <div className={`mb-2 grid gap-2 ${images.length > 1 ? "grid-cols-2" : "grid-cols-1"}`} aria-label="消息图片">
          {images.map((image) => <a key={image.id} href={chatImageContentUrl(image.id)} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-xl bg-black/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white">
            <img src={chatImageContentUrl(image.id)} alt={image.original_filename} className="max-h-80 w-full object-cover" />
          </a>)}
        </div>}
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
            {status === "interrupted" && (
              <div className="mt-3 flex items-center gap-2 border-t border-zinc-200 pt-2 text-xs text-zinc-500" role="status">
                <span className="grid size-4 place-items-center rounded-full bg-zinc-200 text-[9px] text-zinc-700" aria-hidden="true">■</span>
                <span>回答已停止，内容可能不完整</span>
              </div>
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
  onRunStatusChange,
  onOpenSettings,
  projects,
  activeProjectId,
  onSelectProject,
  onOpenFolder,
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
  const [isStopping, setIsStopping] = useState(false);
  const [executionMode, setExecutionMode] = useState<"direct" | "planned">("direct");
  const [currentRun, setCurrentRun] = useState<AgentRunState | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [composerNotice, setComposerNotice] = useState("");
  const [attachments, setAttachments] = useState<KnowledgeDocument[]>([]);
  const [images, setImages] = useState<ChatImage[]>([]);
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [conversationTokens, setConversationTokens] = useState(0);
  const [cacheHitRate, setCacheHitRate] = useState<number | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [runTrace, setRunTrace] = useState<RunTraceItem[]>([]);
  const [runHistory, setRunHistory] = useState<Record<string, AgentRunHistory>>({});
  const [traceOpen, setTraceOpen] = useState(true);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const locallyCreatedConversationRef = useRef<string | null>(null);
  const messageScrollRef = useRef<HTMLDivElement>(null);
  const activeConversationRef = useRef(conversationId);
  const messagesConversationRef = useRef(conversationId);
  const initialRunHistoryConversationRef = useRef<string | null>(null);
  const lastPositionedConversationRef = useRef<string | null>(null);

  const applyLiveSession = useCallback((session: LiveRunSession | null) => {
    setStreaming(session?.streaming ?? "");
    setStreamingSources(session?.streamingSources ?? []);
    setToolActivities(session?.toolActivities ?? []);
    setApprovals(session?.approvals ?? []);
    setIsStopping(session?.isStopping ?? false);
    setCurrentRun(session?.currentRun ?? null);
    setContextUsage(session?.contextUsage ?? null);
    setContextLoading(session?.contextLoading ?? false);
    setRunTrace(session?.runTrace ?? []);
    setTraceOpen(session?.traceOpen ?? false);
    setElapsedSeconds(session?.elapsedSeconds ?? 0);
    setIsStreaming(session?.running ?? false);
    setError(session?.error ?? "");
  }, []);

  useLayoutEffect(() => {
    activeConversationRef.current = conversationId;
    applyLiveSession(conversationId ? getLiveRunSession(conversationId) : null);
  }, [applyLiveSession, conversationId]);

  useEffect(() => {
    if (!conversationId) return;
    return subscribeLiveRunSession(conversationId, applyLiveSession);
  }, [applyLiveSession, conversationId]);

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
      messagesConversationRef.current = null;
      initialRunHistoryConversationRef.current = null;
      setMessages([]);
      setStreaming("");
      setStreamingSources([]);
      setToolActivities([]);
      setApprovals([]);
      setIsStopping(false);
      setCurrentRun(null);
      setContextUsage(null);
      setConversationTokens(0);
      setCacheHitRate(null);
      setRunHistory({});
      applyLiveSession(conversationId ? getLiveRunSession(conversationId) : null);
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
          messagesConversationRef.current = conversationId;
          setMessages(rows);
          setConversationTokens(rows.reduce((total, row) => total + Number(row.token_estimate || 0), 0));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    fetchCurrentConversationRun(conversationId)
      .then((run) => {
        if (cancelled) return;
        const existing = getLiveRunSession(conversationId);
        if (existing) {
          if (run) updateLiveRunSession(conversationId, (session) => ({ ...session, currentRun: run }));
          return;
        }
        if (run?.status === "running") {
          onRunStatusChange(conversationId, "running");
          publishLiveRunSession(conversationId, {
            runId: run.id,
            controller: null,
            currentRun: run,
            streaming: "",
            streamingSources: [],
            toolActivities: [],
            approvals: [],
            isStopping: false,
            contextUsage: null,
            contextLoading: true,
            runTrace: [{ key: "detached", label: "任务仍在运行", detail: "已重新连接到这个会话，正在等待后台任务完成", status: "running" }],
            traceOpen: true,
            startedAt: Date.parse(run.created_at) || Date.now(),
            elapsedSeconds: 0,
            error: "",
            running: true,
          });
        } else {
          setCurrentRun(run);
        }
      })
      .catch(() => { if (!cancelled) setCurrentRun(null); });
    fetchConversationRunStats(conversationId)
      .then((stats) => {
        if (!cancelled) setCacheHitRate(stats.average_cache_hit_rate);
      })
      .catch(() => { if (!cancelled) setCacheHitRate(null); });
    fetchConversationRunHistory(conversationId)
      .then((rows) => {
        if (!cancelled) {
          initialRunHistoryConversationRef.current = conversationId;
          setRunHistory(Object.fromEntries(rows.map((run) => [run.id, run])));
        }
      })
      .catch(() => { if (!cancelled) setRunHistory({}); });
    return () => {
      cancelled = true;
    };
  }, [applyLiveSession, conversationId, onRunStatusChange]);

  useEffect(() => {
    if (!conversationId || !isStreaming) return;
    const updateElapsed = () => {
      updateLiveRunSession(conversationId, (session) => ({
        ...session,
        elapsedSeconds: Math.floor((Date.now() - session.startedAt) / 1000),
      }));
    };
    updateElapsed();
    const timer = window.setInterval(() => {
      updateElapsed();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [conversationId, isStreaming]);

  useLayoutEffect(() => {
    const activeConversationId = activeConversationRef.current;
    const hasVisibleContent = messages.length > 0 || streaming !== "" || toolActivities.length > 0 || approvals.length > 0;
    if (!activeConversationId || messagesConversationRef.current !== activeConversationId || !hasVisibleContent) return;
    const isInitialPosition = lastPositionedConversationRef.current !== activeConversationId;
    lastPositionedConversationRef.current = activeConversationId;
    if (isInitialPosition) {
      messageScrollRef.current?.scrollTo({ top: messageScrollRef.current.scrollHeight, behavior: "auto" });
      return;
    }
    messageScrollRef.current?.scrollTo({ top: messageScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming, toolActivities, approvals]);

  useLayoutEffect(() => {
    const activeConversationId = activeConversationRef.current;
    if (!activeConversationId || initialRunHistoryConversationRef.current !== activeConversationId) return;
    initialRunHistoryConversationRef.current = null;
    messageScrollRef.current?.scrollTo({ top: messageScrollRef.current.scrollHeight, behavior: "auto" });
  }, [runHistory]);

  const updateToolActivity = useCallback(
    (ownerConversationId: string, key: string, tool: string, status: ToolStatus, result = "") => {
      updateLiveRunSession(ownerConversationId, (session) => {
        const items = session.toolActivities;
        const existing = items.findIndex((item) => item.key === key);
        const next = { key, tool, status, result };
        return {
          ...session,
          toolActivities: existing < 0
            ? [...items, next]
            : items.map((item, index) => (index === existing ? next : item)),
        };
      });
    },
    [],
  );

  const updateTrace = useCallback((ownerConversationId: string, key: string, label: string, status: TraceStatus, detail = "") => {
    updateLiveRunSession(ownerConversationId, (session) => {
      const items = session.runTrace;
      const next = { key, label, status, detail };
      return {
        ...session,
        runTrace: items.some((item) => item.key === key)
          ? items.map((item) => item.key === key ? next : item)
          : [...items, next],
      };
    });
  }, []);

  const selectModel = useCallback((id: string) => {
    setSelectedModelId(id);
    setContextUsage(null);
  }, []);

  const handleApproval = useCallback(async (approvalId: string, approved: boolean) => {
    if (!conversationId) return;
    updateLiveRunSession(conversationId, (session) => ({
      ...session,
      approvals: session.approvals.map((item) =>
        item.approvalId === approvalId ? { ...item, state: "submitting", error: "" } : item,
      ),
    }));
    try {
      await submitApproval(approvalId, approved);
    } catch (approvalError) {
      const message = String(approvalError);
      updateLiveRunSession(conversationId, (session) => ({
        ...session,
        approvals: session.approvals.map((item) =>
          item.approvalId === approvalId
            ? {
                ...item,
                state: message.includes("404") ? "expired" : "pending",
                error: message.includes("404") ? "" : message,
              }
            : item,
        ),
      }));
    }
  }, [conversationId]);

  const send = useCallback(
    async (text: string, documentIds: string[] = [], chatImages: ChatImage[] = []) => {
      let convId = conversationId;
      if (!convId) {
        try {
          convId = await onAutoCreate();
          locallyCreatedConversationRef.current = convId;
          messagesConversationRef.current = convId;
          onStarted(convId);
        } catch (e) {
          setError(String(e));
          return;
        }
      }
      const controller = new AbortController();
      const runId = crypto.randomUUID().replace(/-/g, "");
      const startedAt = Date.now();
      const pendingRun: AgentRunState = {
        id: runId,
        conversation_id: convId,
        execution_mode: executionMode,
        status: "running",
        input_message: text,
        error: null,
        has_checkpoint: false,
        created_at: new Date(startedAt).toISOString(),
      };
      const initialSession: LiveRunSession = {
        runId,
        controller,
        currentRun: pendingRun,
        streaming: "",
        streamingSources: [],
        toolActivities: [],
        approvals: [],
        isStopping: false,
        contextUsage: null,
        contextLoading: true,
        runTrace: [{ key: "analysis", label: "分析请求", detail: `当前理解：${compactText(text)}`, status: "running" }],
        traceOpen: true,
        startedAt,
        elapsedSeconds: 0,
        error: "",
        running: true,
      };
      publishLiveRunSession(convId, initialSession);
      onRunStatusChange(convId, "running");
      // 自动创建会话时父组件尚未完成重渲染，立即显示本次 Run。
      applyLiveSession(initialSession);
      setMessages((ms) => [
        ...ms,
        { id: `local-${Date.now()}`, role: "user", content: text, citations: [], images: chatImages, run_id: null, status: "completed", token_estimate: estimateMessageTokens(text, chatImages.length), created_at: "" },
      ]);
      setConversationTokens((total) => total + estimateMessageTokens(text, chatImages.length));
      try {
        await streamChat(
          convId,
          text,
          (ev) => {
            if (ev.event === "run.started") {
              const actualRunId = String(ev.data.run_id ?? runId);
              const actualExecutionMode = String(ev.data.execution_mode ?? executionMode) as "direct" | "planned";
              const planningSkipped = Boolean(ev.data.planning_skipped);
              updateLiveRunSession(convId, (session) => ({
                ...session,
                runId: actualRunId,
                currentRun: session.currentRun ? {
                  ...session.currentRun,
                  id: actualRunId,
                  execution_mode: actualExecutionMode,
                } : session.currentRun,
              }));
              updateTrace(convId, "analysis", "分析请求", "completed", `当前理解：${compactText(text)}\n执行方式：${planningSkipped ? "这是非执行问题，无需制定计划，已由自主模式回答" : actualExecutionMode === "planned" ? "规划模式：生成 Markdown 实施方案，不执行任务或调用工具" : "自主模式：自行回答或选择已启用工具；有风险的操作仍需确认"}`);
            } else if (ev.event === "intent.completed") {
              updateTrace(convId, "intent", "识别意图", "completed", `类型：${String(ev.data.intent ?? "conversation")} · 路由：${String(ev.data.source ?? "rule")} · 置信度：${Math.round(Number(ev.data.confidence ?? 0) * 100)}%`);
            } else if (ev.event === "context.started") {
              updateLiveRunSession(convId, (session) => ({ ...session, contextLoading: true }));
              updateTrace(convId, "context", "装配上下文", "running", "正在读取会话、记忆和相关资料");
            } else if (ev.event === "context.completed") {
              const memories = Number(ev.data.memory_count ?? 0);
              const sources = Number(ev.data.source_count ?? 0);
              const selected = Number(ev.data.selected_document_count ?? 0);
              const memoryCandidates = Number(ev.data.memory_candidate_count ?? memories);
              const knowledgeCandidates = Number(ev.data.knowledge_candidate_count ?? sources);
              const memoryExcluded = Object.values((ev.data.memory_exclusion_reasons ?? {}) as Record<string, unknown>).reduce<number>((sum, value) => sum + Number(value ?? 0), 0);
              const knowledgeExcluded = Object.values((ev.data.knowledge_exclusion_reasons ?? {}) as Record<string, unknown>).reduce<number>((sum, value) => sum + Number(value ?? 0), 0);
              const rawBreakdown = (ev.data.token_breakdown ?? {}) as Record<string, unknown>;
              updateLiveRunSession(convId, (session) => ({
                ...session,
                contextUsage: {
                  usedTokens: Number(ev.data.token_estimate ?? 0),
                  inputBudgetTokens: Number(ev.data.input_budget_tokens ?? ev.data.max_tokens ?? 8_000),
                  contextWindowTokens: Number(ev.data.context_window_tokens ?? 12_096),
                  maxOutputTokens: Number(ev.data.max_output_tokens ?? 4_096),
                  conversationTokens: Number(ev.data.conversation_token_estimate ?? conversationTokens),
                  breakdown: Object.fromEntries(Object.entries(rawBreakdown).map(([key, value]) => [key, Number(value ?? 0)])),
                },
                contextLoading: false,
              }));
              updateTrace(convId, "context", "装配上下文", "completed", selected > 0 ? `限定 ${selected} 个附件；资料候选 ${knowledgeCandidates}，使用 ${sources}，裁剪 ${knowledgeExcluded}` : `记忆候选 ${memoryCandidates}，使用 ${memories}，裁剪 ${memoryExcluded}；资料使用 ${sources}`);
            } else if (ev.event === "planning.started") {
              const phase = String(ev.data.phase ?? "document");
              updateTrace(convId, "planning", phase === "document" ? "编写规划文档" : "恢复既有任务", "running", phase === "document" ? "正在整理目标、范围、技术方案、步骤和验收标准" : "正在从中断位置核对已完成步骤");
            } else if (ev.event === "model.started") {
              const phase = String(ev.data.phase ?? "response");
              const planningDocument = phase === "planning_document";
              updateTrace(convId, "model", planningDocument ? "生成规划文档" : phase === "synthesis" ? "汇总执行结果" : "生成回答", "running", planningDocument ? "正在生成结构化 Markdown 方案；不会调用工具" : phase === "synthesis" ? "正在整合各步骤的可验证结果" : "模型正在根据当前上下文组织回复");
            } else if (ev.event === "message.delta") {
              updateLiveRunSession(convId, (session) => ({ ...session, streaming: session.streaming + String(ev.data.content ?? "") }));
            } else if (ev.event === "rag.retrieved") {
              const sources = (ev.data.sources as CitationSource[]) ?? [];
              updateLiveRunSession(convId, (session) => ({ ...session, streamingSources: sources }));
              updateTrace(convId, "context", "装配上下文", "completed", `最终使用并引用 ${sources.length} 个资料片段`);
            } else if (ev.event === "tool.proposed") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateTrace(convId, `tool-${key}`, `准备：${TOOL_LABELS[tool] ?? tool}`, "running", toolTraceDetail(ev.data, "proposed"));
            } else if (ev.event === "tool.started") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateToolActivity(convId, key, tool, "running");
              updateTrace(convId, `tool-${key}`, TOOL_LABELS[tool] ?? tool, "running", toolTraceDetail(ev.data, "running"));
            } else if (ev.event === "tool.completed") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              const status = String(ev.data.status ?? "failed") as ToolStatus;
              updateToolActivity(
                convId,
                key,
                tool,
                status,
                String(ev.data.result_summary ?? ""),
              );
              updateTrace(convId, `tool-${key}`, TOOL_LABELS[tool] ?? tool, status === "completed" ? "completed" : "failed", String(ev.data.result_summary ?? STATUS_LABELS[status]));
            } else if (ev.event === "tool.reused") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateToolActivity(convId, key, tool, "completed", String(ev.data.result_summary ?? "已复用中断前结果"));
              updateTrace(convId, `tool-${key}`, TOOL_LABELS[tool] ?? tool, "completed", `已根据幂等记录复用完成结果，没有重复执行\n${String(ev.data.result_summary ?? "")}`);
            } else if (ev.event === "approval.required") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "write_file");
              updateTrace(convId, `tool-${key}`, `等待确认：${TOOL_LABELS[tool] ?? tool}`, "running", `${toolTraceDetail(ev.data, "proposed")}\n状态：尚未执行，等待你的决定`);
              updateLiveRunSession(convId, (session) => ({
                ...session,
                approvals: [...session.approvals, {
                  approvalId: String(ev.data.approval_id),
                  tool,
                  argsSummary: String(ev.data.args_summary ?? ""),
                  state: "pending",
                  error: "",
                }],
              }));
            } else if (ev.event === "approval.completed") {
              const approvalId = String(ev.data.approval_id);
              const approved = Boolean(ev.data.approved);
              updateLiveRunSession(convId, (session) => ({
                ...session,
                approvals: session.approvals.map((item) =>
                  item.approvalId === approvalId
                    ? { ...item, state: approved ? "approved" : "rejected" }
                    : item,
                ),
              }));
            } else if (ev.event === "run.failed") {
              onRunStatusChange(convId, "idle");
              updateLiveRunSession(convId, (session) => ({
                ...session,
                currentRun: null,
                traceOpen: false,
                error: String(ev.data.error ?? "运行失败"),
                runTrace: session.runTrace.map((item) => item.status === "running" ? { ...item, status: "failed" } : item),
              }));
              updateTrace(convId, "finished", "结束运行", "failed", String(ev.data.error ?? "运行失败"));
            } else if (ev.event === "run.cancelled") {
              onRunStatusChange(convId, "idle");
              const reason = String(ev.data.reason ?? "运行已停止");
              updateLiveRunSession(convId, (session) => ({
                ...session,
                currentRun: null,
                traceOpen: false,
                runTrace: session.runTrace.map((item) => item.status === "running" ? { ...item, status: "cancelled" } : item),
              }));
              updateTrace(convId, "finished", "停止运行", "cancelled", reason);
            } else if (ev.event === "run.completed") {
              onRunStatusChange(convId, "completed");
              const usage = (ev.data.token_usage ?? {}) as Record<string, unknown>;
              const rawCacheHitRate = usage.average_cache_hit_rate;
              updateLiveRunSession(convId, (session) => ({ ...session, currentRun: null, traceOpen: false }));
              if (activeConversationRef.current === convId) {
                setCacheHitRate(rawCacheHitRate === undefined || rawCacheHitRate === null ? null : Number(rawCacheHitRate));
              }
              updateTrace(convId, "finished", "完成运行", "completed", `输入 ${Number(usage.prompt_tokens ?? 0)} tokens，输出 ${Number(usage.completion_tokens ?? 0)} tokens`);
            } else if (ev.event === "message.completed") {
              updateTrace(convId, "model", executionMode === "planned" ? "生成规划文档" : "生成回答", "completed", executionMode === "planned" ? "Markdown 实施方案已保存到当前对话" : "回答已生成并保存到当前对话");
            } else if (ev.event === "planning.document.completed") {
              updateTrace(convId, "planning", "编写规划文档", "completed", "方案已生成；本次没有调用工具或执行任务");
            }
          },
          controller.signal,
          executionMode,
          documentIds,
          selectedModelId,
          chatImages.map((image) => image.id),
          runId,
          false,
        );
        const [msgs, history] = await Promise.all([
          fetchMessages(convId),
          fetchConversationRunHistory(convId),
        ]);
        const cumulativeTokens = msgs.reduce((total, row) => total + Number(row.token_estimate || 0), 0);
        if (activeConversationRef.current === convId) {
          setMessages(msgs);
          setRunHistory(Object.fromEntries(history.map((run) => [run.id, run])));
          setConversationTokens(cumulativeTokens);
        }
        updateLiveRunSession(convId, (session) => ({
          ...session,
          runTrace: [],
          traceOpen: false,
          contextUsage: session.contextUsage ? { ...session.contextUsage, conversationTokens: cumulativeTokens } : null,
        }));
        onFinished(convId);
      } catch (e) {
        const session = getLiveRunSession(convId);
        if ((e as Error).name !== "AbortError" && !session?.isStopping) {
          onRunStatusChange(convId, "idle");
          updateLiveRunSession(convId, (current) => ({
            ...current,
            error: String(e),
            runTrace: current.runTrace.map((item) => item.status === "running" ? { ...item, status: "failed" } : item),
          }));
        }
      } finally {
        updateLiveRunSession(convId, (session) => ({
          ...session,
          elapsedSeconds: Math.floor((Date.now() - session.startedAt) / 1000),
          streaming: "",
          streamingSources: [],
          contextLoading: false,
          controller: null,
          isStopping: false,
          running: false,
        }));
        void fetchCurrentConversationRun(convId).then((run) => {
          updateLiveRunSession(convId, (session) => ({ ...session, currentRun: run }));
        }).catch(() => undefined);
      }
    },
    [applyLiveSession, conversationId, conversationTokens, executionMode, onAutoCreate, onFinished, onRunStatusChange, onStarted, selectedModelId, updateToolActivity, updateTrace],
  );

  const stop = async () => {
    if (!conversationId) return;
    const session = getLiveRunSession(conversationId);
    if (!session || session.isStopping) return;
    updateLiveRunSession(conversationId, (current) => ({
      ...current,
      isStopping: true,
      runTrace: current.runTrace.map((item) => item.status === "running" ? { ...item, status: "cancelled" } : item),
    }));
    updateTrace(conversationId, "finished", "停止运行", "cancelled", "正在通知后端停止模型、工具和后续步骤…");
    const runId = session.runId;
    const interruptedDraft = session.streaming;
    const localDraftId = runId ? `local-interrupted-${runId}` : "";
    if (runId && interruptedDraft.trim()) {
      setMessages((items) => [
        ...items,
        {
          id: localDraftId,
          role: "assistant",
          content: interruptedDraft,
          citations: session.streamingSources,
          images: [],
          run_id: runId,
          status: "interrupted",
          token_estimate: 0,
          created_at: new Date().toISOString(),
        },
      ]);
      updateLiveRunSession(conversationId, (current) => ({ ...current, streaming: "", streamingSources: [] }));
    }
    try {
      if (runId) {
        await cancelChatRun(runId);
        updateLiveRunSession(conversationId, (current) => ({
          ...current,
          currentRun: current.currentRun?.id === runId
            ? { ...current.currentRun, status: "interrupted", error: "用户已停止运行" }
            : current.currentRun,
        }));
      }
      updateTrace(conversationId, "finished", "停止运行", "cancelled", "后端已接受停止请求，本次运行不会继续后续步骤");
    } catch {
      updateTrace(conversationId, "finished", "停止运行", "cancelled", "连接已中断；运行可能已经结束，系统不会继续接收结果");
    } finally {
      onRunStatusChange(conversationId, "idle");
      session.controller?.abort();
      window.setTimeout(() => {
        void Promise.all([
          fetchMessages(conversationId),
          fetchCurrentConversationRun(conversationId),
          fetchConversationRunHistory(conversationId),
        ]).then(([nextMessages, run, history]) => {
          setMessages((current) => {
            const localDraft = current.find((item) => item.id === localDraftId);
            const persisted = runId && nextMessages.some((item) => item.run_id === runId && item.status === "interrupted");
            return localDraft && !persisted ? [...nextMessages, localDraft] : nextMessages;
          });
          setConversationTokens(nextMessages.reduce((total, row) => total + Number(row.token_estimate || 0), 0));
          setRunHistory(Object.fromEntries(history.map((item) => [item.id, item])));
          updateLiveRunSession(conversationId, (current) => ({
            ...current,
            currentRun: run,
            runTrace: [],
            traceOpen: false,
          }));
        }).catch(() => undefined);
      }, 250);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim() || (images.length > 0 ? "请描述并分析这些图片。" : "");
    if (!text || isStreaming || currentRun?.status === "running" || uploadBusy) return;
    setInput("");
    const documentIds = attachments.map((document) => document.id);
    const selectedImages = images;
    setAttachments([]);
    setImages([]);
    send(text, documentIds, selectedImages);
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

  const handleImageFiles = async (files: File[]) => {
    const selectedModel = appSettings?.model_control.locked
      ? appSettings.model.model
      : appSettings?.models.items.find((profile) => profile.id === selectedModelId)?.model || "";
    if (!modelSupportsImages(selectedModel)) {
      setError("当前模型不支持图片，请先选择 qwen3.8-max");
      return;
    }
    const remaining = 4 - images.length;
    if (remaining <= 0) {
      setError("一次最多添加 4 张图片");
      return;
    }
    const selected = files.filter((file) => CHAT_IMAGE_TYPES.has(file.type)).slice(0, remaining);
    if (selected.length === 0) {
      setError("仅支持 JPG、PNG、WebP 图片");
      return;
    }
    setComposerNotice("");
    setUploadBusy(true);
    setError("");
    try {
      const results = await Promise.allSettled(selected.map((file) => uploadChatImage(file)));
      const uploaded = results
        .filter((result): result is PromiseFulfilledResult<ChatImage> => result.status === "fulfilled")
        .map((result) => result.value);
      if (uploaded.length) {
        setImages((items) => [...items, ...uploaded].slice(0, 4));
        setComposerNotice(`${uploaded.length} 张图片已就绪，可直接发送给视觉模型`);
      }
      const failed = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
      if (failed) setError(failed.reason instanceof Error ? failed.reason.message : "部分图片上传失败");
    } finally {
      setUploadBusy(false);
    }
  };

  const removeImage = (id: string) => {
    setImages((items) => items.filter((image) => image.id !== id));
    void deleteStagedChatImage(id).catch(() => undefined);
  };

  const empty = messages.length === 0 && !streaming && toolActivities.length === 0 && approvals.length === 0 && !currentRun;
  const composerProps = { projects, activeProjectId, onSelectProject, onOpenFolder, attachments, onRemoveAttachment: (id: string) => setAttachments((items) => items.filter((item) => item.id !== id)), images, onImageFiles: (files: File[]) => void handleImageFiles(files), onRemoveImage: removeImage, onStop: () => void stop(), isStopping };
  const completedRunMessage = runTrace.length > 0 && !isStreaming && messages.at(-1)?.role === "assistant" && messages.at(-1)?.status === "completed" ? messages.at(-1)! : null;
  const visibleMessages = completedRunMessage ? messages.slice(0, -1) : messages;
  const composerLocked = isStreaming || currentRun?.status === "running";

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#fcfcfc]">
      {empty && !loading ? (
        <div className="flex min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8">
          <section className="m-auto w-full max-w-5xl py-6 sm:py-12" aria-label="新任务输入区">
            <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={composerLocked} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={selectModel} contextUsage={contextUsage} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} contextLoading={contextLoading} hero uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
            {(composerNotice || error) && <p className={`mt-3 text-center text-sm ${error ? "text-red-600" : "text-emerald-700"}`} role={error ? "alert" : "status"}>{error || composerNotice}</p>}
          </section>
        </div>
      ) : (
        <div ref={messageScrollRef} className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto w-full max-w-4xl space-y-8">
            {visibleMessages.map((message) => <div key={message.id} className="space-y-3">
              {message.role === "assistant" && message.run_id && runHistory[message.run_id] && (
                <HistoricalRunTrace run={runHistory[message.run_id]} />
              )}
              <MessageBubble role={message.role} content={message.content} status={message.status} citations={message.citations} images={message.images} agent={appSettings?.agent} />
            </div>)}
            <RunTracePanel
              items={runTrace}
              open={traceOpen}
              active={isStreaming}
              elapsedSeconds={elapsedSeconds}
              onToggle={() => {
                const next = !traceOpen;
                setTraceOpen(next);
                if (conversationId) {
                  updateLiveRunSession(conversationId, (session) => ({ ...session, traceOpen: next }));
                }
              }}
            />
            <ToolActivityList items={toolActivities} />
            {approvals.map((item) => <ApprovalCard key={item.approvalId} item={item} onSubmit={handleApproval} />)}
            {completedRunMessage && <MessageBubble key={completedRunMessage.id} role={completedRunMessage.role} content={completedRunMessage.content} status={completedRunMessage.status} citations={completedRunMessage.citations} images={completedRunMessage.images} agent={appSettings?.agent} />}
            {(streaming !== "" || (loading && conversationId)) && <MessageBubble role="assistant" content={streaming || "…"} citations={streamingSources} streaming={streaming !== ""} agent={appSettings?.agent} />}
            {error && <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">{error}</div>}
            <div />
          </div>
        </div>
      )}

      {!empty && <div className="border-t border-zinc-200 bg-white/95 px-3 py-3 backdrop-blur sm:px-6">
        <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={composerLocked} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={selectModel} contextUsage={contextUsage} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} contextLoading={contextLoading} uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
        {composerNotice && <p className="mx-auto mt-2 max-w-4xl px-1 text-xs text-emerald-700">{composerNotice}</p>}
      </div>}
    </main>
  );
}
