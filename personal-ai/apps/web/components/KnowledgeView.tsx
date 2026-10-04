"use client";
import { useEffect, useRef, useState } from "react";
import { req } from "@/lib/api";
import StoryCharacterPicker from "./StoryCharacterPicker";
import SmallDialog from "./SmallDialog";
import WorldbookCard from "./WorldbookCard";
import WorldbookPages from "./WorldbookPages";
import NovelReader from "./NovelReader";
import BookImport from "./BookImport";
type Book = {id:string;title:string;synopsis:string;structured:boolean};
type Page = Book & {page:number;total:number;content:{title:string;text:string}};
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function KnowledgeView({onAgentCreated}:{onAgentCreated?:()=>void}) {
  const [tab,setTab]=useState<"read"|"import">("read");
  const [books,setBooks]=useState<Book[]>([]);
  const [page,setPage]=useState<Page|null>(null);
  const [characters,setCharacters]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const requestId=useRef(0);
  useEffect(()=>{let stale=false;req<Book[]>("/api/worldbooks").then(v=>{if(!stale)setBooks(v);}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[]);
  async function open(id:string,n?:number) {
    const ticket=++requestId.current;setBusy(true);setError("");
    try {let target=n;if(target===undefined){try{target=Number(localStorage.getItem("reader.progress."+id))||0;}catch{target=0;}}let value:Page;try{value=await req<Page>("/api/worldbooks/"+id+"?page="+target);}catch(e){if(!target)throw e;value=await req<Page>("/api/worldbooks/"+id+"?page=0");}if(ticket===requestId.current){setPage(value);}}
    catch(e){if(ticket===requestId.current)setError(String(e));}finally{if(ticket===requestId.current)setBusy(false);}
  }
  async function remove(book:Book) {
    if(!window.confirm(`删除书籍“${book.title}”？将移除这本书及其索引，角色卡不会被删除。`))return;
    setBusy(true);setError("");
    try {await req("/api/documents/"+book.id,{method:"DELETE"});setBooks(v=>v.filter(b=>b.id!==book.id));}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function upload(file?:File) {
    if(!file)return;setBusy(true);setError("");
    try {const body = new FormData();body.append("file",file);await req("/api/files?worldbook=true",{method:"POST",body});setBooks(await req<Book[]>("/api/worldbooks"));}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
    <header className={page?"flex shrink-0 items-center justify-between gap-4 border-b border-zinc-200 px-6 py-5":"mx-auto flex w-full max-w-5xl shrink-0 items-center justify-between gap-4 px-5 pt-8 pb-8 sm:px-8 lg:px-14 lg:pt-14"}>
      <div className="flex min-w-0 items-center gap-4">{page&&<button className={button} onClick={()=>{++requestId.current;setPage(null);setBusy(false);}}>← 书架</button>}<h1 className="truncate text-2xl font-semibold">{page?.title||"书籍"}</h1></div>
      <div className="flex flex-wrap gap-2">{page&&<><a className={button+" flex items-center"} href={"/api/worldbooks/"+page.id+"/export/txt"}>导出 TXT</a><a className={button+" flex items-center"} href={"/api/worldbooks/"+page.id+"/export/epub"}>导出 EPUB</a>{page.structured?<button className={button} onClick={()=>setCharacters(true)}>书中角色</button>:<NovelReader documentId={page.id} onCreated={onAgentCreated}/>}</>}{!page&&tab==="read"&&<label className={button+" flex cursor-pointer items-center bg-zinc-900 text-white hover:bg-zinc-800"}>{busy?"正在上传…":"上传文件"}<input type="file" accept=".md,.txt,.json,.pdf,.docx" className="sr-only" disabled={busy} onChange={e=>{void upload(e.target.files?.[0]);e.target.value="";}}/></label>}</div>
    </header>
    {!page&&<nav aria-label="书籍功能" className="mx-auto mb-8 flex w-full max-w-5xl gap-2 px-5 sm:px-8 lg:px-14">{([["read","书架阅读"],["import","导入转换"]] as const).map(([value,label])=><button type="button" key={value} aria-pressed={tab===value} onClick={()=>setTab(value)} className={button+(tab===value?" bg-zinc-900 text-white hover:bg-zinc-800":"")}>{label}</button>)}</nav>}
    {error&&<p role="alert" className="px-6 py-3 text-sm text-red-700">{error}</p>}
    {!page&&tab==="import"?<div className="min-h-0 flex-1 overflow-y-auto"><BookImport onImported={async id=>{setBooks(await req<Book[]>("/api/worldbooks"));setTab("read");await open(id,0);}}/></div>:page ? <WorldbookPages page={page} busy={busy} onPage={n=>void open(page.id,n)}/> : <div className="min-h-0 flex-1 overflow-y-auto"><div className="mx-auto grid w-full max-w-5xl gap-5 px-5 pb-8 sm:grid-cols-2 sm:px-8 lg:px-14 lg:pb-14 xl:grid-cols-3">{books.map(book=><WorldbookCard compact key={book.id} title={book.title} synopsis={book.synopsis} onClick={()=>void open(book.id)} onDelete={()=>void remove(book)} disabled={busy}/>)}</div>{!books.length&&<p className="py-24 text-center text-sm text-zinc-400">还没有书籍，上传文件或与故事文档助手一起创作。</p>}</div>}
    {characters&&page&&<SmallDialog title="书中角色" onClose={()=>setCharacters(false)}><StoryCharacterPicker documentId={page.id} onCreated={onAgentCreated}/></SmallDialog>}
  </main>;
}
