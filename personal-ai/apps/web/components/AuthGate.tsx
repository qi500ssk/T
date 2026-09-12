"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { fetchAuthStatus } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authorizedPath, setAuthorizedPath] = useState<string | null>(null);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const invalidate = useCallback(() => { sequence.current++; }, []);
  const check = useCallback(() => {
    const current = ++sequence.current;
    fetchAuthStatus().then((status) => {
      if (current !== sequence.current) return;
      setError("");
      if (status.authenticated) setAuthorizedPath(pathname);
      else { setAuthorizedPath(null); router.replace("/login"); }
    }).catch((reason) => {
      if (current === sequence.current) setError(reason instanceof Error ? reason.message : "连接失败");
    });
  }, [pathname, router]);

  useEffect(() => {
    if (pathname !== "/login") check();
    const expired = () => { invalidate(); setAuthorizedPath(null); router.replace("/login"); };
    window.addEventListener("personal-ai:unauthorized", expired);
    return () => { invalidate(); window.removeEventListener("personal-ai:unauthorized", expired); };
  }, [pathname, router, check, invalidate]);

  if (pathname === "/login" || authorizedPath === pathname) return children;
  return <main className="grid min-h-dvh place-items-center bg-zinc-50 p-6 text-center text-zinc-600">
    <div><p role={error ? "alert" : "status"}>{error || "正在连接你的工作区…"}</p>
      {error && <button onClick={check} className="mt-4 min-h-11 rounded-xl bg-zinc-950 px-6 text-white">重新连接</button>}
    </div>
  </main>;
}
