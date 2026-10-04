"use client";
import { useState } from "react";
import { req, type AgentSettings } from "@/lib/api";
export default function StoryOpening({agent,disabled,onSend,onLibrary}:{agent:AgentSettings;disabled:boolean;onSend:(text:string,documents?:string[])=>Promise<void>;onLibrary:()=>void}) {
  const [books,setBooks]=useState<{id:string;title:string}[]|null>(null);
  const [selected,setSelected]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  async function choose(index:number,text:string) {
    setError("");setBusy(true);
    try {
      if(index===1){onLibrary();return;}
      if(index===2){setBooks(await req("/api/worldbooks"));return;}
      await onSend(text);
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <div className="mx-auto mb-8 max-w-3xl">
    <p className="mb-5 text-lg leading-8 text-zinc-800">{agent.opening_message}</p>
    <div className="grid gap-3 sm:grid-cols-3">{agent.opening_options?.map((option,index)=><button type="button" key={option} disabled={disabled||busy} onClick={()=>void choose(index,option)} className="rounded-2xl border border-zinc-200 bg-white p-4 text-left text-sm leading-6 hover:border-zinc-400 disabled:opacity-40">{option}</button>)}</div>
    {books&&<div className="mt-4 rounded-2xl border border-zinc-200 bg-white p-4"><label className="grid gap-2 text-sm">选择本次要继续的作品<select aria-label="选择已有作品" value={selected} onChange={e=>setSelected(e.target.value)} className="min-h-11 rounded-xl border border-zinc-200 px-3"><option value="">请选择书籍</option>{books.map(book=><option key={book.id} value={book.id}>{book.title}</option>)}</select></label><button type="button" disabled={disabled||busy||!selected} onClick={async()=>{setBusy(true);try{await onSend(`这次我要继续《${books.find(b=>b.id===selected)?.title}》，只使用这部作品的资料（document_id: ${selected}）。先询问我接续的章节与创作目标，不要沿用其他作品。`,[selected]);}catch(e){setError(String(e));}finally{setBusy(false);}}} className="mt-3 min-h-10 rounded-xl bg-zinc-900 px-4 text-sm text-white disabled:opacity-40">使用这本书开始</button>{!books.length&&<p className="mt-2 text-sm text-zinc-500">书架还没有作品，可以先导入小说。</p>}</div>}
    {error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    <p className="mt-3 text-xs text-zinc-500">也可以直接在下方写下你的想法。</p>
  </div>;
}
