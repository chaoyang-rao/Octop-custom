import { asList, type Agent } from "./core.ts";

// The companion consumes the Teams HTTP contract without importing dashboard code.
export interface TeamRecord {
  team_id: string;
  agent_id: string;
  name: string;
  kind: "team";
  primary_agent_id?: string | null;
  primary_agent_name?: string | null;
  member_ids: string[];
  members: { agent_id: string; name: string }[];
}
export function teamRecords(raw: unknown): TeamRecord[] {
  return asList(raw, ["items", "teams"]).filter(
    (t) =>
      typeof t.agent_id === "string" &&
      Array.isArray(t.member_ids) &&
      Array.isArray(t.members),
  ) as unknown as TeamRecord[];
}
export function markTeams(agents: Agent[], teams: TeamRecord[]): Agent[] {
  const ids = new Set(teams.map((t) => t.agent_id));
  return agents.map((a) => ({ ...a, is_team: a.is_team || ids.has(a.id) }));
}
export function teamProblem(
  team: TeamRecord | undefined,
  agents: Agent[],
): string | undefined {
  if (!team) return "请先选择或创建团队。";
  const host = agents.find((a) => a.id === team.primary_agent_id);
  if (!host || host.name !== "小通" || team.primary_agent_name !== "小通")
    return "团队必须由本人已开放的小通主专家主持。";
  if (!agents.some((a) => a.id === team.agent_id))
    return "这个团队当前未向桌宠开放，请刷新或核对授权。";
  const experts = agents.filter((a) => !a.is_team);
  const ids = new Set(team.member_ids);
  if (!ids.has(host.id) || ids.size < 2)
    return "请至少添加一位参与专家，小通会固定保留为主持人。";
  if ([...ids].some((id) => !experts.some((a) => a.id === id)))
    return "团队中有当前不可用的专家，请先调整成员或核对授权。";
}
export function liveTeamSpeakers(
  previous: string[],
  frame: Record<string, unknown>,
  team: TeamRecord,
): string[] {
  const id = String(
    frame.speaker_agent_id ?? frame.agent_id ?? frame.agent ?? "",
  );
  if (
    !id ||
    id === team.agent_id ||
    (id === team.primary_agent_id && !frame.team_wrapup)
  )
    return previous;
  if (["done", "error", "hitl_required"].includes(String(frame.type)))
    return previous.filter((v) => v !== id);
  if (["token", "reasoning", "tool_call_chunk"].includes(String(frame.type)))
    return [...new Set([...previous, id])];
  return previous;
}
