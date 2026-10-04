"use client";
import { useEffect, useRef, useState } from "react";
export type BookPage={id?:string;title:string;page:number;total:number;content:{title:string;text:string};chapters?:{title:string;characters:number}[]};
const button="min-h-10 rounded-xl border border-current/20 px-4 text-sm hover:opacity-70 disabled:opacity-30";
export default function WorldbookPages({page,busy,onPage}:{page:BookPage;busy:boolean;onPage:(page:number)=>void}) {
  const reader=useRef<HTMLDivElement>(null);
  const container=useRef<HTMLDivElement>(null);
  const [fullscreen,setFullscreen]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const isFullscreen=fullscreen||expanded;
  useEffect(()=>{
    const sync=()=>setFullscreen(document.fullscreenElement===container.current);
    document.addEventListener("fullscreenchange",sync);
    return ()=>document.removeEventListener("fullscreenchange",sync);
  },[]);
  useEffect(()=>{
    if(!expanded)return;
    const escape=(event:KeyboardEvent)=>{if(event.key==="Escape")setExpanded(false);};
    document.addEventListener("keydown",escape);
    return ()=>document.removeEventListener("keydown",escape);
  },[expanded]);
  async function toggleFullscreen(){
    if(expanded){setExpanded(false);return;}
    if(document.fullscreenElement===container.current){await document.exitFullscreen().catch(()=>{});return;}
    if(!container.current)return;
    try{
      if(!container.current.requestFullscreen){setExpanded(true);return;}
      await container.current.requestFullscreen();
    }catch{setExpanded(true);}
  }
  const [toc,setToc]=useState(false);
  const [size,setSize]=useState(19);
  const [theme,setTheme]=useState("paper");
  useEffect(()=>{
    const frame=requestAnimationFrame(()=>{try {
      setSize(Math.min(28,Math.max(14,Number(localStorage.getItem("reader.font"))||19)));
      const savedTheme=localStorage.getItem("reader.theme");
      setTheme(savedTheme&&["paper","white","night"].includes(savedTheme)?savedTheme:"paper");
    }catch{}});
    return ()=>cancelAnimationFrame(frame);
  },[]);
  useEffect(()=>{reader.current?.scrollTo({top:0,behavior:"instant"});if(page.id)try{localStorage.setItem("reader.progress."+page.id,String(page.page));}catch{}},[page.id,page.page]);
  const palette=theme==="night"?"bg-zinc-900 text-zinc-200":theme==="white"?"bg-white text-zinc-800":"bg-[#f8f3e8] text-[#423c32]";
  return <div ref={container} className={"flex min-h-0 flex-1 flex-col "+palette+(expanded?" fixed inset-0 z-[100] h-dvh w-screen":fullscreen?" h-dvh w-screen":"")}>
    <nav aria-label="阅读设置" className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-current/10 px-5 py-3">
      <div className="flex items-center gap-2"><button type="button" aria-expanded={toc} className={button} onClick={()=>setToc(!toc)}>目录 · {page.total} {page.chapters?"章":"页"}</button><button type="button" aria-pressed={isFullscreen} title={isFullscreen?"退出全屏（Esc）":"全屏阅读"} className={button} onClick={()=>void toggleFullscreen()}>{isFullscreen?"退出全屏":"全屏阅读"}</button></div>
      <div className="flex items-center gap-2"><button type="button" aria-label="缩小字号" className={button} disabled={size<=14} onClick={()=>{setSize(size-1);localStorage.setItem("reader.font",String(size-1));}}>A−</button><button type="button" aria-label="放大字号" className={button} disabled={size>=28} onClick={()=>{setSize(size+1);localStorage.setItem("reader.font",String(size+1));}}>A＋</button><select aria-label="阅读主题" value={theme} onChange={e=>{setTheme(e.target.value);localStorage.setItem("reader.theme",e.target.value);}} className="min-h-10 rounded-xl border border-current/20 bg-transparent px-3 text-sm"><option value="paper">纸张</option><option value="white">明亮</option><option value="night">夜间</option></select></div>
    </nav>
    <div className="relative flex min-h-0 flex-1">
      {toc&&<aside aria-label="章节目录" className={"absolute inset-y-0 left-0 z-10 w-72 max-w-[85vw] overflow-y-auto border-r border-current/10 p-3 shadow-lg "+palette}><ol>{(page.chapters||Array.from({length:page.total},(_,i)=>({title:`第 ${i+1} 页`}))).map((chapter,index)=><li key={index}><button type="button" aria-current={index===page.page?"page":undefined} disabled={busy} onClick={()=>{onPage(index);setToc(false);}} className={"min-h-11 w-full rounded-lg px-3 py-3 text-left text-sm hover:bg-black/5 "+(index===page.page?"bg-black/10 font-semibold":"")}>{chapter.title}</button></li>)}</ol></aside>}
      <div ref={reader} aria-busy={busy} className="min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges] px-6 py-10 sm:px-10"><article className="mx-auto w-full max-w-3xl"><p className="mb-3 text-sm opacity-50">{page.title}</p><h2 className="mb-10 text-2xl font-semibold leading-relaxed">{page.content.title}</h2><div style={{fontSize:size,lineHeight:1.95}} className="space-y-5 break-words">{page.content.text.split(/\n\s*\n/).filter(Boolean).map((p,index)=><p key={index} className="whitespace-normal">{p}</p>)}</div></article></div>
    </div>
    <footer className="shrink-0 border-t border-current/10 px-6 py-4 sm:px-10"><div className="mx-auto grid w-full max-w-3xl grid-cols-[1fr_auto_1fr] items-center gap-5"><button className={button+" justify-self-end"} disabled={busy||page.page===0} onClick={()=>onPage(page.page-1)}>← 上一{page.chapters?"章":"页"}</button><span className="text-sm tabular-nums opacity-60">{page.page+1} / {Math.max(1,page.total)}</span><button className={button+" justify-self-start"} disabled={busy||page.page+1>=page.total} onClick={()=>onPage(page.page+1)}>下一{page.chapters?"章":"页"} →</button></div></footer>
  </div>;
}
