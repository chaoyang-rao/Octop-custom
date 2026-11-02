/**
 * "What I sent" panel: files uploaded to the agent workspace ``inbound/`` folder
 * plus links pasted in the current thread (with page titles).
 * Shipped as a standalone asset module, so it is written without JSX.
 */

function messageText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (!part || typeof part !== "object") return "";
        return typeof part.text === "string" ? part.text : "";
      })
      .join("\n");
  }
  return "";
}

export function collectSentLinks(messages) {
  const seen = new Set();
  const found = [];
  for (const message of messages) {
    if (!message || typeof message !== "object") continue;
    const role = String(message.role || message.type || "");
    if (!/user|human/i.test(role)) continue;
    const text = messageText(message.content);
    const matches = text.match(/https?:\/\/[^\s<>"'`）)，。；]+/g) || [];
    for (const raw of matches) {
      const url = raw.replace(/[.,;:!?]+$/, "");
      if (url.length < 8 || seen.has(url)) continue;
      seen.add(url);
      found.push(url);
    }
  }
  return found.slice(-20).reverse();
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_error) {
    return url;
  }
}

export function createComposerFilesButton({ React, Icon }) {
  const { createElement: h, useCallback, useEffect, useRef, useState } = React;

  function readToken() {
    try {
      return (
        window.localStorage.getItem("auth_token") ||
        window.sessionStorage.getItem("auth_token") ||
        ""
      );
    } catch (_error) {
      return "";
    }
  }

  function authHeaders(json) {
    const token = readToken();
    const headers = { Accept: "application/json" };
    if (json) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  function displayName(row) {
    const raw = String((row && (row.path || row.name)) || "");
    const base = raw.replace(/\\/g, "/").split("/").pop() || raw;
    return base.replace(/^\d{10}_/, "");
  }

  function formatSize(size) {
    const value = Number(size) || 0;
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
    return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  function formatTime(raw) {
    if (!raw) return "";
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
      date.getMinutes(),
    )}`;
  }

  return function ComposerFilesButton({ agentId, threadId, t, floating, buttonClassName }) {
    const [open, setOpen] = useState(false);
    const [files, setFiles] = useState(null);
    const [failed, setFailed] = useState(false);
    const [failDetail, setFailDetail] = useState("");
    const [links, setLinks] = useState([]);
    const [busyPath, setBusyPath] = useState("");
    const rootRef = useRef(null);

    const label = t("chat.files.sent", "我发过的文件");

    useEffect(() => {
      if (!open) return undefined;
      const onDown = (event) => {
        if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
      };
      const onKey = (event) => {
        if (event.key === "Escape") setOpen(false);
      };
      document.addEventListener("mousedown", onDown);
      document.addEventListener("keydown", onKey);
      return () => {
        document.removeEventListener("mousedown", onDown);
        document.removeEventListener("keydown", onKey);
      };
    }, [open]);

    // Files: agent-scoped only, so a changing thread id never restarts the load.
    useEffect(() => {
      if (!open || !agentId) return undefined;
      let alive = true;
      setFailed(false);
      setFailDetail("");
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 10000);

      fetch(`/api/agents/${encodeURIComponent(agentId)}/workspace/tree?path=inbound`, {
        headers: authHeaders(false),
        cache: "no-store",
        credentials: "same-origin",
        signal: controller.signal,
      })
        .then((response) => {
          if (response.status === 404) return [];
          if (response.ok) return response.json();
          const error = new Error(String(response.status));
          error.status = response.status;
          throw error;
        })
        .then((rows) => {
          if (!alive) return;
          window.clearTimeout(timer);
          const list = (Array.isArray(rows) ? rows : [])
            .filter((row) => row && !row.is_dir)
            .sort((a, b) =>
              String(b.modified_at || "").localeCompare(String(a.modified_at || "")),
            );
          setFiles(list);
        })
        .catch((error) => {
          if (!alive) return;
          window.clearTimeout(timer);
          setFiles((current) => (current === null ? [] : current));
          setFailed(true);
          setFailDetail(
            error && (error.status || error.name) ? String(error.status || error.name) : "",
          );
        });

      return () => {
        alive = false;
        window.clearTimeout(timer);
        controller.abort();
      };
    }, [open, agentId]);

    // Links: scanned from this thread's history, titles resolved by the server.
    useEffect(() => {
      if (!open || !agentId || !threadId) return undefined;
      let alive = true;
      setLinks([]);
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), 45000);
      const base = `/api/agents/${encodeURIComponent(agentId)}`;
      const pageSize = 200;

      // The history API caps each page at 200 messages, so early messages
      // (where a user's link usually lives) fall outside a single page.
      // Walk pages until the archive is exhausted (bounded at 10 pages).
      const loadAllMessages = async () => {
        const all = [];
        for (let offset = 0, page = 0; page < 10; page += 1, offset += pageSize) {
          const response = await fetch(
            `${base}/threads/${encodeURIComponent(threadId)}/history?limit=${pageSize}&offset=${offset}`,
            { headers: authHeaders(false), credentials: "same-origin", signal: controller.signal },
          );
          if (!response.ok) break;
          const data = await response.json();
          const messages = (data && data.messages) || [];
          all.push(...messages);
          if (!data || !data.has_more) break;
        }
        return all;
      };

      loadAllMessages()
        .then((messages) => {
          if (!alive) return undefined;
          const urls = collectSentLinks(messages);
          if (urls.length === 0) return undefined;
          return fetch("/api/link-titles", {
            method: "POST",
            headers: authHeaders(true),
            credentials: "same-origin",
            signal: controller.signal,
            body: JSON.stringify(urls.map((url) => ({ url }))),
          })
            .then((response) => (response.ok ? response.json() : []))
            .then((rows) => {
              if (!alive) return;
              const titles = new Map(
                (Array.isArray(rows) ? rows : []).map((row) => [row.url, row.title || ""]),
              );
              setLinks(urls.map((url) => ({ url, title: titles.get(url) || "" })));
            });
        })
        .catch(() => {
          /* links are optional; keep the file list usable */
        })
        .finally(() => window.clearTimeout(timer));

      return () => {
        alive = false;
        window.clearTimeout(timer);
        controller.abort();
      };
    }, [open, agentId, threadId]);

    const openFile = useCallback(
      async (row) => {
        if (!agentId || busyPath) return;
        setBusyPath(row.path);
        try {
          const response = await fetch(
            `/api/agents/${encodeURIComponent(agentId)}/workspace/download?path=${encodeURIComponent(
              row.path,
            )}`,
            { headers: authHeaders(false) },
          );
          if (!response.ok) throw new Error(String(response.status));
          const blob = await response.blob();
          const href = URL.createObjectURL(blob);
          const win = window.open(href, "_blank");
          if (!win) {
            const anchor = document.createElement("a");
            anchor.href = href;
            anchor.download = displayName(row) || "download";
            anchor.click();
          }
          window.setTimeout(() => URL.revokeObjectURL(href), 60000);
        } catch (_error) {
          setBusyPath("");
          return;
        }
        setBusyPath("");
      },
      [agentId, busyPath],
    );

    const fileSection = (() => {
      if (!agentId) {
        return h(
          "div",
          { className: "octop-composer-files-hint" },
          t("chat.files.noAgent", "请先选择智能体"),
        );
      }
      if (files === null && !failed) {
        return h(
          "div",
          { className: "octop-composer-files-hint" },
          t("chat.files.loading", "加载中…"),
        );
      }
      if (failed) {
        return h(
          "div",
          { className: "octop-composer-files-hint" },
          failDetail
            ? `${t("chat.files.loadFailed", "文件列表加载失败")} (${failDetail})`
            : t("chat.files.loadFailed", "文件列表加载失败"),
        );
      }
      if (files.length === 0 && links.length === 0) {
        return h(
          "div",
          { className: "octop-composer-files-hint" },
          t("chat.files.empty", "还没有发送过文件或链接"),
        );
      }
      if (files.length === 0) return null;
      return h(
        "ul",
        { className: "octop-composer-files-list" },
        files.map((row) =>
          h(
            "li",
            { key: row.path },
            h(
              "button",
              {
                type: "button",
                className: "octop-composer-files-item",
                disabled: Boolean(busyPath),
                onClick: () => openFile(row),
                title: displayName(row),
              },
              h("span", { className: "octop-composer-files-name" }, displayName(row)),
              h(
                "span",
                { className: "octop-composer-files-meta" },
                `${formatSize(row.size)}${
                  formatTime(row.modified_at) ? ` · ${formatTime(row.modified_at)}` : ""
                }`,
              ),
            ),
          ),
        ),
      );
    })();

    const linkSection =
      links.length === 0
        ? null
        : h(
            "div",
            { className: "octop-composer-files-section" },
            h("div", { className: "octop-composer-files-head" }, t("chat.files.links", "链接")),
            h(
              "ul",
              { className: "octop-composer-files-list" },
              links.map((link) =>
                h(
                  "li",
                  { key: link.url },
                  h(
                    "a",
                    {
                      className: "octop-composer-files-item",
                      href: link.url,
                      target: "_blank",
                      rel: "noreferrer noopener",
                      title: link.url,
                    },
                    h(
                      "span",
                      { className: "octop-composer-files-name" },
                      link.title || hostOf(link.url),
                    ),
                    h("span", { className: "octop-composer-files-meta" }, hostOf(link.url)),
                  ),
                ),
              ),
            ),
          );

    return h(
      "div",
      {
        className: floating
          ? "octop-composer-files octop-composer-files--float"
          : "octop-composer-files",
        ref: rootRef,
      },
      h(
        "button",
        {
          type: "button",
          className: buttonClassName
            ? `octop-composer-files-btn octop-composer-files-btn--hosted ${buttonClassName}`
            : "octop-composer-files-btn",
          "aria-label": label,
          title: label,
          "aria-expanded": open ? "true" : "false",
          onClick: () => setOpen((value) => !value),
        },
        h(Icon, { size: floating ? 20 : 16, strokeWidth: floating ? 2.1 : 1.75 }),
      ),
      open
        ? h(
            "div",
            {
              className: "octop-composer-files-panel",
              role: "dialog",
              "aria-label": label,
            },
            h("div", { className: "octop-composer-files-head" }, label),
            fileSection,
            linkSection,
          )
        : null,
    );
  };
}
