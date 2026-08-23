"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  chatImageContentUrl,
  cancelChatRun,
  deleteStagedChatImage,
  documentContentUrl,
  fetchAppSettings,
  fetchConversationPlans,
  fetchMessages,
  submitApproval,
  streamChat,
  uploadFile,
  uploadChatImage,
  type AppSettings,
  type ChatMessage,
  type ChatImage,
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

interface PlanApprovalItem {
  approvalId: string;
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
  onUpload,
  onOpenSettings,
  projects,
  activeProjectId,
  onSelectProject,
  onCreateProject,
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
  onUpload: (file: File) => void;
  onOpenSettings?: (view: "workspace" | "model") => void;
  projects: Project[];
  activeProjectId: string | null;
  onSelectProject: (id: string | null) => void;
  onCreateProject: () => void;
  attachments: KnowledgeDocument[];
  onRemoveAttachment: (id: string) => void;
  images: ChatImage[];
  onImageFiles: (files: File[]) => void;
  onRemoveImage: (id: string) => void;
}) {
  const [projectOpen, setProjectOpen] = useState(false);
  const activeProject = projects.find((project) => project.id === activeProjectId);
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
            <option value="direct">直接回答</option><option value="planned">规划执行</option>
          </select>
          <span className="pointer-events-none absolute right-2.5 top-2.5 text-xs text-zinc-400">⌄</span>
        </label>
        <ContextMeter usage={contextUsage} contextWindowTokens={contextWindowTokens} maxOutputTokens={maxOutputTokens} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} loading={contextLoading} />
        {environmentLocked ? <button type="button" onClick={() => onOpenSettings?.("model")} className="min-h-10 max-w-44 truncate rounded-xl bg-zinc-100 px-3 text-xs font-medium text-zinc-700 sm:max-w-64 sm:text-sm" title=".env 环境模型具有最高优先级">{settings?.model.model} · 环境锁定</button> : modelProfiles.length > 0 ? <label className="relative min-w-0"><span className="sr-only">本次对话使用的模型</span><select value={selectedModelId} disabled={isStreaming} onChange={(event) => setSelectedModelId(event.target.value)} className="h-10 max-w-28 appearance-none truncate rounded-xl bg-transparent py-0 pl-2 pr-6 text-xs text-zinc-600 outline-none hover:bg-zinc-100 focus:ring-2 focus:ring-zinc-300 sm:max-w-64 sm:pl-3 sm:pr-8 sm:text-sm">{modelProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.model || "Mock"}{profile.is_default ? "（默认）" : ""}</option>)}</select><span className="pointer-events-none absolute right-2 top-2.5 text-xs text-zinc-400 sm:right-2.5">⌄</span></label> : <button type="button" onClick={() => onOpenSettings?.("model")} className="min-h-10 rounded-xl bg-amber-50 px-2 text-xs font-medium text-amber-800 hover:bg-amber-100 sm:px-3 sm:text-sm">配置模型</button>}
        <button type="submit" disabled={(!input.trim() && images.length === 0) || isStreaming || uploadBusy || !modelReady || !canSubmitImages} className="grid size-10 shrink-0 place-items-center rounded-xl bg-zinc-900 text-lg font-medium text-white transition hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:bg-zinc-300" aria-label={modelReady ? "发送消息" : "请先配置模型"} title={!canSubmitImages ? "请切换到支持图片的模型" : modelReady ? "发送消息" : "请先配置并选择模型"}>↑</button>
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
          {item.status === "cancelled" && <span className="text-xs">已停止</span>}
        </p>
        {item.detail && <p className="mt-2 whitespace-pre-line break-words text-[15px] leading-7 text-zinc-700">{item.detail}</p>}
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

