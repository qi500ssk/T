"use client";

import { useEffect, useRef, useState } from "react";
import { req } from "@/lib/api";
import SelectMenu from "@/components/SelectMenu";

type Status = {
  provider: string; model: string; dimension: number; base_url: string; has_api_key: boolean;
  request_dimensions: boolean; semantic_ready: boolean; active_model: string; notice: string;
  cache_dir: string; model_path: string; query_instruction: string; retrieval_mode: string;
  models: { id: string; name: string; dimension: number; size: string; language: string; cached_path: string | null }[];
  job: { status: string; processed: number; total: number; error?: string };
};
type LocalModel = { path: string; name: string; dimension: number; runtime_ready: boolean };
const field = "w-full rounded-xl border border-zinc-300 bg-white px-3 py-2 text-sm focus:outline-2 focus:outline-zinc-700";
const defaultModel = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2";

export default function RetrievalSettingsView() {
  const [status, setStatus] = useState<Status | null>(null);
  const [provider, setProvider] = useState("fastembed");
  const [model, setModel] = useState(defaultModel);
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [key, setKey] = useState("");
  const [dimension, setDimension] = useState(1536);
  const [dimensions, setDimensions] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modelPath, setModelPath] = useState("");
  const [queryInstruction, setQueryInstruction] = useState("");
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [inspected, setInspected] = useState<LocalModel | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const downloadDialog = useRef<HTMLDialogElement>(null);
  const selectedModel = status?.models.find((item) => item.id === model);
  const busy = submitting || !!status && ["preparing", "indexing"].includes(status.job.status);

  useEffect(() => {
    let stopped = false;
    req<Status>("/api/settings/retrieval").then((value) => {
      if (stopped) return;
      setStatus(value);
      const supported = ["fastembed", "local", "keyword", "openai-compatible"].includes(value.provider);
      setProvider(supported ? value.provider : "fastembed");
      setModel(supported ? value.model : defaultModel);
      setBaseUrl(value.base_url || "https://api.openai.com/v1");
      setDimension(value.provider === "openai-compatible" ? value.dimension : 1536);
      setDimensions(value.request_dimensions);
      setModelPath(value.model_path || ""); setQueryInstruction(value.query_instruction || "");
    }).catch((reason) => { if (!stopped) setError(String(reason)); });
    return () => { stopped = true; };
  }, []);

  useEffect(() => {
    if (provider !== "local") return;
    let stopped = false;
    req<{models: LocalModel[]}>("/api/settings/retrieval/local-models").then((value) => {
      if (!stopped) setLocalModels(value.models);
    }).catch((reason) => { if (!stopped) setError(String(reason)); });
    return () => { stopped = true; };
  }, [provider]);

  useEffect(() => {
    if (confirming) downloadDialog.current?.showModal();
    else downloadDialog.current?.close();
  }, [confirming]);

  useEffect(() => {
    if (!busy) return;
    let stopped = false;
    const timer = setInterval(() => {
      req<Status>("/api/settings/retrieval").then((value) => { if (!stopped) setStatus(value); })
        .catch((reason) => { if (!stopped) setError(String(reason)); });
    }, 1500);
    return () => { stopped = true; clearInterval(timer); };
  }, [busy]);

  async function save(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if (provider === "fastembed" && !selectedModel?.cached_path) { setConfirming(true); return; }
    await submit(false);
  }

  async function inspect(path: string) {
    setInspecting(true); setError(""); setInspected(null);
    try {
      const value = await req<LocalModel>("/api/settings/retrieval/inspect-local", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({path}),
      });
      setInspected(value); setModelPath(value.path);
      if (/bge.*zh/i.test(value.name)) setQueryInstruction("为这个句子生成表示以用于检索相关文章：");
    } catch (reason) { setError(String(reason)); }
    finally { setInspecting(false); }
  }

  async function submit(download: boolean) {
    setConfirming(false); setSubmitting(true); setError("");
    try {
      const value = await req<Status>("/api/settings/retrieval", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model, base_url: baseUrl, api_key: key || null,
          dimension, request_dimensions: dimensions, download, model_path: modelPath, query_instruction: queryInstruction }),
      });
      setStatus(value); setKey("");
    } catch (reason) { setError(String(reason)); }
    finally { setSubmitting(false); }
  }

  return <main className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-white p-5 sm:p-8">
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold">知识与记忆检索</h1>
      <p className="mt-2 text-sm leading-6 text-zinc-500">向量模型为检索增加语义匹配，不会关闭关键词检索。知识库启用模型后使用 BM25 + 向量检索，通过 RRF 融合排序。</p>
      <div className="my-6 rounded-2xl border border-zinc-200 bg-zinc-50 p-4" role="status">
        <p className="text-sm font-medium">{status ? status.retrieval_mode === "hybrid" ? "当前生效：混合检索（BM25 + 向量）" : "当前生效：关键词检索（BM25）" : "正在读取配置…"}</p>
        <p className="mt-2 text-sm text-zinc-600">好友记忆结合关键词、语义相关性与核心记忆优先，不直接套用文档的 BM25 排序。</p>
        {status?.semantic_ready && <p className="mt-2 break-all text-xs text-zinc-500">当前模型：{status.provider === "local" ? status.model_path : status.model}</p>}
        {status?.notice && <p className="mt-2 text-sm text-zinc-600">{status.notice}</p>}
        {busy && <p className="mt-2 text-sm">{status?.job.status === "indexing" ? `正在重建：${status.job.processed} / ${status.job.total}` : "正在准备、下载或测试模型，请稍候…"}</p>}
        {status?.job.status === "completed" && <p className="mt-2 text-sm text-emerald-700">配置与索引已更新，原始资料和角色记忆保留。</p>}
        {status?.job.error && <p className="mt-2 text-sm text-red-700">{status.job.error}</p>}
      </div>
      <form onSubmit={save} className="space-y-5">
        <fieldset disabled={busy || !status || inspecting} className="space-y-5 disabled:opacity-60">
          <label className="block text-sm font-medium">向量模型来源<SelectMenu ariaLabel="向量模型来源" value={provider} onChange={(next) => {
            setProvider(next);
            setModel(next === "openai-compatible" ? "text-embedding-3-small" : defaultModel);
          }} className={`${field} mt-2 min-h-11 font-normal`} disabled={busy || !status || inspecting} options={[
            { value: "fastembed", label: "下载或复用缓存模型 · 混合检索" },
            { value: "local", label: "使用已有模型文件夹 · 混合检索" },
            { value: "keyword", label: "不使用向量模型 · 仅关键词检索" },
            { value: "openai-compatible", label: "在线 Embedding 服务 · 混合检索" },
          ]} /></label>
          {provider === "fastembed" && <>
            <label className="block text-sm font-medium">本地模型<SelectMenu ariaLabel="本地模型" value={model} onChange={setModel} className={`${field} mt-2 min-h-11 font-normal`} disabled={busy || !status || inspecting}
              options={(status?.models ?? []).map((item) => ({ value: item.id, label: `${item.name} · ${item.size}${item.cached_path ? " · 已下载" : " · 待下载"}` }))} /></label>
            <div className="rounded-xl bg-zinc-50 p-3 text-sm leading-6 text-zinc-600"><p>{selectedModel?.cached_path ? "已发现缓存，直接加载现有文件，不联网补下载。" : "尚未下载。点击下载按钮后需再次确认，选择模型本身不会下载。"}</p><p className="mt-2">下载目录：</p><p className="break-all font-mono text-xs">{status?.cache_dir}</p>{selectedModel?.cached_path && <><p className="mt-2">当前模型文件夹：</p><p className="break-all font-mono text-xs">{selectedModel.cached_path}</p></>}</div>
            <p className="text-sm leading-6 text-zinc-500">多语言 MiniLM 适合中文及多语言资料；MiniLM L6 主要适合英文。显示体积是下载参考值。</p>
          </>}
          {provider === "local" && <>
            {localModels.length > 0 && <label className="block text-sm font-medium">检测到的已有模型<SelectMenu ariaLabel="检测到的已有模型" className={`${field} mt-2 min-h-11 font-normal`} disabled={busy || !status || inspecting} value={localModels.some((item) => item.path === modelPath) ? modelPath : ""} onChange={(value) => { if (value) { setModelPath(value); void inspect(value); } }} options={[{ value: "", label: "选择一个本机模型" }, ...localModels.map((item) => ({ value: item.path, label: `${item.name} · ${item.dimension} 维` }))]} /></label>}
            <label className="block text-sm font-medium">已有模型文件夹<input value={modelPath} onChange={(event) => { setModelPath(event.target.value); setInspected(null); }} required placeholder="粘贴模型文件夹的完整路径，支持 ModelScope 快照目录" className={`${field} mt-2`} /></label>
            <button type="button" className="min-h-10 rounded-xl border border-zinc-300 px-4 text-sm hover:bg-zinc-50" disabled={!modelPath} onClick={() => void inspect(modelPath)}>{inspecting ? "正在检查…" : "检查目录"}</button>
            {inspected && <div className="rounded-xl bg-zinc-50 p-3 text-sm leading-6" role="status"><p>已识别：{inspected.name} · {inspected.dimension} 维</p><p className="mt-1 break-all font-mono text-xs">{inspected.path}</p>{!inspected.runtime_ready && <p className="mt-2 text-amber-800">当前安装缺少已有模型运行组件，需要安装 legacy-embedding 可选依赖并重启。此操作不会自动安装依赖。</p>}</div>}
            <label className="block text-sm font-medium">检索问题前缀（可选）<input value={queryInstruction} onChange={(event) => setQueryInstruction(event.target.value)} maxLength={300} className={`${field} mt-2`} /></label>
            <p className="text-sm leading-6 text-zinc-500">原地读取已有的 Sentence Transformers 模型（如 BGE Small / Large），自动识别维度。支持包含 config.json、model.safetensors、tokenizer.json 和 modules.json 的完整目录；不会复制模型、补下载文件或执行自定义模型代码。</p>
          </>}
          {provider === "openai-compatible" && <>
            <label className="block text-sm font-medium">服务地址<input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required className={`${field} mt-2`} /></label>
            <label className="block text-sm font-medium">模型名称<input value={model} onChange={(event) => setModel(event.target.value)} required className={`${field} mt-2`} /></label>
            <label className="block text-sm font-medium">API Key<input type="password" autoComplete="new-password" value={key} onChange={(event) => setKey(event.target.value)} placeholder={status?.has_api_key ? "已保存，留空保持；更换服务地址需重新填写" : "填写服务提供的密钥"} className={`${field} mt-2`} /></label>
            <label className="block text-sm font-medium">向量维度<input type="number" min={1} max={4096} value={dimension} onChange={(event) => setDimension(Number(event.target.value))} required className={`${field} mt-2`} /></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={dimensions} onChange={(event) => setDimensions(event.target.checked)} />向接口传递自定义维度（服务需支持）</label>
            <p className="text-sm leading-6 text-zinc-500">text-embedding-3-small 默认维度为 1536。保存并重建会把资料与记忆文本发送给所选服务，可能产生 API 费用。</p>
          </>}
          <p className="text-sm leading-6 text-zinc-500">保存前请结束正在运行的任务。模型会先测试再重建索引；更新期间暂停业务请求，失败时保留旧配置。</p>
          <button className="min-h-11 rounded-xl bg-zinc-900 px-5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50" type="submit" disabled={provider === "local" && (!inspected || !inspected.runtime_ready || inspected.path !== modelPath)}>{busy ? "正在更新…" : provider === "fastembed" ? selectedModel?.cached_path ? "使用已下载模型并重建索引" : "下载并启用…" : provider === "local" ? "使用此目录并重建索引" : "测试、保存并重建索引"}</button>
        </fieldset>
      </form>
      {error && <p className="mt-4 text-sm text-red-700" role="alert">{error}</p>}
      <dialog ref={downloadDialog} onCancel={(event) => { event.preventDefault(); setConfirming(false); }} onClose={() => setConfirming(false)} aria-labelledby="download-model-title" className="m-auto w-[min(92vw,34rem)] rounded-2xl bg-white p-6 text-zinc-900 shadow-xl backdrop:bg-black/35">
        <h2 id="download-model-title" className="text-lg font-semibold">确认下载检索模型</h2>
        <p className="mt-4 text-sm leading-6">{selectedModel?.name} · {selectedModel?.size}</p>
        <p className="mt-3 text-sm">保存到：</p><p className="mt-1 break-all font-mono text-xs leading-5">{status?.cache_dir}</p>
        <p className="mt-3 text-sm leading-6 text-zinc-600">将联网下载到本机，完成测试后重建现有资料与记忆的向量索引。更新期间暂停其他业务请求，原文和记忆正文保留。</p>
        <div className="mt-5 flex justify-end gap-3"><button autoFocus type="button" onClick={() => setConfirming(false)} className="min-h-11 rounded-xl border border-zinc-300 px-4 text-sm">取消</button><button type="button" onClick={() => void submit(true)} className="min-h-11 rounded-xl bg-zinc-900 px-4 text-sm text-white">确认下载并重建</button></div>
      </dialog>
    </div>
  </main>;
}
