"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import SelectMenu from "@/components/SelectMenu";

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
type OwnerView = "agent" | "shared";

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

export default function MemoryView({
  agentId,
  agentName,
}: {
  agentId: string | null;
  agentName: string;
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [ownerView, setOwnerView] = useState<OwnerView>("agent");
  const [includeHistory, setIncludeHistory] = useState(false);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryKind>("semantic");
  const [importance, setImportance] = useState(3);
  const [scopeType, setScopeType] = useState<"global" | "agent" | "project" | "conversation">("agent");
  const [projectId, setProjectId] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [editing, setEditing] = useState<EditDraft | null>(null);
  const [history, setHistory] = useState<Record<string, Memory[]>>({});
  const [historyOpen, setHistoryOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    const rows = ownerView === "shared"
      ? await fetchMemories({ scope_type: "global", status: includeHistory ? "all" : "active" })
      : agentId
        ? await fetchMemories({ agent_id: agentId, status: includeHistory ? "all" : "active" })
        : [];
    setMemories(rows);
  }, [agentId, includeHistory, ownerView]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      ownerView === "shared"
        ? fetchMemories({ scope_type: "global", status: includeHistory ? "all" : "active" })
        : agentId
          ? fetchMemories({ agent_id: agentId, status: includeHistory ? "all" : "active" })
          : Promise.resolve([]),
      fetchProjects(),
      fetchConversations(),
    ])
      .then(([rows, projectRows, conversationRows]) => {
        if (cancelled) return;
        setMemories(rows);
        setProjects(projectRows);
        setConversations(conversationRows);
        const allowedProjects = projectRows.filter(
          (project) => agentId !== null && project.agent_ids.includes(agentId),
        );
        setProjectId((current) => (
          allowedProjects.some((project) => project.id === current)
            ? current
            : allowedProjects[0]?.id ?? ""
        ));
        const allowedConversations = conversationRows.filter(
          (conversation) => agentId !== null && conversation.agent_id === agentId,
        );
        setConversationId((current) => (
          allowedConversations.some((conversation) => conversation.id === current)
            ? current
            : allowedConversations[0]?.id ?? ""
        ));
        setError("");
      })
      .catch((reason) => { if (!cancelled) setError(errorMessage(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [agentId, includeHistory, ownerView]);

  const availableProjects = useMemo(
    () => projects.filter((project) => agentId !== null && project.agent_ids.includes(agentId)),
    [agentId, projects],
  );
  const availableConversations = useMemo(
    () => conversations.filter(
      (conversation) => agentId !== null && conversation.agent_id === agentId,
    ),
    [agentId, conversations],
  );

  function selectOwnerView(value: OwnerView) {
    setOwnerView(value);
    setScopeType(value === "shared" ? "global" : "agent");
    setScopeFilter("all");
    setEditing(null);
    setHistoryOpen(null);
    setNotice("");
    setError("");
  }

  const projectNames = useMemo(
    () => Object.fromEntries(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  const conversationNames = useMemo(
    () => Object.fromEntries(conversations.map((conversation) => [conversation.id, conversation.title])),
    [conversations],
  );

  const scopeLabel = useCallback((memory: Memory) => {
    if (memory.scope_type === "global") return "公共记忆";
    if (memory.scope_type === "agent") return `${agentName}的好友记忆`;
    if (memory.scope_type === "project") return `项目 · ${projectNames[memory.scope_key] ?? "未知项目"}`;
    return `会话 · ${conversationNames[memory.scope_key] ?? memory.scope_key.slice(0, 8)}`;
  }, [agentName, conversationNames, projectNames]);

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
    if (
      !value
      || busy
      || (scopeType === "agent" && !agentId)
      || (scopeType === "project" && !projectId)
      || (scopeType === "conversation" && !conversationId)
    ) return;
    await runMutation(async () => {
      await createMemory({
        content: value,
        kind,
        importance,
        scope_type: scopeType,
        scope_key: scopeType === "agent"
          ? agentId ?? undefined
          : scopeType === "project"
            ? projectId
            : scopeType === "conversation"
              ? conversationId
              : undefined,
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
                好友记忆彼此隔离，项目记忆由获准访问项目的好友共享，公共记忆对所有好友生效。
              </p>
            </div>
            <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-right shadow-sm">
              <p className="text-2xl font-semibold tabular-nums text-zinc-900">{activeCount}</p>
              <p className="text-xs text-zinc-500">条实际启用</p>
            </div>
          </div>

          <div className="mt-5 inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-zinc-200 bg-zinc-100 p-1" role="tablist" aria-label="记忆归属">
            <button type="button" role="tab" aria-selected={ownerView === "agent"} onClick={() => selectOwnerView("agent")} className={`min-h-10 shrink-0 rounded-lg px-4 text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 ${ownerView === "agent" ? "bg-white font-medium text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}>
              {agentName}的记忆
            </button>
            <button type="button" role="tab" aria-selected={ownerView === "shared"} onClick={() => selectOwnerView("shared")} className={`min-h-10 shrink-0 rounded-lg px-4 text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 ${ownerView === "shared" ? "bg-white font-medium text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"}`}>
              公共记忆
            </button>
          </div>

          <div className="mt-3 flex flex-wrap gap-2" aria-label="记忆筛选">
            <SelectMenu value={scopeFilter} onChange={(value) => setScopeFilter(value as ScopeFilter)} options={ownerView === "shared" ? [{ value: "all", label: "全部作用域" }, { value: "global", label: "公共记忆" }] : [{ value: "all", label: "全部作用域" }, { value: "agent", label: "好友记忆" }, { value: "project", label: "项目共享记忆" }, { value: "conversation", label: "会话记忆" }]} ariaLabel="按作用域筛选" className="h-9 rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-700" />
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
            <p className="mt-1 text-xs text-zinc-500">
              {ownerView === "shared"
                ? "公共记忆会被所有 AI 好友读取，只适合共同使用的用户资料和约定。"
                : `默认保存给${agentName}；临时信息可限定到一条会话，需要协作的约定可选择项目。`}
            </p>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(16rem,1fr)_12rem_10rem_8rem]">
            <input value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} placeholder={ownerView === "shared" ? "例如：用户希望所有好友都称呼他为昴大人" : `例如：用户希望${agentName}称呼他为昴大人`} className="h-11 min-w-0 rounded-lg border border-zinc-300 px-3 text-sm outline-none focus:border-zinc-900 focus:ring-2 focus:ring-zinc-100" aria-label="记忆内容" />
            <SelectMenu value={kind} onChange={(value) => setKind(value as MemoryKind)} options={Object.entries(kindLabels).map(([value, label]) => ({ value, label }))} ariaLabel="记忆类型" className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" />
            <SelectMenu value={scopeType} onChange={(value) => setScopeType(value as "global" | "agent" | "project" | "conversation")} options={ownerView === "shared" ? [{ value: "global", label: "所有好友共享" }] : [{ value: "agent", label: `仅 ${agentName}` }, { value: "conversation", label: "指定会话" }, { value: "project", label: "指定项目共享" }]} ariaLabel="记忆作用域" className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" />
            <SelectMenu value={String(importance)} onChange={(value) => setImportance(Number(value))} options={[1, 2, 3, 4, 5].map((value) => ({ value: String(value), label: `重要度 ${value}` }))} ariaLabel="重要度" className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-sm" />
          </div>
          {scopeType === "project" && (
            <SelectMenu value={projectId} onChange={setProjectId} options={availableProjects.length === 0 ? [{ value: "", label: "当前好友暂无项目", disabled: true }] : availableProjects.map((project) => ({ value: project.id, label: project.name }))} ariaLabel="选择项目" className="mt-3 h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm sm:max-w-sm" />
          )}
          {scopeType === "conversation" && (
            <SelectMenu value={conversationId} onChange={setConversationId} options={availableConversations.length === 0 ? [{ value: "", label: "当前好友暂无可选会话", disabled: true }] : availableConversations.map((conversation) => ({ value: conversation.id, label: conversation.title }))} ariaLabel="选择会话" className="mt-3 h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm sm:max-w-sm" />
          )}
          <div className="mt-4 flex justify-end">
            <button disabled={!content.trim() || busy || (scopeType === "agent" && !agentId) || (scopeType === "project" && !projectId) || (scopeType === "conversation" && !conversationId)} className="min-h-10 rounded-lg bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35">添加到长期记忆</button>
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
                              <SelectMenu value={draft.kind} onChange={(value) => setEditing({ ...draft, kind: value as MemoryKind })} options={Object.entries(kindLabels).map(([value, label]) => ({ value, label }))} ariaLabel="修改记忆类型" className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" />
                              <SelectMenu value={draft.scopeType} onChange={(nextValue) => { const value = nextValue as Memory["scope_type"]; setEditing({ ...draft, scopeType: value, scopeKey: value === "global" ? "global" : value === "agent" ? (agentId ?? "") : value === "project" ? (availableProjects[0]?.id ?? "") : value === "conversation" ? (availableConversations[0]?.id ?? "") : memory.scope_key }); }} options={ownerView === "shared" ? [{ value: "global", label: "公共记忆" }] : [{ value: "agent", label: `仅 ${agentName}` }, { value: "conversation", label: "指定会话" }, { value: "project", label: "项目共享记忆" }]} ariaLabel="修改记忆作用域" className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" />
                              <SelectMenu value={String(draft.importance)} onChange={(value) => setEditing({ ...draft, importance: Number(value) })} options={[1, 2, 3, 4, 5].map((value) => ({ value: String(value), label: `重要度 ${value}` }))} ariaLabel="修改重要度" className="h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm" />
                            </div>
                            {draft.scopeType === "project" && <SelectMenu value={draft.scopeKey} onChange={(value) => setEditing({ ...draft, scopeKey: value })} options={availableProjects.map((project) => ({ value: project.id, label: project.name }))} ariaLabel="修改所属项目" className="h-10 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm sm:max-w-sm" />}
                            {draft.scopeType === "conversation" && <SelectMenu value={draft.scopeKey} onChange={(value) => setEditing({ ...draft, scopeKey: value })} options={availableConversations.length === 0 ? [{ value: "", label: "当前好友暂无可选会话", disabled: true }] : availableConversations.map((conversation) => ({ value: conversation.id, label: conversation.title }))} ariaLabel="修改所属会话" className="h-10 w-full rounded-lg border border-zinc-300 bg-white px-2 text-sm sm:max-w-sm" />}
                            <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(null)} className="min-h-9 rounded-lg border border-zinc-300 px-3 text-sm">取消</button><button disabled={busy || !draft.content.trim() || (draft.scopeType === "agent" && !draft.scopeKey) || (draft.scopeType === "project" && !draft.scopeKey) || (draft.scopeType === "conversation" && !draft.scopeKey)} className="min-h-9 rounded-lg bg-zinc-950 px-4 text-sm text-white disabled:opacity-35">保存并保留旧版本</button></div>
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
