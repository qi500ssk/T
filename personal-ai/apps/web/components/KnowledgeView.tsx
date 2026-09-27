"use client";
import { useEffect, useRef, useState } from "react";
import { req, uploadFile } from "@/lib/api";
import StoryCharacterPicker from "./StoryCharacterPicker";
import SmallDialog from "./SmallDialog";
type Book = {id:string;title:string;synopsis:string;structured:boolean};
type Page = Book & {page:number;total:number;content:{title:string;text:string}};
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function KnowledgeView({onAgentCreated}:{onAgentCreated?:()=>void}) {
  const [books,setBooks]=useState<Book[]>([]);
  const [page,setPage]=useState<Page|null>(null);
  const [characters,setCharacters]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const reader=useRef<HTMLDivElement>(null);
  const requestId=useRef(0);
  useEffect(()=>{let stale=false;req<Book[]>("/api/worldbooks").then(v=>{if(!stale)setBooks(v);}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[]);
  async function open(id:string,n=0) {
    const ticket=++requestId.current;setBusy(true);setError("");
    try {const value=await req<Page>("/api/worldbooks/"+id+"?page="+n);if(ticket===requestId.current){setPage(value);reader.current?.scrollTo({top:0,behavior:"instant"});}}
    catch(e){if(ticket===requestId.current)setError(String(e));}finally{if(ticket===requestId.current)setBusy(false);}
  }
  async function upload(file?:File) {
    if(!file)return;setBusy(true);setError("");
    try {await uploadFile(file);setBooks(await req<Book[]>("/api/worldbooks"));}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-zinc-200 px-6 py-5">
      <div className="flex min-w-0 items-center gap-4">{page&&<button className={button} onClick={()=>{++requestId.current;setPage(null);setBusy(false);}}>← 书架</button>}<h1 className="truncate text-xl font-semibold">{page?.title||"世界书"}</h1></div>
      {page ? page.structured&&<button className={button} onClick={()=>setCharacters(true)}>书中角色</button> : <label className={button+" flex cursor-pointer items-center bg-zinc-900 text-white hover:bg-zinc-800"}>{busy?"正在上传…":"上传文件"}<input type="file" accept=".md,.txt,.json,.pdf,.docx" className="sr-only" disabled={busy} onChange={e=>{void upload(e.target.files?.[0]);e.target.value="";}} /></label>}
    </header>
    {error&&<p role="alert" className="px-6 py-3 text-sm text-red-700">{error}</p>}
    {page ? <>
      <div ref={reader} className="min-h-0 flex-1 overflow-y-auto px-6 py-10"><article className="mx-auto max-w-3xl"><p className="mb-3 text-sm text-zinc-400">{page.title}</p><h2 className="mb-8 text-2xl font-semibold">{page.content.title}</h2><p className="whitespace-pre-wrap break-words text-lg leading-9 text-zinc-800">{page.content.text}</p></article></div>
      <footer className="flex shrink-0 items-center justify-center gap-6 border-t border-zinc-200 p-4"><button className={button} disabled={busy||page.page===0} onClick={()=>void open(page.id,page.page-1)}>← 上一页</button><span className="text-sm tabular-nums text-zinc-500">{page.page+1} / {Math.max(1,page.total)}</span><button className={button} disabled={busy||page.page+1>=page.total} onClick={()=>void open(page.id,page.page+1)}>下一页 →</button></footer>
    </> : <div className="min-h-0 flex-1 overflow-y-auto p-6 lg:p-8"><div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{books.map(book=><button key={book.id} className="min-h-52 rounded-2xl border border-zinc-200 bg-white p-6 text-left transition hover:border-zinc-400 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-zinc-900" onClick={()=>void open(book.id)}><h2 className="text-lg font-semibold">{book.title}</h2><p className="mt-4 line-clamp-4 text-sm leading-7 text-zinc-500">{book.synopsis}</p></button>)}</div>{!books.length&&<p className="py-24 text-center text-sm text-zinc-400">还没有世界书，上传文件或与故事文档助手一起创作。</p>}</div>}
    {characters&&page&&<SmallDialog title="书中角色" onClose={()=>setCharacters(false)}><StoryCharacterPicker documentId={page.id} onCreated={onAgentCreated}/></SmallDialog>}
  </main>;
}
