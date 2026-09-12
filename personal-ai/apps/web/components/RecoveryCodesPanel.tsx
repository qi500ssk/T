"use client";

import { useState } from "react";

interface RecoveryCodesPanelProps {
  codes: string[];
  onDone: () => void;
  doneLabel: string;
}

export default function RecoveryCodesPanel({ codes, onDone, doneLabel }: RecoveryCodesPanelProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");

  const asText = () => [
    "Personal AI 账号恢复码",
    "",
    ...codes,
    "",
    "每行一个，用掉即作废；忘记密码时输入用户名和其中一组即可重设密码。",
    "请离线保存，不要在聊天或邮件里发送。",
  ].join("\n");

  async function copy() {
    try {
      await navigator.clipboard.writeText(asText());
      setNotice("已复制，请粘贴到密码管理器或离线笔记里。");
    } catch {
      setNotice("浏览器不允许自动复制，请手动选中上面的恢复码保存。");
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([asText()], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "personal-ai-recovery-codes.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  return <div>
    <p className="text-xs font-medium tracking-widest text-zinc-500">账号恢复码</p>
    <h1 className="mt-3 text-2xl font-semibold tracking-tight">把这 {codes.length} 组恢复码保存好</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-500">只显示这一次，之后无法再查看。忘记密码时输入用户名和其中任意一组即可重设，用掉的那一组随即作废。</p>
    <ul className="mt-5 grid grid-cols-2 gap-2 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 font-mono text-sm tabular-nums sm:text-base">
      {codes.map((code) => <li key={code} className="select-all rounded-lg bg-white px-3 py-2 text-center tracking-wider">{code}</li>)}
    </ul>
    <div className="mt-4 flex flex-wrap gap-3">
      <button type="button" onClick={copy} className="min-h-11 rounded-xl border border-zinc-300 px-4 text-sm font-medium hover:bg-zinc-50">复制全部</button>
      <button type="button" onClick={download} className="min-h-11 rounded-xl border border-zinc-300 px-4 text-sm font-medium hover:bg-zinc-50">下载为文本</button>
    </div>
    {notice && <p role="status" className="mt-3 text-xs leading-5 text-zinc-500">{notice}</p>}
    <label className="mt-5 flex items-start gap-3 rounded-2xl bg-amber-50 p-4 text-sm leading-6 text-amber-900">
      <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-1.5 size-4 rounded border-amber-300"/>
      我已经把恢复码保存到这台电脑以外的地方。它和密码一样重要，丢失后没有任何办法找回账号。
    </label>
    <button type="button" disabled={!confirmed} onClick={onDone} className="mt-5 min-h-12 w-full rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40">{doneLabel}</button>
  </div>;
}
