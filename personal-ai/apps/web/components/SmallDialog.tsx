"use client";
import { useEffect, useRef, type ReactNode } from "react";

export default function SmallDialog({title, onClose, children, size = "default"}: {title:string;onClose:()=>void;children:ReactNode;size?:"default"|"large"}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node=ref.current; node?.showModal(); return () => node?.close(); }, []);
  return <dialog ref={ref} onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose();}} className={`m-auto overflow-y-auto rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-xl backdrop:bg-black/30 ${size === "large" ? "h-[88dvh] max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] md:w-[76vw]" : "max-h-[85dvh] w-[min(42rem,calc(100%-2rem))]"}`} aria-label={title}>
    <header className="mb-5 flex items-center justify-between gap-4"><h2 className="text-lg font-semibold">{title}</h2><button type="button" onClick={onClose} aria-label="关闭" className="size-10 rounded-lg hover:bg-zinc-100">×</button></header>{children}
  </dialog>;
}
