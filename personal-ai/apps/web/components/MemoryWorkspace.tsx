"use client";
import { useState } from "react";
import MemoryView from "@/components/MemoryView";
import CharacterMemoryView from "@/components/CharacterMemoryView";
import Avatar, { agentAvatarUrl } from "./Avatar";
import type { AgentProfile } from "@/lib/api";

export default function MemoryWorkspace(props: { agentId: string | null; agentName: string; agents?: AgentProfile[] }) {
  const [tab, setTab] = useState("character");
  const [selected, setSelected] = useState<AgentProfile|null>(null);
  const owner = selected ? {agentId:selected.id,agentName:selected.name} : props;
  return <div className="flex h-full min-h-0 w-full flex-1 flex-col">
    {selected&&<nav className="flex shrink-0 gap-2 border-b border-zinc-200 px-5 py-3" aria-label="记忆分类">
      {[["character", "角色记忆"], ["conversation", "相处与用户记忆"]].map(([value, label]) => <button type="button" key={value} onClick={() => setTab(value)} aria-pressed={tab === value} className={`min-h-10 rounded-xl px-4 text-sm ${tab === value ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100"}`}>{label}</button>)}
    </nav>}
    {selected&&<div className="px-6 pt-4"><button className="min-h-10 text-sm text-zinc-500" onClick={()=>{setSelected(null);setTab("character");}}>← 全部角色</button></div>}
    {tab === "character" ? selected ? <CharacterMemoryView key={selected.id} {...owner} /> : <div className="min-h-0 flex-1 overflow-y-auto p-6 lg:p-8"><div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{props.agents?.map(agent=><button key={agent.id} onClick={()=>setSelected(agent)} className="min-h-48 rounded-2xl border border-zinc-200 bg-white p-6 text-left hover:border-zinc-400"><Avatar src={agentAvatarUrl(agent)} alt={agent.name} className="mb-4 size-12 rounded-xl"/><h2 className="text-lg font-semibold">{agent.name}</h2><p className="mt-3 line-clamp-3 text-sm leading-6 text-zinc-500">{agent.role}</p></button>)}</div></div> : <MemoryView key={owner.agentId} {...owner} />}
  </div>;
}
