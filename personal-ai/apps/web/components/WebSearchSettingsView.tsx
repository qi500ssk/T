"use client";
import { useEffect, useState } from "react";
import { fetchWebSearchSettings, saveWebSearchSettings, testWebSearchSettings, type WebSearchSettings } from "@/lib/api";

export default function WebSearchSettingsView() {
  const [settings, setSettings] = useState<WebSearchSettings | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { fetchWebSearchSettings().then(setSettings).catch(e => setError(String(e))); }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch(e) { setError(e instanceof Error ? e.message : "操作失败"); } finally { setBusy(false); }
  }
  const button = "min-h-11 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-100 disabled:opacity-50";
  return <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white"><div className="mx-auto max-w-5xl px-5 py-10 sm:px-10">
    <h1 className="text-3xl font-bold tracking-tight">联网搜索</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-500">开启后，AI 会根据你的问题判断是否需要搜索或读取网页。普通聊天不必联网。</p>
    <div aria-live="polite" className="mt-5 text-sm">{error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p className="text-emerald-700">{notice}</p>}</div>
    {!settings ? <p className="mt-8 text-sm text-zinc-500">{error ? "配置加载失败，请重新打开此页面。" : "加载中…"}</p> : <>
      <section className="mt-6 rounded-2xl border border-zinc-200 bg-zinc-50 p-5 sm:p-7">
        <div className="flex items-start gap-5"><div className="flex-1"><h2 className="font-medium">允许 AI 联网</h2><p className="mt-2 text-sm leading-6 text-zinc-500">{settings.enabled ? "已开启 · 由 AI 按需使用，回答时注明来源。" : "已关闭 · AI 不会使用内置联网搜索和网页读取工具。"}</p></div><button type="button" role="switch" aria-label="允许 AI 联网" aria-checked={settings.enabled} disabled={busy || (!settings.has_api_key && !key.trim())} onClick={() => void run(async () => { setSettings(await saveWebSearchSettings({ enabled: !settings.enabled, api_key: key.trim() || undefined })); setKey(""); setNotice(settings.enabled ? "联网搜索已关闭。" : "联网搜索已开启，AI 会按需搜索。"); })} className={`mt-1 inline-flex h-7 w-12 shrink-0 items-center rounded-full p-1 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40 ${settings.enabled ? "bg-zinc-950" : "bg-zinc-300"}`}><span className={`size-5 rounded-full bg-white transition-transform motion-reduce:transition-none ${settings.enabled ? "translate-x-5" : ""}`} /></button></div>
      </section>
      <form className="mt-5 space-y-5 rounded-2xl border border-zinc-200 p-5 sm:p-7" onSubmit={e => { e.preventDefault(); void run(async () => { setSettings(await saveWebSearchSettings({api_key:key.trim()})); setKey(""); setNotice("Key 已保存，联网开关保持当前状态。"); }); }}>
        <div className="flex items-center justify-between gap-4"><h2 className="font-medium">Tavily</h2><span className="text-xs text-zinc-500">{settings.has_api_key ? "已保存 Key" : "尚未配置"}</span></div>
        <label className="grid gap-2 text-sm">API Key<input type="password" autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)} maxLength={2000} disabled={busy} placeholder={settings.has_api_key ? "已保存，留空不修改" : "填写你的 Tavily API Key"} className="h-11 rounded-xl border border-zinc-200 px-3 outline-none focus:border-zinc-500 focus:ring-2 focus:ring-zinc-100" /></label>
        <p className="text-xs leading-6 text-zinc-500">Key 保存在本机，保存后不回显。搜索关键词和需要读取的网址会发送给 Tavily。<a href="https://app.tavily.com" target="_blank" rel="noreferrer" className="ml-1 underline underline-offset-4">获取 API Key ↗</a></p>
        <div className="flex flex-wrap gap-3"><button type="submit" disabled={busy || !key.trim()} className={`${button} bg-zinc-950 text-white hover:bg-zinc-800`}>保存 Key</button><button type="button" disabled={busy || (!settings.has_api_key && !key.trim())} onClick={() => void run(async () => { const result = await testWebSearchSettings({api_key:key.trim() || undefined}); setNotice(result.message); })} className={button}>{busy ? "处理中…" : "测试连接"}</button>{settings.has_api_key && <button type="button" disabled={busy} onClick={() => void run(async () => { setSettings(await saveWebSearchSettings({clear_api_key:true})); setKey(""); setNotice("Key 已清除，联网搜索已关闭。"); })} className={`${button} ml-auto text-red-700`}>清除 Key</button>}</div>
        <p className="text-xs leading-5 text-zinc-500">测试会发起一次基础搜索，可能消耗 Tavily 额度；不会自动开启联网。</p>
      </form>
    </>}
  </div></main>;
}
