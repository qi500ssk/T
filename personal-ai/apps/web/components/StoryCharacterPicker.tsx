"use client";
import { useEffect, useState } from "react";
import { req } from "@/lib/api";
type Person={id:string;name:string;description:string;admission:{active:number}};
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function StoryCharacterPicker({documentId,onCreated}:{documentId:string;onCreated?:()=>void}) {
  const [people,setPeople]=useState<Person[]>([]);
  const [busy,setBusy]=useState("");
  const [notice,setNotice]=useState("");
  const [created,setCreated]=useState<string[]>([]);
  useEffect(()=>{let stale=false;req<{characters:Person[]}>("/api/stories/"+documentId).then(v=>{if(!stale)setPeople(v.characters);}).catch(e=>{if(!stale)setNotice(String(e));});return()=>{stale=true;};},[documentId]);
  async function create(person:Person) {
    setBusy(person.id);setNotice("");
    try {const result=await req<{name:string;memories:number}>("/api/stories/"+documentId+"/characters/"+person.id,{method:"POST"});setNotice("已创建"+result.name+"，自动保存了 "+result.memories+" 条专属记忆。");setCreated(ids=>[...ids,person.id]);onCreated?.();}
    catch(e){setNotice(String(e));}finally{setBusy("");}
  }
  return <section><p className="mb-4 text-sm leading-6 text-zinc-500">从本书结尾开始生活。每个角色只记得自己知道的经历。</p><div className="space-y-4">{people.map(person=><article key={person.id} className="rounded-xl border border-zinc-200 p-4"><h3 className="font-semibold">{person.name}</h3><p className="my-3 text-sm leading-7 text-zinc-500">{person.description}</p><button className={button} disabled={!!busy||created.includes(person.id)} onClick={()=>void create(person)}>{created.includes(person.id)?"已创建":busy===person.id?"正在建立记忆…":"创建此角色"}</button></article>)}</div>{notice&&<p role="status" className="mt-4 text-sm leading-7">{notice}</p>}</section>;
}
