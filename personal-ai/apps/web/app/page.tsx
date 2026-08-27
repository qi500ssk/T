"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";

import ChatView from "@/components/ChatView";
import ActivityView from "@/components/ActivityView";
import MemoryView from "@/components/MemoryView";
import KnowledgeView from "@/components/KnowledgeView";
import SettingsSidebar, { type SettingsView } from "@/components/SettingsSidebar";
import Sidebar, { type WorkspaceView } from "@/components/Sidebar";
import UtilitySidebar from "@/components/UtilitySidebar";
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
  fetchAppSettings,
  fetchConversations,
  fetchProjects,
  grantProjectAccess,
  revokeProjectAccess,
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
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [pendingConversationKind, setPendingConversationKind] = useState<"friend" | "normal" | "project">("normal");
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(true);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(true);
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
    fetchAppSettings().then((value) => {
      if (cancelled) return;
      setAppSettings(value);
      setSelectedAgentId((current) => current ?? value.agents.active_agent_id);
    }).catch(console.error);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      setLeftSidebarOpen(localStorage.getItem("personal-ai-left-sidebar") !== "closed");
      setRightSidebarOpen(localStorage.getItem("personal-ai-right-sidebar") !== "closed");
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  const setLeftOpen = useCallback((open: boolean) => {
    setLeftSidebarOpen(open);
    localStorage.setItem("personal-ai-left-sidebar", open ? "open" : "closed");
  }, []);

  const setRightOpen = useCallback((open: boolean) => {
    setRightSidebarOpen(open);
    localStorage.setItem("personal-ai-right-sidebar", open ? "open" : "closed");
  }, []);

  const handleCreate = useCallback(async () => {
    const conv = await createConversation({
      projectId: activeProjectId,
      agentId: selectedAgentId,
      kind: activeProjectId ? "project" : pendingConversationKind,
    });
    return conv.id;
  }, [activeProjectId, pendingConversationKind, selectedAgentId]);

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
      setActiveProjectId(null);
      setPendingConversationKind("normal");
      setView("chat");
      setNewConversationKey((value) => value + 1);
    });
  }, []);

  const handleCreateFriendConversation = useCallback((agentId: string) => {
    flushSync(() => {
      setSelectedAgentId(agentId);
      setActiveId(null);
      setActiveProjectId(null);
      setPendingConversationKind("normal");
      setView("chat");
      setNewConversationKey((value) => value + 1);
    });
  }, []);

  const handleSelectAgent = useCallback((agentId: string) => {
    const latest = conversations.find(
      (item) =>
        item.agent_id === agentId
        && item.project_id === null
        && (item.conversation_kind === "normal" || item.conversation_kind === "friend"),
    );
    setSelectedAgentId(agentId);
    setActiveProjectId(null);
    setPendingConversationKind("normal");
    setView("chat");
    setActiveId(latest?.id ?? null);
    if (latest) markConversationSeen(latest.id);
  }, [conversations, markConversationSeen]);

  const handleSelectConversation = useCallback((id: string) => {
    const conversation = conversations.find((item) => item.id === id);
    markConversationSeen(id);
    setActiveId(id);
    setActiveProjectId(conversation?.project_id ?? null);
    setSelectedAgentId(conversation?.agent_id ?? selectedAgentId);
    setView("chat");
  }, [conversations, markConversationSeen, selectedAgentId]);

  const handleSelectProject = useCallback((projectId: string | null) => {
    setActiveProjectId(projectId);
    setActiveId(null);
    setPendingConversationKind(projectId ? "project" : "normal");
    setView("chat");
  }, []);

  const handleOpenFolder = useCallback(async (workspaceDir: string) => {
    if (!selectedAgentId) {
      window.alert("请先选择一个 AI 好友");
      return;
    }
    const normalized = workspaceDir.replace(/[\\/]+$/, "").toLocaleLowerCase();
    const existing = projects.find((item) => item.workspace_dir?.replace(/[\\/]+$/, "").toLocaleLowerCase() === normalized);
    const folderName = workspaceDir.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || workspaceDir;
    const project = existing ?? await createProject({
      name: folderName,
      workspace_dir: workspaceDir,
      agent_id: selectedAgentId,
    });
    if (existing && !existing.agent_ids.includes(selectedAgentId)) {
      await grantProjectAccess(existing.id, selectedAgentId);
    }
    await refresh();
    setActiveProjectId(project.id);
    setActiveId(null);
    setPendingConversationKind("project");
    setView("chat");
    setFolderDialogOpen(false);
  }, [projects, refresh, selectedAgentId]);

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
    if (!selectedAgentId) return;
    const folderName = project.workspace_dir?.replace(/[\\/]+$/, "").split(/[\\/]/).at(-1) || project.name;
    const conversationCount = conversations.filter(
      (item) => item.project_id === project.id && item.agent_id === selectedAgentId,
    ).length;
    const agentName = appSettings?.agents.items.find((item) => item.id === selectedAgentId)?.name ?? "当前好友";
    const confirmed = window.confirm(
      `从“${agentName}”移除项目“${folderName}”？\n\n会永久删除该好友在此项目中的 ${conversationCount} 个对话。电脑上的文件、其他 AI 好友的权限和对话都不会被删除。`,
    );
    if (!confirmed) return;
    try {
      await revokeProjectAccess(project.id, selectedAgentId, true);
      if (activeProjectId === project.id) {
        flushSync(() => {
          setActiveProjectId(null);
          setActiveId(null);
          setNewConversationKey((value) => value + 1);
        });
      }
      await refresh();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "移除项目失败");
    }
  }, [activeProjectId, appSettings, conversations, refresh, selectedAgentId]);

  const handleOpenActivityConversation = useCallback(
    async (id: string) => {
      markConversationSeen(id);
      setActiveId(id);
      const conversation = conversations.find((item) => item.id === id);
      setActiveProjectId(conversation?.project_id ?? null);
      setSelectedAgentId(conversation?.agent_id ?? selectedAgentId);
      setView("chat");
      await refresh();
    },
    [conversations, markConversationSeen, refresh, selectedAgentId],
  );

  const handleOpenWorkspace = useCallback((nextView: WorkspaceView) => {
    setView(nextView);
  }, []);

  const activeConversation = conversations.find((item) => item.id === activeId);
  const chatAgentId = activeConversation?.agent_id ?? selectedAgentId ?? appSettings?.agents.active_agent_id;
  const chatAgent = appSettings?.agents.items.find((item) => item.id === chatAgentId) ?? appSettings?.agent;
  const authorizedProjects = projects.filter(
    (project) => chatAgentId !== undefined && chatAgentId !== null && project.agent_ids.includes(chatAgentId),
  );

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-white text-zinc-900 md:flex-row">
      {view === "settings" ? (
        <>
          <SettingsSidebar
            onBack={() => setView("chat")}
            onOpenWorkspace={handleOpenWorkspace}
            view={settingsView}
            onViewChange={setSettingsView}
            agent={appSettings?.agent}
          />
          {settingsView === "general" || settingsView === "model" ? (
            <GeneralSettingsView section={settingsView} onUpdated={(value) => {
              setAppSettings(value);
              setSelectedAgentId((current) => current ?? value.agents.active_agent_id);
            }} />
          ) : settingsView === "appearance" ? <AppearanceSettingsView /> : settingsView === "skills" ? <SkillView /> : settingsView === "mcp" ? <McpView /> : <PluginView />}
        </>
      ) : (
        <>
          {leftSidebarOpen ? (
            <Sidebar
              conversations={conversations}
              projects={projects}
              agents={appSettings?.agents.items ?? []}
              agent={chatAgent}
              selectedAgentId={chatAgentId ?? null}
              activeId={activeId}
              activeProjectId={activeProjectId}
              onSelect={handleSelectConversation}
              onSelectAgent={handleSelectAgent}
              onSelectProject={handleSelectProject}
              onCreateNormal={handleStartNewConversation}
              onCreateFriend={handleCreateFriendConversation}
              onAddFriend={() => {
                setSettingsView("general");
                setView("settings");
              }}
              onOpenFolder={() => setFolderDialogOpen(true)}
              onDeleteProject={(project) => void handleDeleteProject(project)}
              onDelete={(id) => void handleDelete(id)}
              view={view}
              onOpenSettings={() => setView("settings")}
              onCollapse={() => setLeftOpen(false)}
              runIndicators={runIndicators}
            />
          ) : null}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col md:flex-row">
            <div className="relative flex min-h-0 min-w-0 flex-1">
              {!leftSidebarOpen ? (
                <button type="button" onClick={() => setLeftOpen(true)} className="absolute left-3 top-3 z-30 grid size-11 place-items-center rounded-xl border border-zinc-200 bg-white/95 text-zinc-600 shadow-sm backdrop-blur hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-zinc-900" aria-label="显示左侧栏" title="显示左侧栏">›</button>
              ) : null}
              {!rightSidebarOpen ? (
                <button type="button" onClick={() => setRightOpen(true)} className="absolute right-3 top-3 z-30 grid size-11 place-items-center rounded-xl border border-zinc-200 bg-white/95 text-zinc-600 shadow-sm backdrop-blur hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-zinc-900" aria-label="显示右侧栏" title="显示右侧栏">‹</button>
              ) : null}
              {view === "chat" ? (
                <ChatView
                  key={`chat-${newConversationKey}`}
                  conversationId={activeId}
                  agent={chatAgent}
                  onAutoCreate={handleCreate}
                  onStarted={handleConversationStarted}
                  onFinished={() => void handleConversationFinished()}
                  onRunStatusChange={handleRunStatusChange}
                  onOpenSettings={(target) => {
                    setSettingsView(target);
                    setView("settings");
                  }}
                  projects={authorizedProjects}
                  activeProjectId={activeProjectId}
                  onSelectProject={handleSelectProject}
                  onOpenFolder={() => setFolderDialogOpen(true)}
                />
              ) : view === "memories" ? (
                <MemoryView key={chatAgentId ?? "none"} agentId={chatAgentId ?? null} agentName={chatAgent?.name ?? "当前好友"} />
              ) : view === "knowledge" ? (
                <KnowledgeView />
              ) : view === "activities" ? (
                <ActivityView agentId={chatAgentId} onOpenConversation={(id) => void handleOpenActivityConversation(id)} />
              ) : null}
            </div>
            {rightSidebarOpen ? <UtilitySidebar view={view} onViewChange={setView} onCollapse={() => setRightOpen(false)} /> : null}
          </div>
        </>
      )}
      <FolderPickerDialog open={folderDialogOpen} initialPath={projects.find((item) => item.id === activeProjectId)?.workspace_dir ?? ""} onClose={() => setFolderDialogOpen(false)} onSelect={(path) => void handleOpenFolder(path)} />
    </div>
  );
}
