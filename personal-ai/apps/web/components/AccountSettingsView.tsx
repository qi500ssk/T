"use client";

import { useCallback, useEffect, useState } from "react";

import RecoveryCodesPanel from "@/components/RecoveryCodesPanel";
import {
  changePassword, fetchAuthStatus, fetchRecoveryCodes, logoutAll,
  regenerateRecoveryCodes, type RecoveryCodeSummary,
} from "@/lib/api";

const inputClass = "h-11 w-full rounded-xl border border-zinc-300 bg-white px-3 text-sm outline-none transition focus:border-zinc-500 focus:ring-4 focus:ring-zinc-100 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-500";

export default function AccountSettingsView() {
  const [username, setUsername] = useState("");
  const [codes, setCodes] = useState<RecoveryCodeSummary | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [applying, setApplying] = useState(false);
  const [regeneratePassword, setRegeneratePassword] = useState("");
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [recoveryError, setRecoveryError] = useState("");

  const loadCodes = useCallback(() => {
    fetchRecoveryCodes().then(setCodes).catch(() => undefined);
  }, []);

  useEffect(() => {
    fetchAuthStatus().then((status) => setUsername(status.username ?? "")).catch(() => undefined);
    loadCodes();
  }, [loadCodes]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(""); setError("");
    if (next !== confirm) { setError("两次输入的新密码不一致"); return; }
    if (next.length < 12) { setError("新密码至少 12 个字符"); return; }
    setBusy("password");
    try {
      await changePassword(current, next);
      setCurrent(""); setNext(""); setConfirm("");
      setNotice("密码已更新，其他设备上的登录已退出。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "修改失败，请重试");
    } finally { setBusy(""); }
  }

  async function submitRegenerate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(""); setRecoveryError("");
    setBusy("regenerate");
    try {
      const result = await regenerateRecoveryCodes(regeneratePassword);
      setRegeneratePassword("");
      setApplying(false);
      setNewCodes(result.recovery_codes);
    } catch (reason) {
      setRecoveryError(reason instanceof Error ? reason.message : "生成失败，请重试");
    } finally { setBusy(""); }
  }

  if (newCodes) return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <section className="rounded-3xl border border-zinc-200 bg-white p-6 ring-1 ring-zinc-100 sm:p-9">
          <RecoveryCodesPanel codes={newCodes} doneLabel="我已保存，返回账号设置" onDone={() => { setNewCodes(null); loadCodes(); }}/>
        </section>
      </div>
    </main>
  );

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-white">
      <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8 lg:px-14 lg:py-14">
        <p className="text-sm font-medium text-zinc-500">基础设置</p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight sm:text-5xl">账号与安全</h1>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-zinc-600">账号和数据保存在本机，不随浏览器同步。使用云端模型或云端 Embedding 时，必要的对话和资料内容会发送给所配置的服务。</p>

        <section className="mt-9 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7" aria-labelledby="account-name">
          <h2 id="account-name" className="text-lg font-semibold">当前账号</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500">每次安装只创建一个本机账号，用于保护你的对话、记忆、知识库和文件。</p>
          <p className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-zinc-200 bg-white px-4 font-mono text-sm">{username || "…"}</p>
        </section>

        <section className="mt-6 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7" aria-labelledby="account-recovery">
          <h2 id="account-recovery" className="text-lg font-semibold">账号恢复码</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500">忘记密码时用恢复码重设，是唯一的找回方式。恢复码只在生成时显示一次。</p>
          {codes && <p className="mt-4 text-sm text-zinc-700">共 {codes.total} 组，已使用 {codes.used} 组，剩余 <strong className={codes.remaining > 0 ? "text-zinc-950" : "text-red-700"}>{codes.remaining}</strong> 组。</p>}
          {codes?.remaining === 0 && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">恢复码已用尽。重新生成一组，否则忘记密码将无法恢复。</p>}
          {applying ? <form onSubmit={submitRegenerate} className="mt-4 flex flex-wrap items-end gap-3">
            <label className="grid min-w-64 flex-1 gap-2 text-sm font-medium">当前密码<input type="password" required maxLength={128} autoComplete="current-password" value={regeneratePassword} onChange={(e) => setRegeneratePassword(e.target.value)} className={inputClass} disabled={busy !== ""}/><span className="text-xs font-normal text-zinc-500">确认身份后会作废现有的全部恢复码</span></label>
            <button type="submit" disabled={busy !== "" || !regeneratePassword} className="min-h-11 rounded-xl bg-zinc-950 px-5 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy === "regenerate" ? "正在生成…" : "生成新恢复码"}</button>
            <button type="button" disabled={busy !== ""} onClick={() => { setApplying(false); setRegeneratePassword(""); }} className="min-h-11 rounded-xl border border-zinc-300 bg-white px-5 text-sm font-medium hover:bg-zinc-50">取消</button>
          </form> : <button type="button" disabled={busy !== ""} onClick={() => { setApplying(true); setNotice(""); setRecoveryError(""); }} className="mt-4 min-h-11 rounded-xl border border-zinc-300 bg-white px-5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50">重新生成恢复码</button>}
          {recoveryError && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{recoveryError}</p>}
        </section>

        <section className="mt-6 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7" aria-labelledby="account-password">
          <h2 id="account-password" className="text-lg font-semibold">修改密码</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500">修改后其他设备需要重新登录，当前设备保持登录状态。</p>
          <form onSubmit={submit} className="mt-5 grid gap-5 sm:grid-cols-3">
            <label className="grid gap-2 text-sm font-medium">当前密码<input type="password" required maxLength={128} autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} className={inputClass} disabled={busy !== ""}/></label>
            <label className="grid gap-2 text-sm font-medium">新密码<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className={inputClass} disabled={busy !== ""}/><span className="text-xs font-normal text-zinc-500">至少 12 个字符</span></label>
            <label className="grid gap-2 text-sm font-medium">确认新密码<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={inputClass} disabled={busy !== ""}/></label>
            <div className="sm:col-span-3 flex justify-end"><button type="submit" disabled={busy !== "" || !current || !next || !confirm} className="min-h-11 rounded-xl bg-zinc-950 px-6 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50">{busy === "password" ? "正在保存…" : "保存新密码"}</button></div>
          </form>
        </section>

        <section className="mt-6 rounded-3xl bg-zinc-100 p-5 ring-1 ring-zinc-200 sm:p-7" aria-labelledby="account-sessions">
          <h2 id="account-sessions" className="text-lg font-semibold">登录状态</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500">退出全部设备会立刻撤销所有登录会话，包括当前这台电脑。</p>
          <button type="button" disabled={busy !== ""} onClick={async () => {
            setBusy("sessions"); setNotice(""); setError("");
            try {
              await logoutAll();
              window.dispatchEvent(new Event("personal-ai:unauthorized"));
            } catch (reason) {
              setError(reason instanceof Error ? reason.message : "操作失败，请重试");
              setBusy("");
            }
          }} className="mt-4 min-h-11 rounded-xl border border-red-200 bg-white px-5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">{busy === "sessions" ? "正在退出…" : "退出全部设备"}</button>
        </section>

        <div className="min-h-12 pt-5 text-sm" aria-live="polite">{error ? <p role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-red-700">{error}</p> : notice ? <p className="rounded-xl bg-emerald-50 px-4 py-3 text-emerald-700">{notice}</p> : null}</div>
      </div>
    </main>
  );
}
