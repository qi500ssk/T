"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createActivity,
  deleteActivity,
  fetchActivities,
  pauseActivity,
  resumeActivity,
  runActivityNow,
  type Activity,
  type ActivityStatus,
} from "@/lib/api";


const STATUS_LABEL: Record<ActivityStatus, string> = {
  scheduled: "已计划",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
};

const STATUS_STYLE: Record<ActivityStatus, string> = {
  scheduled: "bg-blue-50 text-blue-700",
  running: "bg-amber-50 text-amber-700",
  paused: "bg-gray-100 text-gray-600",
  completed: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-700",
};

function defaultLocalTime(): string {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatTime(value: string | null): string {
  if (!value) return "尚未运行";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

interface ActivityViewProps {
  onOpenConversation: (conversationId: string) => void;
}

export default function ActivityView({ onOpenConversation }: ActivityViewProps) {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [scheduleType, setScheduleType] = useState<"once" | "interval">("once");
  const [executionMode, setExecutionMode] = useState<"direct" | "planned">("direct");
  const [intervalMinutes, setIntervalMinutes] = useState("1440");
  const [nextRunAt, setNextRunAt] = useState(defaultLocalTime);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setActivities(await fetchActivities());
    } catch (err) {
      setError(err instanceof Error ? err.message : "活动列表加载失败");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchActivities()
      .then((rows) => {
        if (!cancelled) setActivities(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "活动列表加载失败");
      });
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    setBusy("create");
    setError("");
    try {
      await createActivity({
        title: title.trim(),
        prompt: prompt.trim(),
        schedule_type: scheduleType,
        interval_minutes: scheduleType === "interval" ? Number(intervalMinutes) : null,
        next_run_at: new Date(nextRunAt).toISOString(),
        execution_mode: executionMode,
      });
      setTitle("");
      setPrompt("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(null);
    }
  };

  const runAction = async (id: string, action: () => Promise<unknown>) => {
    setBusy(id);
    setError("");
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6">
          <p className="text-sm font-medium text-blue-600">后台执行</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">活动</h1>
          <p className="mt-2 text-sm text-gray-500">保存任务提示词，让 Agent 在指定时间自动运行。</p>
        </header>

        <form onSubmit={(event) => void handleCreate(event)} className="rounded-xl border border-gray-200 bg-gray-50 p-4 sm:p-5">
          <div className="grid gap-4 lg:grid-cols-2">
            <label className="block text-sm font-medium text-gray-700">
              标题
              <input
                required
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="mt-1.5 min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                placeholder="例如：每日资料总结"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              首次执行时间
              <input
                required
                type="datetime-local"
                value={nextRunAt}
                onChange={(event) => setNextRunAt(event.target.value)}
                className="mt-1.5 min-h-11 w-full rounded-md border border-gray-300 bg-white px-3 text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </label>
          </div>

          <label className="mt-4 block text-sm font-medium text-gray-700">
            任务内容
            <textarea
              required
              maxLength={4000}
              rows={3}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              className="mt-1.5 w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              placeholder="描述希望 Agent 完成的任务"
            />
          </label>

          <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end">
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium text-gray-700">执行模式</legend>
              <div className="inline-flex min-h-11 rounded-md bg-gray-200 p-0.5">
                {(["once", "interval"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={scheduleType === value}
                    onClick={() => setScheduleType(value)}
                    className={`rounded px-4 text-sm ${scheduleType === value ? "bg-white font-medium shadow-sm" : "text-gray-600 hover:text-gray-900"}`}
                  >
                    {value === "once" ? "一次" : "间隔"}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium text-gray-700">执行方式</legend>
              <div className="inline-flex min-h-11 rounded-md bg-gray-200 p-0.5">
                {(["direct", "planned"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={executionMode === value}
                    onClick={() => setExecutionMode(value)}
                    className={`rounded px-3 text-sm ${executionMode === value ? "bg-white font-medium shadow-sm" : "text-gray-600 hover:text-gray-900"}`}
                  >
                    {value === "direct" ? "自主" : "规划"}
                  </button>
                ))}
              </div>
            </fieldset>
            {scheduleType === "interval" && (
              <label className="block text-sm font-medium text-gray-700">
                间隔分钟
                <input
                  required
                  type="number"
                  min={1}
                  max={10080}
                  value={intervalMinutes}
                  onChange={(event) => setIntervalMinutes(event.target.value)}
                  className="mt-1.5 min-h-11 w-36 rounded-md border border-gray-300 bg-white px-3 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </label>
            )}
            <button
              type="submit"
              disabled={busy !== null}
              className="min-h-11 rounded-md bg-blue-600 px-5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-auto"
            >
              {busy === "create" ? "创建中…" : "创建活动"}
            </button>
          </div>
        </form>

        {error && <p role="alert" className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        <section className="mt-8" aria-labelledby="activity-list-title">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="activity-list-title" className="text-base font-semibold">已创建活动</h2>
            <span className="text-sm text-gray-400">{activities.length} / 100</span>
          </div>
          <div className="divide-y divide-gray-200 rounded-xl border border-gray-200">
            {activities.map((activity) => (
              <article key={activity.id} className="p-4 sm:p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium text-gray-900">{activity.title}</h3>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[activity.status]}`}>
                        {STATUS_LABEL[activity.status]}
                      </span>
                      <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
                        {activity.execution_mode === "planned" ? "规划模式" : "自主模式"}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-gray-500">{activity.prompt}</p>
                  </div>
                  <div className="shrink-0 text-right text-xs text-gray-500">
                    <p>下次：{formatTime(activity.next_run_at)}</p>
                    <p className="mt-1">上次：{formatTime(activity.last_completed_at)}</p>
                  </div>
                </div>
                {activity.last_error && (
                  <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{activity.last_error}</p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  {activity.status === "scheduled" && (
                    <button type="button" disabled={busy === activity.id} onClick={() => void runAction(activity.id, () => pauseActivity(activity.id))} className="min-h-9 rounded-md border border-gray-300 px-3 text-sm hover:bg-gray-50 disabled:opacity-50">暂停</button>
                  )}
                  {activity.status === "paused" && (
                    <button type="button" disabled={busy === activity.id} onClick={() => void runAction(activity.id, () => resumeActivity(activity.id))} className="min-h-9 rounded-md border border-gray-300 px-3 text-sm hover:bg-gray-50 disabled:opacity-50">恢复</button>
                  )}
                  {["scheduled", "completed", "failed"].includes(activity.status) && (
                    <button type="button" disabled={busy === activity.id} onClick={() => void runAction(activity.id, () => runActivityNow(activity.id))} className="min-h-9 rounded-md border border-blue-200 px-3 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50">立即运行</button>
                  )}
                  <button type="button" onClick={() => onOpenConversation(activity.conversation_id)} className="min-h-9 rounded-md border border-gray-300 px-3 text-sm hover:bg-gray-50">查看会话</button>
                  {activity.status !== "running" && (
                    <button
                      type="button"
                      disabled={busy === activity.id}
                      onClick={() => {
                        if (window.confirm(`删除活动“${activity.title}”？历史会话会保留。`)) {
                          void runAction(activity.id, () => deleteActivity(activity.id));
                        }
                      }}
                      className="min-h-9 rounded-md px-3 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50"
                    >
                      删除
                    </button>
                  )}
                </div>
              </article>
            ))}
            {activities.length === 0 && (
              <p className="px-4 py-10 text-center text-sm text-gray-400">暂无活动，先创建一个定时任务。</p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
