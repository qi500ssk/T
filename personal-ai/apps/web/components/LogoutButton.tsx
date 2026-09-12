"use client";

import { useState } from "react";
import { logout } from "@/lib/api";

export default function LogoutButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <div className="px-3 pb-3">
    <button type="button" disabled={busy} className="min-h-11 w-full rounded-xl px-3 text-left text-sm text-zinc-500 hover:bg-zinc-200 focus-visible:outline-2 disabled:opacity-50" onClick={async () => {
      setBusy(true); setError("");
      try { await logout(); window.dispatchEvent(new Event("personal-ai:unauthorized")); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "退出失败，请重试"); setBusy(false); }
    }}>{busy ? "正在退出…" : "退出登录"}</button>
    {error && <p role="alert" className="px-3 text-xs text-red-700">{error}</p>}
  </div>;
}
