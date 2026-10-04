"use client";
import { useState } from "react";
import MemoryView from "@/components/MemoryView";
import CharacterMemoryView from "@/components/CharacterMemoryView";
import Avatar, { agentAvatarUrl } from "./Avatar";
import LibraryCard from "./LibraryCard";
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
    {tab === "character" ? selected ? <CharacterMemoryView key={selected.id} {...owner} /> : <div className="min-h-0 flex-1 overflow-y-auto bg-white"><div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14"><header className="mb-8 flex min-h-10 items-center"><h1 className="text-2xl font-semibold">记忆</h1></header><div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">{props.agents?.map(agent=><LibraryCard key={agent.id} title={agent.name} description={agent.role} avatar={<Avatar src={agentAvatarUrl(agent)} alt={agent.name} className="size-10 shrink-0 rounded-xl ring-1 ring-zinc-200"/>} onOpen={()=>setSelected(agent)}/>)}</div></div></div> : <MemoryView key={owner.agentId} {...owner} />}
  </div>;
}
