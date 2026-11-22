import React from "react";
import { ChevronDown } from "lucide-react";
import type { Agent } from "./core";
import type { TeamRecord } from "./teams";

export default function ExpertPicker({
  experts,
  teams,
  value,
  disabled,
  onChange,
}: {
  experts: Agent[];
  teams: TeamRecord[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const options = [
    ...experts.map((a) => ({ value: `expert:${a.id}`, name: a.name })),
    ...teams.map((t) => ({
      value: `team:${t.agent_id}`,
      name: `${t.name} · ${t.primary_agent_name || "待配置"}主持`,
    })),
  ];
  const selected = options.find((item) => item.value === value);
  return (
    <label
      className={`expert-picker${disabled ? " disabled" : ""}`}
      title={selected?.name || "选择专家"}
    >
      <span className="expert-picker-label" aria-hidden="true">
        {selected?.name || (value ? "原专家（当前不可用）" : "选择专家")}
      </span>
      <select
        aria-label="快捷选择专家"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">选择专家</option>
        {value && !selected && (
          <option value={value}>原专家（当前不可用）</option>
        )}
        <optgroup label="专家">
          {experts.map((a) => (
            <option key={a.id} value={`expert:${a.id}`}>
              {a.name}
            </option>
          ))}
        </optgroup>
        {!!teams.length && (
          <optgroup label="团队">
            {teams.map((t) => (
              <option key={t.agent_id} value={`team:${t.agent_id}`}>
                {t.name} · {t.primary_agent_name || "待配置"}主持
              </option>
            ))}
          </optgroup>
        )}
      </select>
      <ChevronDown size={12} aria-hidden="true" />
    </label>
  );
}
