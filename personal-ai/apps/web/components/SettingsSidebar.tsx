"use client";

import type { WorkspaceView } from "@/components/Sidebar";
import type { AgentSettings } from "@/lib/api";

export type SettingsView = "general" | "model" | "appearance" | "skills" | "mcp" | "plugins";

interface SettingsSidebarProps {
  onBack: () => void;
  onOpenWorkspace: (view: WorkspaceView) => void;
  view: SettingsView;
  onViewChange: (view: SettingsView) => void;
  agent?: AgentSettings;
}

export default function SettingsSidebar({ onBack, onOpenWorkspace, view, onViewChange, agent }: SettingsSidebarProps) {
  const itemClass = (active: boolean) => `flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 ${active ? "bg-zinc-200 text-zinc-950" : "text-zinc-600 hover:bg-white hover:text-zinc-950"}`;
  return (
    <aside className="flex max-h-72 w-full shrink-0 flex-col overflow-y-auto border-b border-zinc-200 bg-zinc-100 md:max-h-none md:w-80 md:border-b-0 md:border-r">
      <div className="flex h-16 shrink-0 items-center gap-3 px-5">
        <div className="grid size-8 place-items-center rounded-xl bg-zinc-950 text-sm font-bold text-white">P</div>
        <span className="text-sm font-semibold text-zinc-950">Personal AI</span>
      </div>
      <button
        type="button"
        onClick={onBack}
        className="mx-3 flex min-h-11 shrink-0 items-center gap-2 rounded-xl px-3 text-sm text-zinc-600 hover:bg-white hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
      >
        <span aria-hidden="true">←</span>
        返回工作区
      </button>

      <nav className="px-3 pb-5" aria-label="设置导航">
        <p className="mb-2 mt-5 px-3 text-xs font-medium text-zinc-400">基础设置</p>
        <button type="button" onClick={() => onViewChange("general")} className={itemClass(view === "general")} aria-current={view === "general" ? "page" : undefined}>
          <span aria-hidden="true">☷</span>
          角色设定
        </button>
        <button type="button" onClick={() => onViewChange("model")} className={`${itemClass(view === "model")} mt-1`} aria-current={view === "model" ? "page" : undefined}>
          <span aria-hidden="true">◉</span>
          模型设置
        </button>
        <button type="button" onClick={() => onViewChange("appearance")} className={`${itemClass(view === "appearance")} mt-1`} aria-current={view === "appearance" ? "page" : undefined}>
          <span aria-hidden="true">◐</span>
          外观设置
        </button>

        <p className="mb-2 mt-5 px-3 text-xs font-medium text-zinc-400">Agent 能力</p>
        <button
          type="button"
          onClick={() => onViewChange("skills")}
          className={itemClass(view === "skills")}
          aria-current={view === "skills" ? "page" : undefined}
        >
          <span aria-hidden="true">✦</span>
          技能
        </button>
        <button type="button" onClick={() => onViewChange("mcp")} className={`${itemClass(view === "mcp")} mt-1`} aria-current={view === "mcp" ? "page" : undefined}>
          <span aria-hidden="true">⌁</span>
          MCP 服务器
        </button>
        <button type="button" onClick={() => onViewChange("plugins")} className={itemClass(view === "plugins")} aria-current={view === "plugins" ? "page" : undefined}>
          <span aria-hidden="true">▦</span>
          插件
        </button>

        <p className="mb-2 mt-6 px-3 text-xs font-medium text-zinc-400">数据与上下文</p>
        <button
          type="button"
          onClick={() => onOpenWorkspace("memories")}
          className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-zinc-600 hover:bg-white hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
        >
          <span aria-hidden="true">◇</span>
          记忆
        </button>
        <button
          type="button"
          onClick={() => onOpenWorkspace("knowledge")}
          className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-zinc-600 hover:bg-white hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
        >
          <span aria-hidden="true">▣</span>
          知识库
        </button>
      </nav>

      <div className="mt-auto hidden border-t border-zinc-200 p-4 md:block">
        <div className="flex items-center gap-3 rounded-2xl bg-white p-3">
          <div className="grid size-9 place-items-center rounded-full bg-blue-600 text-sm font-semibold text-white">{agent?.name.slice(0, 1).toUpperCase() || "AI"}</div>
          <div>
            <p className="text-sm font-medium text-zinc-950">{agent?.name || "默认助手"}</p>
            <p className="max-w-48 truncate text-xs text-zinc-500">{agent?.role || "当前配置"}</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
