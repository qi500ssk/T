"use client";

import { useEffect, useState } from "react";

import type { AgentRunHistory, RunHistoryTool } from "@/lib/api";

export type ToolStatus = "running" | "completed" | "rejected" | "failed" | "timeout";

export type TraceStatus = "running" | "completed" | "failed" | "cancelled";

export interface RunTraceItem {
  key: string;
  label: string;
  detail: string;
  status: TraceStatus;
  startedAt?: number;
  endedAt?: number;
}

export const TOOL_LABELS: Record<string, string> = {
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
};

export const STATUS_LABELS: Record<ToolStatus, string> = {
  running: "执行中",
  completed: "已完成",
  rejected: "已拒绝",
  failed: "失败",
  timeout: "已超时",
};

export const RISK_LABELS: Record<string, string> = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

const BREAKDOWN_LABELS: Record<string, string> = {
  system: "系统提示",
  memory: "记忆",
  knowledge: "资料",
  summary: "会话摘要",
  messages: "对话消息",
  tools: "工具定义",
  other: "其他",
};

export function compactText(value: string, maxLength = 180) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

export function formatElapsed(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return remainingSeconds > 0 ? `${minutes} 分 ${remainingSeconds} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours} 小时 ${remainingMinutes} 分` : `${hours} 小时`;
}

export function traceIcon(key: string) {
  if (key === "thinking") return "◌";
  if (key === "analysis") return "◉";
  if (key === "context") return "⌕";
  if (key === "planning") return "≣";
  if (key === "model") return "✎";
  if (key.startsWith("tool-")) return "⌘";
  return "✓";
}

export function stepSeconds(item: RunTraceItem): number | null {
  if (!item.startedAt) return null;
  const end = item.endedAt ?? (item.status === "running" ? Date.now() : undefined);
  if (!end) return null;
  return Math.max(0, Math.round((end - item.startedAt) / 1000));
}

function toolTraceDetail(tool: RunHistoryTool, detailed: boolean) {
  const base = `${tool.args_summary || "未记录参数"}${tool.result_summary ? `\n${tool.result_summary}` : ""}`;
  if (!detailed) return base;
  const status = STATUS_LABELS[(tool.status as ToolStatus) in STATUS_LABELS ? (tool.status as ToolStatus) : "failed"];
  const risk = RISK_LABELS[tool.risk_level ?? ""] ?? "未知风险";
  const duration = tool.duration_ms != null ? ` · 耗时 ${(tool.duration_ms / 1000).toFixed(1)} 秒` : "";
  return `${base}\n状态：${status} · ${risk}${duration}`;
}

function contextDetail(context: Record<string, unknown>, detailed: boolean) {
  const memoryCount = Number(context.memory_count ?? 0);
  const memoryCandidates = Number(context.memory_candidate_count ?? memoryCount);
  const sourceCount = Number(context.source_count ?? 0);
  const knowledgeCandidates = Number(context.knowledge_candidate_count ?? sourceCount);
  const base = `记忆候选 ${memoryCandidates}，使用 ${memoryCount}；资料候选 ${knowledgeCandidates}，使用 ${sourceCount}`;
  if (!detailed) return base;
  const breakdown = (context.token_breakdown ?? {}) as Record<string, unknown>;
  const parts = Object.entries(BREAKDOWN_LABELS)
    .filter(([key]) => breakdown[key] != null)
    .map(([key, label]) => `${label} ${Number(breakdown[key] ?? 0)}`);
  const total = Number(context.token_estimate ?? 0);
  const budget = Number(context.input_budget_tokens ?? 0);
  return `${base}\n上下文预算 ${total}${budget ? ` / ${budget}` : ""} tokens${parts.length ? `\n构成：${parts.join(" + ")}` : ""}`;
}