function PlanApprovalCard({
  item,
  onSubmit,
}: {
  item: PlanApprovalItem;
  onSubmit: (approvalId: string, approved: boolean) => void;
}) {
  const waiting = item.state === "pending";
  return (
    <section className="mx-auto w-full max-w-3xl rounded-xl border border-zinc-200 bg-white p-4 shadow-sm" aria-label="计划执行确认">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-zinc-900 text-xs text-white" aria-hidden="true">✓</span>
        <div className="min-w-0 flex-1">
          <h3 className="font-medium text-zinc-900">计划已准备好</h3>
          <p className="mt-1 text-sm leading-6 text-zinc-500">检查上面的步骤。确认后才会开始调用工具，你也可以取消本次执行。</p>
          {item.error && <p className="mt-2 text-sm text-red-600" role="alert">{item.error}</p>}
          {waiting ? (
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <button type="button" onClick={() => onSubmit(item.approvalId, true)} className="min-h-11 rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900">开始执行</button>
              <button type="button" onClick={() => onSubmit(item.approvalId, false)} className="min-h-11 rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900">取消计划</button>
            </div>
          ) : (
            <p className="mt-3 text-sm font-medium text-zinc-600" aria-live="polite">
              {item.state === "submitting" && "正在提交决定…"}
              {item.state === "approved" && "已确认，开始执行计划"}
              {item.state === "rejected" && "已取消，计划没有执行"}
              {item.state === "expired" && "确认已失效，计划没有执行"}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function MessageBubble({
  role,
  content,
  streaming,
  citations = [],
  images = [],
}: {
  role: string;
  content: string;
  streaming?: boolean;
  citations?: CitationSource[];
  images?: ChatImage[];
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
  const [planApproval, setPlanApproval] = useState<PlanApprovalItem | null>(null);
  const [isStopping, setIsStopping] = useState(false);
  const [executionMode, setExecutionMode] = useState<"direct" | "planned">("direct");
  const [plan, setPlan] = useState<Plan | null>(null);
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
  const [traceOpen, setTraceOpen] = useState(true);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const stoppingRef = useRef(false);
  const runStartedAtRef = useRef<number | null>(null);
  const locallyCreatedConversationRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeConversationRef = useRef(conversationId);
  const lastPositionedConversationRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    activeConversationRef.current = conversationId;
  }, [conversationId]);

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
      setPlanApproval(null);
      setIsStopping(false);
      setPlan(null);
      setContextUsage(null);
      setConversationTokens(0);
      setCacheHitRate(null);
      setContextLoading(false);
      setRunTrace([]);
      setElapsedSeconds(0);
      runStartedAtRef.current = null;
      activeRunIdRef.current = null;
      stoppingRef.current = false;
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
          setConversationTokens(rows.reduce((total, row) => total + Number(row.token_estimate || 0), 0));
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

  useLayoutEffect(() => {
    const activeConversationId = activeConversationRef.current;
    const hasVisibleContent = messages.length > 0 || streaming !== "" || toolActivities.length > 0 || approvals.length > 0 || planApproval !== null;
    if (!activeConversationId || !hasVisibleContent) return;
    const isInitialPosition = lastPositionedConversationRef.current !== activeConversationId;
    bottomRef.current?.scrollIntoView({ behavior: isInitialPosition ? "auto" : "smooth", block: "end" });
    lastPositionedConversationRef.current = activeConversationId;
  }, [messages, streaming, toolActivities, approvals, planApproval]);

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

  const selectModel = useCallback((id: string) => {
    setSelectedModelId(id);
    setContextUsage(null);
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

  const handlePlanApproval = useCallback(async (approvalId: string, approved: boolean) => {
    setPlanApproval((item) => item?.approvalId === approvalId ? { ...item, state: "submitting", error: "" } : item);
    try {
      await submitApproval(approvalId, approved);
    } catch (approvalError) {
      const message = String(approvalError);
      setPlanApproval((item) => item?.approvalId === approvalId ? {
        ...item,
        state: message.includes("404") ? "expired" : "pending",
        error: message.includes("404") ? "" : message,
      } : item);
    }
  }, []);

  const send = useCallback(
    async (text: string, documentIds: string[] = [], chatImages: ChatImage[] = []) => {
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
      setPlanApproval(null);
      setPlan(null);
      setContextUsage(null);
      setContextLoading(true);
      setRunTrace([{ key: "analysis", label: "分析请求", detail: `当前理解：${compactText(text)}`, status: "running" }]);
      setTraceOpen(true);
      runStartedAtRef.current = Date.now();
      setElapsedSeconds(0);
      setMessages((ms) => [
        ...ms,
        { id: `local-${Date.now()}`, role: "user", content: text, citations: [], images: chatImages, token_estimate: estimateMessageTokens(text, chatImages.length), created_at: "" },
      ]);
      setConversationTokens((total) => total + estimateMessageTokens(text, chatImages.length));
      const controller = new AbortController();
      const runId = crypto.randomUUID().replace(/-/g, "");
      abortRef.current = controller;
      activeRunIdRef.current = runId;
      stoppingRef.current = false;
      setIsStopping(false);
      setIsStreaming(true);
      try {
        await streamChat(
          convId,
          text,
          (ev) => {
            if (ev.event === "run.started") {
              updateTrace("analysis", "分析请求", "completed", `当前理解：${compactText(text)}\n执行方式：${executionMode === "planned" ? "先制定计划，确认后执行" : "直接回答；如需工具会先展示目标与参数"}`);
            } else if (ev.event === "context.started") {
              setContextLoading(true);
              updateTrace("context", "装配上下文", "running", "正在读取会话、记忆和相关资料");
            } else if (ev.event === "context.completed") {
              const memories = Number(ev.data.memory_count ?? 0);
              const sources = Number(ev.data.source_count ?? 0);
              const selected = Number(ev.data.selected_document_count ?? 0);
              const rawBreakdown = (ev.data.token_breakdown ?? {}) as Record<string, unknown>;
              setContextUsage({
                usedTokens: Number(ev.data.token_estimate ?? 0),
                inputBudgetTokens: Number(ev.data.input_budget_tokens ?? ev.data.max_tokens ?? 8_000),
                contextWindowTokens: Number(ev.data.context_window_tokens ?? 12_096),
                maxOutputTokens: Number(ev.data.max_output_tokens ?? 4_096),
                conversationTokens: Number(ev.data.conversation_token_estimate ?? conversationTokens),
                breakdown: Object.fromEntries(Object.entries(rawBreakdown).map(([key, value]) => [key, Number(value ?? 0)])),
              });
              setContextLoading(false);
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
            } else if (ev.event === "tool.proposed") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateTrace(`tool-${key}`, `准备：${TOOL_LABELS[tool] ?? tool}`, "running", toolTraceDetail(ev.data, "proposed"));
            } else if (ev.event === "tool.started") {
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "tool");
              updateToolActivity(key, tool, "running");
              updateTrace(`tool-${key}`, TOOL_LABELS[tool] ?? tool, "running", toolTraceDetail(ev.data, "running"));
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
              const key = `${String(ev.data.run_id)}-${String(ev.data.step_index)}`;
              const tool = String(ev.data.tool ?? "write_file");
              updateTrace(`tool-${key}`, `等待确认：${TOOL_LABELS[tool] ?? tool}`, "running", `${toolTraceDetail(ev.data, "proposed")}\n状态：尚未执行，等待你的决定`);
              setApprovals((items) => [
                ...items,
                {
                  approvalId: String(ev.data.approval_id),
                  tool,
                  argsSummary: String(ev.data.args_summary ?? ""),
                  state: "pending",
                  error: "",
                },
              ]);
            } else if (ev.event === "plan.approval.required") {
              setPlanApproval({ approvalId: String(ev.data.approval_id), state: "pending", error: "" });
              updateTrace("planning", "制定执行计划", "running", `计划包含 ${Number(ev.data.step_count ?? 0)} 个步骤，等待你确认后开始`);
            } else if (ev.event === "plan.approval.completed") {
              const approved = Boolean(ev.data.approved);
              setPlanApproval((item) => item ? { ...item, state: approved ? "approved" : "rejected" } : item);
              updateTrace("planning", "制定执行计划", approved ? "completed" : "cancelled", approved ? "你已确认，开始按计划执行" : "你已取消，计划没有执行");
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
            } else if (ev.event === "run.cancelled") {
              const reason = String(ev.data.reason ?? "运行已停止");
              setPlan((current) => current ? { ...current, status: "cancelled" } : current);
              setRunTrace((items) => items.map((item) => item.status === "running" ? { ...item, status: "cancelled" } : item));
              updateTrace("finished", "停止运行", "cancelled", reason);
            } else if (ev.event === "run.completed") {
              const usage = (ev.data.token_usage ?? {}) as Record<string, unknown>;
              const rawCacheHitRate = usage.cache_hit_rate;
              setCacheHitRate(rawCacheHitRate === undefined || rawCacheHitRate === null ? null : Number(rawCacheHitRate));
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
          chatImages.map((image) => image.id),
          runId,
          executionMode === "planned",
        );
        const msgs = await fetchMessages(convId);
        const cumulativeTokens = msgs.reduce((total, row) => total + Number(row.token_estimate || 0), 0);
        setMessages(msgs);
        setConversationTokens(cumulativeTokens);
        setContextUsage((current) => current ? { ...current, conversationTokens: cumulativeTokens } : current);
        onFinished(convId);
      } catch (e) {
        if ((e as Error).name !== "AbortError" && !stoppingRef.current) {
          setError(String(e));
          setRunTrace((items) => items.map((item) => item.status === "running" ? { ...item, status: "failed" } : item));
        }
      } finally {
        if (runStartedAtRef.current !== null) {
          setElapsedSeconds(Math.floor((Date.now() - runStartedAtRef.current) / 1000));
        }
        setStreaming("");
        setStreamingSources([]);
        setContextLoading(false);
        abortRef.current = null;
        activeRunIdRef.current = null;
        stoppingRef.current = false;
        setIsStopping(false);
        setIsStreaming(false);
      }
    },
    [conversationId, conversationTokens, executionMode, onAutoCreate, onFinished, onStarted, selectedModelId, updateToolActivity, updateTrace],
  );

  const stop = async () => {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    setIsStopping(true);
    setRunTrace((items) => items.map((item) => item.status === "running" ? { ...item, status: "cancelled" } : item));
    updateTrace("finished", "停止运行", "cancelled", "正在通知后端停止模型、工具和后续步骤…");
    const runId = activeRunIdRef.current;
    try {
      if (runId) await cancelChatRun(runId);
      updateTrace("finished", "停止运行", "cancelled", "后端已接受停止请求，本次运行不会继续后续步骤");
    } catch {
      updateTrace("finished", "停止运行", "cancelled", "连接已中断；运行可能已经结束，系统不会继续接收结果");
    } finally {
      abortRef.current?.abort();
    }
  };

  const retry = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim() || (images.length > 0 ? "请描述并分析这些图片。" : "");
    if (!text || isStreaming || uploadBusy) return;
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
    if (executionMode === "planned") {
      setExecutionMode("direct");
      setComposerNotice("图片识别已自动切换为直接回答模式");
    } else {
      setComposerNotice("");
    }
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

  const empty = messages.length === 0 && !streaming && toolActivities.length === 0 && approvals.length === 0 && !plan;
  const composerProps = { projects, activeProjectId, onSelectProject, onCreateProject, attachments, onRemoveAttachment: (id: string) => setAttachments((items) => items.filter((item) => item.id !== id)), images, onImageFiles: (files: File[]) => void handleImageFiles(files), onRemoveImage: removeImage };
  const completedRunMessage = runTrace.length > 0 && !isStreaming && messages.at(-1)?.role === "assistant" ? messages.at(-1)! : null;
  const visibleMessages = completedRunMessage ? messages.slice(0, -1) : messages;

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#fcfcfc]">
      {empty && !loading ? (
        <div className="flex min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-8">
          <section className="m-auto w-full max-w-5xl py-6 sm:py-12" aria-label="新任务输入区">
            <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={isStreaming} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={selectModel} contextUsage={contextUsage} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} contextLoading={contextLoading} hero uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
            {(composerNotice || error) && <p className={`mt-3 text-center text-sm ${error ? "text-red-600" : "text-emerald-700"}`} role={error ? "alert" : "status"}>{error || composerNotice}</p>}
          </section>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          <div className="mx-auto w-full max-w-4xl space-y-5">
            {visibleMessages.map((message) => <MessageBubble key={message.id} role={message.role} content={message.content} citations={message.citations} images={message.images} />)}
            <RunTracePanel items={runTrace} open={traceOpen} active={isStreaming} elapsedSeconds={elapsedSeconds} onToggle={() => setTraceOpen((value) => !value)} />
            <PlanProgress plan={plan} />
            {planApproval && <PlanApprovalCard item={planApproval} onSubmit={handlePlanApproval} />}
            <ToolActivityList items={toolActivities} />
            {approvals.map((item) => <ApprovalCard key={item.approvalId} item={item} onSubmit={handleApproval} />)}
            {completedRunMessage && <MessageBubble key={completedRunMessage.id} role={completedRunMessage.role} content={completedRunMessage.content} citations={completedRunMessage.citations} images={completedRunMessage.images} />}
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
              type="button"
              onClick={() => void stop()}
              disabled={isStopping}
              className="min-h-11 rounded border px-3 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-500 focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-60"
            >
              {isStopping ? "正在停止…" : "停止"}
            </button>
          </div>
        )}
        <ChatComposer input={input} setInput={setInput} submit={submit} isStreaming={isStreaming} executionMode={executionMode} setExecutionMode={setExecutionMode} settings={appSettings} selectedModelId={selectedModelId} setSelectedModelId={selectModel} contextUsage={contextUsage} conversationTokens={conversationTokens} cacheHitRate={cacheHitRate} contextLoading={contextLoading} uploadBusy={uploadBusy} onUpload={(file) => void handleUpload(file)} onOpenSettings={onOpenSettings} {...composerProps} />
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
