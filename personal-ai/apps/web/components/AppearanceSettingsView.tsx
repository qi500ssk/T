"use client";

import { useEffect, useState } from "react";

import {
  DEFAULT_APPEARANCE,
  readAppearance,
  saveAppearance,
  type AppearancePreferences,
  type InterfaceScale,
} from "@/lib/appearance";


const scales: { value: InterfaceScale; label: string; description: string }[] = [
  { value: "90", label: "紧凑", description: "同屏显示更多内容" },
  { value: "100", label: "标准", description: "推荐的默认大小" },
  { value: "110", label: "放大", description: "文字和控件更醒目" },
];

export default function AppearanceSettingsView() {
  const [preferences, setPreferences] = useState<AppearancePreferences>(DEFAULT_APPEARANCE);

  useEffect(() => {
    const timer = window.setTimeout(() => setPreferences(readAppearance()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const update = (next: AppearancePreferences) => {
    setPreferences(next);
    saveAppearance(next);
  };

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <p className="text-sm font-medium text-zinc-500">基础设置</p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">外观设置</h1>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-600">只调整当前浏览器中的界面显示，不会选择项目文件夹，也不会改变 Agent 的编码权限。</p>

        <section className="mt-9 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7">
          <fieldset>
            <legend className="font-semibold">界面缩放</legend>
            <p className="mt-1 text-sm text-zinc-500">调整侧栏、文字和操作控件的整体大小。</p>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {scales.map((item) => (
                <label key={item.value} className={`cursor-pointer rounded-2xl border bg-white p-4 transition motion-reduce:transition-none ${preferences.scale === item.value ? "border-zinc-950 ring-1 ring-zinc-950" : "border-zinc-200 hover:border-zinc-400"}`}>
                  <input type="radio" name="interface-scale" value={item.value} checked={preferences.scale === item.value} onChange={() => update({ ...preferences, scale: item.value })} className="sr-only" />
                  <span className="flex items-center justify-between gap-3"><strong className="text-sm">{item.label}</strong><span className="text-xs text-zinc-400">{item.value}%</span></span>
                  <span className="mt-2 block text-xs leading-5 text-zinc-500">{item.description}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="mt-6 flex items-center justify-between gap-5 rounded-2xl border border-zinc-200 bg-white p-4">
            <div><h2 className="text-sm font-semibold">减少动态效果</h2><p className="mt-1 text-xs leading-5 text-zinc-500">关闭不必要的过渡和加载动画，界面变化更直接。</p></div>
            <label className="inline-flex min-h-11 cursor-pointer items-center">
              <span className="sr-only">减少动态效果</span>
              <input type="checkbox" checked={preferences.reduceMotion} onChange={(event) => update({ ...preferences, reduceMotion: event.target.checked })} className="peer sr-only" />
              <span aria-hidden="true" className="relative h-7 w-12 rounded-full bg-zinc-300 transition peer-checked:bg-zinc-950 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-zinc-900 after:absolute after:left-1 after:top-1 after:size-5 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5 motion-reduce:after:transition-none" />
            </label>
          </div>
        </section>
        <p className="mt-5 text-sm text-zinc-500" aria-live="polite">外观修改会自动保存到当前浏览器。</p>
      </div>
    </main>
  );
}
