"use client";

import Avatar, { agentAvatarUrl } from "@/components/Avatar";
import {
  projectFolderName,
  type AgentProfile,
  type AgentSettings,
  type Conversation,
  type Project,
} from "@/lib/api";

export type WorkspaceView = "chat" | "memories" | "knowledge" | "activities";

interface SidebarProps {
  conversations: Conversation[];
  projects: Project[];
  agents: AgentProfile[];
  agent?: AgentSettings;
  selectedAgentId: string | null;
  activeId: string | null;
  activeProjectId: string | null;
  view: WorkspaceView;
  runIndicators: Record<string, "running" | "completed">;
  onSelect: (id: string) => void;
  onSelectAgent: (id: string) => void;
  onSelectProject: (id: string | null) => void;
  onCreateNormal: () => void;
  onCreateFriend: (agentId: string) => void;
  onAddFriend: () => void;
  onOpenFolder: () => void;
  onDeleteProject: (project: Project) => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
  onCollapse: () => void;
}

export default function Sidebar(props: SidebarProps) {
  const {
    conversations,
    projects,
    agents,
    agent,
    selectedAgentId,
    activeId,
    activeProjectId,
    view,
    runIndicators,
    onSelect,
    onSelectAgent,
    onSelectProject,
    onCreateNormal,
    onCreateFriend,
    onAddFriend,
    onOpenFolder,
    onDeleteProject,
    onDelete,
    onOpenSettings,
    onCollapse,
  } = props;

  const conversationsForProject = (projectId: string) =>
    conversations.filter(
      (item) => item.project_id === projectId && item.agent_id === selectedAgentId,
    );
  const conversationsForAgent = (agentId: string | null) =>
    conversations.filter(
      (item) =>
        item.project_id === null
        && item.agent_id === agentId
        && (item.conversation_kind === "normal" || item.conversation_kind === "friend"),
    );
  // 旧版的 friend 对话继续可见，但与 normal 对话统一归入“普通对话”。
  const normalConversations = conversationsForAgent(selectedAgentId);
  const visibleProjects = projects.filter(
    (project) => selectedAgentId !== null && project.agent_ids.includes(selectedAgentId),
  );

  const taskRows = (items: Conversation[]) => (
    <ul className="space-y-0.5 pb-2 pl-4">
      {items.map((conversation) => (
        <li key={conversation.id}>
          <div
            className={`group flex items-center rounded-lg text-[13px] ${
              activeId === conversation.id && view === "chat"
                ? "bg-zinc-200 text-zinc-950"
                : "text-zinc-600 hover:bg-zinc-100"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(conversation.id)}
              className="min-w-0 flex-1 truncate px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900"
            >
              {conversation.title}
            </button>
            {runIndicators[conversation.id] === "running" ? (
              <span className="mr-1 grid size-5 shrink-0 place-items-center" aria-label="任务进行中" role="status">
                <span className="size-3 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-950 motion-reduce:animate-none" />
              </span>
            ) : runIndicators[conversation.id] === "completed" ? (
              <span className="mr-1 grid size-5 shrink-0 place-items-center" aria-label="任务已完成" role="status">
                <span className="size-2 rounded-full bg-zinc-950" />
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => onDelete(conversation.id)}
              className="mr-1 grid size-7 place-items-center rounded-md text-zinc-400 hover:bg-white hover:text-red-600 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100"
              aria-label={`删除对话：${conversation.title}`}
              title="删除对话"
            >
              ×
            </button>
          </div>
        </li>
      ))}
    </ul>
  );

  return (
    <aside className="flex max-h-80 min-w-0 w-full shrink-0 flex-col overflow-hidden border-b border-zinc-200 bg-zinc-50 md:max-h-none md:w-72 md:border-b-0 md:border-r">
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-zinc-200 px-4">
        <Avatar src={agentAvatarUrl(agent)} alt={`${agent?.name || "AI"}的头像`} className="size-9 rounded-xl ring-1 ring-zinc-200" previewable />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-zinc-950">Personal AI</p>
          <p className="truncate text-xs text-zinc-500">你的专属 AI 好友</p>
        </div>
        <button type="button" onClick={onCollapse} className="grid size-10 place-items-center rounded-xl text-zinc-500 hover:bg-zinc-200 focus-visible:outline-2 focus-visible:outline-zinc-900" aria-label="隐藏左侧栏" title="隐藏左侧栏">‹</button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        <section className="mb-4">
          <div className="flex min-h-9 items-center px-3">
            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">AI 好友</p>
            <button type="button" onClick={onAddFriend} className="ml-auto min-h-8 rounded-lg px-2 text-xs text-zinc-600 hover:bg-zinc-200" title="添加好友">＋ 添加好友</button>
          </div>
          <div className="space-y-1">
            {agents.map((profile) => {
              const chatCount = conversationsForAgent(profile.id).length;
              // 好友是当前工作归属，不应因为打开右侧工具页而丢失选中状态。
              const selected = selectedAgentId === profile.id;
              return (
                <section key={profile.id}>
                  <div className={`group flex min-h-12 items-center rounded-xl ${selected ? "bg-white shadow-sm ring-1 ring-zinc-200" : "hover:bg-zinc-100"}`}>
                    <button type="button" onClick={() => onSelectAgent(profile.id)} className="flex min-w-0 flex-1 items-center gap-3 self-stretch rounded-xl px-3 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900">
                      <Avatar src={agentAvatarUrl(profile)} alt={`${profile.name}的头像`} className="size-8 rounded-full ring-1 ring-zinc-200" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-zinc-900">{profile.name}</span>
                        <span className="block truncate text-xs text-zinc-500">{profile.role}</span>
                      </span>
                      <span className="text-xs text-zinc-400">{chatCount}</span>
                    </button>
                    <button type="button" onClick={() => onCreateFriend(profile.id)} className="mr-1 grid size-8 shrink-0 place-items-center rounded-lg text-lg text-zinc-500 hover:bg-zinc-200" aria-label={`与 ${profile.name} 新建对话`} title="新建普通对话">＋</button>
                  </div>
                </section>
              );
            })}
          </div>
        </section>

        <section className="mb-4">
          <div className="flex min-h-9 items-center px-3">
            <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">普通对话</p>
            <span className="ml-auto text-xs text-zinc-400">{normalConversations.length}</span>
            <button type="button" onClick={onCreateNormal} className="ml-1 grid size-8 place-items-center rounded-lg text-lg text-zinc-500 hover:bg-zinc-200" aria-label="新建普通对话" title="新建普通对话">＋</button>
          </div>
          {normalConversations.length > 0 ? taskRows(normalConversations) : <p className="px-3 py-2 text-sm text-zinc-400">暂无普通对话</p>}
        </section>

        <div className="mb-1 flex min-h-9 items-center px-3">
          <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">项目</p>
          <button type="button" onClick={onOpenFolder} className="ml-auto grid size-8 place-items-center rounded-lg text-lg text-zinc-500 hover:bg-zinc-200" aria-label="打开文件夹" title="打开文件夹">＋</button>
        </div>
        {visibleProjects.map((project) => {
          const folderName = projectFolderName(project);
          const chats = conversationsForProject(project.id);
          return (
            <section key={project.id} className="mb-1">
              <div className={`group flex min-h-10 items-center rounded-lg ${activeProjectId === project.id && view === "chat" ? "bg-zinc-200 text-zinc-950" : "text-zinc-700 hover:bg-zinc-100"}`}>
                <button type="button" onClick={() => onSelectProject(project.id)} className="flex min-w-0 flex-1 items-center gap-2 self-stretch rounded-lg px-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900" title={project.workspace_dir || project.name}>
                  <span className="text-zinc-400">▱</span>
                  <span className="min-w-0 flex-1 truncate">{folderName}</span>
                  {project.agent_ids.length > 1 ? (
                    <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-normal text-zinc-500">共享</span>
                  ) : null}
                  <span className="text-xs text-zinc-400">{chats.length}</span>
                </button>
                <button type="button" onClick={() => onDeleteProject(project)} className="mr-1 grid size-7 shrink-0 place-items-center rounded-md text-zinc-400 hover:bg-white hover:text-red-600 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100" aria-label={`从当前好友移除项目：${folderName}`} title="从当前好友移除项目">×</button>
              </div>
              {activeProjectId === project.id ? taskRows(chats) : null}
            </section>
          );
        })}
        {visibleProjects.length === 0 ? <p className="px-3 py-2 text-sm text-zinc-400">为当前好友打开文件夹后会显示在这里</p> : null}
      </div>

      <button type="button" onClick={onOpenSettings} className="m-3 mt-auto flex min-h-11 shrink-0 items-center gap-3 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-100"><span>⚙</span>设置与技能</button>
    </aside>
  );
}
