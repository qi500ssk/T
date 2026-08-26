/* eslint-disable @next/next/no-img-element */

import { API_URL, type AgentSettings } from "@/lib/api";

export const DEFAULT_AI_AVATAR = "/avatars/ai-default.png";
export const DEFAULT_USER_AVATAR = "/avatars/user-default.jpg";

export function agentAvatarUrl(agent?: Pick<AgentSettings, "avatar_url"> | null) {
  if (!agent?.avatar_url) return DEFAULT_AI_AVATAR;
  if (/^https?:\/\//i.test(agent.avatar_url)) return agent.avatar_url;
  if (/^https?:\/\//i.test(API_URL)) return new URL(agent.avatar_url, API_URL).toString();
  return agent.avatar_url;
}

export default function Avatar({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  return <img src={src} alt={alt} className={`shrink-0 object-cover ${className}`} />;
}
