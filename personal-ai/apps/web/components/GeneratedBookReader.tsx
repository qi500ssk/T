"use client";
import { useEffect, useRef, useState } from "react";
import { req } from "@/lib/api";
import SmallDialog from "./SmallDialog";
import WorldbookPages, { type BookPage } from "./WorldbookPages";
export default function GeneratedBookReader({jobId,title,onClose}:{jobId:string;title:string;onClose:()=>void}) {
  const [page,setPage]=useState<BookPage|null>(null),[busy,setBusy]=useState(true),[error,setError]=useState("");
  const ticket=useRef(0);
  async function open(n:number) {
    const id=++ticket.current;setBusy(true);setError("");
    try {const data=await req<BookPage>(`/api/story-builds/${jobId}/read?page=${n}`);if(id===ticket.current)setPage(data);}
    catch(e){if(id===ticket.current)setError(String(e));}finally{if(id===ticket.current)setBusy(false);}
  }
  useEffect(()=>{void open(0);return()=>{++ticket.current;};},[jobId]); // Reader is keyed by job ID.
  return <SmallDialog title={title} size="large" onClose={onClose}><div className="flex h-[calc(88dvh-8rem)] min-h-0 flex-col">{error&&<p role="alert" className="p-4 text-sm text-red-700">{error}<button className="ml-3 underline" onClick={()=>void open(page?.page??0)}>重试</button></p>}{page?<WorldbookPages page={page} busy={busy} onPage={n=>void open(n)}/>:busy&&<p className="p-6 text-sm text-zinc-500">正在打开全文…</p>}</div></SmallDialog>;
}
