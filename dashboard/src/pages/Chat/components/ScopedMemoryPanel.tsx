import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  List,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  scopedMemoryApi,
  type MemoryRevision,
  type MemoryScope,
  type ScopedMemoryAtom,
  type ScopedMemoryList,
} from "../../../api/modules/scopedMemory";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatServerIsoDateTime } from "../../../utils/formatMessageTime";

interface Props {
  agentId: string;
  threadId: string;
  onClose: () => void;
}

export default function ScopedMemoryPanel({
  agentId,
  threadId,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const failedText = t("scopedMemory.failed");
  const timeZone = useServerTimezone();
  const [scope, setScope] = useState<MemoryScope>("auto");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [includeOld, setIncludeOld] = useState(false);
  const [data, setData] = useState<ScopedMemoryList>();
  const [availableScopes, setAvailableScopes] = useState<MemoryScope[]>([
    "user",
    "expert",
    "session",
  ]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<ScopedMemoryAtom>();
  const [revisions, setRevisions] = useState<MemoryRevision[]>();
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const version = ++generation.current;
    setLoading(true);
    setError("");
    setData(undefined);
    try {
      const next = await scopedMemoryApi.list(
        agentId,
        threadId,
        scope,
        query,
        offset,
        includeOld,
      );
      if (generation.current === version) {
        setData(next);
        setAvailableScopes(next.available_scopes);
      }
    } catch (e) {
      if (generation.current === version)
        setError(e instanceof Error ? e.message : failedText);
    } finally {
      if (generation.current === version) setLoading(false);
    }
  }, [agentId, threadId, scope, query, offset, includeOld, failedText]);
  useEffect(() => {
    const generationRef = generation;
    void reload();
    return () => {
      generationRef.current++;
    };
  }, [reload]);

  const mutate = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      setDraft("");
      setEditing(undefined);
      setRevisions(undefined);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("scopedMemory.failed"));
    } finally {
      setBusy(false);
    }
  };
  const selected = data?.scope ?? scope;
  const options = ["auto", ...availableScopes] as MemoryScope[];
  return (
    <Drawer open onClose={onClose} title={t("scopedMemory.title")} width={520}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary">
          {t("scopedMemory.description")}
        </Typography.Paragraph>
        <Select
          aria-label={t("scopedMemory.scope")}
          value={scope}
          disabled={busy}
          style={{ width: "100%" }}
          options={options.map((value) => ({
            value,
            label: t(`scopedMemory.scopes.${value}`),
          }))}
          onChange={(value) => {
            setScope(value);
            setOffset(0);
            setEditing(undefined);
            setDraft("");
            setRevisions(undefined);
          }}
        />
        {data?.project_name && <Tag>{data.project_name}</Tag>}
        <Input.Search
          allowClear
          aria-label={t("scopedMemory.search")}
          placeholder={t("scopedMemory.search")}
          onSearch={(value) => {
            setQuery(value);
            setOffset(0);
          }}
        />
        <Space>
          <Switch
            size="small"
            checked={includeOld}
            aria-label={t("scopedMemory.includeOld")}
            disabled={busy}
            onChange={(value) => {
              setIncludeOld(value);
              setOffset(0);
            }}
          />
          <Typography.Text>{t("scopedMemory.includeOld")}</Typography.Text>
        </Space>
        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            action={
              <Button size="small" onClick={() => void reload()}>
                {t("common.retry")}
              </Button>
            }
          />
        )}
        <List
          loading={loading}
          dataSource={data?.items ?? []}
          locale={{
            emptyText: error ? (
              " "
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("scopedMemory.empty")}
              />
            ),
          }}
          renderItem={(atom) => (
            <List.Item>
              <Space
                direction="vertical"
                style={{ width: "100%" }}
                size="small"
              >
                <Typography.Text
                  delete={!!atom.deprecated_at}
                  style={{ whiteSpace: "pre-wrap" }}
                >
                  {atom.assertion}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {formatServerIsoDateTime(atom.created_at, timeZone)}
                  {atom.deprecated_at ? ` · ${t("scopedMemory.retired")}` : ""}
                </Typography.Text>
                {atom.sources.map((source, index) => (
                  <Link
                    key={`${source.thread_id}-${index}`}
                    to={`/chat/${encodeURIComponent(
                      source.agent_id,
                    )}/${encodeURIComponent(source.thread_id)}`}
                    onClick={onClose}
                  >
                    {t("scopedMemory.source")}: {source.title}
                  </Link>
                ))}
                <Space>
                  {!atom.deprecated_at && (
                    <Button
                      size="small"
                      type="text"
                      disabled={busy || loading}
                      onClick={() => {
                        setEditing(atom);
                        setDraft(atom.assertion);
                        setRevisions(undefined);
                      }}
                    >
                      {t("scopedMemory.correct")}
                    </Button>
                  )}
                  {!atom.deprecated_at && (
                    <Button
                      size="small"
                      type="text"
                      disabled={busy || loading}
                      onClick={() =>
                        void mutate(() =>
                          scopedMemoryApi.retire(
                            agentId,
                            threadId,
                            selected,
                            atom.id,
                            data!.scope_token,
                          ),
                        )
                      }
                    >
                      {t("scopedMemory.retire")}
                    </Button>
                  )}
                  <Button
                    size="small"
                    type="text"
                    disabled={busy || loading}
                    onClick={async () => {
                      const version = generation.current;
                      try {
                        const result = await scopedMemoryApi.revisions(
                          agentId,
                          threadId,
                          selected,
                          atom.id,
                        );
                        if (version === generation.current)
                          setRevisions(result.items);
                      } catch (e) {
                        if (version === generation.current)
                          setError(
                            e instanceof Error
                              ? e.message
                              : t("scopedMemory.failed"),
                          );
                      }
                    }}
                  >
                    {t("scopedMemory.revisions")}
                  </Button>
                </Space>
              </Space>
            </List.Item>
          )}
        />
        {data && (
          <Space>
            <Button
              size="small"
              disabled={!offset || busy}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              {t("scopedMemory.previous")}
            </Button>
            <Typography.Text type="secondary">
              {t("scopedMemory.total", { count: data.total })}
            </Typography.Text>
            <Button
              size="small"
              disabled={!data.has_more || busy}
              onClick={() => setOffset(offset + 20)}
            >
              {t("scopedMemory.next")}
            </Button>
          </Space>
        )}
        {revisions && (
          <Alert
            type="info"
            message={t("scopedMemory.revisions")}
            description={
              <Space direction="vertical">
                {revisions.map((item) => (
                  <div key={item.id}>
                    <Typography.Text type="secondary">
                      {formatServerIsoDateTime(item.timestamp, timeZone)}
                    </Typography.Text>
                    <div>{item.before?.assertion}</div>
                    <div>{item.after?.assertion ?? item.action}</div>
                  </div>
                ))}
              </Space>
            }
            closable
            onClose={() => setRevisions(undefined)}
          />
        )}
        <Typography.Text strong>
          {t(editing ? "scopedMemory.correct" : "scopedMemory.add")}
        </Typography.Text>
        <Input.TextArea
          aria-label={t("scopedMemory.content")}
          value={draft}
          maxLength={4000}
          autoSize={{ minRows: 3, maxRows: 8 }}
          disabled={busy || loading || !data}
          placeholder={t("scopedMemory.content")}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Space>
          <Button
            type="primary"
            loading={busy}
            disabled={!draft.trim() || loading || !data}
            onClick={() =>
              void mutate(() =>
                scopedMemoryApi.save(
                  agentId,
                  threadId,
                  selected,
                  draft.trim(),
                  data!.scope_token,
                  editing?.id,
                ),
              )
            }
          >
            {t("common.save")}
          </Button>
          {editing && (
            <Button
              disabled={busy}
              onClick={() => {
                setEditing(undefined);
                setDraft("");
              }}
            >
              {t("common.cancel")}
            </Button>
          )}
        </Space>
        <Typography.Paragraph type="secondary">
          {t("scopedMemory.historyHint")}
        </Typography.Paragraph>
      </Space>
    </Drawer>
  );
}
