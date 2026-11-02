import type { ComponentType } from "react";
import type { MenuProps } from "antd";
import type { OctopAgent } from "../../../../context/AgentContext";
import type { Session } from "../../hooks/useSessions";
import type { SessionWorkStatus } from "../../utils/sessionWorkStatus";

export interface ProjectRowProps {
  session: Session;
  isActive: boolean;
  workStatus?: SessionWorkStatus;
  onSelect: (id: string) => void;
  onDelete: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
  projectMenuItems?: MenuProps["items"];
}
export interface ProjectSessionListProps {
  agent: OctopAgent;
  sessions: Session[];
  activeId: string | null;
  searchQuery?: string;
  onSelect: (id: string, agentId: string) => void;
  onDelete: ProjectRowProps["onDelete"];
  onRename: ProjectRowProps["onRename"];
  onPin: ProjectRowProps["onPin"];
  onFork: (id: string, agentId?: string | null) => void;
  activeForkDisabled?: boolean;
  activeForkDisabledHint?: string;
  liveWorkingIds: ReadonlySet<string>;
  compact?: boolean;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
}
export function createProjectFolders(
  options: unknown,
): ComponentType<ProjectSessionListProps>;
