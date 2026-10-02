"use client";
import { useEffect, useRef } from "react";
export type BookPage={title:string;page:number;total:number;content:{title:string;text:string}};
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function WorldbookPages({page,busy,onPage}:{page:BookPage;busy:boolean;onPage:(page:number)=>void}) {
  const reader=useRef<HTMLDivElement>(null);
  useEffect(()=>{reader.current?.scrollTo({top:0,behavior:"instant"});},[page]);
  return <><div ref={reader} className="min-h-0 flex-1 overflow-y-auto px-6 py-10"><article className="mx-auto max-w-3xl"><p className="mb-3 text-sm text-zinc-400">{page.title}</p><h2 className="mb-8 text-2xl font-semibold">{page.content.title}</h2><p className="whitespace-pre-wrap break-words text-lg leading-9 text-zinc-800">{page.content.text}</p></article></div><footer className="flex shrink-0 items-center justify-center gap-6 border-t border-zinc-200 p-4"><button className={button} disabled={busy||page.page===0} onClick={()=>onPage(page.page-1)}>← 上一页</button><span className="text-sm tabular-nums text-zinc-500">{page.page+1} / {Math.max(1,page.total)}</span><button className={button} disabled={busy||page.page+1>=page.total} onClick={()=>onPage(page.page+1)}>下一页 →</button></footer></>;
}
