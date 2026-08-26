"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import AppearanceSettingsView from "@/components/AppearanceSettingsView";
import FolderPickerDialog from "@/components/FolderPickerDialog";
import {
  createConversation,
  createProject,
  deleteConversation,
  deleteProject,
  fetchAppSettings,
  fetchConversations,
  fetchProjects,
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
  const [folderDialogOpen, setFolderDialogOpen] = useState(false);
  const [view, setView] = useState<WorkspaceView | "settings">("chat");
  const [settingsView, setSettingsView] = useState<SettingsView>("general");
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [runIndicators, setRunIndicators] = useState<Record<string, "running" | "completed">>({});
  const visibleConversationRef = useRef<{ id: string | null; isChat: boolean }>({ id: null, isChat: true });

  useEffect(() => {
    visibleConversationRef.current = { id: activeId, isChat: view === "chat" };
  }, [activeId, view]);

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

  const handleConversationFinished = useCallback(async () => {
    // 后台 Run 结束只刷新侧栏标题；用户已经切到别的会话时不能被强行拉回。
    await refresh();
  }, [refresh]);

  const handleConversationStarted = useCallback((id: string) => {
    setActiveId(id);
    void refresh();
  }, [refresh]);

  const handleRunStatusChange = useCallback(
    (id: string, status: "running" | "completed" | "idle") => {
      setRunIndicators((current) => {
        const visible = visibleConversationRef.current;
        const nextStatus = status === "completed" && visible.isChat && visible.id === id
          ? "idle"
          : status;
        if (nextStatus === "idle") {
          if (!(id in current)) return current;
          const next = { ...current };
          delete next[id];
          return next;
        }
        return current[id] === nextStatus ? current : { ...current, [id]: nextStatus };
      });
    },
    [],
  );

  const markConversationSeen = useCallback((id: string) => {
    setRunIndicators((current) => {
      if (current[id] !== "completed") return current;
      const next = { ...current };
      delete next[id];
      return next;
    });
  }, []);

  const handleStartNewConversation = useCallback(() => {
    // 在点击事件返回前完成 ChatView 重建，避免用户立即输入时又被稍后的重置覆盖。
    flushSync(() => {
      setActiveId(null);
      setView("chat");
      setNewConversationKey((value) => value + 1);
    });
  }, []);

  const handleSelectConversation = useCallback((id: string) => {
    const conversation = conversations.find((item) => item.id === id);
    markConversationSeen(id);
    setActiveId(id);
    setActiveProjectId(conversation?.project_id ?? null);
  }, [conversations, markConversationSeen]);

  const handleSelectProject = useCallback((projectId: string | null) => {
    setActiveProjectId(projectId);
    setActiveId(null);
  }, []);

  const handleOpenFolder = useCallback(async (workspaceDir: string) => {
    const normalized = workspaceDir.replace(/[\\/]+$/, "").toLocaleLowerCase();
    const existing = projects.find((item) => item.workspace_dir?.replace(/[\\/]+$/, "").toLocaleLowerCase() === normalized);
    const folderName = workspaceDir.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || workspaceDir;
    const project = existing ?? await createProject({ name: folderName, workspace_dir: workspaceDir });
    await refresh();
    setActiveProjectId(project.id);
    setActiveId(null);
    setView("chat");
    setFolderDialogOpen(false);
  }, [projects, refresh]);

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteConversation(id);
      setRunIndicators((current) => {
        if (!(id in current)) return current;
        const next = { ...current };
        delete next[id];
        return next;
      });
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

  const handleDeleteProject = useCallback(async (project: Project) => {
    const folderName = project.workspace_dir?.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || project.name;
    const conversationCount = conversations.filter((item) => item.project_id === project.id).length;
    const confirmed = window.confirm(
      `删除文件夹“${folderName}”及其 ${conversationCount} 个对话？\n\n聊天记录将永久删除且无法恢复。电脑上的文件夹和其中的文件不会被删除。`,
    );
    if (!confirmed) return;
    try {
      await deleteProject(project.id, true);
      if (activeProjectId === project.id) {
        flushSync(() => {
          setActiveProjectId(null);
          setActiveId(null);
          setNewConversationKey((value) => value + 1);
        });
      }
      await refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "删除文件夹失败");
    }
  }, [activeProjectId, conversations, refresh]);

  const handleOpenActivityConversation = useCallback(
    async (id: string) => {
      markConversationSeen(id);
      setActiveId(id);
      const conversation = conversations.find((item) => item.id === id);
      setActiveProjectId(conversation?.project_id ?? null);
      setView("chat");
      await refresh();
    },
    [conversations, markConversationSeen, refresh],
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
          onSelectProject={handleSelectProject}
          onCreate={handleStartNewConversation}
          onOpenFolder={() => setFolderDialogOpen(true)}
          onDeleteProject={(project) => void handleDeleteProject(project)}
          onDelete={(id) => void handleDelete(id)}
          view={view}
          onViewChange={setView}
          onOpenSettings={() => setView("settings")}
          runIndicators={runIndicators}
          agent={appSettings?.agent}
        />
      )}
      {view === "settings" ? (
        settingsView === "general" || settingsView === "model" ? (
          <GeneralSettingsView section={settingsView} onUpdated={setAppSettings} />
        ) : settingsView === "appearance" ? <AppearanceSettingsView /> : settingsView === "skills" ? <SkillView /> : settingsView === "mcp" ? <McpView /> : <PluginView />
      ) : view === "chat" ? (
        <ChatView
          key={`chat-${newConversationKey}`}
          conversationId={activeId}
          onAutoCreate={handleCreate}
          onStarted={handleConversationStarted}
          onFinished={() => void handleConversationFinished()}
          onRunStatusChange={handleRunStatusChange}
          onOpenSettings={(target) => {
            setSettingsView(target);
            setView("settings");
          }}
          projects={projects}
          activeProjectId={activeProjectId}
          onSelectProject={handleSelectProject}
          onOpenFolder={() => setFolderDialogOpen(true)}
        />
      ) : view === "memories" ? (
        <MemoryView />
      ) : view === "knowledge" ? (
        <KnowledgeView />
      ) : view === "activities" ? (
        <ActivityView onOpenConversation={(id) => void handleOpenActivityConversation(id)} />
      ) : null}
      <FolderPickerDialog open={folderDialogOpen} initialPath={projects.find((item) => item.id === activeProjectId)?.workspace_dir ?? ""} onClose={() => setFolderDialogOpen(false)} onSelect={(path) => void handleOpenFolder(path)} />
    </div>
  );
}
