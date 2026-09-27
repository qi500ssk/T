"use client";

import { useRef, useState } from "react";

type Question = { title: string; options: string[] };

export function parseStoryQuestions(content: string) {
  const match = /```story-questions\s*\n([\s\S]*?)```/.exec(content);
  if (!match) return null;
  try {
    const value = JSON.parse(match[1]);
    if (!Array.isArray(value.questions) || value.questions.length < 1 || value.questions.length > 3) return null;
    if (!value.questions.every((q: Question) => typeof q.title === "string" && q.title.trim() && q.title.length <= 300 && Array.isArray(q.options) && q.options.length === 3 && q.options.every(o => typeof o === "string" && o.trim() && o.length <= 200) && new Set(q.options).size === q.options.length)) return null;
    return { questions: value.questions as Question[], text: content.replace(match[0], "").trim() };
  } catch { return null; }
}

export default function StoryQuestions({ questions, disabled, onSubmit }: { questions: Question[]; disabled: boolean; onSubmit?: (text: string) => Promise<void> }) {
  const [custom, setCustom] = useState(false);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const lock = useRef(false);
  const question = questions[0];
  async function answer(value: string) {
    if (!value.trim() || disabled || lock.current || !onSubmit) return;
    lock.current = true; setSending(true);
    try { await onSubmit(`${question.title}\n${value.trim()}`); }
    finally { lock.current = false; setSending(false); }
  }
  return <section aria-label="当前创作问题" className="mx-auto max-w-5xl rounded-2xl border border-zinc-200 bg-white p-4">
    <h3 className="mb-3 text-sm font-semibold text-zinc-900">{question.title}</h3>
    <div className="flex flex-col gap-2">
      {question.options.map((option, index) => <button key={option} type="button" disabled={disabled || sending} onClick={() => void answer(option)} className="rounded-xl border border-zinc-200 bg-white px-4 py-2.5 w-full text-left text-sm hover:border-zinc-700 hover:bg-zinc-50 disabled:opacity-40"><span className="mr-3 inline-block w-5 font-semibold">{"ABC"[index]}</span>{option}</button>)}
      <button type="button" disabled={disabled || sending} aria-expanded={custom} onClick={() => setCustom(v => !v)} className="rounded-xl border border-zinc-200 px-4 py-2.5 text-left text-sm hover:bg-zinc-50 disabled:opacity-40"><span className="mr-3 inline-block w-5 font-semibold">D</span>其他，自行填写</button>
    </div>
    {custom && <form className="mt-3 flex items-end gap-2" onSubmit={e => { e.preventDefault(); void answer(text); }}>
      <textarea autoFocus aria-label="我的想法" disabled={disabled || sending} value={text} onChange={e => setText(e.target.value)} maxLength={2000} placeholder="按你的想法来，不必局限于上面的选项" className="min-h-20 flex-1 rounded-xl border border-zinc-200 p-3 text-sm" />
      <button type="submit" disabled={disabled || sending || !text.trim()} className="rounded-xl bg-zinc-900 px-4 py-2.5 text-sm text-white disabled:opacity-40">发送想法</button>
    </form>}
    <p className="mt-2 text-xs text-zinc-500">{sending ? "正在继续…" : "点击选项回复，或选择 D 写下你的想法。"}</p>
  </section>;
}

