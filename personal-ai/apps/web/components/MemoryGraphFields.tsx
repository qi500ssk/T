"use client";

import SelectMenu from "@/components/SelectMenu";

export type GraphData = {
  summary: string; event: string; stage: string; people: string[];
  relationships: { subject: string; predicate: string; object: string; quote: string }[];
  event_links: { event: string; relation: "before" | "after" | "causes"; quote: string }[];
  start: string | null; end: string | null; time_quote: string;
  importance: number; importance_reason: string;
};
export const emptyGraph: GraphData = { summary: "", event: "", stage: "", people: [], relationships: [], event_links: [], start: null, end: null, time_quote: "", importance: 3, importance_reason: "" };
export type RoleMemory = {
  chunk_id?: string; world_fact_id?: string | null; source_available?: boolean;
  perspective?: { knowledge: string; content: string; evidence_quote: string; importance: number; importance_reason: string; emotion: string; memory_strength: number; relationship_change: string; confidence: number };
  id: string; kind: string; content: string; evidence_type: string; is_core: boolean;
  known_to_character: boolean; time_label: string; tags: string[]; graph: Partial<GraphData>;
  source_quote: string; source_name: string; source_section: string; document_id: string | null; status: string;
};
const input = "mt-1 min-h-10 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 focus:outline-2 focus:outline-zinc-500";
const button = "min-h-9 rounded-lg border border-zinc-200 px-3 text-xs hover:bg-zinc-100";

export default function MemoryGraphFields({ value, onChange, worldMode = false }: { value: Partial<GraphData>; onChange: (value: GraphData) => void; worldMode?: boolean }) {
  const g = { ...emptyGraph, ...value };
  const set = (patch: Partial<GraphData>) => onChange({ ...g, ...patch });
  return <fieldset className="space-y-4 rounded-2xl border border-zinc-200 bg-zinc-50/60 p-4">
    <legend className="px-2 text-sm font-medium">事件、时间与关系</legend>
    <label className="block text-sm">检索摘要<textarea className={input} value={g.summary} maxLength={240} placeholder="保留关键事实与不确定性；聊天优先使用这段摘要" onChange={e => set({ summary: e.target.value })} /></label>
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="text-sm">故事阶段<input className={input} value={g.stage} maxLength={100} placeholder="例如：相遇与组队；不明确时留空" onChange={e => set({ stage: e.target.value })} /></label>
      <label className="text-sm">事件名称<input className={input} value={g.event} maxLength={100} placeholder="例如：第一次搬家" onChange={e => set({ event: e.target.value })} /></label>
      <label className="text-sm">涉及人物（逗号分隔）<input className={input} value={g.people.join(",")} placeholder="只填写明确涉及的人物" onChange={e => set({ people: e.target.value.split(/[,，]/).slice(0, 12) })} /></label>
      <label className="text-sm">开始日期<input className={input} type="date" value={g.start || ""} onChange={e => set({ start: e.target.value || null })} /></label>
      <label className="text-sm">结束日期<input className={input} type="date" min={g.start || undefined} value={g.end || ""} onChange={e => set({ end: e.target.value || null })} /></label>
    </div>
    <p className="text-xs leading-5 text-zinc-500">只有原文明确到日期才填写。童年、某年或毕业后等写在上方“时间”中；未知时间留空。</p>
    <label className="block text-sm">时间依据<input className={input} maxLength={500} value={g.time_quote} onChange={e => set({ time_quote: e.target.value })} /></label>
    {!worldMode && <div className="grid gap-4 sm:grid-cols-[150px_1fr]">
      <label className="text-sm">重要程度<SelectMenu className={input} ariaLabel="重要程度" value={String(g.importance)} onChange={v => set({ importance: Number(v) })} options={[1,2,3,4,5].map(v => ({ value: String(v), label: `${v} · ${["细节", "日常", "普通", "重要", "关键"][v - 1]}` }))} /></label>
      <label className="text-sm">判断理由<input className={input} maxLength={200} value={g.importance_reason} onChange={e => set({ importance_reason: e.target.value })} /></label>
    </div>}
    <div className="space-y-3">
      <p className="text-sm font-medium">人物关系</p>
      {g.relationships.map((r, i) => <div key={i} className="space-y-2 rounded-xl border border-zinc-200 p-3">
        <div className="grid gap-2 sm:grid-cols-3">{(["subject", "predicate", "object"] as const).map((key, j) => <label key={key} className="text-xs text-zinc-500">{["人物", "关系", "另一人物"][j]}<input required maxLength={80} className={input} value={r[key]} onChange={e => set({ relationships: g.relationships.map((item, n) => n === i ? { ...item, [key]: e.target.value } : item) })} /></label>)}</div>
        <label className="block text-xs text-zinc-500">原文依据<input className={input} maxLength={500} value={r.quote} onChange={e => set({ relationships: g.relationships.map((item, n) => n === i ? { ...item, quote: e.target.value } : item) })} /></label>
        <button type="button" className={button} onClick={() => set({ relationships: g.relationships.filter((_, n) => n !== i) })}>移除此关系</button>
      </div>)}
      <button type="button" className={button} disabled={g.relationships.length >= 12} onClick={() => set({ relationships: [...g.relationships, { subject: "", predicate: "", object: "", quote: "" }] })}>＋ 添加人物关系</button>
    </div>
    <div className="space-y-3">
      <p className="text-sm font-medium">事件的先后与因果</p>
      {g.event_links.map((r, i) => <div key={i} className="space-y-2 rounded-xl border border-zinc-200 p-3">
        <div className="flex gap-2"><SelectMenu ariaLabel="事件关系" className={input} value={r.relation} onChange={v => set({ event_links: g.event_links.map((item, n) => n === i ? { ...item, relation: v as typeof r.relation } : item) })} options={[{ value: "before", label: "当前事件早于" }, { value: "after", label: "当前事件晚于" }, { value: "causes", label: "当前事件导致" }]} /><input aria-label="目标事件名称" required maxLength={100} placeholder="另一事件的完整名称" className={input} value={r.event} onChange={e => set({ event_links: g.event_links.map((item, n) => n === i ? { ...item, event: e.target.value } : item) })} /></div>
        <label className="block text-xs text-zinc-500">关系依据<input required className={input} maxLength={500} value={r.quote} onChange={e => set({ event_links: g.event_links.map((item, n) => n === i ? { ...item, quote: e.target.value } : item) })} /></label>
        <button type="button" className={button} onClick={() => set({ event_links: g.event_links.filter((_, n) => n !== i) })}>移除此关联</button>
      </div>)}
      <button type="button" className={button} disabled={g.event_links.length >= 8} onClick={() => set({ event_links: [...g.event_links, { event: "", relation: "after", quote: "" }] })}>＋ 添加事件关联</button>
      <p className="text-xs leading-5 text-zinc-500">目标事件名称必须唯一匹配才能连线。重名或尚未导入的事件保留记录，暂不连线。</p>
    </div>
  </fieldset>;
}
