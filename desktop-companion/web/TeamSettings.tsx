import React, { useEffect, useRef, useState } from "react";
import type { Agent } from "./core";
import type { TeamRecord } from "./teams";

export default function TeamSettings({
  teams,
  experts,
  selectedId,
  locked,
  error,
  onSelect,
  onSave,
}: {
  teams: TeamRecord[];
  experts: Agent[];
  selectedId: string;
  locked: boolean;
  error: string;
  onSelect: (id: string) => void;
  onSave: (
    name: string,
    memberIds: string[],
    teamId?: string,
  ) => Promise<TeamRecord>;
}) {
  const selected = teams.find((t) => t.agent_id === selectedId),
    host = experts.find((a) => a.name === "小通" && !a.is_team);
  const [creating, setCreating] = useState(!selectedId),
    [name, setName] = useState("小通团队"),
    [members, setMembers] = useState<string[]>([]),
    [dirty, setDirty] = useState(false),
    [saving, setSaving] = useState(false),
    [notice, setNotice] = useState("");
  const previousId = useRef(selectedId);
  const savingRef = useRef(false);
  useEffect(() => {
    const changed = previousId.current !== selectedId;
    previousId.current = selectedId;
    if (changed) {
      setCreating(!selectedId);
      setDirty(false);
      setNotice("");
    }
    if (selected && (changed || (!dirty && !creating))) {
      setName(selected.name);
      setMembers(
        selected.member_ids.filter((id) => id !== selected.primary_agent_id),
      );
    }
  }, [selectedId, selected, dirty, creating]);
  const choices = [
    ...experts.filter((a) => !a.is_team && a.id !== host?.id),
    ...(selected?.members || [])
      .filter(
        (m) =>
          m.agent_id !== selected?.primary_agent_id &&
          !experts.some((a) => a.id === m.agent_id),
      )
      .map((m) => ({
        id: m.agent_id,
        name: m.name + "（当前不可用）",
        is_team: false,
      })),
  ];
  const blocked = locked || saving;
  async function save() {
    if (blocked || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setNotice("");
    try {
      await onSave(name, members, creating ? undefined : selectedId);
      setDirty(false);
      setCreating(false);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "团队未保存，请重试。");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }
  return (
    <div className="team-settings">
      <label>
        团队
        <select
          aria-label="选择团队"
          disabled={blocked}
          value={creating ? "" : selectedId}
          onChange={(e) => {
            if (!e.target.value) {
              setCreating(true);
              setName("小通团队");
              setMembers([]);
              setDirty(false);
            } else {
              setCreating(false);
              setDirty(false);
              onSelect(e.target.value);
            }
          }}
        >
          <option value="">新建团队…</option>
          {selectedId && !selected && (
            <option value={selectedId}>原团队（当前不可用）</option>
          )}
          {teams.map((t) => (
            <option key={t.agent_id} value={t.agent_id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <div className="team-host">
        <strong>小通</strong>
        <span>主持人 · 固定</span>
      </div>
      <label>
        团队名称
        <input
          aria-label="团队名称"
          disabled={blocked}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setDirty(true);
          }}
        />
      </label>
      <fieldset disabled={blocked}>
        <legend>参与专家</legend>
        <div className="resource-options">
          {choices.map((a) => (
            <label key={a.id}>
              <input
                type="checkbox"
                checked={members.includes(a.id)}
                disabled={
                  !experts.some((v) => v.id === a.id) && !members.includes(a.id)
                }
                onChange={(e) => {
                  setMembers((old) =>
                    e.target.checked
                      ? [...new Set([...old, a.id])]
                      : old.filter((id) => id !== a.id),
                  );
                  setDirty(true);
                }}
              />
              {a.name}
            </label>
          ))}
        </div>
      </fieldset>
      {(notice || error || !host) && (
        <p role="alert">
          {notice || error || "请先准备本人已开放的小通主专家。"}
        </p>
      )}
      <button
        className="primary"
        disabled={
          blocked ||
          !host ||
          !name.trim() ||
          !members.length ||
          (!creating && !dirty)
        }
        onClick={() => void save()}
      >
        {saving ? "正在保存…" : creating ? "创建团队" : "保存成员"}
      </button>
    </div>
  );
}
