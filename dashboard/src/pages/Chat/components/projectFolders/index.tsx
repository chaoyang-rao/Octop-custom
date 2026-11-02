import * as React from "react";
import i18n from "../../../../i18n";
import { Dropdown } from "antd";
import { ChevronRight, MoreHorizontal, Plus } from "lucide-react";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";
import { projectFoldersRequest } from "../../../../api/modules/projectFolders";
import { sortSessions, toSession } from "../../hooks/useSessions";
import { emitSessionEvent, onSessionEvent } from "../../hooks/chatStore";
import { resolveSessionWorkStatus } from "../../utils/sessionWorkStatus";
import {
  createProjectFolders,
  type ProjectRowProps,
  type ProjectSessionListProps,
} from "./project-folders.mjs";
import "./project-folders.css";
import "./project-folder-picker.css";

export function projectSessionListFor(Row: ComponentType<ProjectRowProps>) {
  const ProjectFolders = createProjectFolders({
    React,
    request: projectFoldersRequest,
    toSession,
    sortSessions,
    Row,
    CompactRow: () => Row,
    resolveStatus: resolveSessionWorkStatus,
    emitSessionEvent,
    onSessionEvent,
    Dropdown,
    Plus,
    More: MoreHorizontal,
    Chevron: ChevronRight,
    translate: (key: string, values?: Record<string, unknown>) =>
      i18n.t(`chat.projectFolders.${key}`, values),
  });
  return function ProjectSessionList(props: ProjectSessionListProps) {
    const { t } = useTranslation();
    const { agent, sessions, activeId, liveWorkingIds } = props;
    // Project/thread APIs scope local folders to the authenticated user.
    if (!agent.bridge) {
      return <ProjectFolders {...props} />;
    }
    return (
      <>
        {sessions.length === 0 ? (
          <div className={styles.minimalAgentEmpty}>
            {t("chat.noSessionsYet")}
          </div>
        ) : (
          sessions.map((session) => (
            <Row
              key={session.id}
              session={session}
              isActive={session.id === activeId}
              workStatus={resolveSessionWorkStatus(session, liveWorkingIds)}
              onSelect={(id) => props.onSelect(id, agent.agent_id)}
              onDelete={props.onDelete}
              onRename={props.onRename}
              onPin={props.onPin}
              onFork={(id) => props.onFork(id, agent.agent_id)}
              forkDisabled={
                session.id === activeId ? props.activeForkDisabled : undefined
              }
              forkDisabledHint={
                session.id === activeId
                  ? props.activeForkDisabledHint
                  : undefined
              }
            />
          ))
        )}
        {props.hasMore ? (
          <button
            type="button"
            className={styles.sessionLoadMore}
            onClick={props.onLoadMore}
            disabled={props.loadingMore}
          >
            {props.loadingMore ? t("common.loading") : t("chat.expandMore")}
          </button>
        ) : null}
      </>
    );
  };
}
