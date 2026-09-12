"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import RecoveryCodesPanel from "@/components/RecoveryCodesPanel";
import { fetchAuthStatus, login, recoverAccount, setupAdmin, type AuthStatus } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [mode, setMode] = useState<"form" | "recovery">("form");
  const [issuedCodes, setIssuedCodes] = useState<string[] | null>(null);
  const [recovered, setRecovered] = useState<number | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [token, setToken] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const usernameRef = useRef<HTMLInputElement>(null);

  const setup = status?.setup_required ?? false;
  const needsToken = status?.setup_token_required ?? false;
  const fill = (reason: unknown, fallback: string) => setError(reason instanceof Error ? reason.message : fallback);

  useEffect(() => {
    fetchAuthStatus().then((value) => {
      if (value.authenticated) router.replace("/");
      else setStatus(value);
    }).catch((reason) => fill(reason, "暂时无法连接本地服务"));
  }, [router]);

  useEffect(() => { if (status && !issuedCodes) usernameRef.current?.focus(); }, [status, issuedCodes, mode]);

  async function submitAuth(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!status) return;
    setError("");
    if (setup && password !== confirm) { setError("两次输入的密码不一致"); return; }
    setBusy(true);
    try {
      if (setup) setIssuedCodes((await setupAdmin(username.trim(), password, token.trim())).recovery_codes);
      else {
        await login(username.trim(), password, remember);
        router.replace("/");
      }
    } catch (reason) { fill(reason, "登录失败，请重试"); } finally { setBusy(false); }
  }

  async function submitRecovery(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password !== confirm) { setError("两次输入的新密码不一致"); return; }
    if (password.length < 12) { setError("新密码至少 12 个字符"); return; }
    setBusy(true);
    try {
      const result = await recoverAccount(username.trim(), recoveryCode.trim(), password);
      setRecovered(result.recovery_codes_remaining);
      setPassword(""); setConfirm(""); setRecoveryCode("");
    } catch (reason) { fill(reason, "重设失败，请检查用户名和恢复码"); } finally { setBusy(false); }
  }

  const inputClass = "mt-2 min-h-12 w-full rounded-xl border border-zinc-200 bg-white px-4 text-base text-zinc-950 outline-none transition focus:border-zinc-600 focus:ring-2 focus:ring-zinc-200 disabled:bg-zinc-100";
  const linkClass = "text-xs font-medium text-zinc-500 underline underline-offset-4 hover:text-zinc-950";
  const card = (content: React.ReactNode) => <main className="flex min-h-dvh items-center justify-center bg-zinc-50 px-5 py-10 text-zinc-950">
    <div className="w-full max-w-md">
      <div className="mb-8 flex items-center justify-center gap-3"><span aria-hidden="true" className="grid size-10 place-items-center rounded-2xl bg-zinc-950 text-xl text-white">✦</span><span className="text-lg font-semibold tracking-tight">Personal AI</span></div>
      <section className="rounded-3xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-9">{content}</section>
      <p className="mt-6 text-center text-xs leading-6 text-zinc-500">本机账号 · 本地保存 · 模型服务由你选择</p>
    </div>
  </main>;

  if (status === null) return card(<>
    <h1 className="text-2xl font-semibold tracking-tight">正在连接本地服务…</h1>
    <p role={error ? "alert" : "status"} className={`mt-4 text-sm ${error ? "text-red-700" : "text-zinc-500"}`}>{error || "稍等一下，马上就好。"}</p>
    {error && <button onClick={() => window.location.reload()} className="mt-4 min-h-11 rounded-xl border px-4">重新连接</button>}
  </>);

  if (issuedCodes) return card(<RecoveryCodesPanel codes={issuedCodes} doneLabel="进入工作区" onDone={() => router.replace("/")}/>);

  if (recovered !== null) return card(<>
    <p className="text-xs font-medium tracking-widest text-zinc-500">密码已重设</p>
    <h1 className="mt-3 text-2xl font-semibold tracking-tight">可以继续使用了</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-500">{recovered > 0 ? `其他设备上的登录已退出。你还有 ${recovered} 组未使用的恢复码。` : "其他设备上的登录已退出。这是最后一组恢复码，已经用掉了。"}</p>
    {recovered === 0 && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">进入后请到“设置 → 账号与安全”重新生成一批恢复码，否则下次忘记密码就无法恢复了。</p>}
    <button onClick={() => router.replace("/")} className="mt-6 min-h-12 w-full rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white hover:bg-zinc-800">进入工作区</button>
  </>);

  if (mode === "recovery") return card(<>
    <p className="mb-3 text-xs font-medium tracking-widest text-zinc-500">忘记密码</p>
    <h1 className="text-2xl font-semibold tracking-tight">用恢复码重设密码</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-500">输入创建账号时保存的任意一组恢复码。用掉的那一组会立即作废，其他设备上的登录会被退出。</p>
    <form onSubmit={submitRecovery} className="mt-7 space-y-5">
      <div><label htmlFor="recovery-username" className="text-sm font-medium">用户名</label><input id="recovery-username" value={username} onChange={(e) => setUsername(e.target.value)} required maxLength={80} autoComplete="username" autoCapitalize="none" spellCheck={false} className={inputClass} disabled={busy}/></div>
      <div><label htmlFor="recovery-code" className="text-sm font-medium">恢复码</label><input id="recovery-code" value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} required maxLength={64} autoComplete="off" spellCheck={false} placeholder="XXXX-XXXX" className={`${inputClass} font-mono tracking-widest`} disabled={busy}/></div>
      <div><label htmlFor="recovery-password" className="text-sm font-medium">新密码</label><input id="recovery-password" type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} maxLength={128} autoComplete="new-password" className={inputClass} disabled={busy}/><p className="mt-2 text-xs text-zinc-500">至少 12 个字符</p></div>
      <div><label htmlFor="recovery-confirm" className="text-sm font-medium">确认新密码</label><input id="recovery-confirm" type={showPassword ? "text" : "password"} value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={12} maxLength={128} autoComplete="new-password" className={inputClass} disabled={busy}/></div>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm leading-6 text-red-700">{error}</p>}
      <button disabled={busy} type="submit" className="min-h-12 w-full rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-wait disabled:opacity-60">{busy ? "正在处理…" : "重设密码并登录"}</button>
      <button type="button" onClick={() => { setMode("form"); setError(""); }} className={`${linkClass} block w-full text-center`}>返回登录</button>
    </form>
  </>);

  return card(<>
    <p className="mb-3 text-xs font-medium tracking-widest text-zinc-500">{setup ? "第一次使用" : "本机账号"}</p>
    <h1 className="text-2xl font-semibold tracking-tight">{setup ? "创建你的账号" : "欢迎回来"}</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-500">{setup ? "账号只保存在这台电脑上，用来保护你的对话、知识与文件。" : "登录后继续你的对话、知识库与代码项目。"}</p>
    <form onSubmit={submitAuth} className="mt-7 space-y-5">
      {setup && needsToken && <div><label htmlFor="setup-token" className="text-sm font-medium">首次设置码</label><input id="setup-token" value={token} onChange={(e) => setToken(e.target.value)} required maxLength={128} autoComplete="off" spellCheck={false} className={inputClass} disabled={busy} aria-describedby="setup-help"/><p id="setup-help" className="mt-2 text-xs leading-5 text-zinc-500">这次访问不是来自运行服务的电脑。请在主机查看 <code className="break-all">data/auth-setup-token</code> 文件内容后填入。</p></div>}
      <div><label htmlFor="username" className="text-sm font-medium">用户名</label><input ref={usernameRef} id="username" value={username} onChange={(e) => setUsername(e.target.value)} required maxLength={80} pattern="[a-zA-Z0-9_.\-]+" title="使用字母、数字、下划线、点或短横线" autoComplete="username" autoCapitalize="none" spellCheck={false} className={inputClass} disabled={busy}/></div>
      <div>
        <div className="flex items-baseline justify-between gap-4"><label htmlFor="password" className="text-sm font-medium">密码</label><button type="button" onClick={() => setShowPassword((value) => !value)} className={linkClass} aria-pressed={showPassword}>{showPassword ? "隐藏密码" : "显示密码"}</button></div>
        <input id="password" type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={setup ? 12 : 1} maxLength={128} autoComplete={setup ? "new-password" : "current-password"} className={inputClass} disabled={busy}/>
        {setup && <p className="mt-2 text-xs text-zinc-500">至少 12 个字符，不会上传到任何服务器。忘记密码时只能用恢复码重设，请妥善保存。</p>}
      </div>
      {setup ? <div><label htmlFor="confirm" className="text-sm font-medium">确认密码</label><input id="confirm" type={showPassword ? "text" : "password"} value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={12} maxLength={128} autoComplete="new-password" className={inputClass} disabled={busy}/></div> : <label className="flex items-center gap-3 text-sm text-zinc-600"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="size-4 rounded border-zinc-300" disabled={busy}/>记住我，30 天内在这台电脑上免登录</label>}
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm leading-6 text-red-700">{error}</p>}
      <button disabled={busy} type="submit" className="min-h-12 w-full rounded-xl bg-zinc-950 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-zinc-700 disabled:cursor-wait disabled:opacity-60">{busy ? "正在处理…" : setup ? "创建账号并进入" : "登录"}</button>
      {setup ? <p className="text-center text-xs leading-5 text-zinc-500">创建后会显示一批一次性恢复码，用于以后忘记密码时重设，请提前准备好保存位置。</p> : <button type="button" onClick={() => { setMode("recovery"); setError(""); }} className={`${linkClass} block w-full text-center`}>忘记密码？用恢复码重设</button>}
    </form>
  </>);
}
