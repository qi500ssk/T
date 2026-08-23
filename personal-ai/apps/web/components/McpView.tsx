"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  deleteMcpServer,
  fetchMcpServers,
  refreshMcpServers,
  saveMcpServer,
  testMcpServer,
  updateMcpServer,
  type McpServerInput,
  type McpServerItem,
} from "@/lib/api";


const emptyInput: McpServerInput = {
  name: "",
  transport: "stdio",
  command: "",
  args: [],
  url: "",
  env: {},
  headers: {},
  enabled: false,
  default_risk_level: "high",
  allowed_tools: [],
  tool_risk_levels: {},
};

function objectField(value: FormDataEntryValue | null, label: string): Record<string, string> {
  const text = String(value || "").trim();
  if (!text) return {};
  const parsed: unknown = JSON.parse(text);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(`${label} 必须是 JSON 对象`);
  for (const item of Object.values(parsed)) if (typeof item !== "string") throw new Error(`${label} 的值必须是字符串`);
  return parsed as Record<string, string>;
}

function ServerDialog({
  value,
  busy,
  onClose,
  onSave,
  onTest,
}: {
  value: McpServerInput | null;
  busy: boolean;
  onClose: () => void;
  onSave: (body: McpServerInput) => Promise<void>;
  onTest: (body: McpServerInput) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [transport, setTransport] = useState(value?.transport ?? "stdio");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    const dialog = ref.current;
    if (value && dialog && !dialog.open) {
      setTransport(value.transport);
      setFormError("");
      dialog.showModal();
    }
    if (!value && dialog?.open) dialog.close();
  }, [value]);

  const parse = (form: HTMLFormElement): McpServerInput => {
    const data = new FormData(form);
    return {
      name: String(data.get("name") || "").trim(),
      transport,
      command: String(data.get("command") || "").trim(),
      args: String(data.get("args") || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      url: String(data.get("url") || "").trim(),
      env: objectField(data.get("env"), "环境变量"),
      headers: objectField(data.get("headers"), "Headers"),
      enabled: false,
      default_risk_level: data.get("risk") as McpServerInput["default_risk_level"],
      allowed_tools: String(data.get("allowed_tools") || "").split(",").map((item) => item.trim()).filter(Boolean),
      tool_risk_levels: {},
    };
  };

  const submit = (event: FormEvent<HTMLFormElement>, action: "save" | "test") => {
    event.preventDefault();
    try {
      setFormError("");
      const body = parse(event.currentTarget);
      void (action === "save" ? onSave(body) : onTest(body));
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "配置格式错误");
    }
  };

  const testCurrentForm = (form: HTMLFormElement | null) => {
    if (!form) return;
    try {
      setFormError("");
      void onTest(parse(form));
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "配置格式错误");
    }
  };

  return (
    <dialog ref={ref} onCancel={(event) => busy ? event.preventDefault() : onClose()} onClose={onClose} className="m-auto w-[min(94vw,46rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35">
      {value && (
        <form key={value.name || "new"} onSubmit={(event) => submit(event, "save")} className="p-6 sm:p-8">
          <div className="flex items-start justify-between gap-5">
            <div><h2 className="text-2xl font-bold">{value.name ? "编辑 MCP Server" : "新建 MCP Server"}</h2><p className="mt-2 text-sm text-zinc-600">保存时默认关闭。先测试连接，再手动启用。</p></div>
            <button type="button" onClick={onClose} disabled={busy} aria-label="关闭" className="min-h-11 min-w-11 rounded-xl text-xl text-zinc-500 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-zinc-900">×</button>
          </div>
          <div className="mt-6 grid gap-5 sm:grid-cols-2">
            <label className="grid gap-2 text-sm font-medium">名称<input name="name" required pattern="[A-Za-z0-9_-]+" defaultValue={value.name} readOnly={Boolean(value.name)} className="h-11 rounded-xl border border-zinc-300 px-3 font-normal read-only:bg-zinc-100" /></label>
            <label className="grid gap-2 text-sm font-medium">传输方式<select value={transport} onChange={(event) => setTransport(event.target.value as McpServerInput["transport"])} className="h-11 rounded-xl border border-zinc-300 bg-white px-3 font-normal"><option value="stdio">本地 stdio</option><option value="streamable_http">Streamable HTTP</option></select></label>
            {transport === "stdio" ? <>
              <label className="grid gap-2 text-sm font-medium sm:col-span-2">启动命令<input name="command" required defaultValue={value.command} placeholder="python" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal" /></label>
              <label className="grid gap-2 text-sm font-medium sm:col-span-2">参数（每行一个）<textarea name="args" defaultValue={value.args.join("\n")} rows={3} placeholder={"-m\nmy_mcp_server"} className="rounded-xl border border-zinc-300 px-3 py-2 font-mono text-sm font-normal" /></label>
              <label className="grid gap-2 text-sm font-medium sm:col-span-2">环境变量 JSON<textarea name="env" defaultValue={Object.keys(value.env).length ? JSON.stringify(value.env, null, 2) : ""} rows={3} placeholder={'{"TOKEN":"..."}'} className="rounded-xl border border-zinc-300 px-3 py-2 font-mono text-sm font-normal" /></label>
            </> : <>
              <label className="grid gap-2 text-sm font-medium sm:col-span-2">Server URL<input name="url" type="url" required defaultValue={value.url} placeholder="https://example.com/mcp" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal" /></label>
              <label className="grid gap-2 text-sm font-medium sm:col-span-2">认证 Headers JSON<textarea name="headers" defaultValue={Object.keys(value.headers).length ? JSON.stringify(value.headers, null, 2) : ""} rows={3} placeholder={'{"Authorization":"Bearer ..."}'} className="rounded-xl border border-zinc-300 px-3 py-2 font-mono text-sm font-normal" /></label>
            </>}
            <label className="grid gap-2 text-sm font-medium">默认风险等级<select name="risk" defaultValue={value.default_risk_level} className="h-11 rounded-xl border border-zinc-300 bg-white px-3 font-normal"><option value="high">高（推荐）</option><option value="medium">中</option><option value="low">低</option></select></label>
            <label className="grid gap-2 text-sm font-medium">允许的工具<input name="allowed_tools" defaultValue={value.allowed_tools.join(", ")} placeholder="留空表示全部" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal" /></label>
          </div>
          <div aria-live="polite" className="mt-4 min-h-6 text-sm text-red-700">{formError}</div>
          <div className="mt-3 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end"><button type="button" onClick={(event) => testCurrentForm(event.currentTarget.form)} disabled={busy} className="min-h-11 rounded-xl border border-zinc-300 px-5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50">测试连接</button><button type="submit" disabled={busy} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy ? "处理中…" : "保存配置"}</button></div>
        </form>
      )}
    </dialog>
  );
}

