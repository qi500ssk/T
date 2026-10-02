"use client";
import LibraryCard from "./LibraryCard";
export default function WorldbookCard({title,synopsis,onClick,onDelete,disabled,compact=false}:{title:string;synopsis:string;onClick:()=>void;onDelete?:()=>void;disabled?:boolean;compact?:boolean}) {
  if(compact)return <LibraryCard title={title} description={synopsis} onOpen={onClick} onDelete={onDelete} disabled={disabled}/>;
  return <article className="flex min-h-64 flex-col rounded-2xl border border-zinc-200 bg-white p-6 transition hover:border-zinc-400">
    <button type="button" onClick={onClick} className="flex-1 rounded-lg text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-900">
      <h2 className="break-words text-lg font-semibold leading-7">{title}</h2>
      <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-zinc-500">{synopsis}</p>
    </button>
    {onDelete&&<div className="mt-4 flex justify-end"><button type="button" onClick={onDelete} disabled={disabled} aria-label={`删除${title}`} className="min-h-9 rounded-lg px-2 text-xs text-red-600 hover:bg-red-50 disabled:opacity-40">删除</button></div>}
  </article>;
}
