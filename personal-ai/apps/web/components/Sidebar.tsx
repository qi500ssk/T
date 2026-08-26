"use client";

import { projectFolderName, type AgentSettings, type Conversation, type Project } from "@/lib/api";

export type WorkspaceView = "chat" | "memories" | "knowledge" | "activities";

interface SidebarProps {
  conversations: Conversation[];
  projects: Project[];
  activeId: string | null;
  activeProjectId: string | null;
  onSelect: (id: string) => void;
  onSelectProject: (id: string | null) => void;
  onCreate: () => void;
  onOpenFolder: () => void;
  onDeleteProject: (project: Project) => void;
  onDelete: (id: string) => void;
  view: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  onOpenSettings: () => void;
  runIndicators: Record<string, "running" | "completed">;
  agent?: AgentSettings;
}

const navigation: { id: WorkspaceView; label: string; icon: string }[] = [
  { id: "chat", label: "新对话", icon: "＋" },
  { id: "memories", label: "记忆", icon: "◇" },
  { id: "knowledge", label: "知识库", icon: "▣" },
  { id: "activities", label: "活动", icon: "◷" },
];

export default function Sidebar(props: SidebarProps) {
  const { conversations, projects, activeId, activeProjectId, onSelect, onSelectProject, onCreate, onOpenFolder, onDeleteProject, onDelete, view, onViewChange, onOpenSettings, runIndicators, agent } = props;
  const grouped = (projectId: string | null) => conversations.filter((item) => item.project_id === projectId);
  const openTask = (id: string) => { onViewChange("chat"); onSelect(id); };
  const openProject = (id: string | null) => { onViewChange("chat"); onSelectProject(id); };
  const taskRows = (items: Conversation[]) => <ul className="space-y-0.5 pb-2 pl-4">
    {items.map((conversation) => <li key={conversation.id}><div className={`group flex items-center rounded-lg text-[13px] ${activeId === conversation.id && view === "chat" ? "bg-zinc-200 text-zinc-950" : "text-zinc-600 hover:bg-zinc-100"}`}>
      <button type="button" onClick={() => openTask(conversation.id)} className="min-w-0 flex-1 truncate px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900">{conversation.title}</button>
      {runIndicators[conversation.id] === "running" ? (
        <span className="mr-1 grid size-5 shrink-0 place-items-center" aria-label="任务进行中" role="status" title="任务进行中">
          <span className="size-3 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-950 motion-reduce:animate-none" aria-hidden="true" />
        </span>
      ) : runIndicators[conversation.id] === "completed" ? (
        <span className="mr-1 grid size-5 shrink-0 place-items-center" aria-label="任务已完成" role="status" title="任务已完成">
          <span className="size-2 rounded-full bg-zinc-950" aria-hidden="true" />
        </span>
      ) : null}
      <button type="button" onClick={() => onDelete(conversation.id)} className="mr-1 grid size-7 place-items-center rounded-md text-zinc-400 hover:bg-white hover:text-red-600 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100" aria-label={`删除任务：${conversation.title}`} title="删除任务">×</button>
    </div></li>)}
  </ul>;

  return <aside className="flex max-h-72 min-w-0 w-full shrink-0 flex-col overflow-hidden border-b border-zinc-200 bg-zinc-50 md:max-h-none md:w-72 md:border-b-0 md:border-r">
    <div className="flex h-16 shrink-0 items-center gap-3 border-b border-zinc-200 px-5"><div className="grid size-8 place-items-center rounded-xl bg-zinc-950 text-sm font-bold text-white">{agent?.name.slice(0, 1).toUpperCase() || "P"}</div><div><p className="text-sm font-semibold text-zinc-950">Personal AI</p><p className="max-w-40 truncate text-xs text-zinc-500">{agent?.name || "默认助手"}</p></div></div>
    <nav className="grid shrink-0 grid-cols-4 gap-1 p-3 md:grid-cols-1" aria-label="工作区导航">{navigation.map((item) => <button key={item.id} type="button" onClick={() => { if (item.id === "chat") { onViewChange("chat"); onCreate(); } else { onViewChange(item.id); } }} className={`flex min-h-10 items-center justify-center gap-3 rounded-xl px-3 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 md:justify-start ${view === item.id ? "bg-white font-medium text-zinc-950 shadow-sm ring-1 ring-zinc-200" : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950"}`}><span className="text-base text-zinc-500" aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav>
    <button type="button" onClick={onOpenSettings} className="mx-3 mb-3 min-h-10 rounded-xl border border-zinc-200 bg-white text-sm font-medium text-zinc-700 md:hidden">⚙ 设置与技能</button>
    <div className="hidden min-h-0 flex-1 flex-col md:flex">
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        <section className="mb-4">
          <div className="flex min-h-8 items-center px-3"><p className="text-xs font-medium uppercase tracking-wider text-zinc-400">普通对话</p><span className="ml-auto text-xs text-zinc-400">{grouped(null).length}</span></div>
          {grouped(null).length > 0 ? taskRows(grouped(null)) : <p className="px-3 py-3 text-sm text-zinc-400">未选择项目时创建的对话会显示在这里</p>}
        </section>
        <div className="mb-1 flex min-h-8 items-center justify-between px-3"><p className="text-xs font-medium uppercase tracking-wider text-zinc-400">文件夹</p><button type="button" onClick={onOpenFolder} className="grid size-7 place-items-center rounded-lg text-lg text-zinc-500 hover:bg-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900" aria-label="打开文件夹" title="打开文件夹">＋</button></div>
        {projects.map((project) => {
          const folderName = projectFolderName(project);
          return <section key={project.id} className="mb-1">
            <div className={`group flex min-h-9 items-center rounded-lg ${activeProjectId === project.id && view === "chat" ? "bg-zinc-200 text-zinc-950" : "text-zinc-700 hover:bg-zinc-100"}`}>
              <button type="button" onClick={() => openProject(project.id)} className="flex min-w-0 flex-1 items-center gap-2 self-stretch rounded-lg px-3 text-left text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-zinc-900" title={project.workspace_dir || project.name}>
                <span className="text-zinc-400" aria-hidden="true">▱</span>
                <span className="min-w-0 flex-1 truncate">{folderName}</span>
                <span className="text-xs text-zinc-400">{grouped(project.id).length}</span>
              </button>
              <button type="button" onClick={() => onDeleteProject(project)} className="mr-1 grid size-7 shrink-0 place-items-center rounded-md text-zinc-400 hover:bg-white hover:text-red-600 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-red-600 focus-visible:opacity-100 md:opacity-0 md:group-hover:opacity-100" aria-label={`删除文件夹及对话：${folderName}`} title="删除文件夹及其全部对话">×</button>
            </div>
            {taskRows(grouped(project.id))}
          </section>;
        })}
        {projects.length === 0 && <p className="px-3 py-3 text-sm text-zinc-400">打开文件夹后，会在这里归类相关对话</p>}
      </div>
    </div>
    <button type="button" onClick={onOpenSettings} className="m-3 mt-auto hidden min-h-11 shrink-0 items-center gap-3 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-700 hover:bg-zinc-100 md:flex"><span aria-hidden="true">⚙</span>设置与技能</button>
  </aside>;
}
