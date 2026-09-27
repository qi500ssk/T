"use client";
import { useEffect, useState } from "react";
import { createMemory, deleteMemory, fetchMemories, fetchProjects, fetchConversations, type Memory, type MemoryKind, type Project, type Conversation } from "@/lib/api";
import SmallDialog from "./SmallDialog";
import SelectMenu from "./SelectMenu";
const button="min-h-10 rounded-xl border border-zinc-200 bg-white px-4 text-sm whitespace-nowrap disabled:opacity-40";
const kinds:Record<MemoryKind,string>={profile:"偏好与身份",semantic:"长期事实",episodic:"重要事件"};
const scopes:Record<Memory['scope_type'],string>={agent:"当前角色",project:"指定项目",conversation:"指定会话",global:"所有角色（公共）"};
export default function MemoryView({agentId,agentName}:{agentId:string|null;agentName:string}) {
  const [rows,setRows]=useState<Memory[]>([]);
  const [scope,setScope]=useState<Memory['scope_type']|'all'>('all');
  const [kind,setKind]=useState<MemoryKind|'all'>('all');
  const [projects,setProjects]=useState<Project[]>([]);
  const [conversations,setConversations]=useState<Conversation[]>([]);
  const [adding,setAdding]=useState(false);
  const [content,setContent]=useState('');
  const [newKind,setNewKind]=useState<MemoryKind>('semantic');
  const [newScope,setNewScope]=useState<Memory['scope_type']>('agent');
  const [target,setTarget]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{let stale=false;Promise.all([fetchProjects(),fetchConversations()]).then(([p,c])=>{if(!stale){setProjects(p.filter(v=>v.agent_ids.includes(agentId||'')));setConversations(c.filter(v=>v.agent_id===agentId));}}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[agentId]);
  useEffect(()=>{let stale=false;const promise=scope==='global'?fetchMemories({scope_type:'global',status:'active'}):agentId?fetchMemories({agent_id:agentId,status:'active'}):Promise.resolve([]);promise.then(v=>{if(!stale){setRows(v);setError('');}}).catch(e=>{if(!stale)setError(String(e));});return()=>{stale=true;};},[agentId,scope]);
  async function mutate(action:()=>Promise<unknown>, afterScope=scope) {
    setBusy(true);setError('');
    try {await action();setRows(await fetchMemories(afterScope==='global'?{scope_type:'global',status:'active'}:{agent_id:agentId||undefined,status:'active'}));}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  const visible=rows.filter(r=>r.is_active&&(scope==='all'||r.scope_type===scope)&&(kind==='all'||r.kind===kind));
  const targets=newScope==='project'?projects.map(p=>({id:p.id,name:p.name})):conversations.map(c=>({id:c.id,name:c.title}));
  function scopeLabel(r:Memory){return r.scope_type==='agent'?agentName:r.scope_type==='global'?'所有角色':r.scope_type==='project'?'项目：'+(projects.find(p=>p.id===r.scope_key)?.name||r.scope_key):'会话：'+(conversations.find(c=>c.id===r.scope_key)?.title||r.scope_key);}
  return <section className="min-h-0 flex-1 overflow-y-auto py-6 sm:px-6 lg:p-8"><header className="mb-6 flex items-center justify-between gap-4"><div><h1 className="text-xl font-semibold">{agentName} · 相处与用户记忆</h1><p className="mt-2 text-sm text-zinc-500">重要信息自动记住；公共记忆对所有角色可见。</p></div><button className={button} disabled={busy||!agentId} onClick={()=>setAdding(true)}>＋ 新增</button></header>
    <div className="mb-6 flex flex-wrap gap-4"><label className="flex items-center gap-3 whitespace-nowrap text-sm">作用域<SelectMenu ariaLabel="筛选作用域" value={scope} className={button+" min-w-52"} disabled={busy} onChange={v=>setScope(v as typeof scope)} options={[{value:'all',label:'该角色的全部作用域'},...Object.entries(scopes).map(([value,label])=>({value,label}))]}/></label><label className="flex items-center gap-3 whitespace-nowrap text-sm">记忆类型<SelectMenu ariaLabel="筛选记忆类型" className={button+" min-w-36"} value={kind} onChange={v=>setKind(v as typeof kind)} options={[{value:'all',label:'全部类型'},...Object.entries(kinds).map(([value,label])=>({value,label}))]}/></label></div>
    {error&&<p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
    <div className="divide-y divide-zinc-200 rounded-2xl border border-zinc-200">{visible.map(row=><article key={row.id} className="flex items-start gap-5 p-5"><div className="min-w-0 flex-1"><p className="whitespace-pre-wrap text-sm leading-7">{row.content}</p><p className="mt-2 text-xs text-zinc-500">{kinds[row.kind]} · 作用域：{scopeLabel(row)}</p></div><button className="min-h-10 px-2 text-sm text-red-600 disabled:opacity-40" disabled={busy} onClick={()=>{if(window.confirm('删除这条记忆？删除后将不再用于后续聊天。'))void mutate(()=>deleteMemory(row.id));}}>删除</button></article>)}</div>
    {!visible.length&&<p className="py-16 text-center text-sm text-zinc-400">当前筛选下没有记忆</p>}
    {adding&&<SmallDialog title="新增记忆" onClose={()=>{if(!busy)setAdding(false);}}><form onSubmit={e=>{e.preventDefault();void mutate(async()=>{await createMemory({content:content.trim(),kind:newKind,importance:3,scope_type:newScope,scope_key:newScope==='global'?'global':newScope==='agent'?agentId!:target});setAdding(false);setContent('');setScope(newScope);setKind('all');},newScope);}}><div className="mb-4 grid gap-4 sm:grid-cols-2"><label className="grid gap-2 text-sm">记忆类型<SelectMenu ariaLabel="记忆类型" value={newKind} onChange={v=>setNewKind(v as MemoryKind)} options={Object.entries(kinds).map(([value,label])=>({value,label}))}/></label><label className="grid gap-2 text-sm">作用域<SelectMenu ariaLabel="作用域" value={newScope} onChange={v=>{setNewScope(v as Memory['scope_type']);setTarget('');}} options={Object.entries(scopes).map(([value,label])=>({value,label}))}/></label></div>
    {(newScope==='project'||newScope==='conversation')&&<label className="mb-4 grid gap-2 text-sm">{newScope==='project'?'选择项目':'选择会话'}<SelectMenu ariaLabel={newScope==='project'?'选择项目':'选择会话'} value={target} onChange={setTarget} options={[{value:'',label:'请选择',disabled:true},...targets.map(t=>({value:t.id,label:t.name}))]}/></label>}
    <p className="mb-3 text-xs text-zinc-500">{newScope==='global'?'所有角色均可使用这条记忆。':newScope==='project'?'此项目授权的角色可在项目中使用。':newScope==='conversation'?'仅在选定会话中使用。':'只属于'+agentName+'，不会分享给其他角色。'}</p><label className="grid gap-2 text-sm">记忆内容<textarea autoFocus required maxLength={2000} rows={5} className="w-full rounded-xl border border-zinc-300 p-3 leading-7" value={content} onChange={e=>setContent(e.target.value)}/></label>{error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}<div className="mt-4 flex justify-end"><button className={button} disabled={busy||!content.trim()||((newScope==='project'||newScope==='conversation')&&!target)}>保存</button></div></form></SmallDialog>}
  </section>;
}
