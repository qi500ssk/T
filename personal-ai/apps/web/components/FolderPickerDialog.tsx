"use client";
import { useEffect, useRef, useState } from "react";
import { fetchDirectories, pickLocalDirectory, type DirectoryListing } from "@/lib/api";

export default function FolderPickerDialog({open,initialPath,onClose,onSelect}:{open:boolean;initialPath:string;onClose:()=>void;onSelect:(path:string,name?:string)=>Promise<void>}) {
  const ref=useRef<HTMLDialogElement>(null);
  const pickId=useRef<string|null>(null);
  const [name,setName]=useState("");
  const [path,setPath]=useState("");
  const [picking,setPicking]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [listing,setListing]=useState<DirectoryListing|null>(null);
  const busy=picking||saving;
  useEffect(()=>{const dialog=ref.current;if(!dialog)return;if(open&&!dialog.open){setName("");setPath(initialPath);setError("");dialog.showModal();}else if(!open&&dialog.open)dialog.close();},[open,initialPath]);
  useEffect(()=>{
    if(!open)return;
    let cancelled=false;
    fetchDirectories().then(result=>{if(!cancelled)setListing(result);}).catch(e=>{if(!cancelled)setError(String(e));});
    return()=>{cancelled=true;};
  },[open]);
  async function browse(nextPath?:string){
    setPicking(true);setError("");
    try{const result=await fetchDirectories(nextPath);setListing(result);setPath(result.current_path??"");}
    catch(e){setError(e instanceof Error?e.message:"无法读取文件夹");}
    finally{setPicking(false);}
  }
  async function pick(){const id=crypto.randomUUID();pickId.current=id;setPicking(true);setError("");try{const result=await pickLocalDirectory(id);if(pickId.current===id&&result.path)setPath(result.path);}catch(e){if(pickId.current===id)setError(e instanceof Error?e.message:"无法选择文件夹");}finally{if(pickId.current===id){pickId.current=null;setPicking(false);}}}
  async function create(){if(!path||busy)return;setSaving(true);setError("");try{await onSelect(path,name.trim());}catch(e){setError(e instanceof Error?e.message:"创建项目失败");}finally{setSaving(false);}}
  return <dialog ref={ref} onCancel={e=>{e.preventDefault();if(!busy)onClose();}} className="m-auto h-[min(80vh,42rem)] w-[min(94vw,46rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35" aria-labelledby="folder-dialog-title">
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-5"><h2 id="folder-dialog-title" className="text-xl font-bold">创建项目</h2><button type="button" disabled={busy} onClick={onClose} aria-label="关闭文件夹选择" className="size-10 rounded-lg text-zinc-500 hover:bg-zinc-100 disabled:opacity-40">×</button></header>
      <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-6">
        <label className="grid gap-3 text-sm font-medium">项目名<input value={name} onChange={e=>setName(e.target.value)} maxLength={120} disabled={busy} placeholder="不填写则使用文件夹名称" className="h-12 w-full rounded-xl border border-zinc-200 px-4 font-normal outline-none focus:border-zinc-500"/></label>
        <section className="flex flex-1 flex-col"><h3 className="mb-3 text-sm font-medium">源文件夹</h3><div className="flex min-h-44 flex-1 flex-col items-center justify-center gap-5 rounded-2xl border border-zinc-200 p-6">
          {path&&<p className="max-w-full break-all text-center text-sm text-zinc-600">{path}</p>}
          {listing?.native_picker_available===false?<div className="grid w-full gap-3">
            <p className="text-xs text-zinc-500">选择挂载工作区中的文件夹</p>
            <p className="break-all text-sm text-zinc-600">{listing.current_path}</p>
            {listing.parent_path&&<button type="button" disabled={busy} onClick={()=>void browse(listing.parent_path!)} className="rounded-lg border p-2 text-left text-sm">返回上级文件夹</button>}
            <div className="max-h-52 overflow-y-auto">{listing.directories.map(directory=><button key={directory.path} type="button" disabled={busy} onClick={()=>void browse(directory.path)} className="block w-full rounded-lg p-2 text-left text-sm hover:bg-zinc-50">📁 {directory.name}</button>)}</div>
            <button type="button" disabled={busy} onClick={()=>setPath(listing.current_path??"")} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm hover:bg-zinc-50">使用当前文件夹</button>
          </div>:<button type="button" onClick={()=>void pick()} disabled={busy||!listing} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm hover:bg-zinc-50 disabled:opacity-50">{picking?"文件夹窗口已打开":path?"更换文件夹":"在此电脑中选择文件夹"}</button>}
        </div></section>
        {error&&<p role="alert" className="text-sm text-red-600">{error}</p>}
      </div>
      <footer className="flex items-center justify-between gap-4 border-t border-zinc-200 px-6 py-4"><p className="hidden text-xs text-zinc-500 sm:block">这里只选择位置，不会上传文件内容</p><div className="ml-auto flex gap-3"><button type="button" disabled={busy} onClick={onClose} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm disabled:opacity-40">取消</button><button type="button" disabled={busy||!path} onClick={()=>void create()} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white disabled:opacity-40">{saving?"创建中…":"创建项目"}</button></div></footer>
    </div>
  </dialog>;
}
