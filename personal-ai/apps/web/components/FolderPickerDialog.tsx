"use client";

import { useEffect, useRef, useState } from "react";

import { fetchDirectories, type DirectoryListing } from "@/lib/api";


export default function FolderPickerDialog({
  open,
  initialPath,
  onClose,
  onSelect,
}: {
  open: boolean;
  initialPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async (path?: string | null) => {
    setLoading(true);
    setError("");
    try {
      setListing(await fetchDirectories(path));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "文件夹读取失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      void load(initialPath);
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initialPath]);

  return (
    <dialog
      ref={ref}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClose={onClose}
      className="m-auto h-[min(80vh,42rem)] w-[min(94vw,46rem)] rounded-3xl bg-white p-0 text-zinc-950 shadow-2xl backdrop:bg-zinc-950/35"
      aria-labelledby="folder-dialog-title"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between border-b border-zinc-200 px-5 py-5 sm:px-6">
          <div>
            <h2 id="folder-dialog-title" className="text-xl font-bold">打开文件夹</h2>
            <p className="mt-1 text-sm text-zinc-500">选择后会授权给当前 AI 好友；再次选择同一目录可共享给其他好友。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-zinc-500 hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900" aria-label="关闭文件夹选择">×</button>
        </div>
        <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 sm:px-6">
          <button type="button" onClick={() => void load()} className="min-h-10 rounded-xl border border-zinc-200 px-3 text-sm font-medium hover:bg-zinc-50">磁盘</button>
          <button type="button" disabled={!listing?.parent_path || loading} onClick={() => void load(listing?.parent_path)} className="min-h-10 rounded-xl border border-zinc-200 px-3 text-sm font-medium hover:bg-zinc-50 disabled:opacity-40">↑ 上一级</button>
          <p className="min-w-0 flex-1 truncate rounded-xl bg-zinc-100 px-3 py-2.5 font-mono text-xs text-zinc-600" title={listing?.current_path ?? "选择磁盘"}>{listing?.current_path ?? "选择一个磁盘"}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {error && <p role="alert" className="m-3 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          {loading ? (
            <div className="grid gap-2 p-3"><div className="h-12 animate-pulse rounded-xl bg-zinc-100 motion-reduce:animate-none" /><div className="h-12 animate-pulse rounded-xl bg-zinc-100 motion-reduce:animate-none" /></div>
          ) : (
            <ul className="space-y-1">
              {listing?.directories.map((directory) => (
                <li key={directory.path}>
                  <button type="button" onClick={() => void load(directory.path)} className="flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-left text-sm hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900">
                    <span className="text-amber-500" aria-hidden="true">▰</span>
                    <span className="min-w-0 flex-1 truncate">{directory.name}</span>
                    <span className="text-xs text-zinc-400">打开 ›</span>
                  </button>
                </li>
              ))}
              {!loading && listing && listing.directories.length === 0 && <li className="px-4 py-10 text-center text-sm text-zinc-400">这个文件夹中没有子文件夹</li>}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between gap-4 border-t border-zinc-200 px-4 py-4 sm:px-6">
          <p className="hidden text-xs text-zinc-500 sm:block">这里只选择位置，不会上传文件内容</p>
          <div className="ml-auto flex gap-3">
            <button type="button" onClick={onClose} className="min-h-11 rounded-xl border border-zinc-200 px-5 text-sm font-medium hover:bg-zinc-50">取消</button>
            <button type="button" disabled={!listing?.current_path} onClick={() => listing?.current_path && onSelect(listing.current_path)} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40">选择此文件夹</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
