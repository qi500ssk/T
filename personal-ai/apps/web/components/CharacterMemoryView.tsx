"use client";
import { useEffect, useState } from "react";
import { req } from "@/lib/api";
import type { RoleMemory } from "@/lib/role-memory";
import SmallDialog from "./SmallDialog";
import SelectMenu from "./SelectMenu";
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function CharacterMemoryView({agentId,agentName}:{agentId:string|null;agentName:string}) {
  const [rows,setRows]=useState<RoleMemory[]>([]);
  const [adding,setAdding]=useState(false);
  const [kind,setKind]=useState("all");
  const labels:Record<string,string>={experience:"亲身经历",world:"世界知识",identity:"身份",personality:"性格",relationship:"人物关系",preference:"偏好"};
  const [content,setContent]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const root="/api/characters/"+encodeURIComponent(agentId||"")+"/memories";
  useEffect(()=>{let stale=false;if(agentId)req<{memories:RoleMemory[]}>(root).then(v=>{if(!stale)setRows(v.memories);}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[agentId,root]);
  async function mutate(action:()=>Promise<unknown>) {
    setBusy(true);setError("");
    try {await action();setRows((await req<{memories:RoleMemory[]}>(root)).memories);}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  const visible=rows.filter(r=>r.status==="active"&&r.known_to_character&&r.source_available!==false&&(kind==="all"||r.kind===kind));
  return <main className="min-h-0 flex-1 overflow-y-auto p-6 lg:p-8"><header className="mb-6 flex items-center justify-between gap-4"><h1 className="text-xl font-semibold">{agentName}的记忆</h1><button className={button} disabled={!agentId||busy} onClick={()=>setAdding(true)}>＋ 新增</button></header>
    <div className="mb-5 flex flex-wrap items-center gap-3 text-sm"><span className="text-zinc-500">作用域：仅 {agentName}</span><label className="flex items-center gap-3">记忆类型<SelectMenu ariaLabel="角色记忆类型" value={kind} onChange={setKind} className={button+" min-w-36 bg-white"} options={[{value:'all',label:'全部类型'},...Array.from(new Set(rows.map(r=>r.kind))).map(v=>({value:v,label:labels[v]||v}))]}/></label></div>
    {error&&<p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
    <div className="divide-y divide-zinc-200 rounded-2xl border border-zinc-200">{visible.map(row=><article key={row.id} className="flex items-start gap-5 p-5"><div className="min-w-0 flex-1"><p className="whitespace-pre-wrap text-sm leading-7">{row.content}</p><p className="mt-2 text-xs text-zinc-500">{labels[row.kind]||row.kind}</p>{row.time_label&&<p className="mt-2 text-xs text-zinc-400">{row.time_label}</p>}</div><button className="min-h-10 px-2 text-sm text-red-600 disabled:opacity-40" disabled={busy} onClick={()=>{if(window.confirm("删除这条角色记忆？删除后将不再用于后续聊天。"))void mutate(()=>req(root+"/"+row.id,{method:"DELETE"}));}}>删除</button></article>)}</div>
    {!visible.length&&<p className="py-20 text-center text-sm text-zinc-400">还没有记忆。从书籍创建角色时，会自动保存这个角色知道的经历。</p>}
    {adding&&<SmallDialog title="新增角色记忆" onClose={()=>{if(!busy)setAdding(false);}}><form onSubmit={e=>{e.preventDefault();void mutate(async()=>{await req(root,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:content.trim()})});setAdding(false);setContent("");});}}><label className="grid gap-2 text-sm">记忆内容<textarea autoFocus required maxLength={1200} rows={6} value={content} onChange={e=>setContent(e.target.value)} className="w-full rounded-xl border border-zinc-300 p-3 leading-7"/></label>{error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}<div className="mt-4 flex justify-end"><button className={button} disabled={busy||!content.trim()}>保存</button></div></form></SmallDialog>}
  </main>;
}
