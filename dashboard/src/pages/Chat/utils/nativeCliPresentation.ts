import type { OctopAgent } from "../../../context/AgentContext";

export interface NativeCliPresentation {
  agentId: string;
  runner: string;
  modelId: string;
  canManage: boolean;
  canSelectModel: boolean;
}

/** Teams use their real primary expert's engine. */
export function nativeCliForChat(
  activeAgent: OctopAgent | null,
  agents: readonly OctopAgent[],
  isAdmin: boolean,
): NativeCliPresentation | undefined {
  const actor =
    activeAgent?.kind === "team"
      ? agents.find((agent) => agent.agent_id === activeAgent.primary_agent_id)
      : activeAgent;
  const raw = actor?.config?.native_cli;
  if (!actor || !raw || typeof raw !== "object" || Array.isArray(raw)) return;
  const spec = raw as Record<string, unknown>;
  if (
    spec.enabled !== true ||
    typeof spec.runner !== "string" ||
    !spec.runner.trim()
  )
    return;
  return {
    agentId: actor.agent_id,
    runner: spec.runner.trim(),
    modelId: typeof spec.model_id === "string" ? spec.model_id.trim() : "",
    canManage: isAdmin && actor.is_owner === true && !actor.bridge,
    canSelectModel: actor.is_owner === true && !actor.bridge,
  };
}
