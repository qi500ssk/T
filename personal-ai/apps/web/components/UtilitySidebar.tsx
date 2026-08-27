"use client";

import type { WorkspaceView } from "@/components/Sidebar";

interface UtilitySidebarProps {
  view: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  onCollapse: () => void;
}

const items: { id: Exclude<WorkspaceView, "chat">; label: string; description: string; icon: string }[] = [
  { id: "memories", label: "记忆", description: "管理长期记忆", icon: "◇" },
  { id: "knowledge", label: "知识库", description: "文档与检索", icon: "▣" },
  { id: "activities", label: "活动", description: "定时与后台任务", icon: "◷" },
];

export default function UtilitySidebar({ view, onViewChange, onCollapse }: UtilitySidebarProps) {
  return (
    <aside className="flex max-h-60 w-full shrink-0 flex-col overflow-hidden border-t border-zinc-200 bg-zinc-50 md:max-h-none md:w-60 md:border-l md:border-t-0">
      <div className="flex h-16 shrink-0 items-center border-b border-zinc-200 px-3">
        <button type="button" onClick={onCollapse} className="grid size-10 place-items-center rounded-xl text-zinc-500 hover:bg-zinc-200 focus-visible:outline-2 focus-visible:outline-zinc-900" aria-label="隐藏右侧栏" title="隐藏右侧栏">›</button>
        <p className="ml-2 text-sm font-semibold text-zinc-900">工具</p>
      </div>
      <nav className="grid gap-1 p-3" aria-label="数据与后台功能">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onViewChange(item.id)}
            className={`flex min-h-14 items-center gap-3 rounded-xl px-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 ${view === item.id ? "bg-white text-zinc-950 shadow-sm ring-1 ring-zinc-200" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950"}`}
          >
            <span className="grid size-8 place-items-center rounded-lg bg-white text-base text-zinc-500 ring-1 ring-zinc-200" aria-hidden="true">{item.icon}</span>
            <span>
              <span className="block text-sm font-medium">{item.label}</span>
              <span className="block text-xs text-zinc-400">{item.description}</span>
            </span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
