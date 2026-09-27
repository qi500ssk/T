"use client";
import {useCallback,useEffect,useState} from "react";
import {req} from "@/lib/api";
type Candidate={id:string;content:string;expires_at:string};
export default function MemoryCandidates({agentId,onChanged}:{agentId:string|null;onChanged:()=>void}) {
 const [items,setItems]=useState<Candidate[]>([]);const [error,setError]=useState("");const [busy,setBusy]=useState("");
 const root=`/api/characters/${encodeURIComponent(agentId||"")}/memory-candidates`;
 const refresh=useCallback(async()=>{if(agentId)setItems(await req<Candidate[]>(root));},[agentId,root]);
 useEffect(()=>{let stale=false;if(agentId)req<Candidate[]>(root).then(v=>{if(!stale)setItems(v);}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[agentId,root]);
 async function review(id:string,action:string){setBusy(id);setError("");try{await req(`${root}/${id}/${action}`,{method:"POST"});await refresh();onChanged();}catch(e){setError(String(e));}finally{setBusy("");}}
 return <details className="my-5 rounded-xl border border-zinc-200 bg-white p-4"><summary className="cursor-pointer text-sm font-medium">候选记忆 · {items.length} 条待确认</summary>
 <p className="mt-2 text-xs leading-6 text-zinc-500">未达到长期保留标准的线索暂存 30 天，不进入聊天检索。后续明确事实可重新评估；你也可以确认保存或舍弃，不会按出现次数自动当真。</p>
 <div className="mt-3 max-h-80 space-y-3 overflow-auto">{items.map(item=><article key={item.id} className="rounded-lg border border-zinc-200 p-3"><p className="whitespace-pre-wrap text-sm leading-6">{item.content}</p><div className="mt-2 flex gap-3 text-xs"><button disabled={!!busy} className="min-h-9 rounded-lg border px-3" onClick={()=>void review(item.id,"confirm")}>确认记住</button><button disabled={!!busy} className="min-h-9 rounded-lg border px-3" onClick={()=>void review(item.id,"dismiss")}>舍弃</button><span className="self-center text-zinc-400">到期：{new Date(item.expires_at).toLocaleDateString()}</span></div></article>)}</div>
 {error&&<p role="alert" className="mt-3 text-xs text-red-700">{error}</p>}</details>;
}
