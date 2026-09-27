"use client";
import { useState } from "react";
import SelectMenu from "@/components/SelectMenu";
import { importMcpServers, saveMcpServer, testMcpServer, type McpServerInput, type McpServerItem } from "@/lib/api";
const blank: McpServerInput = { name: "", transport: "stdio", command: "", args: [], url: "", env: {}, headers: {}, enabled: false, timeout_ms: 30000, default_risk_level: "high", allowed_tools: [], tool_risk_levels: {} };
function entries(text: string): McpServerInput[] {
  const parsed = JSON.parse(text);
  const rows = parsed?.mcpServers ?? parsed?.mcp_servers ?? parsed;
  if (!rows || Array.isArray(rows) || typeof rows !== "object" || !Object.keys(rows).length) throw new Error("请提供以服务器名称为键的 JSON 对象");
  return Object.entries(rows).map(([name, value]) => {
    if (!value || Array.isArray(value) || typeof value !== "object") throw new Error(`${name} 配置必须是对象`);
    const raw = value as Record<string, unknown>;
    const { type, ...rest } = raw;
    const unknown = Object.keys(rest).filter(key => !(key in blank));
    if (unknown.length) throw new Error(`不支持的字段：${unknown.join("、")}`);
    const transport = type ?? raw.transport ?? (raw.url ? "streamable_http" : "stdio");
    const result = { ...blank, ...rest, name, transport: transport === "http" ? "streamable_http" : transport, enabled: false } as McpServerInput;
    if (!["stdio", "sse", "streamable_http"].includes(result.transport) || !Array.isArray(result.args) || result.args.some(a => typeof a !== "string") || !Array.isArray(result.allowed_tools)) throw new Error("传输方式或参数格式无效");
    return result;
  });
}
export default function McpServerEditor({ initial, importing, onClose, onSaved }: { initial?: McpServerItem; importing: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const [value, setValue] = useState<McpServerInput>(() => initial ? { ...blank, name: initial.name, transport: initial.transport, command: initial.command, args: initial.args, url: initial.url, timeout_ms: initial.timeout_ms ?? 30000, default_risk_level: initial.default_risk_level, allowed_tools: initial.allowed_tools, tool_risk_levels: initial.tool_risk_levels } : { ...blank });
  const [mode, setMode] = useState(importing ? "json" : "form");
  const [json, setJson] = useState('{\n  "my-mcp-server": {\n    "type": "stdio",\n    "command": "",\n    "args": []\n  }\n}');
  const [env, setEnv] = useState("");
  const [headers, setHeaders] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const field = "w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-200 disabled:opacity-50";
  const button = "min-h-11 rounded-xl border border-zinc-200 px-4 text-sm disabled:opacity-50";
  function map(text: string) { const parsed = text.trim() ? JSON.parse(text) : {}; if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || Object.values(parsed).some(v => typeof v !== "string")) throw new Error("环境变量和请求头必须是字符串键值 JSON 对象"); return parsed; }
  function body() { return { ...value, args: value.args.filter(a => a !== ""), allowed_tools: value.allowed_tools.map(t => t.trim()).filter(Boolean), env: map(env), headers: map(headers) }; }
  function single() { const rows = entries(json); if (rows.length !== 1) throw new Error("多个服务器请使用导入"); if (initial && rows[0].name !== initial.name) throw new Error("编辑时不能更改服务器名称"); return rows[0]; }
  function changeMode(next: string) {
    try { setError(""); if (next === "json") { const { name, ...raw } = body(); setJson(JSON.stringify({ [name || "my-mcp-server"]: raw }, null, 2)); } else { const nextValue = single(); setValue(nextValue); setEnv(JSON.stringify(nextValue.env, null, 2)); setHeaders(JSON.stringify(nextValue.headers, null, 2)); } setMode(next); } catch (e) { setError(String(e)); }
  }
  async function act(test: boolean) {
    setBusy(true); setError(""); setResult("");
    try {
      if (importing) { await importMcpServers(JSON.parse(json)); await onSaved(); return; }
      const data = mode === "json" ? single() : body();
      if (test) { const response = await testMcpServer(data); setResult(`连接成功，发现 ${response.tools.length} 个工具：${response.tools.map(t => t.name).join("、") || "无"}`); }
      else { await saveMcpServer({ ...data, enabled: false }); await onSaved(); }
    } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); } finally { setBusy(false); }
  }
  return <>
    <nav className="mb-10 flex items-center gap-3 text-sm text-zinc-500"><button disabled={busy} onClick={onClose} className="min-h-11 hover:text-zinc-950">MCP 服务器</button><span>›</span><span className="text-zinc-900">{importing ? "导入配置" : initial ? "编辑服务器" : "新建服务器"}</span></nav>
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-semibold">{importing ? "导入 MCP 服务器" : initial ? "编辑 MCP 服务器" : "新建 MCP 服务器"}</h1><p className="mt-2 text-sm text-zinc-500">保存后返回列表，服务器保持关闭，由你手动启用。</p></div>{!importing && <div className="flex rounded-full bg-zinc-100 p-1" aria-label="配置编辑方式">{["form", "json"].map(tab => <button key={tab} disabled={busy} aria-pressed={mode === tab} onClick={() => mode !== tab && changeMode(tab)} className={`min-h-10 rounded-full px-4 text-sm ${mode === tab ? "bg-white shadow-sm" : "text-zinc-500"}`}>{tab === "form" ? "表单" : "JSON"}</button>)}</div>}</div>
    <form onSubmit={e => { e.preventDefault(); void act(false); }} className="rounded-2xl border border-zinc-200 bg-zinc-50/60 p-5 sm:p-7">
      <fieldset disabled={busy} className="space-y-5"><div className="flex justify-end text-xs text-zinc-500">作用域：本机用户 · 协议版本：自动协商</div>
      {mode === "json" ? <label className="grid gap-3 text-sm">完整配置<textarea aria-label="完整配置" value={json} onChange={e => setJson(e.target.value)} rows={16} spellCheck={false} className={`${field} font-mono`} /><span className="text-xs leading-6 text-zinc-500">支持 {`{"server-name": {...}}`} 或 {`{"mcpServers": {"server-name": {...}}}`}。导入不会覆盖同名配置，所有服务器默认关闭。</span></label> : <>
        <div className="grid gap-5 sm:grid-cols-2"><label className="grid gap-2 text-sm">名称<input required pattern="[A-Za-z0-9_-]+" maxLength={40} readOnly={Boolean(initial)} value={value.name} onChange={e => setValue({ ...value, name: e.target.value })} placeholder="my-mcp-server" className={field} /></label><label className="grid gap-2 text-sm">类型<SelectMenu disabled={busy} value={value.transport} onChange={transport => setValue({ ...value, transport: transport as McpServerInput["transport"] })} options={[{ value: "stdio", label: "stdio（本地命令）" }, { value: "streamable_http", label: "HTTP（Streamable HTTP）" }, { value: "sse", label: "SSE（兼容旧服务）" }]} ariaLabel="传输方式" className={field} /></label><label className="grid gap-2 text-sm">连接超时时间（ms）<input type="number" min={1000} max={300000} step={1} required value={value.timeout_ms} onChange={e => setValue({ ...value, timeout_ms: Number(e.target.value) })} className={field} /></label></div>
        {value.transport === "stdio" ? <><label className="grid gap-2 text-sm">命令<input required value={value.command} onChange={e => setValue({ ...value, command: e.target.value })} placeholder="npx / uvx / python / 可执行文件完整路径" className={field} /></label><label className="grid gap-2 text-sm">参数（每行一个，含空格的路径也放在同一行）<textarea value={value.args.join("\n")} onChange={e => setValue({ ...value, args: e.target.value.split("\n") })} rows={3} placeholder={"-y\n包名"} className={`${field} font-mono`} /></label><details><summary className="cursor-pointer text-sm text-zinc-600">环境变量（可选）{initial?.env_keys.length ? ` · 已配置 ${initial.env_keys.join("、")}` : ""}</summary><textarea aria-label="环境变量 JSON" value={env} onChange={e => setEnv(e.target.value)} rows={4} placeholder={'{"API_KEY": "你的密钥"}'} className={`${field} mt-3 font-mono`} /></details></> : <><label className="grid gap-2 text-sm">URL<input required type="url" value={value.url} onChange={e => setValue({ ...value, url: e.target.value })} placeholder={value.transport === "sse" ? "https://mcp.example.com/sse" : "https://mcp.example.com/mcp"} className={field} /></label><details><summary className="cursor-pointer text-sm text-zinc-600">请求头（可选）{initial?.header_keys.length ? ` · 已配置 ${initial.header_keys.join("、")}` : ""}</summary><textarea aria-label="请求头 JSON" value={headers} onChange={e => setHeaders(e.target.value)} rows={4} placeholder={'{"Authorization": "Bearer 你的密钥"}'} className={`${field} mt-3 font-mono`} /></details></>}
        {initial && <p className="text-xs leading-6 text-zinc-500">认证信息不回显，留空保留原值；更改地址或启动命令及参数后需重新填写对应认证信息。</p>}
        <details><summary className="cursor-pointer text-sm text-zinc-600">工具权限（高级）</summary><div className="mt-4 grid gap-4 sm:grid-cols-2"><label className="grid gap-2 text-sm">默认风险<SelectMenu disabled={busy} value={value.default_risk_level} onChange={risk => setValue({ ...value, default_risk_level: risk as McpServerInput["default_risk_level"] })} options={[{ value: "high", label: "高（推荐）" }, { value: "medium", label: "中" }, { value: "low", label: "低" }]} ariaLabel="默认风险等级" className={field} /></label><label className="grid gap-2 text-sm">允许的工具（逗号分隔）<input value={value.allowed_tools.join(",")} onChange={e => setValue({ ...value, allowed_tools: e.target.value.split(",") })} placeholder="留空表示全部" className={field} /></label></div><p className="mt-3 text-xs text-zinc-500">单个工具的风险规则可在 JSON 中设置；切换编辑方式会保留这些规则。</p></details>
      </>}
      <p className="text-xs leading-6 text-zinc-500">测试连接会实际启动本地命令或访问远程服务。npx、uvx 等命令可能下载依赖。</p>
      <div aria-live="polite">{error && <p role="alert" className="break-all text-sm text-red-700">{error}</p>}{result && <p className="break-all text-sm text-emerald-700">{result}</p>}</div>
      <div className="flex flex-wrap justify-end gap-3">{!importing && <button type="button" className={button} onClick={() => void act(true)}>测试连接</button>}<button type="button" className={button} onClick={onClose}>取消</button><button type="submit" className={`${button} bg-zinc-950 text-white`}>{busy ? "处理中…" : importing ? "导入并保存" : "保存配置"}</button></div>
      </fieldset>
    </form>
  </>;
}