/** 从历史 Run 记录重建处理步骤；detailed 模式给“过程”整页视图用，不截断细节。 */
export function historicalTraceItems(run: AgentRunHistory, detailed = false): RunTraceItem[] {
  const intent = run.intent ?? {};
  const context = run.context_stats ?? {};
  const items: RunTraceItem[] = [
    {
      key: "analysis",
      label: "分析请求",
      status: "completed",
      detail: `当前理解：${detailed ? run.input_message || "历史请求" : compactText(run.input_message || "历史请求")}\n执行方式：${run.execution_mode === "planned" ? "规划模式" : "自主模式"}`,
    },
  ];
  if (run.thinking?.trim()) {
    items.push({
      key: "thinking",
      label: "思考回应",
      status: "completed",
      detail: detailed ? run.thinking.trim() : compactText(run.thinking),
    });
  }
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
      ? contextDetail(context, detailed)
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
      detail: toolTraceDetail(tool, detailed),
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

export function runElapsedSeconds(run: AgentRunHistory) {
  if (!run.completed_at) return 0;
  return Math.max(0, Math.round((Date.parse(run.completed_at) - Date.parse(run.created_at)) / 1000));
}

export function RunStepsList({ items }: { items: RunTraceItem[] }) {
  return (
    <ol className="space-y-6">
      {items.map((item) => {
        const seconds = stepSeconds(item);
        return (
          <li key={item.key} className="relative text-sm">
            <span
              className={`absolute -left-[35px] top-0 grid size-4 place-items-center bg-white text-xs ${item.status === "failed" ? "text-red-500" : item.status === "running" ? "animate-pulse text-blue-500 motion-reduce:animate-none" : "text-zinc-400"}`}
              aria-hidden="true"
            >
              {traceIcon(item.key)}
            </span>
            <p className={`flex flex-wrap items-center gap-2 ${item.status === "failed" ? "text-red-600" : "text-zinc-500"}`}>
              <span className="font-medium">{item.label}</span>
              {item.status === "running" && <span className="text-xs text-blue-500">进行中</span>}
              {item.status === "cancelled" && <span className="text-xs">已停止</span>}
              {seconds != null && seconds > 0 && <span className="text-xs tabular-nums text-zinc-400">{formatElapsed(seconds)}</span>}
            </p>
            {item.detail && <p className="mt-2 whitespace-pre-line break-words text-[13px] leading-6 text-zinc-700">{item.detail}</p>}
          </li>
        );
      })}
    </ol>
  );
}

export function RunTracePanel({
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
  return (
    <section aria-label="Agent 工作记录">
      <button
        type="button"
        onClick={onToggle}
        className="group flex min-h-11 w-full items-center gap-3 text-left text-sm text-zinc-500 focus-visible:rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
        aria-expanded={open}
      >
        <span className="shrink-0 font-medium">{heading} {formatElapsed(elapsedSeconds)}</span>
        <span className="h-px min-w-6 flex-1 bg-zinc-200" aria-hidden="true" />
        <span className={`grid size-7 shrink-0 place-items-center rounded-full text-xs text-zinc-400 transition group-hover:bg-zinc-100 group-hover:text-zinc-700 ${open ? "rotate-180" : ""}`} aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="ml-2 border-l border-zinc-200 pb-2 pl-7 pt-3">
          <RunStepsList items={items} />
        </div>
      )}
    </section>
  );
}

/** 角色内心独白：生成时直播展示，结束后可折叠；历史消息默认折叠。 */
export function ThinkingBlock({
  text,
  active,
  startedAt,
  endedAt,
  defaultOpen,
}: {
  text: string;
  active: boolean;
  startedAt: number | null;
  endedAt: number | null;
  defaultOpen: boolean;
}) {
  // manualOpen 为 null 时跟随直播状态：思考中展开，结束后收起。
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const live = active && !endedAt;
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);
  const open = manualOpen ?? (defaultOpen && live);
  const seconds = live
    ? Math.max(0, Math.floor((now - (startedAt ?? now)) / 1000))
    : startedAt && endedAt
      ? Math.max(1, Math.round((endedAt - startedAt) / 1000))
      : null;
  if (!text.trim() && !live) return null;
  return (
    <div className="flex justify-start">
      <section
        className={`w-full max-w-[calc(100%-3.25rem)] rounded-2xl border px-4 py-3 transition-colors ${live ? "border-zinc-200 bg-zinc-50" : "border-zinc-100 bg-zinc-50/60"}`}
        aria-label="角色内心独白"
        aria-live={live ? "polite" : undefined}
      >
        <button
          type="button"
          onClick={() => setManualOpen(!open)}
          className="flex min-h-7 items-center gap-2 text-left text-xs font-medium text-zinc-400 transition hover:text-zinc-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
          aria-expanded={open}
        >
          <span aria-hidden="true">💭</span>
          <span>{live ? `思考中…${seconds != null && seconds > 0 ? ` ${seconds} 秒` : ""}` : seconds != null ? `已思考 ${seconds} 秒` : "内心独白"}</span>
          <span className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true">⌄</span>
        </button>
        {open && (
          <p className={`mt-2 whitespace-pre-wrap break-words text-[13px] leading-6 ${live ? "text-zinc-500" : "text-zinc-400"}`}>
            {text || "…"}
          </p>
        )}
      </section>
    </div>
  );
}
