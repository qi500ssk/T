"use client";

import type { Conversation } from "@/lib/api";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  view: "chat" | "memories" | "knowledge";
  onViewChange: (view: "chat" | "memories" | "knowledge") => void;
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  view,
  onViewChange,
}: SidebarProps) {
  return (
    <aside className="flex max-h-48 w-full shrink-0 flex-col border-b border-gray-200 bg-gray-50 md:max-h-none md:w-64 md:border-r md:border-b-0">
      <nav className="m-3 grid h-9 shrink-0 grid-cols-3 rounded-md bg-gray-200 p-0.5" aria-label="主导航">
        <button
          type="button"
          onClick={() => onViewChange("chat")}
          className={`rounded px-3 text-sm ${view === "chat" ? "bg-white font-medium shadow-sm" : "text-gray-600 hover:text-gray-900"}`}
        >
          对话
        </button>
        <button
          type="button"
          onClick={() => onViewChange("memories")}
          className={`rounded px-3 text-sm ${view === "memories" ? "bg-white font-medium shadow-sm" : "text-gray-600 hover:text-gray-900"}`}
        >
          记忆
        </button>
        <button
          type="button"
          onClick={() => onViewChange("knowledge")}
          className={`rounded px-2 text-sm ${view === "knowledge" ? "bg-white font-medium shadow-sm" : "text-gray-600 hover:text-gray-900"}`}
        >
          知识库
        </button>
      </nav>
      <button
        onClick={() => {
          onViewChange("chat");
          onCreate();
        }}
        className="mx-3 mb-3 rounded-md bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        + 新对话
      </button>
      <ul className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {conversations.map((c) => (
          <li
            key={c.id}
              onClick={() => {
                onViewChange("chat");
                onSelect(c.id);
              }}
            className={`group flex cursor-pointer items-center rounded-lg px-3 py-2 text-sm ${
              activeId === c.id ? "bg-blue-100" : "hover:bg-gray-200"
            }`}
          >
            <span className="flex-1 truncate">{c.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(c.id);
              }}
              className="ml-2 min-h-6 min-w-6 text-gray-400 hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100 md:opacity-0"
              aria-label={`删除会话：${c.title}`}
              title="删除会话"
            >
              ×
            </button>
          </li>
        ))}
        {conversations.length === 0 && (
          <li className="px-3 py-2 text-sm text-gray-400">暂无会话</li>
        )}
      </ul>
    </aside>
  );
}
