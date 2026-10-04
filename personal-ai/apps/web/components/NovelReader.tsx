"use client";

import { useEffect, useRef, useState } from "react";
import { req } from "@/lib/api";
import SmallDialog from "./SmallDialog";

type Person = {name: string; agent_id: string; custom_instructions: string};
type Job = {
  id: string; document_id: string | null; status: string; running: boolean; error: string;
  request: {search_query: string; characters: string[]}; result: Person[];
  report: {source_chars?: number; read_chars?: number; completed_batches?: number; total_batches?: number;
    input_tokens?: number; output_tokens?: number; cached_input_tokens?: number; source_url?: string; model?: string; characters_checked?: boolean};
};
const button = "min-h-10 rounded-xl border border-zinc-200 px-4 py-2 text-sm hover:bg-zinc-50 disabled:opacity-40";
const labels: Record<string, string> = {pending: "准备阅读", searching: "正在寻找完整正文", reading: "正在阅读原小说并生成角色", checking: "原小说已读完，正在核对角色档案", completed: "角色已创建", paused: "已暂停", failed: "未完成"};

export default function NovelReader({documentId, onCreated}: {documentId: string; onCreated?: () => void}) {
  const [open, setOpen] = useState(false);
  const [names, setNames] = useState("");
  const [requirements, setRequirements] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const seen = useRef(new Set<string>());
  const callbacks = useRef({onCreated});
  useEffect(() => { callbacks.current = {onCreated}; }, [onCreated]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      try {
        const rows = await req<Job[]>("/api/novel-readings" + ("?document_id=" + encodeURIComponent(documentId)));
        if (cancelled) return;
        setJobs(rows);
        for (const row of rows) {
          const completedKey = `${row.id}:${Boolean(row.report.characters_checked)}`;
          if (row.status === "completed" && !seen.current.has(completedKey)) {
            seen.current.add(completedKey);
            window.dispatchEvent(new Event("personal-ai:agents-changed"));
            callbacks.current.onCreated?.();
          }
        }
      } catch (e) { if (!cancelled) setError(String(e)); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [open, documentId]);

  async function action(work: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await work(); setJobs(await req<Job[]>("/api/novel-readings" + ("?document_id=" + encodeURIComponent(documentId)))); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  const running = jobs.some(job => job.running);
  return <>
    <button type="button" className={button} onClick={() => setOpen(true)}>阅读全书并创建角色</button>
    {open && <SmallDialog title="阅读原小说并创建角色" size="large" onClose={() => setOpen(false)}>
      <p className="mb-5 text-sm leading-6 text-zinc-500">原小说直接作为书籍。完整阅读一次，同时创建你需要的角色，不重写小说；完成后角色会出现在 AI 好友列表。超过模型窗口时按顺序分批读完。</p>
      <label className="block text-sm font-medium">需要创建的角色<input aria-label="需要创建的角色" value={names} onChange={e => setNames(e.target.value)} className="mt-2 w-full rounded-xl border border-zinc-200 p-3" placeholder="用逗号分隔；留空提取至多五名主要人物" /></label>
      <label className="mt-4 block text-sm">其他要求、版本或剧情截止点<textarea aria-label="小说角色要求" value={requirements} onChange={e => setRequirements(e.target.value)} maxLength={2000} className="mt-2 min-h-20 w-full rounded-xl border border-zinc-200 p-3" /></label>
      <button type="button" className={button + " mt-4 bg-zinc-900 text-white hover:bg-zinc-800"} disabled={busy || running} onClick={() => void action(() => req("/api/novel-readings", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({document_id: documentId, characters: names.split(/[,，、]/).map(name => name.trim()).filter(Boolean), requirements})}))}>{busy ? "正在提交…" : "阅读全书并创建角色"}</button>
      {error && <p role="alert" className="mt-4 whitespace-pre-wrap text-sm text-red-700">{error}</p>}
      <div className="mt-6 space-y-4">{jobs.map(job => <article key={job.id} className="rounded-xl border border-zinc-200 p-4">
        <h3 className="font-semibold">{job.request.search_query || "上传的小说"} · {labels[job.status] || job.status}</h3>
        <p className="mt-2 text-sm text-zinc-500">已阅读 {(job.report.read_chars || 0).toLocaleString()} / {(job.report.source_chars || 0).toLocaleString()} 字符 · {job.report.completed_batches || 0} / {job.report.total_batches || 0} 批</p>
        <p className="mt-2 text-sm tabular-nums">输入 {(job.report.input_tokens || 0).toLocaleString()} · 输出 {(job.report.output_tokens || 0).toLocaleString()} · 缓存命中 {(job.report.cached_input_tokens || 0).toLocaleString()} tokens</p>
        {job.report.source_url && <a className="mt-2 block break-all text-xs text-blue-600 underline" href={job.report.source_url} target="_blank" rel="noreferrer">查看实际小说来源</a>}
        {job.error && <p role="alert" className="mt-2 whitespace-pre-wrap break-words text-sm text-red-700">{job.error}</p>}
        {job.status === "completed" && <button type="button" disabled={busy || running} className={button + " mt-3"} onClick={() => void action(() => req(`/api/novel-readings/${job.id}/check`, {method: "POST"}))}>核对角色档案</button>}
        {job.running ? <button type="button" className={button + " mt-3"} onClick={() => void action(() => req(`/api/novel-readings/${job.id}/pause`, {method: "POST"}))}>暂停</button> : job.status !== "completed" && <button type="button" disabled={busy || running} className={button + " mt-3"} onClick={() => void action(() => req(`/api/novel-readings/${job.id}/resume`, {method: "POST"}))}>继续</button>}
        {job.result.map(person => <details key={person.agent_id} className="mt-3 rounded-lg bg-zinc-50 p-3"><summary className="cursor-pointer text-sm font-medium">{person.name} · 已创建，查看角色提示词</summary><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7">{person.custom_instructions}</p></details>)}
      </article>)}</div>
    </SmallDialog>}
  </>;
}
