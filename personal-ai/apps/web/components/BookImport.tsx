"use client";
import { useState } from "react";
import { req } from "@/lib/api";

type Preview = {title:string;chapters:{title:string;characters:number}[];characters:number;ignored_files:string[];excerpt:string;document_id?:string};
const button = "min-h-11 rounded-xl border border-zinc-200 bg-white px-4 py-2 text-sm hover:bg-zinc-50 disabled:opacity-40";

export default function BookImport({onImported}:{onImported:(id:string)=>Promise<void>}) {
  const [files,setFiles] = useState<File[]>([]);
  const [title,setTitle] = useState("");
  const [preview,setPreview] = useState<Preview|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  function select(list:FileList|null) { setFiles(Array.from(list||[]));setPreview(null);setTitle("");setError(""); }
  async function convert(save:boolean) {
    setBusy(true);setError("");
    try {
      const body=new FormData();
      files.forEach(file=>body.append("files",file,file.webkitRelativePath||file.name));
      body.append("title",title);body.append("preview",String(!save));
      const result=await req<Preview>("/api/worldbooks/import",{method:"POST",body});
      setPreview(result);setTitle(result.title);
      if(result.document_id)await onImported(result.document_id);
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <section className="mx-auto w-full max-w-5xl space-y-6 px-5 pb-10 sm:px-8 lg:px-14">
    <div><h2 className="text-xl font-semibold">把已有小说放进书架</h2><p className="mt-2 text-sm leading-7 text-zinc-500">支持 TXT、EPUB、Markdown、章节文件夹和 ZIP。先检查章节目录，再保存；之后可阅读并导出 TXT 或 EPUB。</p></div>
    <div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 p-6 sm:p-8">
      <h3 className="font-medium">选择小说文件</h3>
      <p className="mt-2 text-sm leading-7 text-zinc-500">整本小说、ZIP 压缩包或多个文件都可以，导入后自动整理章节。</p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <label className={"relative inline-flex cursor-pointer items-center "+button+" focus-within:ring-2 focus-within:ring-zinc-500"}>选择文件<input aria-label="选择小说文件" type="file" multiple accept=".txt,.md,.epub,.zip" disabled={busy} onChange={e=>select(e.target.files)} className="absolute inset-0 w-full cursor-pointer opacity-0 disabled:cursor-default"/></label>
        <span className="text-sm text-zinc-400">或</span>
        <label className="relative inline-flex min-h-11 cursor-pointer items-center rounded-lg px-2 text-sm text-zinc-600 underline underline-offset-4 focus-within:ring-2 focus-within:ring-zinc-500">选择整个文件夹<input aria-label="选择整个小说文件夹" type="file" multiple {...{webkitdirectory:""}} disabled={busy} onChange={e=>select(e.target.files)} className="absolute inset-0 w-full cursor-pointer opacity-0 disabled:cursor-default"/></label>
      </div>
    </div>
    {files.length>0&&<div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-zinc-50 p-4"><p className="text-sm">已选择 {files.length} 个文件 · {(files.reduce((sum,f)=>sum+f.size,0)/1024/1024).toFixed(2)} MB</p><button type="button" disabled={busy} onClick={()=>void convert(false)} className={button}>{busy?"正在解析…":"识别章节与预览"}</button></div>}
    {error&&<p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {preview&&<div className="space-y-5 rounded-2xl border border-zinc-200 p-5 sm:p-6">
      <label className="grid gap-2 text-sm font-medium">书名<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={100} disabled={busy} className="min-h-11 rounded-xl border border-zinc-200 px-3"/></label>
      <p className="text-sm text-zinc-500">识别到 {preview.chapters.length} 个章节／正文分段 · {preview.characters.toLocaleString()} 字符</p>
      <details open><summary className="cursor-pointer text-sm font-medium">检查阅读顺序</summary><ol className="mt-3 max-h-72 divide-y divide-zinc-100 overflow-y-auto">{preview.chapters.map((chapter,index)=><li key={index} className="flex justify-between gap-4 py-3 text-sm"><span>{index+1}. {chapter.title}</span><span className="shrink-0 text-zinc-400">{chapter.characters.toLocaleString()} 字符</span></li>)}</ol></details>
      {preview.ignored_files.length>0&&<details className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900"><summary className="cursor-pointer">{preview.ignored_files.length} 个说明、设定或不支持的文件未加入正文</summary><ul className="mt-3 max-h-40 overflow-auto break-all">{preview.ignored_files.map(name=><li key={name}>{name}</li>)}</ul></details>}
      <details><summary className="cursor-pointer text-sm font-medium">正文预览</summary><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-zinc-600">{preview.excerpt}</p></details>
      <button type="button" disabled={busy||!title.trim()} onClick={()=>void convert(true)} className={button+" bg-zinc-900 text-white hover:bg-zinc-800"}>{busy?"正在保存…":"保存到书架并阅读"}</button>
    </div>}
  </section>;
}
