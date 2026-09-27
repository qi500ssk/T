"use client";
import { useRef, useState, type ComponentPropsWithoutRef } from "react";

export default function CopyCode({ children, ...props }: ComponentPropsWithoutRef<"pre">) {
  const ref = useRef<HTMLPreElement>(null);
  const [notice, setNotice] = useState("");
  return <div className="relative my-4 overflow-hidden rounded-xl border border-zinc-200">
    <div className="flex justify-end bg-zinc-100 px-3 py-1.5 text-xs text-zinc-700"><button type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(ref.current?.textContent || ""); setNotice("已复制"); }
      catch { setNotice("复制失败，请选择代码手动复制"); }
    }}>{notice || "复制代码"}</button></div>
    <pre {...props} ref={ref} className="!m-0 max-h-[32rem] overflow-auto !rounded-none">{children}</pre>
  </div>;
}
