"use client";

import type { Conversation } from "@/lib/api";


export type WorkspaceView = "chat" | "memories" | "knowledge" | "activities";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  view: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  onOpenSettings: () => void;
}

const navigation: { id: WorkspaceView; label: string; icon: string }[] = [
  { id: "chat", label: "对话", icon: "◉" },
  { id: "memories", label: "记忆", icon: "◇" },
  { id: "knowledge", label: "知识库", icon: "▣" },
  { id: "activities", label: "活动", icon: "◷" },
];

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  view,
  onViewChange,
  onOpenSettings,
}: SidebarProps) {
  return (
    <aside className="flex max-h-72 min-w-0 w-full shrink-0 flex-col overflow-hidden border-b border-zinc-200 bg-zinc-50 md:max-h-none md:w-72 md:border-b-0 md:border-r">
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-zinc-200 px-5">
        <div className="grid size-8 place-items-center rounded-xl bg-zinc-950 text-sm font-bold text-white">P</div>
        <div>
          <p className="text-sm font-semibold text-zinc-950">Personal AI</p>
          <p className="text-xs text-zinc-500">默认助手</p>
        </div>
      </div>

      <nav className="grid shrink-0 grid-cols-4 gap-1 p-3 md:grid-cols-1" aria-label="工作区导航">
        {navigation.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onViewChange(item.id)}
            className={`flex min-h-10 items-center justify-center gap-3 rounded-xl px-3 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 md:justify-start ${
              view === item.id
                ? "bg-white font-medium text-zinc-950 shadow-sm ring-1 ring-zinc-200"
                : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950"
            }`}
          >
            <span className="text-base text-zinc-500" aria-hidden="true">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      <button
        type="button"
        onClick={() => {
          onViewChange("chat");
          onCreate();
        }}
        className="mx-3 mb-3 min-h-11 shrink-0 rounded-xl bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        ＋ 新对话
      </button>

      <button
        type="button"
        onClick={onOpenSettings}
        className="mx-3 mb-3 min-h-10 rounded-xl border border-zinc-200 bg-white text-sm font-medium text-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 md:hidden"
      >
        ⚙ 设置与技能
      </button>

      <div className="hidden min-h-0 flex-1 flex-col md:flex">
        <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wider text-zinc-400">最近对话</p>
        <ul className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <div
                className={`group flex items-center rounded-xl text-sm ${
                  activeId === conversation.id && view === "chat" ? "bg-blue-50 text-blue-950" : "hover:bg-zinc-100"
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    onViewChange("chat");
                    onSelect(conversation.id);
                  }}
                  className="min-w-0 flex-1 truncate px-3 py-2.5 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900"
                >
                  {conversation.title}
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(conversation.id)}
                  className="mr-2 grid size-7 place-items-center rounded-lg text-zinc-400 hover:bg-white hover:text-red-600 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100"
                  aria-label={`删除会话：${conversation.title}`}
                  title="删除会话"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
          {conversations.length === 0 && <li className="px-3 py-3 text-sm text-zinc-400">暂无会话</li>}
        </ul>
      </div>

      <button
        type="button"
        onClick={onOpenSettings}
        className="m-3 mt-auto hidden min-h-11 shrink-0 items-center gap-3 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 md:flex"
      >
        <span aria-hidden="true">⚙</span>
        设置与技能
      </button>
    </aside>
  );
}
