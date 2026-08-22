"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  deletePlugin,
  fetchPlugins,
  importPluginFolder,
  refreshPlugins,
  updatePlugin,
  type PluginItem,
} from "@/lib/api";


export default function PluginView() {
  const [items, setItems] = useState<PluginItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const folderRef = useRef<HTMLInputElement>(null);

  useEffect(() => { fetchPlugins().then(setItems).catch((err) => setError(String(err))).finally(() => setLoading(false)); }, []);
  const filtered = useMemo(() => items.filter((item) => `${item.name} ${item.description} ${item.id}`.toLowerCase().includes(query.toLowerCase())), [items, query]);
  const run = async (id: string, task: () => Promise<void>) => { setBusyId(id); setError(""); setNotice(""); try { await task(); } catch (err) { setError(err instanceof Error ? err.message : "操作失败"); } finally { setBusyId(null); } };

  const importFolder = (files: File[]) => void run("import", async () => {
    const installed = await importPluginFolder(files);
    setItems(await fetchPlugins());
    setNotice(`${installed.name} 已安装，默认处于关闭状态`);
    if (folderRef.current) folderRef.current.value = "";
  });

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between"><div><p className="text-sm font-medium text-zinc-500">Agent 能力</p><h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">插件</h1><p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-600">一个插件文件夹可以同时带来多个 Skill 和 MCP Server。当前只支持安全的声明式内容，不执行插件中的任意代码。</p></div><input aria-label="搜索插件" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索插件…" className="h-12 w-full rounded-2xl border border-zinc-200 px-4 text-sm lg:w-96" /></div>
        <div className="mt-10 flex flex-wrap items-center gap-3 border-b border-zinc-200 pb-5"><div className="mr-auto"><span className="font-medium">已安装 {items.length}</span><span className="ml-3 text-sm text-zinc-500">已启用 {items.filter((item) => item.enabled).length}</span></div><button type="button" onClick={() => void run("refresh", async () => { setItems(await refreshPlugins()); setNotice("已重新扫描插件目录"); })} className="min-h-11 rounded-xl border border-zinc-200 px-4 text-sm font-medium">↻ 刷新</button><input ref={(element) => { folderRef.current = element; element?.setAttribute("webkitdirectory", ""); element?.setAttribute("directory", ""); }} type="file" multiple tabIndex={-1} className="sr-only" onChange={(event) => importFolder(Array.from(event.target.files ?? []))} /><button type="button" onClick={() => folderRef.current?.click()} disabled={busyId === "import"} className="min-h-11 rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white disabled:opacity-50">{busyId === "import" ? "安装中…" : "＋ 导入插件文件夹"}</button></div>
        <div className="min-h-10 pt-3 text-sm" aria-live="polite">{error ? <p role="alert" className="text-red-700">{error}</p> : notice ? <p className="text-emerald-700">{notice}</p> : null}</div>

        {loading ? <div className="h-28 animate-pulse rounded-3xl bg-zinc-100 motion-reduce:animate-none" /> : filtered.length ? <div className="overflow-hidden rounded-3xl bg-zinc-100 ring-1 ring-zinc-200">{filtered.map((item) => <article key={item.id} className="border-b border-zinc-200 p-5 last:border-b-0 sm:p-6"><div className="flex flex-col gap-4 sm:flex-row sm:items-start"><div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-white text-xl" aria-hidden="true">▦</div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{item.name}</h2><span className="rounded-full bg-white px-2 py-0.5 text-xs text-zinc-500">v{item.version}</span>{item.status === "invalid" && <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">格式错误</span>}</div><p className="mt-1 text-sm leading-6 text-zinc-600">{item.description}</p><p className="mt-2 text-xs text-zinc-500">{item.skill_count} 个 Skill · {item.mcp_server_count} 个 MCP Server · ID: {item.id}</p>{item.error && <p className="mt-2 text-sm text-red-700">{item.error}</p>}</div><div className="flex items-center gap-2"><button type="button" onClick={() => void run(item.id, async () => { await deletePlugin(item.id); setItems((rows) => rows.filter((row) => row.id !== item.id)); setNotice(`${item.name} 已移入回收目录`); })} disabled={busyId === item.id} className="min-h-11 rounded-xl px-3 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50">删除</button><label className="inline-flex min-h-11 cursor-pointer items-center"><span className="sr-only">{item.enabled ? "关闭" : "启用"} {item.name}</span><input type="checkbox" checked={item.enabled} disabled={item.status === "invalid" || busyId === item.id} onChange={() => void run(item.id, async () => { const updated = await updatePlugin(item.id, !item.enabled); setItems((rows) => rows.map((row) => row.id === item.id ? updated : row)); setNotice(`${item.name} 已${updated.enabled ? "启用" : "关闭"}`); })} className="peer sr-only" /><span aria-hidden="true" className="relative h-7 w-12 rounded-full bg-zinc-300 transition peer-checked:bg-zinc-950 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-zinc-900 after:absolute after:left-1 after:top-1 after:size-5 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5 motion-reduce:after:transition-none" /></label></div></div></article>)}</div> : <div className="rounded-3xl border border-dashed border-zinc-300 px-6 py-16 text-center"><p className="font-medium">尚未安装插件</p><p className="mt-2 text-sm text-zinc-500">选择一个包含 plugin.yaml 的普通文件夹；安装后默认关闭。</p><button type="button" onClick={() => folderRef.current?.click()} className="mt-6 min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white">浏览文件夹</button></div>}

        <section className="mt-10 rounded-3xl border border-zinc-200 bg-zinc-50 p-5 sm:p-6" aria-labelledby="plugin-format"><h2 id="plugin-format" className="font-semibold">最小插件结构</h2><pre className="mt-3 overflow-x-auto rounded-2xl bg-zinc-950 p-4 text-xs leading-6 text-zinc-100"><code>{`my-plugin/
  plugin.yaml
  skills/
    my-skill/
      SKILL.md`}</code></pre><p className="mt-3 text-sm leading-6 text-zinc-600">plugin.yaml 填写 id、name、description、version，也可以声明 mcp_servers。任何 .py、.js、.exe 等可执行文件都会被拒绝。</p></section>
      </div>
    </main>
  );
}
