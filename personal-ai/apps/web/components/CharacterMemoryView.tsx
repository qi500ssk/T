"use client";

import { useCallback, useEffect, useState } from "react";
import { req, fetchDocuments, uploadFile, documentContentUrl, type KnowledgeDocument } from "@/lib/api";
import SelectMenu from "@/components/SelectMenu";

type RoleMemory = {
  id: string; kind: string; content: string; evidence_type: string; is_core: boolean;
  known_to_character: boolean; time_label: string; tags: string[];
  source_quote: string; source_name: string; source_section: string; document_id: string | null; status: string;
};
type Library = { memories: RoleMemory[];
  jobs: { id: string; status: string; total: number; processed: number; rejected: number; error: string | null }[] };
const kinds: Record<string, string> = { personality: "性格", experience: "经历", relationship: "人物关系", world: "世界背景" };
const states: Record<string, string> = { draft: "待确认", active: "已生效", disabled: "已停用", rejected: "已舍弃" };
const input = "rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm focus:outline-2 focus:outline-zinc-700";
const button = "min-h-10 rounded-lg border border-zinc-300 px-3 text-sm hover:bg-zinc-100 disabled:opacity-40";

export default function CharacterMemoryView({ agentId, agentName }: { agentId: string | null; agentName: string }) {
  const [data, setData] = useState<Library>({ memories: [], jobs: [] });
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<RoleMemory | null>(null);
  const [filter, setFilter] = useState("draft");
  const [newMemory, setNewMemory] = useState("");
  const [newCore, setNewCore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const root = `/api/characters/${encodeURIComponent(agentId || "")}`;
  const extracting = data.jobs.some((job) => job.status === "running");

  const refresh = useCallback(async () => {
    if (!agentId) return;
    const value = await req<Library>(`${root}/memories`); setData(value);
    setDocs(await fetchDocuments());
  }, [root, agentId]);
  useEffect(() => {
    if (!agentId) return;
    let stopped = false;
    Promise.all([req<Library>(`${root}/memories`), fetchDocuments()]).then(([value, documents]) => {
      if (stopped) return;
      setData(value); setDocs(documents);
    }).catch((reason) => { if (!stopped) setError(String(reason)); });
    return () => { stopped = true; };
  }, [root, agentId]);
  useEffect(() => {
    if (!extracting) return;
    const timer = setInterval(() => { void refresh().catch((reason) => setError(String(reason))); }, 1500);
    return () => clearInterval(timer);
  }, [extracting, refresh]);

  async function action(work: () => Promise<unknown>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); await refresh(); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  async function save(row: RoleMemory, status = row.status) {
    const { kind, content, evidence_type, is_core, known_to_character, time_label, tags, source_quote } = row;
    return req(`${root}/memories/${row.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, content, evidence_type, is_core, known_to_character, time_label, tags, source_quote, status }) });
  }
  const visible = data.memories.filter((row) => row.status === filter);
  const chosenDoc = docs.find((row) => row.id === documentId);

  return <main className="min-h-0 flex-1 overflow-y-auto bg-white p-4 sm:p-6">
    <div className="mx-auto max-w-4xl">
      <h1 className="text-lg font-semibold">{agentName}的背景与经历</h1>
      <p className="mt-2 text-sm leading-6 text-zinc-500">每个好友都有自己的人生。你可以写下它的故事，也可以从资料中整理性格、重要关系和过往经历。提取的草稿经你确认后才会用于聊天。</p>
      {!agentId ? <p className="mt-6 text-sm">请先选择或创建一个好友角色。</p> : <>
        <section className="my-5 rounded-2xl border border-zinc-200 bg-zinc-50 p-4" aria-label="从资料提取">
          <label className="block text-sm font-medium">选择原始资料<SelectMenu ariaLabel="选择原始资料" value={documentId} onChange={setDocumentId} className={`${input} mt-2 min-h-11 w-full font-normal`} disabled={busy || extracting}
            options={[{ value: "", label: "请选择已上传的文档" }, ...docs.filter((row) => row.status === "indexed" && (!row.agent_id || row.agent_id === agentId)).map((row) => ({ value: row.id, label: `${row.original_filename} · ${row.chunk_count} 个片段` }))]} /></label>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <label className={`${button} inline-flex cursor-pointer items-center`}>上传资料<input type="file" className="sr-only" accept=".txt,.md,.pdf,.docx" disabled={busy || extracting} onChange={(event) => {
              const file = event.target.files?.[0]; event.target.value = "";
              if (file) void action(async () => { const row = await uploadFile(file); setDocumentId(row.id); });
            }} /></label>
            <button type="button" disabled={!documentId || busy || extracting} className={`${button} bg-zinc-900 text-white hover:bg-zinc-700`} onClick={() => void action(async () => {
              await req(`${root}/extract`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_id: documentId }) });
              setFilter("draft");
            })}>{extracting ? "正在逐段提取…" : "为当前角色生成记忆草稿"}</button>
          </div>
          <p className="mt-3 text-xs leading-5 text-zinc-500">提取后资料归属当前角色。{chosenDoc ? `将逐段读取 ${chosenDoc.chunk_count} 个片段。` : ""}使用云端聊天模型时，资料会发送到所选服务，可能产生调用费用。</p>
          {data.jobs.slice(0, 1).map((job) => <p key={job.id} role="status" className="mt-3 text-sm">{job.status === "running" ? "提取中" : job.status === "completed" ? "提取完成，请检查草稿" : "提取未完成"}：{job.processed} / {job.total}。{job.rejected > 0 ? ` ${job.rejected} 条无法验证来源的结果已过滤。` : ""}{job.error}</p>)}
        </section>
        <form className="mb-5 space-y-3 rounded-2xl border border-zinc-200 p-4" onSubmit={(event) => { event.preventDefault(); void action(async () => {
          await req(`${root}/memories`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: newMemory.trim(), is_core: newCore }) });
          setNewMemory(""); setNewCore(false); setFilter("active"); setNotice("这段记忆已保存。");
        }); }}>
          <label className="block text-sm font-medium">写下一段记忆<textarea value={newMemory} onChange={(event) => setNewMemory(event.target.value)} maxLength={1200} required placeholder="它曾经历过什么？谁对它很重要？哪些往事塑造了现在的它？" className={`${input} mt-2 min-h-24 w-full`} /></label>
          <div className="flex flex-wrap items-center gap-4"><label className="text-sm"><input type="checkbox" checked={newCore} onChange={(event) => setNewCore(event.target.checked)} /> 核心记忆 · 对它特别重要</label><button className={button} disabled={busy || !newMemory.trim()}>保存这段记忆</button></div>
        </form>
        <div className="mb-4 flex flex-wrap gap-2" aria-label="记忆状态">
          {Object.entries(states).map(([value, label]) => <button type="button" key={value} onClick={() => { setFilter(value); setSelected([]); }} aria-pressed={filter === value} className={`${button} ${filter === value ? "bg-zinc-200 font-medium" : ""}`}>{label} · {data.memories.filter((row) => row.status === value).length}</button>)}
        </div>
        {filter === "draft" && visible.length > 0 && <div className="mb-4 flex items-center gap-3">
          <label className="text-sm"><input type="checkbox" checked={visible.every((row) => selected.includes(row.id))} onChange={(event) => setSelected(event.target.checked ? visible.map((row) => row.id) : [])} /> 选择全部草稿</label>
          <button type="button" disabled={!selected.length || busy} className={button} onClick={() => void action(async () => {
            for (const row of visible.filter((item) => selected.includes(item.id))) { await save(row, "active"); setSelected((ids) => ids.filter((id) => id !== row.id)); }
            setNotice("选中的记忆已确认，后续聊天会按范围和相关性调用。");
          })}>确认选中记忆（{selected.length}）</button>
        </div>}
        {visible.length === 0 && <div className="rounded-2xl border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500">这里还没有{states[filter]}的记忆。</div>}
        <div className="space-y-3">{visible.map((row) => <article key={row.id} className="rounded-2xl border border-zinc-200 p-4">
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            {row.status === "draft" && <input type="checkbox" aria-label={`选择记忆：${row.content.slice(0, 30)}`} checked={selected.includes(row.id)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, row.id] : ids.filter((id) => id !== row.id))} />}
            <span>{kinds[row.kind]}</span><span>{row.source_name === "用户编写" ? "用户编写" : row.evidence_type === "fact" ? "原文支持" : "AI 推断 · 请核对"}</span>{row.is_core && <span>核心记忆</span>}{!row.known_to_character && <span>角色不知情</span>}
            {row.time_label && <span>{row.time_label}</span>}
          </div>
          <p className="my-3 whitespace-pre-wrap text-sm leading-6">{row.content}</p>
          {row.tags.length > 0 && <p className="mb-2 text-xs text-zinc-500">{row.tags.join(" · ")}</p>}
          <details className="text-xs text-zinc-500"><summary className="cursor-pointer">来源：{row.source_name} {row.source_section}</summary><blockquote className="my-2 border-l-2 border-zinc-200 pl-3 leading-5">{row.source_quote}</blockquote>{row.document_id && <a className="underline" href={documentContentUrl(row.document_id)} target="_blank" rel="noreferrer">查看原始文件</a>}</details>
          <div className="mt-3 flex gap-2"><button type="button" className={button} disabled={busy} onClick={() => setEditing({ ...row })}>编辑</button>
            <button type="button" className={button} disabled={busy} onClick={() => void action(async () => { await save(row, row.status === "active" ? "disabled" : "active"); })}>{row.status === "active" ? "停用" : "确认启用"}</button>
            {row.status === "draft" && <button type="button" className={button} disabled={busy} onClick={() => void action(async () => { await save(row, "rejected"); })}>舍弃草稿</button>}
          </div>
          {editing?.id === row.id && <form className="mt-4 space-y-3 border-t border-zinc-200 pt-4" onSubmit={(event) => { event.preventDefault(); void action(async () => { await save(editing); setEditing(null); }); }}>
            <label className="block text-sm">记忆内容<textarea autoFocus value={editing.content} maxLength={1200} required onChange={(event) => setEditing({ ...editing, content: event.target.value })} className={`${input} mt-2 min-h-28 w-full`} /></label>
            <div className="flex flex-wrap gap-3">
              <label className="flex items-center gap-2 text-sm">分类<SelectMenu ariaLabel="分类" value={editing.kind} onChange={(value) => setEditing({ ...editing, kind: value })} className={`${input} min-h-10 min-w-28`} disabled={busy} options={Object.entries(kinds).map(([value, label]) => ({ value, label }))} /></label>
              <label className="flex items-center gap-2 text-sm">依据<SelectMenu ariaLabel="依据" value={editing.evidence_type} onChange={(value) => setEditing({ ...editing, evidence_type: value })} className={`${input} min-h-10 min-w-28`} disabled={busy} options={[{ value: "fact", label: "原文支持" }, { value: "inference", label: "推断" }]} /></label>
              <label className="text-sm">时间（可选）<input value={editing.time_label} maxLength={200} placeholder="例如童年、大学时期" onChange={(event) => setEditing({ ...editing, time_label: event.target.value })} className={`${input} ml-2 w-44`} /></label>
            </div>
            <label className="block text-sm">主题标签（逗号分隔）<input value={editing.tags.join(",")} onChange={(event) => setEditing({ ...editing, tags: event.target.value.split(/[,，]/).slice(0, 12) })} className={`${input} mt-2 w-full`} /></label>
            <div className="flex gap-4 text-sm"><label><input type="checkbox" checked={editing.is_core} onChange={(event) => setEditing({ ...editing, is_core: event.target.checked })} /> 核心记忆</label><label><input type="checkbox" checked={editing.known_to_character} onChange={(event) => setEditing({ ...editing, known_to_character: event.target.checked })} /> 角色知情</label></div>
            <button disabled={busy} className={button}>保存修改</button><button type="button" onClick={() => setEditing(null)} className={`${button} ml-2`}>取消</button>
          </form>}
        </article>)}</div>
      </>}
      {error && <p className="my-4 text-sm text-red-700" role="alert">{error}</p>}
      {notice && <p className="my-4 text-sm text-emerald-700" role="status">{notice}</p>}
    </div>
  </main>;
}
