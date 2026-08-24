import type { Plan } from "@/lib/api";


const LABEL: Record<string, string> = {
  pending: "等待",
  running: "执行中",
  interrupted: "已中断",
  completed: "完成",
  blocked: "受阻",
  failed: "失败",
  superseded: "已替换",
  cancelled: "已取消",
};

export default function PlanProgress({ plan }: { plan: Plan | null }) {
  if (!plan) return null;
  return (
    <section className="mx-auto w-full max-w-3xl rounded-xl border border-indigo-200 bg-indigo-50/60 p-4" aria-live="polite" aria-label="计划执行进度">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-indigo-950">{plan.goal}</h3>
        <span className="text-xs text-indigo-700">版本 {plan.current_version}{plan.replan_count ? ` · 已重规划 ${plan.replan_count} 次` : ""}</span>
      </div>
      <ol className="mt-3 space-y-2">
        {plan.steps.map((step) => (
          <li key={step.id} className={`rounded-md border bg-white px-3 py-2 text-sm ${step.status === "superseded" ? "opacity-50" : ""}`}>
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${step.status === "completed" ? "bg-emerald-500" : step.status === "running" ? "animate-pulse bg-blue-500 motion-reduce:animate-none" : step.status === "interrupted" ? "bg-amber-500" : ["blocked", "failed"].includes(step.status) ? "bg-red-500" : "bg-gray-300"}`} />
              <span className="font-medium text-gray-800">{step.title}</span>
              <span className="ml-auto text-xs text-gray-500">{LABEL[step.status] ?? step.status}</span>
            </div>
            {step.output_summary && <p className="mt-1 line-clamp-2 pl-4 text-xs text-gray-600">{step.output_summary}</p>}
            {step.error && <p className="mt-1 pl-4 text-xs text-red-700">{step.error}</p>}
          </li>
        ))}
      </ol>
    </section>
  );
}
