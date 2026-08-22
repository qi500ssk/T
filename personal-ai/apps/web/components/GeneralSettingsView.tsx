"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  createModelProfile,
  deleteModelProfile,
  fetchAppSettings,
  fetchDirectories,
  setDefaultModelProfile,
  testModelSettings,
  updateAgentSettings,
  updateModelProfile,
  updateWorkspaceSettings,
  type AgentSettings,
  type AppSettings,
  type DirectoryListing,
  type ModelProfile,
  type ModelProfileInput,
  type ModelSettingsInput,
} from "@/lib/api";


export type GeneralSettingsSection = "general" | "model" | "workspace";

const inputClass = "h-11 w-full rounded-xl border border-zinc-300 bg-white px-3 text-sm outline-none transition focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-500";
const textareaClass = "w-full resize-y rounded-xl border border-zinc-300 bg-white px-3 py-3 text-sm leading-6 outline-none transition focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100";

export function FolderDialog({ open, initialPath, onClose, onSelect }: { open: boolean; initialPath: string; onClose: () => void; onSelect: (path: string) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async (path?: string | null) => {
    setLoading(true);
    setError("");
    try {
      setListing(await fetchDirectories(path));
    } catch (err) {
      setError(err instanceof Error ? err.message : "文件夹读取失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      void load(initialPath);
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initialPath]);

  return (
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} onClose={onClose} className="m-auto h-[min(80vh,42rem)] w-[min(94vw,46rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35" aria-labelledby="folder-dialog-title">
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between border-b border-zinc-200 px-6 py-5">
          <div>
            <h2 id="folder-dialog-title" className="text-xl font-bold">选择编码工作区</h2>
            <p className="mt-1 text-sm text-zinc-500">Agent 的编码工具只能访问你选中的文件夹。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-zinc-500 hover:bg-zinc-100" aria-label="关闭">×</button>
        </div>
        <div className="flex items-center gap-2 border-b border-zinc-200 px-6 py-3">
          <button type="button" onClick={() => void load()} className="min-h-10 rounded-xl border border-zinc-200 px-3 text-sm font-medium hover:bg-zinc-50">磁盘</button>
          <button type="button" disabled={!listing?.parent_path || loading} onClick={() => void load(listing?.parent_path)} className="min-h-10 rounded-xl border border-zinc-200 px-3 text-sm font-medium hover:bg-zinc-50 disabled:opacity-40">↑ 上一级</button>
          <p className="min-w-0 flex-1 truncate rounded-xl bg-zinc-100 px-3 py-2.5 font-mono text-xs text-zinc-600" title={listing?.current_path ?? "选择磁盘"}>{listing?.current_path ?? "选择一个磁盘"}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {error && <p role="alert" className="m-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          {loading ? <div className="grid gap-2 p-3"><div className="h-12 animate-pulse rounded-xl bg-zinc-100" /><div className="h-12 animate-pulse rounded-xl bg-zinc-100" /></div> : (
            <ul className="space-y-1">
              {listing?.directories.map((directory) => (
                <li key={directory.path}>
                  <button type="button" onClick={() => void load(directory.path)} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-left text-sm hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900">
                    <span className="text-amber-500" aria-hidden="true">▰</span>
                    <span className="min-w-0 flex-1 truncate">{directory.name}</span>
                    <span className="text-xs text-zinc-400">打开 ›</span>
                  </button>
                </li>
              ))}
              {!loading && listing && listing.directories.length === 0 && <li className="px-4 py-10 text-center text-sm text-zinc-400">这个文件夹中没有子文件夹</li>}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between gap-4 border-t border-zinc-200 px-6 py-4">
          <p className="hidden text-xs text-zinc-500 sm:block">不会上传或读取文件内容</p>
          <div className="ml-auto flex gap-3">
            <button type="button" onClick={onClose} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm font-medium hover:bg-zinc-50">取消</button>
            <button type="button" disabled={!listing?.current_path} onClick={() => listing?.current_path && onSelect(listing.current_path)} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40">选择当前文件夹</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

export default function GeneralSettingsView({ section, onUpdated }: { section: GeneralSettingsSection; onUpdated?: (settings: AppSettings) => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [agent, setAgent] = useState<AgentSettings | null>(null);
  const [model, setModel] = useState<ModelProfileInput | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const [folderOpen, setFolderOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchAppSettings().then((value) => {
      if (cancelled) return;
      setSettings(value);
      setAgent(value.agent);
      const selected = value.models.items.find((item) => item.id === value.models.default_model_id);
      if (selected) {
        setSelectedModelId(selected.id);
        setModel({ name: selected.name, provider: selected.provider === "mock" ? "mock" : "openai-compatible", base_url: selected.base_url, model: selected.model, timeout_seconds: selected.timeout_seconds });
        setApiKeyConfigured(selected.api_key_configured);
      } else {
        setModel({ name: "DeepSeek", provider: "openai-compatible", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", timeout_seconds: 60 });
      }
      setWorkspace(value.workspace.coding_workspace_dir);
    }).catch((err) => setError(err instanceof Error ? err.message : "设置加载失败"));
    return () => { cancelled = true; };
  }, []);

  const preset = useMemo(() => {
    if (model?.provider === "mock") return "mock";
    if (model?.base_url.includes("api.deepseek.com")) return "deepseek";
    if (model?.base_url.includes("localhost:11434") || model?.base_url.includes("127.0.0.1:11434")) return "ollama";
    return "custom";
  }, [model]);

  const finish = (next: AppSettings, message: string) => {
    setSettings(next);
    setNotice(message);
    setError("");
    onUpdated?.(next);
  };

  const run = async (id: string, task: () => Promise<void>) => {
    setBusy(id); setNotice(""); setError("");
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : "保存失败"); } finally { setBusy(""); }
  };

  if (!settings || !agent || !model) return <main className="min-w-0 flex-1 overflow-y-auto bg-white"><div className="mx-auto max-w-5xl p-8 lg:p-14"><div className="h-10 w-48 animate-pulse rounded-xl bg-zinc-100" /><div className="mt-8 h-72 animate-pulse rounded-3xl bg-zinc-100" />{error && <p className="mt-4 text-sm text-red-700">{error}</p>}</div></main>;

  const saveAgent = (event: FormEvent) => { event.preventDefault(); void run("agent", async () => {
    const saved = await updateAgentSettings(agent);
    finish({ ...settings, agent: saved }, "Agent 设定已保存，新对话和后续消息会立即使用");
  }); };

  const modelPayload = (): ModelSettingsInput => ({ model_id: selectedModelId || undefined, provider: model.provider, base_url: model.base_url, model: model.model, timeout_seconds: model.timeout_seconds, api_key: apiKey || undefined, clear_api_key: clearApiKey });
  const profilePayload = (): ModelProfileInput => ({ ...modelPayload(), name: model.name.trim() });
  const selectProfile = (profile: ModelProfile) => {
    setSelectedModelId(profile.id);
    setModel({ name: profile.name, provider: profile.provider === "mock" ? "mock" : "openai-compatible", base_url: profile.base_url, model: profile.model, timeout_seconds: profile.timeout_seconds });
    setApiKey(""); setClearApiKey(false); setApiKeyConfigured(profile.api_key_configured); setNotice(""); setError("");
  };
  const refreshSettings = async (message: string, preferredId?: string | null) => {
    const next = await fetchAppSettings();
    const profile = next.models.items.find((item) => item.id === (preferredId ?? selectedModelId)) ?? next.models.items.find((item) => item.id === next.models.default_model_id);
    if (profile) selectProfile(profile);
    finish(next, message);
  };
  const saveModel = () => void run("model", async () => {
    const saved = selectedModelId
      ? await updateModelProfile(selectedModelId, profilePayload())
      : await createModelProfile(profilePayload());
    setApiKey(""); setClearApiKey(false);
    await refreshSettings(selectedModelId ? "模型配置已更新" : "模型配置已保存，可在聊天框中选择", saved.id);
  });
  const newProfile = () => {
    setSelectedModelId(null);
    setModel({ name: "", provider: "openai-compatible", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", timeout_seconds: 60 });
    setApiKey(""); setClearApiKey(false); setApiKeyConfigured(false); setNotice(""); setError("");
  };

  const choosePreset = (value: string) => {
    if (value === "deepseek") setModel({ ...model, provider: "openai-compatible", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" });
    else if (value === "ollama") setModel({ ...model, provider: "openai-compatible", base_url: "http://localhost:11434/v1", model: "qwen2.5:7b" });
    else setModel({ ...model, provider: "openai-compatible" });
  };

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        {section === "general" && (
          <form onSubmit={saveAgent}>
            <p className="text-sm font-medium text-zinc-500">基础设置</p>
            <h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">Agent 设定</h1>
            <p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-600">定义它是谁、怎样说话以及需要长期遵守的行为偏好。这相当于你的个人 System Prompt。Mock 只展示名称，完整性格需要真实模型理解。</p>
            <section className="mt-9 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7">
              <div className="flex items-center gap-4 rounded-2xl bg-white p-4">
                <div className="grid size-12 place-items-center rounded-2xl bg-zinc-950 text-lg font-bold text-white">{agent.name.slice(0, 1).toUpperCase()}</div>
                <div className="min-w-0"><h2 className="truncate font-semibold">{agent.name}</h2><p className="truncate text-sm text-zinc-500">{agent.role}</p></div>
                <div className="ml-auto hidden flex-wrap justify-end gap-2 sm:flex"><span className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600">{agent.tone}</span><span className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600">{agent.verbosity}</span></div>
              </div>
              <div className="mt-6 grid gap-5 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">Agent 名称<input required maxLength={80} value={agent.name} onChange={(e) => setAgent({ ...agent, name: e.target.value })} className={inputClass} placeholder="小派" /></label>
                <label className="grid gap-2 text-sm font-medium">扮演角色<input required maxLength={160} value={agent.role} onChange={(e) => setAgent({ ...agent, role: e.target.value })} className={inputClass} placeholder="我的个人 AI 助手" /></label>
                <label className="grid gap-2 text-sm font-medium">默认语言<select value={agent.language} onChange={(e) => setAgent({ ...agent, language: e.target.value })} className={inputClass}><option value="zh-CN">简体中文</option><option value="zh-TW">繁体中文</option><option value="en-US">English</option><option value="ja-JP">日本語</option></select></label>
                <label className="grid gap-2 text-sm font-medium">语气<input required value={agent.tone} onChange={(e) => setAgent({ ...agent, tone: e.target.value })} className={inputClass} placeholder="温柔、自然、像熟悉的朋友" /></label>
                <label className="grid gap-2 text-sm font-medium">回答长度<select value={agent.verbosity} onChange={(e) => setAgent({ ...agent, verbosity: e.target.value })} className={inputClass}><option>简洁</option><option>适中</option><option>详细</option><option>根据问题自动调整</option></select></label>
                <label className="grid gap-2 text-sm font-medium">幽默程度<select value={agent.humor} onChange={(e) => setAgent({ ...agent, humor: e.target.value })} className={inputClass}><option>关闭</option><option>少量</option><option>适度</option><option>活泼</option></select></label>
                <label className="grid gap-2 text-sm font-medium">正式程度<input required value={agent.formality} onChange={(e) => setAgent({ ...agent, formality: e.target.value })} className={inputClass} placeholder="轻松但不失专业" /></label>
                <label className="grid gap-2 text-sm font-medium">主动程度<input required value={agent.proactivity} onChange={(e) => setAgent({ ...agent, proactivity: e.target.value })} className={inputClass} placeholder="低，不主动打扰" /></label>
                <label className="grid gap-2 text-sm font-medium sm:col-span-2">自定义提示词<textarea rows={9} maxLength={12000} value={agent.custom_instructions} onChange={(e) => setAgent({ ...agent, custom_instructions: e.target.value })} className={textareaClass} placeholder="例如：称呼我为小王；不要使用过多表情；给建议时先说结论……" /><span className="flex justify-between text-xs font-normal text-zinc-500"><span>只控制回答行为，不能绕过工具权限和审批。</span><span>{agent.custom_instructions.length}/12000</span></span></label>
              </div>
            </section>
            <div className="mt-6 flex justify-end"><button type="submit" disabled={busy === "agent"} className="min-h-11 rounded-xl bg-zinc-950 px-6 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy === "agent" ? "保存中…" : "保存 Agent 设定"}</button></div>
          </form>
        )}

        {section === "model" && (
          <div>
            <p className="text-sm font-medium text-zinc-500">基础设置</p><h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">模型设置</h1><p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-600">保存多个模型配置，设置一个全局默认模型，也可以在每次聊天前临时选择其他模型；完整的 .env 模型配置始终具有最高优先级。</p>
            {settings.model_control.locked && <div className="mt-6 rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900" role="status"><strong>环境模型已锁定：</strong>当前所有聊天固定使用 <span className="font-mono">{settings.model.model}</span>。下方配置可以继续管理，但删除 .env 中的 LLM_* 配置并重启前不会生效。</div>}
            {settings.model_control.error && <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-800" role="alert"><strong>.env 模型配置不完整：</strong>{settings.model_control.error}。修正或删除相关 LLM_* 配置并重启后才能聊天。</div>}
            <div className="mt-9 grid items-start gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
              <aside className="rounded-3xl border border-zinc-200 bg-white p-3" aria-label="已保存模型">
                <div className="flex items-center justify-between px-2 py-2"><div><h2 className="font-semibold">已保存模型</h2><p className="mt-0.5 text-xs text-zinc-500">{settings.models.items.length} 个配置</p></div><button type="button" onClick={newProfile} className="min-h-10 rounded-xl bg-zinc-950 px-3 text-sm font-medium text-white hover:bg-zinc-800">＋ 新建</button></div>
                <div className="mt-2 space-y-2">
                  {settings.models.items.map((profile) => <div key={profile.id} className={`rounded-2xl border p-2 ${profile.id === selectedModelId ? "border-zinc-900 bg-zinc-50" : "border-zinc-200"}`}>
                    <button type="button" onClick={() => selectProfile(profile)} className="w-full rounded-xl px-2 py-2 text-left hover:bg-white focus-visible:outline-2 focus-visible:outline-zinc-900"><span className="flex items-center gap-2"><strong className="min-w-0 flex-1 truncate text-sm">{profile.name}</strong>{profile.is_default && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">默认</span>}</span><span className="mt-1 block truncate text-xs text-zinc-500">{profile.model || "未命名模型"}</span></button>
                    <div className="flex gap-1 px-1 pb-1">{!profile.is_default && <button type="button" disabled={busy !== ""} onClick={() => void run("default", async () => { await setDefaultModelProfile(profile.id); await refreshSettings(`${profile.name} 已设为默认模型`, profile.id); })} className="min-h-9 rounded-lg px-2 text-xs font-medium text-zinc-600 hover:bg-white">设为默认</button>}<button type="button" disabled={busy !== "" || profile.is_default} onClick={() => { if (window.confirm(`删除模型配置“${profile.name}”？`)) void run("delete", async () => { await deleteModelProfile(profile.id); await refreshSettings("模型配置已删除", null); }); }} className="ml-auto min-h-9 rounded-lg px-2 text-xs text-red-600 hover:bg-red-50 disabled:text-zinc-300" title={profile.is_default ? "请先把另一个模型设为默认" : "删除配置"}>删除</button></div>
                  </div>)}
                  {settings.models.items.length === 0 && <div className="rounded-2xl border border-dashed border-zinc-300 px-4 py-8 text-center text-sm text-zinc-500">还没有可用模型<br /><button type="button" onClick={newProfile} className="mt-3 font-medium text-zinc-950 underline underline-offset-4">创建第一个配置</button></div>}
                </div>
              </aside>
              <section className="rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7" aria-label={selectedModelId ? "编辑模型配置" : "新建模型配置"}>
                <div className="mb-6"><h2 className="text-lg font-semibold">{selectedModelId ? "编辑模型配置" : "新建模型配置"}</h2><p className="mt-1 text-xs leading-5 text-zinc-500">云端模型必须填写 API Key；localhost 上的 Ollama 等本地服务可以免 Key。</p></div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <label className="grid gap-2 text-sm font-medium sm:col-span-2">配置名称<input required maxLength={80} value={model.name} onChange={(e) => setModel({ ...model, name: e.target.value })} className={inputClass} placeholder="例如：DeepSeek 日常对话" /></label>
                  <label className="grid gap-2 text-sm font-medium sm:col-span-2">配置模板<select value={preset === "mock" ? "custom" : preset} onChange={(e) => choosePreset(e.target.value)} className={inputClass}><option value="deepseek">DeepSeek API</option><option value="ollama">Ollama 本地模型</option><option value="custom">其他 OpenAI 兼容服务</option></select></label>
                  <label className="grid gap-2 text-sm font-medium sm:col-span-2">API 地址<input value={model.base_url} onChange={(e) => setModel({ ...model, base_url: e.target.value })} className={inputClass} placeholder="https://api.example.com/v1" /></label>
                  <label className="grid gap-2 text-sm font-medium">模型名称<input value={model.model} onChange={(e) => setModel({ ...model, model: e.target.value })} className={inputClass} placeholder="deepseek-chat" /></label>
                  <label className="grid gap-2 text-sm font-medium">请求超时（秒）<input type="number" min={5} max={300} value={model.timeout_seconds} onChange={(e) => setModel({ ...model, timeout_seconds: Number(e.target.value) })} className={inputClass} /></label>
                  <label className="grid gap-2 text-sm font-medium sm:col-span-2">API Key<input type="password" autoComplete="off" disabled={clearApiKey} value={apiKey} onChange={(e) => { setApiKey(e.target.value); setClearApiKey(false); }} className={inputClass} placeholder={apiKeyConfigured ? "已安全保存；留空表示不修改" : "云端模型必须填写；本地服务可留空"} /><span className="flex flex-wrap items-center justify-between gap-2 text-xs font-normal text-zinc-500"><span>Key 只保存在本机运行时配置，不返回浏览器，也不写入 Git。</span>{apiKeyConfigured && <label className="inline-flex items-center gap-2"><input type="checkbox" checked={clearApiKey} onChange={(e) => setClearApiKey(e.target.checked)} />清除已保存的 Key</label>}</span></label>
                </div>
                <div className="mt-6 flex flex-wrap justify-end gap-3"><button type="button" disabled={busy !== ""} onClick={() => void run("test", async () => setNotice((await testModelSettings(modelPayload())).message))} className="min-h-11 rounded-xl border border-zinc-300 bg-white px-5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50">{busy === "test" ? "测试中…" : "测试连接"}</button><button type="button" disabled={busy !== "" || !model.name.trim()} onClick={saveModel} className="min-h-11 rounded-xl bg-zinc-950 px-6 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy === "model" ? "保存中…" : selectedModelId ? "保存修改" : "保存配置"}</button></div>
              </section>
            </div>
          </div>
        )}

        {section === "workspace" && (
          <div>
            <p className="text-sm font-medium text-zinc-500">基础设置</p><h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">工作区</h1><p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-600">选择 Developer Tools 可以查看和修改的唯一项目文件夹。更换后立即生效，不需要重启。</p>
            <section className="mt-9 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7"><label className="grid gap-2 text-sm font-medium">编码工作区<div className="flex flex-col gap-3 sm:flex-row"><input value={workspace} onChange={(e) => setWorkspace(e.target.value)} className={`${inputClass} font-mono`} placeholder="E:\\Projects\\my-project" /><button type="button" onClick={() => setFolderOpen(true)} className="min-h-11 shrink-0 rounded-xl border border-zinc-300 bg-white px-5 text-sm font-medium hover:bg-zinc-50">浏览文件夹…</button></div><span className="text-xs font-normal leading-5 text-zinc-500">只有开启 Developer Tools 插件后，Agent 才能使用此目录中的编码工具。</span></label><div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900"><strong>权限边界：</strong>敏感文件、依赖目录、符号链接和工作区外路径仍会被拒绝；切换目录不会自动开启编码插件。</div></section>
            <div className="mt-6 flex justify-end"><button type="button" disabled={busy === "workspace"} onClick={() => void run("workspace", async () => { const saved = await updateWorkspaceSettings(workspace); setWorkspace(saved.coding_workspace_dir); finish({ ...settings, workspace: saved }, "编码工作区已保存并立即生效"); })} className="min-h-11 rounded-xl bg-zinc-950 px-6 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy === "workspace" ? "保存中…" : "保存工作区"}</button></div>
            <FolderDialog open={folderOpen} initialPath={workspace} onClose={() => setFolderOpen(false)} onSelect={(path) => { setWorkspace(path); setFolderOpen(false); }} />
          </div>
        )}

        <div className="min-h-12 pt-5 text-sm" aria-live="polite">{error ? <p role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-red-700">{error}</p> : notice ? <p className="rounded-xl bg-emerald-50 px-4 py-3 text-emerald-700">{notice}</p> : null}</div>
      </div>
    </main>
  );
}
