"use client";
import type { ReactNode } from "react";
export default function LibraryCard({title,description,avatar,onOpen,onDelete,disabled=false,deleteDisabled=false,deleteTitle="删除"}:{title:string;description:string;avatar?:ReactNode;onOpen:()=>void;onDelete?:()=>void;disabled?:boolean;deleteDisabled?:boolean;deleteTitle?:string}) {
  return <article className="flex h-36 flex-col rounded-2xl border border-zinc-200 bg-white p-5">
    <button type="button" onClick={onOpen} className="flex min-h-14 w-full items-center gap-3 rounded-xl px-2 py-2 text-left focus-visible:outline-2 focus-visible:outline-zinc-900">{avatar}<span className="min-w-0 flex-1"><strong className="block truncate text-sm">{title}</strong><span className="mt-1 block truncate text-xs text-zinc-500">{description}</span></span></button>
    {onDelete&&<div className="mt-auto flex justify-end"><button type="button" disabled={disabled||deleteDisabled} onClick={onDelete} title={deleteTitle} aria-label={`删除${title}`} className="min-h-9 rounded-lg px-2 text-xs text-red-600 hover:bg-red-50 disabled:text-zinc-300">删除</button></div>}
  </article>;
}
