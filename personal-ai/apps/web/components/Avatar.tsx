"use client";

/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { API_URL, type AgentSettings } from "@/lib/api";

export const DEFAULT_AI_AVATAR = "/avatars/ai-default.png";
export const DEFAULT_USER_AVATAR = "/avatars/user-default.jpg";

export function agentAvatarUrl(agent?: Pick<AgentSettings, "avatar_url"> | null) {
  if (!agent?.avatar_url) return DEFAULT_AI_AVATAR;
  if (/^https?:\/\//i.test(agent.avatar_url)) return agent.avatar_url;
  if (/^https?:\/\//i.test(API_URL)) return new URL(agent.avatar_url, API_URL).toString();
  return agent.avatar_url;
}

interface AvatarProps {
  src: string;
  alt: string;
  className?: string;
  previewable?: boolean;
}

export default function Avatar({ src, alt, className = "", previewable = false }: AvatarProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
  }, [open]);

  const close = () => {
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  if (!previewable) {
    return <img src={src} alt={alt} className={`shrink-0 object-cover ${className}`} />;
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        className={`group shrink-0 overflow-hidden transition hover:brightness-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 motion-reduce:transition-none ${className}`}
        aria-label={`查看${alt}大图`}
        title="点击查看头像"
      >
        <img src={src} alt="" className="size-full object-cover transition-transform group-hover:scale-105 motion-reduce:transition-none" />
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              className="fixed inset-0 z-[100] grid place-items-center bg-black/70 p-4 backdrop-blur-sm sm:p-8"
              role="dialog"
              aria-modal="true"
              aria-label={`${alt}大图预览`}
              onMouseDown={(event) => {
                if (event.currentTarget === event.target) close();
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  close();
                } else if (event.key === "Tab") {
                  event.preventDefault();
                  closeRef.current?.focus();
                }
              }}
            >
              <div className="relative flex max-h-full max-w-full items-center justify-center">
                <img
                  src={src}
                  alt={alt}
                  className="max-h-[85vh] max-w-[90vw] rounded-2xl bg-zinc-950 object-contain shadow-2xl ring-1 ring-white/20"
                />
                <button
                  ref={closeRef}
                  type="button"
                  onClick={close}
                  className="absolute -right-2 -top-2 grid size-10 place-items-center rounded-full border border-white/20 bg-zinc-900/90 text-xl text-white shadow-lg hover:bg-zinc-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:-right-4 sm:-top-4"
                  aria-label="关闭头像预览"
                  title="关闭"
                >
                  ×
                </button>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
