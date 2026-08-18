"use client";

import { useCallback, useEffect, useState } from "react";

import ChatView from "@/components/ChatView";
import MemoryView from "@/components/MemoryView";
import KnowledgeView from "@/components/KnowledgeView";
import Sidebar from "@/components/Sidebar";
import {
  createConversation,
  deleteConversation,
  fetchConversations,
  type Conversation,
} from "@/lib/api";

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [view, setView] = useState<"chat" | "memories" | "knowledge">("chat");

  const refresh = useCallback(async () => {
    setConversations(await fetchConversations());
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchConversations()
      .then((rows) => {
        if (!cancelled) setConversations(rows);
      })
      .catch(console.error);
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = useCallback(async () => {
    const conv = await createConversation();
    setActiveId(conv.id);
    await refresh();
    return conv.id;
  }, [refresh]);

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteConversation(id);
      if (activeId === id) setActiveId(null);
      await refresh();
    },
    [activeId, refresh],
  );

  return (
    <div className="flex h-dvh flex-col bg-white text-gray-900 md:flex-row">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onCreate={() => void handleCreate()}
        onDelete={(id) => void handleDelete(id)}
        view={view}
        onViewChange={setView}
      />
      {view === "chat" ? (
        <ChatView
          key={activeId ?? "new"}
          conversationId={activeId}
          onAutoCreate={handleCreate}
          onFinished={() => void refresh()}
        />
      ) : view === "memories" ? (
        <MemoryView />
      ) : (
        <KnowledgeView />
      )}
    </div>
  );
}
