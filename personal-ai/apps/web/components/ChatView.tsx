"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  documentContentUrl,
  fetchMessages,
  streamChat,
  type ChatMessage,
  type CitationSource,
} from "@/lib/api";

interface ChatViewProps {
  conversationId: string | null;
  /** 无会话时点击发送自动创建，返回新会话 id */
  onAutoCreate: () => Promise<string>;
  /** 一次 Run 结束后刷新会话列表（标题可能变化） */
  onFinished: () => void;
}

function MessageBubble({
  role,
  content,
  streaming,
  citations = [],
}: {
  role: string;
  content: string;
  streaming?: boolean;
  citations?: CitationSource[];
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
          isUser ? "bg-blue-600 text-white" : "border bg-white"
        }`}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm">{content}</div>
        ) : (
          <div className="text-sm">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
            {streaming && (
              <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-gray-400 align-middle" />
            )}
            {citations.length > 0 && (
              <div className="mt-3 space-y-2 border-t border-gray-200 pt-3" aria-label="回答引用">
                {citations.map((source) => (
                  <a
                    key={source.citation_id}
                    href={documentContentUrl(source.document_id, source.page_start)}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-md border border-gray-200 bg-gray-50 p-2.5 hover:border-blue-300 hover:bg-blue-50"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="shrink-0 font-medium text-blue-700">[{source.citation_id}]</span>
                      <span className="truncate font-medium text-gray-800">{source.filename}</span>
                      {source.page_start && <span className="ml-auto shrink-0 text-xs text-gray-500">第 {source.page_start} 页</span>}
                    </div>
                    <div className="mt-1 truncate text-xs text-gray-500">{source.section || "正文"}</div>
                    <p className="mt-1 line-clamp-3 text-xs leading-5 text-gray-600">{source.excerpt}</p>
                  </a>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatView({
  conversationId,
  onAutoCreate,
  onFinished,
}: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState("");
  const [streamingSources, setStreamingSources] = useState<CitationSource[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(Boolean(conversationId));
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    fetchMessages(conversationId)
      .then((rows) => {
        if (!cancelled) setMessages(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const send = useCallback(
    async (text: string) => {
      let convId = conversationId;
      if (!convId) {
        try {
          convId = await onAutoCreate();
        } catch (e) {
          setError(String(e));
          return;
        }
      }
      setError("");
      setStreaming("");
      setStreamingSources([]);
      setMessages((ms) => [
        ...ms,
        { id: `local-${Date.now()}`, role: "user", content: text, citations: [], created_at: "" },
      ]);
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);
      try {
        await streamChat(
          convId,
          text,
          (ev) => {
            if (ev.event === "message.delta") {
              setStreaming((s) => s + String(ev.data.content ?? ""));
            } else if (ev.event === "rag.retrieved") {
              setStreamingSources((ev.data.sources as CitationSource[]) ?? []);
            } else if (ev.event === "run.failed") {
              setError(String(ev.data.error ?? "运行失败"));
            }
          },
          controller.signal,
        );
        const msgs = await fetchMessages(convId);
        setMessages(msgs);
        onFinished();
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError(String(e));
      } finally {
        setStreaming("");
        setStreamingSources([]);
        abortRef.current = null;
        setIsStreaming(false);
      }
    },
    [conversationId, onAutoCreate, onFinished],
  );

  const stop = () => abortRef.current?.abort();

  const retry = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) send(lastUser.content);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    send(text);
  };

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && !loading && (
          <div className="mt-16 text-center text-sm text-gray-400">
            {conversationId ? "开始对话吧" : "点击「+ 新对话」或直接输入消息开始"}
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} citations={m.citations} />
        ))}
        {(streaming !== "" || (loading && conversationId)) && (
          <MessageBubble
            role="assistant"
            content={streaming || "…"}
            citations={streamingSources}
            streaming={streaming !== ""}
          />
        )}
        {error && <div className="text-sm text-red-500">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-gray-200 bg-white p-3">
        {isStreaming && (
          <div className="mb-2 flex items-center justify-between px-1 text-xs text-gray-500">
            <span>正在生成…</span>
            <button
              onClick={stop}
              className="rounded border px-2 py-1 hover:bg-gray-100"
            >
              停止
            </button>
          </div>
        )}
        <form onSubmit={submit} className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(e);
              }
            }}
            rows={1}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            className="max-h-40 flex-1 resize-none rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="rounded-lg bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            发送
          </button>
        </form>
        {!isStreaming && messages.some((m) => m.role === "assistant") && (
          <div className="mt-1 px-1 text-right">
            <button
              onClick={retry}
              className="text-xs text-gray-400 hover:text-blue-600"
            >
              重新生成最后回复
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