export default function McpView() {
  const [items, setItems] = useState<McpServerItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<McpServerInput | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { fetchMcpServers().then(setItems).catch((err) => setError(String(err))).finally(() => setLoading(false)); }, []);
  const filtered = useMemo(() => items.filter((item) => `${item.name} ${item.command} ${item.url}`.toLowerCase().includes(query.toLowerCase())), [items, query]);
  const editValue = (item: McpServerItem): McpServerInput => ({ ...emptyInput, name: item.name, transport: item.transport, command: item.command, args: item.args, url: item.url, enabled: false, default_risk_level: item.default_risk_level, allowed_tools: item.allowed_tools });
  const run = async (id: string, task: () => Promise<void>) => { setBusyId(id); setError(""); setNotice(""); try { await task(); } catch (err) { setError(err instanceof Error ? err.message : "操作失败"); } finally { setBusyId(null); } };

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between"><div><p className="text-sm font-medium text-zinc-500">Agent 能力</p><h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">MCP 服务器</h1><p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-600">连接本地或远程能力服务。已连接工具会直接提供给模型，并继续经过参数校验、风险确认和执行审计。</p></div><input aria-label="搜索 MCP Server" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 MCP 服务器…" className="h-12 w-full rounded-2xl border border-zinc-200 px-4 text-sm lg:w-96" /></div>
        <div className="mt-10 flex flex-wrap items-center gap-3 border-b border-zinc-200 pb-5"><div className="mr-auto"><span className="font-medium">已安装 {items.length}</span><span className="ml-3 text-sm text-zinc-500">已连接 {items.filter((item) => item.connected).length}</span></div><button type="button" onClick={() => void run("refresh", async () => { const rows = await refreshMcpServers(); setItems(rows); setNotice("已热刷新 MCP 配置"); })} className="min-h-11 rounded-xl border border-zinc-200 px-4 text-sm font-medium">↻ 刷新</button><button type="button" onClick={() => setEditing({ ...emptyInput })} className="min-h-11 rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white">＋ 新建</button></div>
        <div className="min-h-10 pt-3 text-sm" aria-live="polite">{error ? <p role="alert" className="text-red-700">{error}</p> : notice ? <p className="text-emerald-700">{notice}</p> : null}</div>
        {loading ? <div className="h-28 animate-pulse rounded-3xl bg-zinc-100 motion-reduce:animate-none" /> : filtered.length ? <div className="overflow-hidden rounded-3xl bg-zinc-100 ring-1 ring-zinc-200">{filtered.map((item) => <article key={item.name} className="border-b border-zinc-200 p-5 last:border-b-0 sm:p-6"><div className="flex flex-col gap-4 sm:flex-row sm:items-start"><div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-white text-xl" aria-hidden="true">⌁</div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{item.name}</h2><span className={`rounded-full px-2 py-0.5 text-xs ${item.status === "connected" ? "bg-emerald-100 text-emerald-800" : item.status === "error" ? "bg-red-100 text-red-800" : "bg-zinc-200 text-zinc-600"}`}>{item.status === "connected" ? "已连接" : item.status === "error" ? "连接失败" : "已关闭"}</span><span className="rounded-full bg-white px-2 py-0.5 text-xs text-zinc-500">{item.transport === "stdio" ? "本地" : "HTTP"}</span></div><p className="mt-1 truncate text-sm text-zinc-600">{item.transport === "stdio" ? [item.command, ...item.args].join(" ") : item.url}</p>{item.tools.length > 0 && <p className="mt-2 text-xs text-zinc-500">工具：{item.tools.join("、")}</p>}{item.error && <p className="mt-2 text-sm text-red-700">{item.error}</p>}</div><div className="flex items-center gap-2"><button type="button" onClick={() => setEditing(editValue(item))} disabled={item.source !== "user"} className="min-h-11 rounded-xl px-3 text-sm hover:bg-white disabled:hidden">编辑</button><button type="button" onClick={() => void run(item.name, async () => { await deleteMcpServer(item.name); setItems((rows) => rows.filter((row) => row.name !== item.name)); setNotice(`${item.name} 已删除`); })} disabled={item.source !== "user" || busyId === item.name} className="min-h-11 rounded-xl px-3 text-sm text-red-700 hover:bg-red-50 disabled:hidden">删除</button><label className="inline-flex min-h-11 cursor-pointer items-center gap-2"><span className="sr-only">{item.enabled ? "关闭" : "启用"} {item.name}</span><input type="checkbox" checked={item.enabled} disabled={item.source !== "user" || busyId === item.name} onChange={() => void run(item.name, async () => { const updated = await updateMcpServer(item.name, !item.enabled); setItems((rows) => rows.map((row) => row.name === item.name ? updated : row)); setNotice(`${item.name} 已${updated.enabled ? "启用" : "关闭"}`); })} className="peer sr-only" /><span aria-hidden="true" className="relative h-7 w-12 rounded-full bg-zinc-300 transition peer-checked:bg-zinc-950 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-zinc-900 after:absolute after:left-1 after:top-1 after:size-5 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5 motion-reduce:after:transition-none" /></label></div></div></article>)}</div> : <div className="rounded-3xl border border-dashed border-zinc-300 px-6 py-16 text-center"><p className="font-medium">尚未配置 MCP Server</p><p className="mt-2 text-sm text-zinc-500">可以添加一个简单的本地 stdio Server 开始测试。</p></div>}
      </div>
      <ServerDialog value={editing} busy={busyId === "dialog"} onClose={() => setEditing(null)} onTest={async (body) => void run("dialog", async () => { const result = await testMcpServer(body); setNotice(`连接成功，发现 ${result.tools.length} 个工具：${result.tools.map((item) => item.name).join("、") || "无"}`); })} onSave={async (body) => void run("dialog", async () => { const saved = await saveMcpServer({ ...body, enabled: false }); setItems((rows) => [...rows.filter((row) => row.name !== saved.name), saved].sort((a, b) => a.name.localeCompare(b.name))); setEditing(null); setNotice(`${saved.name} 已保存，默认处于关闭状态`); })} />
    </main>
  );
}
