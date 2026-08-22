"use client";

import { useCallback, useEffect, useState } from "react";
import { flushSync } from "react-dom";

import ChatView from "@/components/ChatView";
import ActivityView from "@/components/ActivityView";
import MemoryView from "@/components/MemoryView";
import KnowledgeView from "@/components/KnowledgeView";
import SettingsSidebar, { type SettingsView } from "@/components/SettingsSidebar";
import Sidebar, { type WorkspaceView } from "@/components/Sidebar";
import SkillView from "@/components/SkillView";
import McpView from "@/components/McpView";
import PluginView from "@/components/PluginView";
import GeneralSettingsView from "@/components/GeneralSettingsView";
import ProjectDialog from "@/components/ProjectDialog";
import {
  createConversation,
  createProject,
  deleteConversation,
  fetchAppSettings,
  fetchConversations,
  fetchProjects,
  updateWorkspaceSettings,
  type AppSettings,
  type Conversation,
  type Project,
} from "@/lib/api";

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [newConversationKey, setNewConversationKey] = useState(0);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [view, setView] = useState<WorkspaceView | "settings">("chat");
  const [settingsView, setSettingsView] = useState<SettingsView>("general");
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);

  const refresh = useCallback(async () => {
    const [conversationRows, projectRows] = await Promise.all([fetchConversations(), fetchProjects()]);
    setConversations(conversationRows);
    setProjects(projectRows);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchConversations(), fetchProjects()])
      .then(([conversationRows, projectRows]) => {
        if (cancelled) return;
        setConversations(conversationRows);
        setProjects(projectRows);
      })
      .catch(console.error);
    fetchAppSettings().then((value) => { if (!cancelled) setAppSettings(value); }).catch(console.error);
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = useCallback(async () => {
    const conv = await createConversation(activeProjectId);
    return conv.id;
  }, [activeProjectId]);

  const handleConversationFinished = useCallback(async (id: string) => {
    setActiveId(id);
    await refresh();
  }, [refresh]);

  const handleConversationStarted = useCallback((id: string) => {
    setActiveId(id);
    void refresh();
  }, [refresh]);

  const handleStartNewConversation = useCallback(() => {
    // 在点击事件返回前完成 ChatView 重建，避免用户立即输入时又被稍后的重置覆盖。
    flushSync(() => {
      setActiveProjectId(null);
      setActiveId(null);
      setView("chat");
      setNewConversationKey((value) => value + 1);
    });
  }, []);

  const handleSelectConversation = useCallback((id: string) => {
    const conversation = conversations.find((item) => item.id === id);
    setActiveId(id);
    setActiveProjectId(conversation?.project_id ?? null);
  }, [conversations]);

  const handleSelectProject = useCallback(async (projectId: string | null) => {
    setActiveProjectId(projectId);
    setActiveId(null);
    const project = projects.find((item) => item.id === projectId);
    if (project?.workspace_dir) {
      await updateWorkspaceSettings(project.workspace_dir);
      setAppSettings((current) => current ? { ...current, workspace: { coding_workspace_dir: project.workspace_dir! } } : current);
    }
  }, [projects]);

  const handleCreateProject = useCallback(async (name: string, workspaceDir: string | null) => {
    const project = await createProject({ name, workspace_dir: workspaceDir });
    await refresh();
    setActiveProjectId(project.id);
    setActiveId(null);
    if (project.workspace_dir) {
      await updateWorkspaceSettings(project.workspace_dir);
      setAppSettings((current) => current ? { ...current, workspace: { coding_workspace_dir: project.workspace_dir! } } : current);
    }
  }, [refresh]);

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteConversation(id);
      if (activeId === id) {
        flushSync(() => {
          setActiveId(null);
          setNewConversationKey((value) => value + 1);
        });
      }
      await refresh();
    },
    [activeId, refresh],
  );

  const handleOpenActivityConversation = useCallback(
    async (id: string) => {
      setActiveId(id);
      const conversation = conversations.find((item) => item.id === id);
      setActiveProjectId(conversation?.project_id ?? null);
      setView("chat");
      await refresh();
    },
    [conversations, refresh],
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
          agent={appSettings?.agent}
        />
      ) : (
        <Sidebar
          conversations={conversations}
          projects={projects}
          activeId={activeId}
          activeProjectId={activeProjectId}
          onSelect={handleSelectConversation}
          onSelectProject={(id) => void handleSelectProject(id)}
          onCreate={handleStartNewConversation}
          onCreateProject={() => setProjectDialogOpen(true)}
          onDelete={(id) => void handleDelete(id)}
          view={view}
          onViewChange={setView}
          onOpenSettings={() => setView("settings")}
          agent={appSettings?.agent}
        />
      )}
      {view === "settings" ? (
        settingsView === "general" || settingsView === "model" || settingsView === "workspace" ? (
          <GeneralSettingsView section={settingsView} onUpdated={setAppSettings} />
        ) : settingsView === "skills" ? <SkillView /> : settingsView === "mcp" ? <McpView /> : <PluginView />
      ) : view === "chat" ? (
        <ChatView
          key={`chat-${newConversationKey}`}
          conversationId={activeId}
          onAutoCreate={handleCreate}
          onStarted={handleConversationStarted}
          onFinished={(id) => void handleConversationFinished(id)}
          onOpenSettings={(target) => {
            setSettingsView(target);
            setView("settings");
          }}
          projects={projects}
          activeProjectId={activeProjectId}
          onSelectProject={(id) => void handleSelectProject(id)}
          onCreateProject={() => setProjectDialogOpen(true)}
        />
      ) : view === "memories" ? (
        <MemoryView />
      ) : view === "knowledge" ? (
        <KnowledgeView />
      ) : view === "activities" ? (
        <ActivityView onOpenConversation={(id) => void handleOpenActivityConversation(id)} />
      ) : null}
      <ProjectDialog open={projectDialogOpen} initialWorkspace={appSettings?.workspace.coding_workspace_dir ?? ""} onClose={() => setProjectDialogOpen(false)} onCreate={handleCreateProject} />
    </div>
  );
}
