function nativeCliForChat(activeAgent, agents, isAdmin) {
  const actor = activeAgent?.kind === "team" ? agents.find((agent) => agent.agent_id === activeAgent.primary_agent_id) : activeAgent;
  const raw = actor?.config?.native_cli;
  if (!actor || !raw || typeof raw !== "object" || Array.isArray(raw)) return;
  const spec = raw;
  if (spec.enabled !== true || typeof spec.runner !== "string" || !spec.runner.trim())
    return;
  return {
    agentId: actor.agent_id,
    runner: spec.runner.trim(),
    modelId: typeof spec.model_id === "string" ? spec.model_id.trim() : "",
    canManage: isAdmin && actor.is_owner === true && !actor.bridge,
    canSelectModel: actor.is_owner === true && !actor.bridge
  };
}
export {
  nativeCliForChat
};
