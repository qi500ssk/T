"use client";

import { useCallback, useEffect, useState } from "react";

import ChatView from "@/components/ChatView";
import ActivityView from "@/components/ActivityView";
import MemoryView from "@/components/MemoryView";
import KnowledgeView from "@/components/KnowledgeView";
import SettingsSidebar, { type SettingsView } from "@/components/SettingsSidebar";
import Sidebar, { type WorkspaceView } from "@/components/Sidebar";
import SkillView from "@/components/SkillView";
import McpView from "@/components/McpView";
import PluginView from "@/components/PluginView";
import {
  createConversation,
  deleteConversation,
  fetchConversations,
  type Conversation,
} from "@/lib/api";

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [view, setView] = useState<WorkspaceView | "settings">("chat");
  const [settingsView, setSettingsView] = useState<SettingsView>("skills");

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

  const handleOpenActivityConversation = useCallback(
    async (id: string) => {
      setActiveId(id);
      setView("chat");
      await refresh();
    },
    [refresh],
  );

  const handleOpenWorkspace = useCallback((nextView: WorkspaceView) => {
    setView(nextView);
  }, []);

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-white text-zinc-900 md:flex-row">
      {view === "settings" ? (
        <SettingsSidebar
          onBack={() => setView("chat")}
          onOpenWorkspace={handleOpenWorkspace}
          view={settingsView}
          onViewChange={setSettingsView}
        />
      ) : (
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={setActiveId}
          onCreate={() => void handleCreate()}
          onDelete={(id) => void handleDelete(id)}
          view={view}
          onViewChange={setView}
          onOpenSettings={() => setView("settings")}
        />
      )}
      {view === "settings" ? (
        settingsView === "skills" ? <SkillView /> : settingsView === "mcp" ? <McpView /> : <PluginView />
      ) : view === "chat" ? (
        <ChatView
          key={activeId ?? "new"}
          conversationId={activeId}
          onAutoCreate={handleCreate}
          onFinished={() => void refresh()}
        />
      ) : view === "memories" ? (
        <MemoryView />
      ) : view === "knowledge" ? (
        <KnowledgeView />
      ) : view === "activities" ? (
        <ActivityView onOpenConversation={(id) => void handleOpenActivityConversation(id)} />
      ) : null}
    </div>
  );
}
