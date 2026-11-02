/** Project folders for the locally customized Octop dashboard.
 * This module uses the app's React instance, authenticated request client,
 * navigation callbacks and conversation rows. It never reads project files.
 */
import { createProjectFolderPicker } from "./project-folder-picker.mjs";

export function createProjectFolders({
  React,
  request,
  toSession,
  sortSessions,
  Row,
  CompactRow,
  resolveStatus,
  emitSessionEvent,
  onSessionEvent,
  Dropdown,
  Plus,
  More,
  Chevron,
  translate,
}) {
  const h = React.createElement;
  const Folder = ({ size = 14, ...props }) =>
    h(
      "svg",
      {
        width: size,
        height: size,
        style: { flexShrink: 0 },
        viewBox: "0 0 24 24",
        fill: "none",
        stroke: "currentColor",
        strokeLinecap: "round",
        strokeLinejoin: "round",
        ...props,
      },
      h("path", {
        d: "M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
      }),
    );
  const apiPath = (id) => `/agents/${encodeURIComponent(id)}`;
  const folderKey = (id) => `octop:project-folders:${id}`;
  const icon = (Icon, props = {}) =>
    h(Icon, { size: 14, strokeWidth: 1.8, "aria-hidden": true, ...props });
  const readableError = (error) => {
    const raw = String(error?.message || error || translate("failed"));
    const jsonStart = raw.indexOf("{");
    if (jsonStart >= 0) {
      try {
        const body = JSON.parse(raw.slice(jsonStart));
        if (typeof body.detail === "string") return body.detail;
      } catch {}
    }
    return raw.includes("409") ? translate("running") : raw;
  };

  function Dialog({ title, busy, onClose, children }) {
    const ref = React.useRef(null);
    React.useEffect(() => {
      const dialog = ref.current;
      if (dialog && !dialog.open) dialog.showModal();
      return () => {
        if (dialog?.open) dialog.close();
      };
    }, []);
    return h(
      "dialog",
      {
        ref,
        className: "octop-project-dialog",
        "aria-label": title,
        onCancel: (e) => {
          e.preventDefault();
          if (!busy) onClose();
        },
        onClick: (e) => {
          if (!busy && e.target === e.currentTarget) {
            const rect = e.currentTarget.getBoundingClientRect();
            if (
              e.clientX < rect.left ||
              e.clientX > rect.right ||
              e.clientY < rect.top ||
              e.clientY > rect.bottom
            )
              onClose();
          }
        },
      },
      h(
        "div",
        { className: "octop-project-dialog-inner" },
        h(
          "div",
          { className: "octop-project-dialog-heading" },
          h("h2", null, title),
          h(
            "button",
            {
              type: "button",
              disabled: busy,
              onClick: onClose,
              "aria-label": translate("close"),
              className: "octop-project-icon-button",
            },
            "×",
          ),
        ),
        children,
      ),
    );
  }

  const ProjectFolderPicker = createProjectFolderPicker({
    React,
    request,
    Dialog,
    readableError,
    translate,
  });

  return function ProjectSessionList({
    agent,
    sessions,
    activeId,
    searchQuery = "",
    onSelect,
    onDelete,
    onRename,
    onPin,
    onFork,
    activeForkDisabled,
    activeForkDisabledHint,
    liveWorkingIds,
    compact = false,
    hasMore,
    loadingMore,
    onLoadMore,
  }) {
    const agentId = agent.agent_id;
    const [projects, setProjects] = React.useState([]);
    const [rows, setRows] = React.useState(sessions || []);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState("");
    const [busy, setBusy] = React.useState(false);
    const [dialog, setDialog] = React.useState(null);
    const [path, setPath] = React.useState("");
    const [name, setName] = React.useState("");
    const generation = React.useRef(0);
    const mounted = React.useRef(true);
    const [collapsed, setCollapsed] = React.useState(() => {
      try {
        return new Set(
          JSON.parse(localStorage.getItem(folderKey(agentId)) || "[]"),
        );
      } catch {
        return new Set();
      }
    });
    const [folderPickerOpen, setFolderPickerOpen] = React.useState(false);
    const activeProjectPath = rows.find(
      (row) => row.id === activeId,
    )?.projectPath;
    React.useEffect(() => {
      if (!activeProjectPath) return;
      setCollapsed((prev) => {
        if (!prev.has(activeProjectPath)) return prev;
        const next = new Set(prev);
        next.delete(activeProjectPath);
        return next;
      });
    }, [activeId, activeProjectPath]);

    const refresh = React.useCallback(async () => {
      const current = ++generation.current;
      try {
        const [groups, threads] = await Promise.all([
          request(`${apiPath(agentId)}/projects`),
          request(`${apiPath(agentId)}/threads?limit=10000`),
        ]);
        if (mounted.current && generation.current === current) {
          setProjects(groups);
          setRows(sortSessions(threads.map(toSession)));
          setError("");
        }
      } catch (e) {
        if (mounted.current && generation.current === current)
          setError(readableError(e));
      } finally {
        if (mounted.current && generation.current === current)
          setLoading(false);
      }
    }, [agentId]);
    React.useEffect(() => {
      mounted.current = true;
      refresh();
      return () => {
        mounted.current = false;
        generation.current++;
      };
    }, [refresh]);
    React.useEffect(() => {
      setRows((previous) =>
        sortSessions([
          ...new Map(
            [...previous, ...(sessions || [])].map((row) => [row.id, row]),
          ).values(),
        ]),
      );
      refresh();
    }, [sessions, refresh]);
    React.useEffect(
      () =>
        onSessionEvent((event) => {
          if (!event.agentId || event.agentId === agentId) refresh();
        }),
      [agentId, refresh],
    );
    const notify = () => emitSessionEvent({ kind: "sessionsChanged", agentId });
    const toggle = (groupPath) => {
      setCollapsed((prev) => {
        const next = new Set(prev);
        next.has(groupPath) ? next.delete(groupPath) : next.add(groupPath);
        try {
          localStorage.setItem(folderKey(agentId), JSON.stringify([...next]));
        } catch {}
        return next;
      });
    };
    const act = async (task) => {
      if (busy) return;
      setBusy(true);
      setError("");
      try {
        await task();
      } catch (e) {
        setError(readableError(e));
      } finally {
        if (mounted.current) setBusy(false);
      }
    };
    const openAdd = () => {
      setError("");
      setPath("");
      setName("");
      setFolderPickerOpen(false);
      setDialog({ kind: "add" });
    };
    const create = (projectPath) =>
      act(async () => {
        const created = await request(`${apiPath(agentId)}/threads`, {
          method: "POST",
          body: JSON.stringify({ project_path: projectPath || null }),
        });
        await refresh();
        notify();
        onSelect(created.thread_id, agentId);
      });
    const saveProject = (e) => {
      e.preventDefault();
      act(async () => {
        await request(`${apiPath(agentId)}/projects`, {
          method: "POST",
          body: JSON.stringify({
            project_path: path.trim(),
            project_name: name.trim() || undefined,
          }),
        });
        await refresh();
        setDialog(null);
      });
    };
    const move = (e) => {
      e.preventDefault();
      act(async () => {
        await request(
          `${apiPath(agentId)}/threads/${encodeURIComponent(
            dialog.session.id,
          )}/project`,
          {
            method: "PATCH",
            body: JSON.stringify({ project_path: path || null }),
          },
        );
        await refresh();
        setDialog(null);
        notify();
      });
    };
    const remove = () =>
      act(async () => {
        await request(`${apiPath(agentId)}/projects`, {
          method: "DELETE",
          body: JSON.stringify({ project_path: dialog.project.project_path }),
        });
        await refresh();
        setDialog(null);
        notify();
      });
    const afterRowAction =
      (handler) =>
      (...args) => {
        const result = handler(...args);
        if (result && typeof result.then === "function")
          result.then(() => refresh()).catch((e) => setError(readableError(e)));
        else window.setTimeout(refresh, 250);
        return result;
      };
    const query = searchQuery.trim().toLowerCase();
    const groupMap = new Map(
      projects.map((project) => [
        project.project_path,
        { ...project, rows: [] },
      ]),
    );
    const ungrouped = [];
    for (const row of rows) {
      if (!row.projectPath) {
        ungrouped.push(row);
        continue;
      }
      if (!groupMap.has(row.projectPath))
        groupMap.set(row.projectPath, {
          project_path: row.projectPath,
          project_name:
            row.projectName || row.projectPath.split("/").filter(Boolean).pop(),
          rows: [],
        });
      groupMap.get(row.projectPath).rows.push(row);
    }
    const groups = [...groupMap.values()].sort((a, b) =>
      a.project_name.localeCompare(b.project_name, "zh-CN"),
    );
    const RowComponent = compact ? CompactRow() : Row;
    const renderRow = (session) =>
      h(RowComponent, {
        key: session.id,
        session,
        isActive: session.id === activeId,
        workStatus: resolveStatus(session, liveWorkingIds),
        onSelect: (id) => onSelect(id, agentId),
        onDelete: afterRowAction(onDelete),
        onRename: afterRowAction(onRename),
        onPin: afterRowAction(onPin),
        onFork: (id) => onFork(id, agentId),
        forkDisabled: session.id === activeId ? activeForkDisabled : undefined,
        forkDisabledHint:
          session.id === activeId ? activeForkDisabledHint : undefined,
        projectMenuItems: [
          {
            key: "move-project",
            label: session.projectPath
              ? translate("changeProject")
              : translate("moveProject"),
            icon: icon(Folder),
            disabled: !!session.turnActive || busy,
            onClick: ({ domEvent }) => {
              domEvent.stopPropagation();
              setError("");
              setPath(session.projectPath || "");
              setDialog({ kind: "move", session });
            },
          },
        ],
      });
    const matches = (session, group) =>
      !query ||
      [session.name, group?.project_name, group?.project_path].some((value) =>
        String(value || "")
          .toLowerCase()
          .includes(query),
      );
    const groupNodes = groups.map((project) => {
      const list = project.rows.filter((row) => matches(row, project));
      if (
        query &&
        !list.length &&
        !`${project.project_name} ${project.project_path}`
          .toLowerCase()
          .includes(query)
      )
        return null;
      const open = !!query || !collapsed.has(project.project_path);
      return h(
        "section",
        {
          className: "octop-project-group",
          key: project.project_path,
          "aria-label": project.project_name,
        },
        h(
          "div",
          { className: "octop-project-header" },
          h(
            "button",
            {
              type: "button",
              className: "octop-project-toggle",
              onClick: () => toggle(project.project_path),
              "aria-expanded": open,
              title: project.project_path,
            },
            icon(Chevron, {
              className: open
                ? "octop-project-chevron open"
                : "octop-project-chevron",
            }),
            icon(Folder),
            h(
              "span",
              { className: "octop-project-name" },
              project.project_name,
            ),
            h(
              "span",
              { className: "octop-project-count" },
              project.rows.length,
            ),
          ),
          h(
            "button",
            {
              type: "button",
              className: "octop-project-icon-button",
              title: translate("newInProject", { name: project.project_name }),
              "aria-label": translate("newInProject", {
                name: project.project_name,
              }),
              disabled: busy,
              onClick: () => create(project.project_path),
            },
            icon(Plus),
          ),
          h(
            Dropdown,
            {
              trigger: ["click"],
              placement: "bottomRight",
              menu: {
                items: [
                  {
                    key: "remove-project",
                    label: translate("removeProject"),
                    onClick: () => {
                      setError("");
                      setDialog({ kind: "remove", project });
                    },
                  },
                ],
              },
            },
            h(
              "button",
              {
                type: "button",
                className: "octop-project-icon-button",
                title: translate("options", { name: project.project_name }),
                "aria-label": translate("options", {
                  name: project.project_name,
                }),
                disabled: busy,
              },
              icon(More),
            ),
          ),
        ),
        open
          ? h(
              "div",
              { className: "octop-project-rows" },
              list.length
                ? list.map(renderRow)
                : h(
                    "p",
                    { className: "octop-project-empty" },
                    translate("emptyProject"),
                  ),
            )
          : null,
      );
    });
    const previewIds = new Set((sessions || []).map((row) => row.id));
    const loose = ungrouped.filter(
      (row) => matches(row) && (query || previewIds.has(row.id)),
    );
    const errorNode = error
      ? h("div", { className: "octop-project-error", role: "alert" }, error)
      : null;
    const actions = (onSubmit, submitLabel) =>
      h(
        "div",
        { className: "octop-project-dialog-actions" },
        h(
          "button",
          {
            type: "button",
            disabled: busy,
            onClick: () => {
              setDialog(null);
              setError("");
            },
          },
          translate("cancel"),
        ),
        h(
          "button",
          {
            type: onSubmit ? "submit" : "button",
            className: "primary",
            disabled: busy,
            onClick: onSubmit ? undefined : remove,
          },
          busy ? translate("busy") : submitLabel,
        ),
      );

    return h(
      "div",
      {
        className: `octop-project-list${compact ? " compact" : ""}`,
        "data-testid": "project-session-list",
      },
      h(
        "div",
        { className: "octop-project-toolbar" },
        h("span", null, translate("projects")),
        h(
          "button",
          {
            type: "button",
            onClick: openAdd,
            disabled: busy,
            className: "octop-project-add",
          },
          icon(Plus),
          translate("add"),
        ),
      ),
      !dialog && errorNode,
      loading && !rows.length && !projects.length
        ? h(
            "p",
            { className: "octop-project-empty", role: "status" },
            translate("loadingProjects"),
          )
        : null,
      groupNodes,
      loose.length || !query
        ? h(
            "section",
            {
              className: "octop-project-ungrouped",
              "aria-label": translate("ungroupedLabel"),
            },
            h(
              "div",
              { className: "octop-project-header" },
              h(
                "span",
                { className: "octop-project-ungrouped-label" },
                translate("ungrouped"),
                h(
                  "span",
                  { className: "octop-project-count" },
                  ungrouped.length,
                ),
              ),
              h(
                "button",
                {
                  type: "button",
                  className: "octop-project-icon-button",
                  title: translate("newUngrouped"),
                  "aria-label": translate("newUngrouped"),
                  disabled: busy,
                  onClick: () => create(null),
                },
                icon(Plus),
              ),
            ),
            loose.length
              ? loose.map(renderRow)
              : h(
                  "p",
                  { className: "octop-project-empty" },
                  translate("emptyUngrouped"),
                ),
          )
        : null,
      hasMore && !query
        ? h(
            "button",
            {
              type: "button",
              className: "octop-project-add",
              disabled: loadingMore,
              onClick: onLoadMore,
            },
            loadingMore ? translate("loading") : translate("more"),
          )
        : null,
      dialog?.kind === "add"
        ? h(
            Dialog,
            {
              title: translate("addFolder"),
              busy: busy || folderPickerOpen,
              onClose: () => {
                setDialog(null);
                setError("");
              },
            },
            h(
              "form",
              { onSubmit: saveProject },
              h("p", { className: "octop-project-help" }, translate("addHint")),
              h(
                "label",
                null,
                translate("name"),
                h("input", {
                  value: name,
                  onChange: (e) => setName(e.target.value),
                  placeholder: translate("namePlaceholder"),
                  autoFocus: true,
                  maxLength: 100,
                }),
              ),
              h(
                "label",
                { htmlFor: `octop-project-path-${agentId}` },
                translate("path"),
              ),
              h(
                "div",
                { className: "octop-project-path-field" },
                h("input", {
                  id: `octop-project-path-${agentId}`,
                  value: path,
                  onChange: (e) => setPath(e.target.value),
                  placeholder: translate("pathPlaceholder"),
                  required: true,
                  spellCheck: false,
                  autoComplete: "off",
                }),
                h(
                  "button",
                  {
                    type: "button",
                    className: "octop-project-browse-button",
                    "aria-label": translate("browse"),
                    disabled: busy,
                    onClick: () => setFolderPickerOpen(true),
                  },
                  icon(Folder),
                  translate("browse"),
                ),
              ),
              h(
                "p",
                { className: "octop-project-help" },
                translate("pathHint"),
              ),
              errorNode,
              actions(true, translate("add")),
            ),
          )
        : null,
      dialog?.kind === "add" && folderPickerOpen
        ? h(ProjectFolderPicker, {
            initialPath:
              path || activeProjectPath || projects[0]?.project_path || "",
            onClose: () => setFolderPickerOpen(false),
            onSelect: (value) => {
              setPath(value);
              setError("");
              setFolderPickerOpen(false);
            },
          })
        : null,
      dialog?.kind === "move"
        ? h(
            Dialog,
            {
              title: translate("changeConversationProject"),
              busy,
              onClose: () => {
                setDialog(null);
                setError("");
              },
            },
            h(
              "form",
              { onSubmit: move },
              h("p", { className: "octop-project-help" }, dialog.session.name),
              h(
                "label",
                null,
                translate("assignedProject"),
                h(
                  "select",
                  {
                    value: path,
                    onChange: (e) => setPath(e.target.value),
                    autoFocus: true,
                  },
                  h("option", { value: "" }, translate("ungrouped")),
                  ...groups.map((project) =>
                    h(
                      "option",
                      {
                        key: project.project_path,
                        value: project.project_path,
                      },
                      project.project_name,
                    ),
                  ),
                ),
              ),
              h(
                "p",
                { className: "octop-project-help" },
                translate("moveHint"),
              ),
              errorNode,
              actions(true, translate("save")),
            ),
          )
        : null,
      dialog?.kind === "remove"
        ? h(
            Dialog,
            {
              title: translate("removeProject"),
              busy,
              onClose: () => {
                setDialog(null);
                setError("");
              },
            },
            h(
              "p",
              null,
              translate("removeDescription", {
                name: dialog.project.project_name,
              }),
            ),
            h(
              "p",
              { className: "octop-project-help" },
              translate("removeHint"),
            ),
            errorNode,
            actions(false, translate("remove")),
          )
        : null,
    );
  };
}
