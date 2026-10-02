"use client";
import { useEffect, useState } from "react";
import { req } from "@/lib/api";
import WorldbookCard from "./WorldbookCard";
import GeneratedBookReader from "./GeneratedBookReader";
type Job={synopsis:string;id:string;title:string;status:string;running:boolean;completed:number;total:number;error:string;output_path:string;plan:{chapters?:{title:string;scope:string}[]};report:{narrative_chars?:number;issues?:string[]};request_message_id?:string};
type Status={message_id:string|null;proposal:{brief:string;chapter_count:number;min_chapter_chars:number}|null;jobs:Job[]};
const button="min-h-10 rounded-xl border border-zinc-200 px-4 text-sm hover:bg-zinc-50 disabled:opacity-40";
export default function StoryBuildProgress({conversationId,revision}:{conversationId:string;revision:string}) {
  const [data,setData]=useState<Status|null>(null);
  const [reading,setReading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const root="/api/story-builds/conversation/"+conversationId;
  useEffect(()=>{let stale=false;async function refresh(){try{const v=await req<Status>(root);if(!stale)setData(v);}catch(e){if(!stale)setError(String(e));}}void refresh();const timer=setInterval(()=>void refresh(),3000);return()=>{stale=true;clearInterval(timer);};},[root,revision]);
  async function action(path:string,body?:object) {
    setBusy(true);setError("");
    try{await req(path,{method:"POST",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});setData(await req<Status>(root));}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  if(!data||(!data.proposal&&!data.jobs.length))return error?<p role="alert" className="text-sm text-red-700">{error}</p>:null;
  const job=data.jobs[0];
  const unstarted=data.proposal&&!data.jobs.some(j=>j.request_message_id===data.message_id);
  return <section aria-label="世界书创作进度" className={job&&["review","imported"].includes(job.status)?"":"rounded-2xl border border-zinc-200 bg-white p-5"}>
    {unstarted&&data.proposal&&<div className="mb-5"><h3 className="font-semibold">创作方案已准备好</h3><p className="my-3 whitespace-pre-wrap text-sm leading-7 text-zinc-600">{data.proposal.brief}</p><p className="mb-4 text-sm text-zinc-500">{data.proposal.chapter_count} 章，每章至少 {data.proposal.min_chapter_chars} 字。文件自动保存到世界书文件夹。</p><button disabled={busy||job?.running} className={button} onClick={()=>void action(root+"/start",{message_id:data.message_id})}>按此方案开始创作</button></div>}
    {job&&['review','imported'].includes(job.status)?<><WorldbookCard title={job.title} synopsis={job.synopsis} onClick={()=>setReading(true)}/><div className="mt-4">{job.status==="review"?<button disabled={busy} className={button} onClick={()=>void action("/api/story-builds/"+job.id+"/import")}>{busy?"正在加入…":"加入世界书"}</button>:<p className="text-sm text-zinc-500">已加入世界书</p>}</div>{reading&&<GeneratedBookReader key={job.id} jobId={job.id} title={job.title} onClose={()=>setReading(false)}/>}</>:job&&<><h3 className="font-semibold">{job.title}</h3><p className="mt-2 text-sm text-zinc-500">{job.status==="imported"?"已加入世界书。请到设置 → 世界书中阅读或创建角色。":job.status==="review"?"全文已生成。":job.status==="memory_incomplete"?"正文已写完，角色记忆尚未完成":job.status==="awaiting_plan"?"大纲已准备好":job.running?"正在创作，完成 "+job.completed+" / "+job.total+" 章":"已保存进度，可以继续创作"}</p>
      {!!job.plan.chapters?.length&&job.status!=="imported"&&<details className="my-4 text-sm"><summary className="cursor-pointer">查看章节大纲</summary><ol className="mt-3 space-y-3">{job.plan.chapters.map((chapter,i)=><li key={i}><strong>{i+1}. {chapter.title}</strong><p className="mt-1 leading-6 text-zinc-500">{chapter.scope}</p></li>)}</ol></details>}
      {job.error&&<p className={"my-3 text-sm "+(job.running?"text-zinc-500":"text-red-700")}>{job.error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">{job.running?<button disabled={busy} className={button} onClick={()=>void action("/api/story-builds/"+job.id+"/stop")}>停止</button>:!['review','imported'].includes(job.status)&&<button disabled={busy} className={button} onClick={()=>void action("/api/story-builds/"+job.id+"/continue")}>{job.status==="memory_incomplete"?"继续补建角色记忆":job.status==="awaiting_plan"?"开始写正文":"继续创作"}</button>}
      </div>
      {job.report.narrative_chars!==undefined&&<p className="mt-3 text-xs text-zinc-500">正文 {job.report.narrative_chars} 字</p>}
      {job.report.issues?.length? <details className="mt-3 text-sm text-zinc-500"><summary>待完善内容</summary><ul className="mt-2 list-disc space-y-1 pl-5">{job.report.issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul></details>:null}
      <p className="mt-3 break-all text-xs text-zinc-400">保存位置：{job.output_path}</p>
    </>}{error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
  </section>;
}
