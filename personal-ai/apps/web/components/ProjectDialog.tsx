"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { FolderDialog } from "@/components/GeneralSettingsView";


export default function ProjectDialog({
  open,
  initialWorkspace,
  onClose,
  onCreate,
}: {
  open: boolean;
  initialWorkspace: string;
  onClose: () => void;
  onCreate: (name: string, workspaceDir: string | null) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const [folderOpen, setFolderOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setName("");
      setWorkspace(initialWorkspace);
      setError("");
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initialWorkspace]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await onCreate(name.trim(), workspace.trim() || null);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "项目创建失败");
    } finally {
      setBusy(false);
    }
  };

  return <>
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} onClose={onClose} className="m-auto w-[min(92vw,34rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35" aria-labelledby="project-dialog-title">
      <form onSubmit={submit} className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="project-dialog-title" className="text-xl font-bold">新建项目</h2><p className="mt-1 text-sm text-zinc-500">任务会按项目归类，编码能力使用项目文件夹。</p></div>
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-zinc-500 hover:bg-zinc-100" aria-label="关闭">×</button>
        </div>
        <label className="mt-6 block text-sm font-medium text-zinc-700">项目名称<input autoFocus value={name} onChange={(event) => setName(event.target.value)} maxLength={120} placeholder="例如：个人网站" className="mt-2 h-11 w-full rounded-xl border border-zinc-300 px-3 outline-none focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100" /></label>
        <div className="mt-5"><span className="text-sm font-medium text-zinc-700">项目文件夹</span><button type="button" onClick={() => setFolderOpen(true)} className="mt-2 flex min-h-11 w-full items-center gap-3 rounded-xl border border-zinc-300 px-3 text-left text-sm hover:bg-zinc-50"><span aria-hidden="true">▱</span><span className="min-w-0 flex-1 truncate text-zinc-600">{workspace || "选择文件夹"}</span><span className="text-zinc-400">浏览</span></button></div>
        {error && <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
        <div className="mt-7 flex justify-end gap-3"><button type="button" onClick={onClose} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm font-medium hover:bg-zinc-50">取消</button><button type="submit" disabled={!name.trim() || !workspace.trim() || busy} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40">{busy ? "创建中…" : "创建项目"}</button></div>
      </form>
    </dialog>
    <FolderDialog open={folderOpen} initialPath={workspace} onClose={() => setFolderOpen(false)} onSelect={(path) => { setWorkspace(path); setFolderOpen(false); }} />
  </>;
}
