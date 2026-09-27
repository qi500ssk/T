"use client";
import { useEffect, useState } from "react";
import McpServerEditor from "@/components/McpServerEditor";
import { deleteMcpServer, fetchMcpServers, refreshMcpServers, updateMcpServer, type McpServerItem } from "@/lib/api";

export default function McpView() {
  const [items, setItems] = useState<McpServerItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<"new" | "import" | McpServerItem | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { fetchMcpServers().then(setItems).catch(e => setError(String(e))).finally(() => setLoading(false)); }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); } finally { setBusy(false); }
  }
  const filtered = items.filter(item => `${item.name} ${item.source} ${item.command} ${item.url}`.toLowerCase().includes(query.toLowerCase()));
  const sources = ["user", ...Array.from(new Set(items.map(item => item.source).filter(source => source !== "user")))];
  const button = "min-h-11 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-100 disabled:opacity-50";
  return <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white"><div className="mx-auto max-w-5xl px-5 py-10 sm:px-10">
    {editor ? <McpServerEditor initial={typeof editor === "object" ? editor : undefined} importing={editor === "import"} onClose={() => setEditor(null)} onSaved={async () => { setItems(await fetchMcpServers()); setEditor(null); setNotice("配置已保存并关闭，可在列表中启用。"); }} /> : <>
      <h1 className="text-3xl font-bold tracking-tight">MCP 服务器</h1><p className="mt-3 text-sm leading-6 text-zinc-500">连接本地命令或远程服务，为 Agent 添加可随时启停的工具。</p>
      <div className="mt-8 flex flex-wrap items-center gap-3"><span className="rounded-full border border-zinc-200 px-3 py-2 text-sm">本机用户</span><span className="mr-auto text-sm text-zinc-500">共 {items.length} 个 · 已连接 {items.filter(i => i.connected).length} 个</span><input aria-label="搜索 MCP 服务器" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索 MCP 服务器…" className="h-11 w-full rounded-xl border border-zinc-200 px-4 text-sm sm:w-64" /></div>
      <div className="mt-6 flex flex-wrap justify-end gap-2"><button className={button} disabled={busy} onClick={() => void run(async () => { setItems(await refreshMcpServers()); setNotice("已重新连接用户配置的服务器。"); })}>↻ 刷新连接</button><button className={button} disabled={busy} onClick={() => setEditor("import")}>导入 JSON</button><button className={`${button} bg-zinc-950 text-white hover:bg-zinc-800`} disabled={busy} onClick={() => setEditor("new")}>＋ 新建</button></div>
      <div aria-live="polite" className="my-4 text-sm">{error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p className="text-emerald-700">{notice}</p>}</div>
      {loading ? <p className="py-10 text-zinc-500">加载中…</p> : <div className="space-y-8">{sources.map(source => {
        const rows = filtered.filter(item => item.source === source);
        if (!rows.length && (source !== "user" || query)) return null;
        return <section key={source}><h2 className="mb-4 text-sm font-medium">{source === "user" ? "自行配置" : `插件 · ${source.replace(/^plugin:/, "")}`} <span className="ml-2 text-zinc-400">{rows.length}</span></h2>
          {!rows.length ? <div className="rounded-2xl border border-dashed border-zinc-300 py-12 text-center"><p>尚未添加 MCP 服务器</p><p className="mt-2 text-sm text-zinc-500">手动填写配置，或粘贴服务提供方的 JSON。</p><button className={`${button} mt-5`} onClick={() => setEditor("new")}>＋ 新建 MCP 服务器</button></div> : <div className="space-y-3">{rows.map(item => <article key={item.name} className="rounded-2xl bg-zinc-50 p-5 ring-1 ring-zinc-200/70">
            <div className="flex flex-wrap items-center gap-3"><span className={`size-2.5 rounded-full ${item.connected ? "bg-emerald-500" : item.error ? "bg-red-500" : "bg-zinc-400"}`} /><h3 className="min-w-0 flex-1 break-all font-medium">{item.name}</h3><span className="text-xs text-zinc-500">{item.transport === "stdio" ? "本地 stdio" : item.transport === "sse" ? "SSE" : "Streamable HTTP"}</span><span className="text-xs">{item.connected ? "已连接" : item.error ? "连接失败" : "已关闭"}</span></div>
            <p className="mt-3 break-all text-sm text-zinc-500">{item.transport === "stdio" ? [item.command, ...item.args].join(" ") : item.url}</p>{item.error && <p role="alert" className="mt-2 break-all text-sm text-red-700">{item.error}</p>}
            <details className="mt-3 text-sm"><summary className="cursor-pointer text-zinc-600">连接详情 · {item.tools.length} 个已注册工具</summary><div className="mt-3 space-y-2 text-zinc-500"><p>连接超时：{item.timeout_ms ?? 30000} ms · 默认风险：{item.default_risk_level}</p>{item.server_info && <p>服务：{String(item.server_info.name ?? "")} {String(item.server_info.version ?? "")}</p>}<p>环境变量：{item.env_keys.join("、") || "无"}；请求头：{item.header_keys.join("、") || "无"}（密钥不回显）</p><ul className="space-y-1 break-all">{item.tools.map(tool => <li key={tool}>{tool}</li>)}</ul></div></details>
            {source === "user" ? <div className="mt-4 flex flex-wrap items-center gap-2"><button className={button} disabled={busy} onClick={() => setEditor(item)}>编辑</button><button className={`${button} text-red-700`} disabled={busy} onClick={() => { if (window.confirm(`删除 ${item.name} 的配置？`)) void run(async () => { await deleteMcpServer(item.name); setItems(rows => rows.filter(row => row.name !== item.name)); }); }}>删除</button><label className="ml-auto flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={item.enabled} disabled={busy} onChange={() => void run(async () => { const updated = await updateMcpServer(item.name, !item.enabled); setItems(rows => rows.map(row => row.name === item.name ? updated : row)); })} className="size-4 accent-zinc-900" />启用</label></div> : <p className="mt-4 text-xs text-zinc-500">此服务由插件提供，请在「插件」设置中配置密钥和启停。</p>}
          </article>)}</div>}
        </section>;
      })}{query && !filtered.length && <p className="py-12 text-center text-zinc-500">没有匹配的服务器</p>}</div>}
    </>}
  </div></main>;
}
