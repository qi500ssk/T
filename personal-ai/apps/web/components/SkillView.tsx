"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  createSkill,
  deleteSkill,
  fetchSkills,
  importSkillFolder,
  refreshSkills,
  updateSkill,
  type SkillItem,
} from "@/lib/api";


const sourceLabel: Record<SkillItem["source"], string> = {
  builtin: "内置",
  local: "本地导入",
  online: "在线下载",
  demo: "开发测试",
};

const statusLabel: Record<SkillItem["status"], string> = {
  enabled: "已启用",
  disabled: "已关闭",
  missing_dependencies: "缺少依赖",
  invalid: "格式错误",
};

function CreateSkillDialog({
  open,
  busy,
  onClose,
  onCreate,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onCreate: (body: {
    id: string;
    name: string;
    description: string;
    instructions: string;
    required_tools: string[];
  }) => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const tools = String(data.get("required_tools") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    void onCreate({
      id: String(data.get("id") || "").trim(),
      name: String(data.get("name") || "").trim(),
      description: String(data.get("description") || "").trim(),
      instructions: String(data.get("instructions") || "").trim(),
      required_tools: tools,
    });
  };

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        if (busy) event.preventDefault();
        else onClose();
      }}
      onClose={onClose}
      className="m-auto w-[min(92vw,42rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35"
      aria-labelledby="create-skill-title"
    >
      <form onSubmit={handleSubmit} className="p-6 sm:p-8">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h2 id="create-skill-title" className="text-2xl font-bold">新建 Skill</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-600">创建后默认关闭，确认内容无误后再启用。</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-lg px-3 py-2 text-zinc-500 hover:bg-zinc-100" aria-label="关闭">×</button>
        </div>
        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          <label className="grid gap-2 text-sm font-medium">
            Skill ID
            <input autoFocus name="id" required minLength={2} maxLength={64} pattern="[a-z0-9][a-z0-9-]+" placeholder="daily-writing" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" />
            <span className="text-xs font-normal text-zinc-500">小写字母、数字和连字符</span>
          </label>
          <label className="grid gap-2 text-sm font-medium">
            显示名称
            <input name="name" required maxLength={80} placeholder="日常写作" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" />
          </label>
          <label className="grid gap-2 text-sm font-medium sm:col-span-2">
            用途说明
            <input name="description" required maxLength={300} placeholder="帮助整理和润色日常文字" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" />
          </label>
          <label className="grid gap-2 text-sm font-medium sm:col-span-2">
            执行指令
            <textarea name="instructions" required maxLength={20000} rows={7} placeholder="说明什么情况下使用，以及应该怎样完成任务……" className="resize-y rounded-xl border border-zinc-300 px-3 py-3 font-normal leading-6 outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" />
          </label>
          <label className="grid gap-2 text-sm font-medium sm:col-span-2">
            所需工具（可选）
            <input name="required_tools" placeholder="get_time, calculate" className="h-11 rounded-xl border border-zinc-300 px-3 font-normal outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" />
            <span className="text-xs font-normal text-zinc-500">多个工具用英文逗号分隔；不存在的工具会被拒绝。</span>
          </label>
        </div>
        <div className="mt-7 flex justify-end gap-3">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50">取消</button>
          <button type="submit" disabled={busy} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy ? "创建中…" : "创建 Skill"}</button>
        </div>
      </form>
    </dialog>
  );
}

function DeleteSkillDialog({ item, busy, onClose, onConfirm }: { item: SkillItem | null; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (item && !dialog.open) dialog.showModal();
    if (!item && dialog.open) dialog.close();
  }, [item]);
  return (
    <dialog ref={dialogRef} onCancel={(event) => busy ? event.preventDefault() : onClose()} onClose={onClose} className="m-auto w-[min(92vw,28rem)] rounded-3xl bg-white p-0 shadow-2xl backdrop:bg-zinc-950/35" aria-labelledby="delete-skill-title">
      <div className="p-6 sm:p-8">
        <h2 id="delete-skill-title" className="text-xl font-bold text-zinc-950">删除 {item?.name}？</h2>
        <p className="mt-3 text-sm leading-6 text-zinc-600">Skill 文件夹会移入项目回收目录，可以手动恢复，不会立即永久删除。</p>
        <div className="mt-7 flex justify-end gap-3">
          <button type="button" autoFocus onClick={onClose} disabled={busy} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50">取消</button>
          <button type="button" onClick={onConfirm} disabled={busy} className="min-h-11 rounded-xl bg-red-600 px-5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">{busy ? "处理中…" : "移入回收目录"}</button>
        </div>
      </div>
    </dialog>
  );
}

