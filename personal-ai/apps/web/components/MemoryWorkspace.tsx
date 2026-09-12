"use client";
import { useState } from "react";
import MemoryView from "@/components/MemoryView";
import CharacterMemoryView from "@/components/CharacterMemoryView";

export default function MemoryWorkspace(props: { agentId: string | null; agentName: string }) {
  const [tab, setTab] = useState("character");
  return <div className="flex h-full min-h-0 w-full flex-1 flex-col">
    <nav className="flex shrink-0 gap-2 border-b border-zinc-200 px-5 py-3" aria-label="记忆分类">
      {[["character", "背景与经历"], ["conversation", "相处与用户记忆"]].map(([value, label]) => <button type="button" key={value} onClick={() => setTab(value)} aria-pressed={tab === value} className={`min-h-10 rounded-xl px-4 text-sm ${tab === value ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100"}`}>{label}</button>)}
    </nav>
    {tab === "character" ? <CharacterMemoryView {...props} /> : <MemoryView {...props} />}
  </div>;
}
