"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  deletePlugin,
  fetchPlugins,
  importPluginFolder,
  refreshPlugins,
  updatePlugin,
  updatePluginSettings,
  type PluginItem,
} from "@/lib/api";


export default function PluginView() {
  const [items, setItems] = useState<PluginItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [configuringId, setConfiguringId] = useState<string | null>(null);
  const [settingValues, setSettingValues] = useState<Record<string, string>>({});
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
      <div className="mx-auto w-full max-w-5xl px-5 py-10 sm:px-10">
        <div className="flex flex-col gap-6"><div><h1 className="text-3xl font-bold tracking-tight">插件</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-500">通过插件扩展技能与工具。导入后按需配置，并随时开启或关闭。</p></div><input aria-label="搜索插件" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索插件…" className="h-11 w-full rounded-xl border border-zinc-200 px-4 text-sm sm:ml-auto sm:w-72" /></div>
        <div className="mt-6 flex flex-wrap items-center gap-3"><div className="mr-auto"><span className="font-medium">已安装 {items.length}</span><span className="ml-3 text-sm text-zinc-500">已启用 {items.filter((item) => item.enabled).length}</span></div><button type="button" onClick={() => void run("refresh", async () => { setItems(await refreshPlugins()); setNotice("已重新扫描插件目录"); })} className="min-h-11 rounded-xl border border-zinc-200 px-4 text-sm font-medium">↻ 刷新</button><input ref={(element) => { folderRef.current = element; element?.setAttribute("webkitdirectory", ""); element?.setAttribute("directory", ""); }} type="file" multiple tabIndex={-1} className="sr-only" onChange={(event) => importFolder(Array.from(event.target.files ?? []))} /><button type="button" onClick={() => folderRef.current?.click()} disabled={busyId === "import"} className="min-h-11 rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white disabled:opacity-50">{busyId === "import" ? "安装中…" : "＋ 导入插件文件夹"}</button></div>
        <div className="min-h-10 pt-3 text-sm" aria-live="polite">{error ? <p role="alert" className="text-red-700">{error}</p> : notice ? <p className="text-emerald-700">{notice}</p> : null}</div>

        {loading ? <div className="h-28 animate-pulse rounded-3xl bg-zinc-100 motion-reduce:animate-none" /> : filtered.length ? <div className="space-y-3">{filtered.map((item) => <article key={item.id} className="rounded-2xl bg-zinc-50 p-5 ring-1 ring-zinc-200/70"><div className="flex flex-col gap-4 sm:flex-row sm:items-start"><div className="grid size-10 shrink-0 place-items-center rounded-xl bg-white text-base ring-1 ring-zinc-200/70" aria-hidden="true">▦</div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="break-words font-medium">{item.name}</h2><span className="rounded-full bg-white px-2 py-0.5 text-xs text-zinc-500">v{item.version}</span>{item.status === "enabled" && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">已启用</span>}{item.status === "disabled" && <span className="rounded-full bg-zinc-200/60 px-2 py-0.5 text-xs text-zinc-500">已关闭</span>}{item.status === "invalid" && <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">格式错误</span>}{item.status === "needs_configuration" && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">待配置</span>}</div><p className="mt-1 text-sm leading-6 text-zinc-600">{item.description}</p><p className="mt-3 text-xs text-zinc-500">{item.skill_count} 个技能 · {item.mcp_server_count} 个 MCP 服务</p>{item.error && <p className="mt-2 text-sm text-red-700">{item.error}</p>}</div><div className="flex flex-wrap items-center justify-end gap-2">{item.settings.length > 0 && <button type="button" aria-expanded={configuringId === item.id} aria-controls={`plugin-settings-${item.id}`} onClick={() => { setConfiguringId((current) => current === item.id ? null : item.id); setSettingValues({}); }} className="min-h-11 rounded-xl px-3 text-sm text-zinc-700 hover:bg-white">配置</button>}<button type="button" onClick={() => void run(item.id, async () => { await deletePlugin(item.id); setItems((rows) => rows.filter((row) => row.id !== item.id)); setNotice(`${item.name} 已移入回收目录`); })} disabled={busyId === item.id || !item.deletable} className="min-h-11 rounded-xl px-3 text-sm text-zinc-500 hover:bg-red-50 disabled:opacity-50">删除</button><label className="inline-flex min-h-11 cursor-pointer items-center"><span className="sr-only">{item.enabled ? "关闭" : "启用"} {item.name}</span><input type="checkbox" checked={item.enabled} disabled={item.status === "invalid" || !item.config_ready || busyId === item.id} onChange={() => void run(item.id, async () => { const updated = await updatePlugin(item.id, !item.enabled); setItems((rows) => rows.map((row) => row.id === item.id ? updated : row)); setNotice(`${item.name} 已${updated.enabled ? "启用" : "关闭"}`); })} className="peer sr-only" /><span aria-hidden="true" className="relative h-7 w-12 rounded-full bg-zinc-300 transition peer-checked:bg-zinc-950 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-zinc-900 after:absolute after:left-1 after:top-1 after:size-5 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5 motion-reduce:after:transition-none" /></label></div></div>{configuringId === item.id && <form id={`plugin-settings-${item.id}`} className="mt-5 rounded-2xl border border-zinc-200 bg-white p-4 sm:ml-16" onSubmit={(event) => { event.preventDefault(); void run(item.id, async () => { const values = Object.fromEntries(Object.entries(settingValues).filter(([, value]) => value.trim())); const updated = await updatePluginSettings(item.id, { values, clear_keys: [] }); setItems((rows) => rows.map((row) => row.id === item.id ? updated : row)); setSettingValues({}); setNotice(`${item.name} 的私密设置已保存`); }); }}><fieldset className="space-y-4"><legend className="font-medium">{item.name} 配置</legend>{item.settings.map((setting) => <div key={setting.key}><label htmlFor={`${item.id}-${setting.key}`} className="text-sm font-medium">{setting.label}{setting.required && <span className="text-red-700"> *</span>}</label><input id={`${item.id}-${setting.key}`} type={setting.secret ? "password" : "text"} autoComplete="off" value={settingValues[setting.key] ?? ""} onChange={(event) => setSettingValues((current) => ({ ...current, [setting.key]: event.target.value }))} placeholder={setting.configured ? "已安全保存；留空表示不修改" : "请输入配置值"} aria-describedby={`${item.id}-${setting.key}-description`} className="mt-2 h-11 w-full rounded-xl border border-zinc-300 px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900" /><p id={`${item.id}-${setting.key}-description`} className="mt-1 text-xs leading-5 text-zinc-500">{setting.description}{setting.configured ? " · 当前已配置" : " · 当前未配置"}</p>{setting.configured && <button type="button" onClick={() => void run(item.id, async () => { const updated = await updatePluginSettings(item.id, { values: {}, clear_keys: [setting.key] }); setItems((rows) => rows.map((row) => row.id === item.id ? updated : row)); setNotice(`${setting.label} 已清除，插件已停止使用该配置`); })} className="mt-2 min-h-10 rounded-lg text-sm text-red-700 hover:underline">清除已保存的值</button>}</div>)}</fieldset><div className="mt-5 flex gap-3"><button type="submit" disabled={busyId === item.id} className="min-h-11 rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white disabled:opacity-50">保存配置</button><button type="button" onClick={() => setConfiguringId(null)} className="min-h-11 rounded-xl border border-zinc-200 px-4 text-sm">取消</button></div></form>}</article>)}</div> : <div className="rounded-2xl border border-dashed border-zinc-300 px-6 py-16 text-center"><p className="font-medium">{query ? "没有匹配的插件" : "尚未安装插件"}</p><p className="mt-2 text-sm text-zinc-500">{query ? "换一个名称或描述试试。" : "导入插件文件夹后，即可在这里管理。"}</p><button type="button" onClick={() => folderRef.current?.click()} className="mt-6 min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white">浏览文件夹</button></div>}

        <details className="mt-8 rounded-2xl border border-zinc-200 p-5"><summary className="cursor-pointer text-sm font-medium text-zinc-600">开发者说明 · 制作插件</summary><pre className="mt-3 overflow-x-auto rounded-2xl bg-zinc-950 p-4 text-xs leading-6 text-zinc-100"><code>{`my-plugin/
  plugin.yaml
  skills/
    my-skill/
      SKILL.md`}</code></pre><p className="mt-3 text-sm leading-6 text-zinc-600">plugin.yaml 填写 id、name、description、version，也可以声明 mcp_servers。任何 .py、.js、.exe 等可执行文件都会被拒绝。</p></details>
      </div>
    </main>
  );
}