function SkillRow({
  item,
  busy,
  expanded,
  onToggle,
  onExpand,
  onDelete,
}: {
  item: SkillItem;
  busy: boolean;
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onDelete: () => void;
}) {
  const statusTone = item.available
    ? item.enabled
      ? "bg-emerald-50 text-emerald-700"
      : "bg-zinc-100 text-zinc-600"
    : "bg-amber-50 text-amber-700";

  return (
    <article className="border-b border-zinc-200 last:border-b-0">
      <div className="flex min-h-24 items-center gap-4 px-5 py-4 sm:px-6">
        <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-white text-lg shadow-sm ring-1 ring-zinc-200" aria-hidden="true">
          ✦
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-zinc-950">{item.name}</h3>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusTone}`}>
              {statusLabel[item.status]}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-sm leading-6 text-zinc-600">{item.description}</p>
          {item.error && <p className="mt-1 text-xs text-amber-700">{item.error}</p>}
        </div>
        <button
          type="button"
          onClick={onExpand}
          className="hidden rounded-lg px-3 py-2 text-sm text-zinc-500 hover:bg-white hover:text-zinc-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 sm:block"
          aria-expanded={expanded}
          aria-controls={`skill-details-${item.id}`}
        >
          {expanded ? "收起" : "详情"}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={item.enabled}
          aria-label={`${item.enabled ? "关闭" : "启用"}${item.name}`}
          disabled={!item.available || busy}
          onClick={onToggle}
          className={`relative h-7 w-12 shrink-0 rounded-full transition-colors motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-not-allowed disabled:opacity-45 ${
            item.enabled ? "bg-zinc-950" : "bg-zinc-300"
          }`}
        >
          <span
            className={`absolute top-1 size-5 rounded-full bg-white shadow-sm transition-transform motion-reduce:transition-none ${
              item.enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>
      {expanded && (
        <div id={`skill-details-${item.id}`} className="border-t border-zinc-200 bg-white px-6 py-5 sm:pl-[5.75rem]">
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-medium text-zinc-900">来源</dt>
              <dd className="mt-1 text-zinc-600">{sourceLabel[item.source]}</dd>
            </div>
            <div>
              <dt className="font-medium text-zinc-900">所需工具</dt>
              <dd className="mt-1 text-zinc-600">{item.required_tools.join("、") || "无需工具"}</dd>
            </div>
          </dl>
          <div className="mt-4">
            <p className="text-sm font-medium text-zinc-900">执行说明</p>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-zinc-600">{item.instructions || "无法读取"}</p>
          </div>
          {item.deletable && (
            <button type="button" onClick={onDelete} className="mt-5 rounded-xl border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600">
              删除本地 Skill
            </button>
          )}
        </div>
      )}
    </article>
  );
}

export default function SkillView() {
  const [items, setItems] = useState<SkillItem[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SkillItem | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSkills()
      .then((rows) => {
        if (!cancelled) setItems(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "技能加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) =>
      `${item.name} ${item.description} ${item.required_tools.join(" ")}`
        .toLowerCase()
        .includes(needle),
    );
  }, [items, query]);

  const groups = useMemo(
    () => [
      { key: "builtin", title: "内置技能", items: filtered.filter((item) => item.source === "builtin") },
      { key: "local", title: "本地与在线", items: filtered.filter((item) => item.source === "local" || item.source === "online") },
      { key: "demo", title: "开发测试", items: filtered.filter((item) => item.source === "demo") },
    ],
    [filtered],
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      const rows = await refreshSkills();
      setItems(rows);
      setNotice(`已重新扫描，共发现 ${rows.length} 个技能`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新失败");
    } finally {
      setRefreshing(false);
    }
  };

  const handleToggle = async (item: SkillItem) => {
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      const updated = await updateSkill(item.id, !item.enabled);
      setItems((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      setNotice(`${item.name} 已${updated.enabled ? "启用" : "关闭"}，将在新对话运行中生效`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新失败");
    } finally {
      setBusyId(null);
    }
  };

  const handleImport = async (files: File[]) => {
    if (!files.length) return;
    setImporting(true);
    setError("");
    setNotice("");
    try {
      const installed = await importSkillFolder(files);
      const rows = await fetchSkills();
      setItems(rows);
      setNotice(`${installed.name} 已导入，默认处于关闭状态`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文件夹导入失败");
    } finally {
      setImporting(false);
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  };

  const handleCreate = async (body: Parameters<typeof createSkill>[0]) => {
    setCreating(true);
    setError("");
    setNotice("");
    try {
      const created = await createSkill(body);
      setItems((current) => [...current, created]);
      setCreateOpen(false);
      setNotice(`${created.name} 已创建，默认处于关闭状态`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setBusyId(target.id);
    setError("");
    setNotice("");
    try {
      await deleteSkill(target.id);
      setItems((current) => current.filter((item) => item.id !== target.id));
      setDeleteTarget(null);
      setExpandedId(null);
      setNotice(`${target.name} 已移入回收目录`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const enabledCount = items.filter((item) => item.enabled).length;

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-medium text-zinc-500">Agent 能力</p>
            <h1 className="mt-2 text-4xl font-bold tracking-tight text-zinc-950 sm:text-5xl">技能</h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-600">
              技能是 Agent 可选择使用的任务说明。启用后只把名称与用途加入目录，Agent 会在真正需要时按需读取完整说明。
            </p>
          </div>
          <label className="relative block w-full lg:w-96">
            <span className="sr-only">搜索技能</span>
            <svg className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-zinc-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <circle cx="11" cy="11" r="7" strokeWidth="1.8" />
              <path d="m16.5 16.5 4 4" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索技能…"
              className="h-12 w-full rounded-2xl border border-zinc-200 bg-white pl-12 pr-4 text-sm outline-none transition focus:border-zinc-400 focus:ring-4 focus:ring-zinc-100"
            />
          </label>
        </div>

        <div className="mt-10 flex flex-wrap items-center gap-3 border-b border-zinc-200 pb-5">
          <div className="mr-auto">
            <span className="font-medium text-zinc-950">已发现 {items.length}</span>
            <span className="ml-3 text-sm text-zinc-500">已启用 {enabledCount}</span>
          </div>
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            className="min-h-10 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:opacity-50"
          >
            {refreshing ? "扫描中…" : "↻ 刷新"}
          </button>
          <input
            ref={(element) => {
              folderInputRef.current = element;
              element?.setAttribute("webkitdirectory", "");
              element?.setAttribute("directory", "");
            }}
            type="file"
            multiple
            className="sr-only"
            tabIndex={-1}
            onChange={(event) => void handleImport(Array.from(event.target.files ?? []))}
          />
          <button type="button" onClick={() => folderInputRef.current?.click()} disabled={importing} className="min-h-10 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:opacity-50">
            {importing ? "导入中…" : "导入文件夹"}
          </button>
          <button type="button" onClick={() => setCreateOpen(true)} className="min-h-10 rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900">
            ＋ 新建
          </button>
        </div>

        <div className="min-h-8 pt-3 text-sm" aria-live="polite" aria-atomic="true">
          {error ? <p role="alert" className="text-red-700">{error}</p> : notice ? <p className="text-emerald-700">{notice}</p> : null}
        </div>

        {loading ? (
          <div className="mt-5 space-y-4" aria-label="正在加载技能">
            {[0, 1, 2].map((item) => <div key={item} className="h-24 animate-pulse rounded-3xl bg-zinc-100 motion-reduce:animate-none" />)}
          </div>
        ) : (
          <div className="mt-2 space-y-10">
            {groups.map((group) => group.items.length > 0 && (
              <section key={group.key} aria-labelledby={`skill-group-${group.key}`}>
                <div className="mb-3 flex items-baseline gap-2">
                  <h2 id={`skill-group-${group.key}`} className="text-lg font-semibold text-zinc-950">{group.title}</h2>
                  <span className="text-sm text-zinc-400">{group.items.length}</span>
                </div>
                <div className="overflow-hidden rounded-3xl bg-zinc-100 ring-1 ring-zinc-200">
                  {group.items.map((item) => (
                    <SkillRow
                      key={item.id}
                      item={item}
                      busy={busyId === item.id}
                      expanded={expandedId === item.id}
                      onExpand={() => setExpandedId((current) => current === item.id ? null : item.id)}
                      onToggle={() => void handleToggle(item)}
                      onDelete={() => setDeleteTarget(item)}
                    />
                  ))}
                </div>
              </section>
            ))}
            {filtered.length === 0 && (
              <div className="rounded-3xl border border-dashed border-zinc-300 px-6 py-16 text-center">
                <p className="font-medium text-zinc-800">没有找到匹配的技能</p>
                <p className="mt-2 text-sm text-zinc-500">换一个名称、描述或工具名试试。</p>
              </div>
            )}
          </div>
        )}
      </div>
      <CreateSkillDialog open={createOpen} busy={creating} onClose={() => setCreateOpen(false)} onCreate={handleCreate} />
      <DeleteSkillDialog item={deleteTarget} busy={busyId === deleteTarget?.id} onClose={() => setDeleteTarget(null)} onConfirm={() => void handleDelete()} />
    </main>
  );
}
