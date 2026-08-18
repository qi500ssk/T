"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createMemory,
  deleteMemory,
  fetchMemories,
  updateMemory,
  type Memory,
  type MemoryKind,
} from "@/lib/api";

const kindLabels: Record<MemoryKind, string> = {
  profile: "偏好与身份",
  semantic: "长期事实",
  episodic: "重要事件",
};

type Filter = "all" | MemoryKind;

export default function MemoryView() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryKind>("semantic");
  const [importance, setImportance] = useState(3);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const rows = await fetchMemories();
      setError("");
      setMemories(rows);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchMemories()
      .then((rows) => {
        if (!cancelled) setMemories(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = useMemo(
    () => memories.filter((memory) => filter === "all" || memory.kind === filter),
    [filter, memories],
  );

  async function addMemory(e: React.FormEvent) {
    e.preventDefault();
    const value = content.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    try {
      await createMemory({ content: value, kind, importance });
      setContent("");
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-gray-200 pb-4">
          <div>
            <h1 className="text-xl font-semibold">长期记忆</h1>
            <p className="mt-1 text-sm text-gray-500">{memories.filter((item) => item.is_active).length} 条启用</p>
          </div>
          <div className="flex rounded-md border border-gray-200 p-0.5" role="tablist" aria-label="记忆类型">
            {(["all", "profile", "semantic", "episodic"] as Filter[]).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={filter === value}
                onClick={() => setFilter(value)}
                className={`rounded px-2.5 py-1.5 text-xs sm:text-sm ${filter === value ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100"}`}
              >
                {value === "all" ? "全部" : kindLabels[value]}
              </button>
            ))}
          </div>
        </header>

        <form onSubmit={addMemory} className="mb-7 grid gap-3 border-b border-gray-200 pb-6 sm:grid-cols-[minmax(0,1fr)_9rem_7rem_auto]">
          <label className="sm:col-span-4 text-sm font-medium" htmlFor="memory-content">手动添加</label>
          <input
            id="memory-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={2000}
            placeholder="例如：用户偏好简洁、直接的回答"
            className="h-10 min-w-0 rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          <select value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)} className="h-10 rounded-md border border-gray-300 bg-white px-2 text-sm">
            {Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <select value={importance} onChange={(e) => setImportance(Number(e.target.value))} className="h-10 rounded-md border border-gray-300 bg-white px-2 text-sm" aria-label="重要度">
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>重要度 {value}</option>)}
          </select>
          <button disabled={!content.trim() || busy} className="h-10 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40">添加</button>
        </form>

        {error && <p role="alert" className="mb-4 text-sm text-red-600">{error}</p>}
        <div className="divide-y divide-gray-200 border-y border-gray-200">
          {visible.map((memory) => (
            <article key={memory.id} className={`py-4 ${memory.is_active ? "" : "opacity-55"}`}>
              <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                <span className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">{kindLabels[memory.kind]}</span>
                <span className="py-1 text-xs text-gray-400">重要度 {memory.importance}</span>
                <span className={`py-1 text-xs ${memory.is_active ? "text-emerald-700" : "text-gray-500"}`}>{memory.is_active ? "已启用" : "已停用"}</span>
                <div className="ml-auto flex gap-3 text-sm">
                  <button type="button" onClick={() => void mutate(() => updateMemory(memory.id, { is_active: !memory.is_active }))} disabled={busy} className="text-gray-600 hover:text-blue-700">{memory.is_active ? "停用" : "启用"}</button>
                  <button type="button" onClick={() => { setEditingId(memory.id); setEditingContent(memory.content); }} className="text-gray-600 hover:text-blue-700">编辑</button>
                  <button type="button" onClick={() => void mutate(() => deleteMemory(memory.id))} disabled={busy} className="text-gray-500 hover:text-red-700">删除</button>
                </div>
              </div>
              {editingId === memory.id ? (
                <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); const value = editingContent.trim(); if (value) void mutate(() => updateMemory(memory.id, { content: value })).then(() => setEditingId(null)); }}>
                  <input autoFocus value={editingContent} onChange={(e) => setEditingContent(e.target.value)} className="h-9 min-w-0 flex-1 rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-blue-500" />
                  <button className="rounded-md bg-gray-900 px-3 text-sm text-white">保存</button>
                  <button type="button" onClick={() => setEditingId(null)} className="rounded-md border border-gray-300 px-3 text-sm">取消</button>
                </form>
              ) : (
                <p className="mt-3 break-words text-sm leading-6 text-gray-800">{memory.content}</p>
              )}
              <p className="mt-2 text-xs text-gray-400">更新于 {new Date(memory.updated_at).toLocaleString("zh-CN")}</p>
            </article>
          ))}
          {visible.length === 0 && <p className="py-12 text-center text-sm text-gray-400">暂无此类记忆</p>}
        </div>
      </div>
    </main>
  );
}
