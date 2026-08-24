"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createMemory,
  deleteMemory,
  expireMemory,
  fetchConversations,
  fetchMemories,
  fetchMemoryHistory,
  fetchProjects,
  updateMemory,
  type Conversation,
  type Memory,
  type MemoryKind,
  type Project,
} from "@/lib/api";

const kindLabels: Record<MemoryKind, string> = {
  profile: "偏好与身份",
  semantic: "长期事实 · 语义记忆",
  episodic: "重要事件 · 情景记忆",
};

const statusLabels: Record<Memory["status"], string> = {
  active: "当前有效",
  superseded: "已被替换",
  expired: "已过期",
};

type KindFilter = "all" | MemoryKind;
type ScopeFilter = "all" | Memory["scope_type"];

interface EditDraft {
  id: string;
  content: string;
  kind: MemoryKind;
  importance: number;
  scopeType: Memory["scope_type"];
  scopeKey: string;
}

function displayTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚未使用";
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function MemoryView() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [includeHistory, setIncludeHistory] = useState(false);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryKind>("semantic");
  const [importance, setImportance] = useState(3);
  const [scopeType, setScopeType] = useState<"global" | "project">("global");
  const [projectId, setProjectId] = useState("");
  const [editing, setEditing] = useState<EditDraft | null>(null);
  const [history, setHistory] = useState<Record<string, Memory[]>>({});
  const [historyOpen, setHistoryOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    const rows = await fetchMemories({ status: includeHistory ? "all" : "active" });
    setMemories(rows);
  }, [includeHistory]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchMemories({ status: includeHistory ? "all" : "active" }),
      fetchProjects(),
      fetchConversations(),
    ])
      .then(([rows, projectRows, conversationRows]) => {
        if (cancelled) return;
        setMemories(rows);
        setProjects(projectRows);
        setConversations(conversationRows);
        setProjectId((current) => current || projectRows[0]?.id || "");
        setError("");
      })
      .catch((reason) => { if (!cancelled) setError(errorMessage(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [includeHistory]);

  const projectNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const conversationNames = useMemo(
    () => Object.fromEntries(conversations.map((conversation) => [conversation.id, conversation.title])),
    [conversations],
  );

  const scopeLabel = useCallback((memory: Memory) => {
    if (memory.scope_type === "global") return "全局记忆";
    if (memory.scope_type === "project") return `项目 · ${projectNames[memory.scope_key] ?? "未知项目"}`;
    return `会话 · ${conversationNames[memory.scope_key] ?? memory.scope_key.slice(0, 8)}`;
  }, [conversationNames, projectNames]);

  const visible = useMemo(
    () => memories.filter((memory) => (
      (kindFilter === "all" || memory.kind === kindFilter)
      && (scopeFilter === "all" || memory.scope_type === scopeFilter)
    )),
    [kindFilter, memories, scopeFilter],
  );

  const groups = useMemo(() => {
    const result = new Map<string, { label: string; rows: Memory[] }>();
    for (const memory of visible) {
      const key = `${memory.scope_type}:${memory.scope_key}`;
      const existing = result.get(key) ?? { label: scopeLabel(memory), rows: [] };
      existing.rows.push(memory);
      result.set(key, existing);
    }
    return [...result.entries()].map(([key, value]) => ({ key, ...value }));
  }, [scopeLabel, visible]);

  const activeCount = memories.filter(
    (memory) => memory.status === "active" && memory.is_active,
  ).length;

  async function runMutation(
    action: () => Promise<unknown>,
    successMessage = "",
    failureHint = "",
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
      setNotice(successMessage);
    } catch (reason) {
      setError(`${errorMessage(reason)}${failureHint ? ` ${failureHint}` : ""}`);
    } finally {
      setBusy(false);
    }
  }

  async function addMemory(event: React.FormEvent) {
    event.preventDefault();
    const value = content.trim();
    if (!value || busy || (scopeType === "project" && !projectId)) return;
    await runMutation(async () => {
      await createMemory({
        content: value,
        kind,
        importance,
        scope_type: scopeType,
        scope_key: scopeType === "project" ? projectId : undefined,
      });
      setContent("");
    });
  }

  async function saveEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing || !editing.content.trim()) return;
    await runMutation(async () => {
      await updateMemory(editing.id, {
        content: editing.content.trim(),
        kind: editing.kind,
        importance: editing.importance,
        scope_type: editing.scopeType,
        scope_key: editing.scopeType === "global" ? "global" : editing.scopeKey,
      });
      setEditing(null);
    }, "纠正已保存。旧版本仍保留在替换历史中，后续召回只使用新版本。", "你编辑的内容仍保留在纠正表单中，没有丢失，可以稍后再次保存。");
  }

  async function toggleHistory(memory: Memory) {
    if (historyOpen === memory.id) {
      setHistoryOpen(null);
      return;
    }
    setHistoryOpen(memory.id);
    if (!history[memory.id]) {
      try {
        const rows = await fetchMemoryHistory(memory.id);
        setHistory((current) => ({ ...current, [memory.id]: rows }));
      } catch (reason) {
        setError(errorMessage(reason));
      }
    }
  }

  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-[#fcfcfc]">
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-7 lg:px-10">
        <header className="border-b border-zinc-200 pb-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-400">Memory governance</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950">长期记忆</h1>
              <p className="mt-1.5 max-w-2xl text-sm leading-6 text-zinc-500">
                这里管理统一 memories 表。类型表示“记住什么”，作用域决定“在哪里能想起来”。
              </p>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-right shadow-sm">
              <p className="text-2xl font-semibold tabular-nums text-zinc-900">{activeCount}</p>
              <p className="text-xs text-zinc-500">条实际启用</p>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2" aria-label="记忆筛选">
            <select value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value as ScopeFilter)} className="h-9 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-700 focus:border-zinc-900 focus:outline-none" aria-label="按作用域筛选">
              <option value="all">全部作用域</option>
              <option value="global">全局记忆</option>
              <option value="project">项目记忆</option>
              <option value="conversation">会话记忆</option>
            </select>
            <label className="flex min-h-9 items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-600">
              <input type="checkbox" checked={includeHistory} onChange={(event) => setIncludeHistory(event.target.checked)} className="size-4 accent-zinc-900" />
              显示替换与过期历史
            </label>
          </div>

          <div className="mt-4 flex gap-1 overflow-x-auto rounded-lg bg-zinc-100 p-1" role="tablist" aria-label="记忆类型">
            {(["all", "profile", "semantic", "episodic"] as KindFilter[]).map((value) => (
              <button key={value} type="button" role="tab" aria-selected={kindFilter === value} onClick={() => setKindFilter(value)} className={`min-h-9 shrink-0 rounded-md px-3 text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 ${kindFilter === value ? "bg-white font-medium text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}>
                {value === "all" ? "全部类型" : kindLabels[value]}
              </button>
            ))}
          </div>
        </header>

        <form onSubmit={addMemory} className="my-6 rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-zinc-900">手动添加</h2>
            <p className="mt-1 text-xs text-zinc-500">项目约定请选择对应项目；跨项目稳定偏好才使用全局作用域。</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(16rem,1fr)_12rem_10rem_8rem]">
            <input value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} placeholder="例如：派蒙项目使用 Milvus 作为向量数据库" className="h-11 min-w-0 rounded-lg border border-zinc-300 px-3 text-sm outline-none focus:border-zinc-900 focus:ring-2 focus:ring-zinc-100" aria-label="记忆内容" />
            <select value={kind} onChange={(event) => setKind(event.target.value as MemoryKind)} className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" aria-label="记忆类型">
              {Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select value={scopeType} onChange={(event) => setScopeType(event.target.value as "global" | "project")} className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" aria-label="记忆作用域">
              <option value="global">全局</option>
              <option value="project">指定项目</option>
            </select>
            <select value={importance} onChange={(event) => setImportance(Number(event.target.value))} className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" aria-label="重要度">
              {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>重要度 {value}</option>)}
            </select>
          </div>
          {scopeType === "project" && (
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="mt-3 h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm sm:max-w-sm" aria-label="选择项目">
              {projects.length === 0 && <option value="">暂无项目</option>}
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          )}
          <div className="mt-4 flex justify-end">
            <button disabled={!content.trim() || busy || (scopeType === "project" && !projectId)} className="min-h-10 rounded-lg bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35">添加到长期记忆</button>
          </div>
        </form>

        {notice && <p role="status" className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}
        {error && <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
        {loading ? (
          <p className="py-16 text-center text-sm text-zinc-400">正在读取记忆…</p>
        ) : groups.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-zinc-300 py-16 text-center text-sm text-zinc-400">当前筛选下没有记忆</p>
        ) : (
          <div className="space-y-8">
            {groups.map((group) => {
              const headingId = `scope-${group.key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
              return (
              <section key={group.key} aria-labelledby={headingId}>
                <div className="mb-2 flex items-center gap-3">
                  <h2 id={headingId} className="text-sm font-semibold text-zinc-800">{group.label}</h2>
                  <span className="text-xs tabular-nums text-zinc-400">{group.rows.length} 条</span>
                  <span className="h-px flex-1 bg-zinc-200" />
                </div>
                <div className="divide-y divide-zinc-200 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
                  {group.rows.map((memory) => {
                    const effective = memory.status === "active" && memory.is_active;
                    const draft = editing?.id === memory.id ? editing : null;
                    return (
                      <article key={memory.id} className={`p-4 sm:p-5 ${effective ? "" : "bg-zinc-50/80"}`}>
                        <div className="flex flex-wrap items-start gap-2">
                          <span className="rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-600">{kindLabels[memory.kind]}</span>
                          <span className="rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-500">重要度 {memory.importance}</span>
                          <span className={`rounded-md px-2 py-1 text-xs ${effective ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-500"}`}>
                            {memory.status !== "active" ? statusLabels[memory.status] : memory.is_active ? "已启用" : "用户已停用"}
                          </span>
                          <div className="ml-auto flex flex-wrap justify-end gap-x-3 gap-y-1 text-sm">
                            {memory.status === "active" && <button type="button" onClick={() => void runMutation(() => updateMemory(memory.id, { is_active: !memory.is_active }))} disabled={busy} className="text-zinc-600 hover:text-zinc-950">{memory.is_active ? "停用" : "恢复"}</button>}
                            {memory.status === "active" && <button type="button" onClick={() => setEditing({ id: memory.id, content: memory.content, kind: memory.kind, importance: memory.importance, scopeType: memory.scope_type, scopeKey: memory.scope_key })} className="text-zinc-600 hover:text-zinc-950">纠正</button>}
                            {memory.status === "active" && <button type="button" onClick={() => { if (window.confirm("将这条记忆标记为过期？历史仍会保留。")) void runMutation(() => expireMemory(memory.id)); }} disabled={busy} className="text-zinc-500 hover:text-amber-700">过期</button>}
                            <button type="button" onClick={() => void toggleHistory(memory)} aria-expanded={historyOpen === memory.id} className="text-zinc-500 hover:text-zinc-950">历史</button>
                            <button type="button" onClick={() => { if (window.confirm("永久删除这条记忆？此操作不可恢复。")) void runMutation(() => deleteMemory(memory.id)); }} disabled={busy} className="text-zinc-400 hover:text-red-700">删除</button>
                          </div>
                        </div>

                        {draft ? (
                          <form onSubmit={saveEdit} className="mt-4 space-y-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3">
                            <textarea autoFocus value={draft.content} onChange={(event) => setEditing({ ...draft, content: event.target.value })} rows={3} className="w-full resize-y rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-zinc-900" aria-label="修改记忆内容" />
                            <div className="grid gap-2 sm:grid-cols-3">
                              <select value={draft.kind} onChange={(event) => setEditing({ ...draft, kind: event.target.value as MemoryKind })} className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" aria-label="修改记忆类型">{Object.entries(kindLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
                              <select value={draft.scopeType} onChange={(event) => { const value = event.target.value as Memory["scope_type"]; setEditing({ ...draft, scopeType: value, scopeKey: value === "global" ? "global" : value === "project" ? (projects[0]?.id ?? "") : memory.scope_key }); }} className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" aria-label="修改记忆作用域">
                                <option value="global">全局记忆</option>
                                <option value="project">项目记忆</option>
                                {memory.scope_type === "conversation" && <option value="conversation">当前来源会话</option>}
                              </select>
                              <select value={draft.importance} onChange={(event) => setEditing({ ...draft, importance: Number(event.target.value) })} className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" aria-label="修改重要度">{[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>重要度 {value}</option>)}</select>
                            </div>
                            {draft.scopeType === "project" && <select value={draft.scopeKey} onChange={(event) => setEditing({ ...draft, scopeKey: event.target.value })} className="h-10 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm sm:max-w-sm" aria-label="修改所属项目">{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>}
                            <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(null)} className="min-h-9 rounded-lg border border-zinc-300 px-3 text-sm">取消</button><button disabled={busy || !draft.content.trim() || (draft.scopeType === "project" && !draft.scopeKey)} className="min-h-9 rounded-lg bg-zinc-950 px-4 text-sm text-white disabled:opacity-35">保存并保留旧版本</button></div>
                          </form>
                        ) : (
                          <p className={`mt-4 break-words text-[15px] leading-7 ${effective ? "text-zinc-800" : "text-zinc-500"}`}>{memory.content}</p>
                        )}

                        <div className="mt-4 grid gap-1 text-xs text-zinc-400 sm:grid-cols-2 lg:grid-cols-4">
                          <span>置信度 {Math.round(memory.confidence * 100)}%</span>
                          <span>实际使用 {memory.usage_count} 次</span>
                          <span>最近使用 {displayTime(memory.last_used_at)}</span>
                          <span>更新 {displayTime(memory.updated_at)}</span>
                        </div>
                        {memory.source_conversation_id && <p className="mt-2 text-xs text-zinc-400">来源会话：{conversationNames[memory.source_conversation_id] ?? memory.source_conversation_id}</p>}

                        {historyOpen === memory.id && (
                          <div className="mt-4 border-t border-zinc-200 pt-4">
                            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">替换历史</h3>
                            {!history[memory.id] ? <p className="mt-2 text-sm text-zinc-400">正在加载…</p> : <ol className="mt-3 space-y-2">{history[memory.id].map((version, index) => <li key={version.id} className="rounded-lg bg-zinc-50 px-3 py-2 text-sm"><div className="flex gap-2 text-xs text-zinc-400"><span>版本 {history[memory.id].length - index}</span><span>{statusLabels[version.status]}</span><span>{displayTime(version.updated_at)}</span></div><p className="mt-1 leading-6 text-zinc-700">{version.content}</p></li>)}</ol>}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}
