/** Expert-only portraits. Account avatars use their existing independent renderer. */
const SHAPES = [
  "blob",
  "pebble",
  "squircle",
  "droplet",
  "cloud",
  "star",
  "triangle",
];
const COLORS = ["ink", "jade", "blue", "violet", "rose", "amber", "coral"];
let previous;
export function randomAvatar(random = Math.random) {
  const shapes = SHAPES.filter((value) => value !== previous?.shape);
  const colors = COLORS.filter((value) => value !== previous?.color);
  previous = {
    shape: shapes[Math.floor(random() * shapes.length)],
    color: colors[Math.floor(random() * colors.length)],
  };
  return { ...previous };
}
export function portraitFor(seed, avatars) {
  const parsed = avatars.parseAvatarUrl(seed);
  if (parsed) return parsed;
  let n = 2166136261;
  for (const char of String(seed || "expert").split(/[?#]/, 1)[0])
    n = Math.imul(n ^ char.codePointAt(0), 16777619) >>> 0;
  return { shape: SHAPES[n % 7], color: COLORS[Math.floor(n / 7) % 7] };
}
export function createExpertPresentation({ React, avatars, useAgent }) {
  const h = React.createElement;
  function memberFace(member) {
    const choice = member?.avatar_shape
      ? { shape: member.avatar_shape, color: member.avatar_color }
      : member?.config?.avatar;
    if (SHAPES.includes(choice?.shape))
      return {
        shape: choice.shape,
        color: COLORS.includes(choice.color) ? choice.color : "ink",
      };
    return portraitFor(member?.icon_url || member?.agent_id, avatars);
  }
  function TeamPortrait({ members = [], size = 48, className }) {
    const portraits = members.length
      ? members.slice(0, 4)
      : [
          "/expert-avatars/v2/blob-jade.svg",
          "/expert-avatars/v2/star-amber.svg",
          "/expert-avatars/v2/cloud-rose.svg",
        ];
    return h(
      "span",
      {
        className: `octop-team-portrait ${className || ""}`,
        style: { width: size, height: size },
        role: "img",
        "aria-label": "Team",
      },
      portraits.map((member, index) => {
        const id = typeof member === "string" ? member : member.agent_id;
        const face =
          typeof member === "string"
            ? portraitFor(member, avatars)
            : memberFace(member);
        return h(
          "span",
          {
            key: id || index,
            className: "octop-team-face",
            "data-face": index,
            style: { width: size * 0.69, height: size * 0.69 },
          },
          avatars.renderAvatar({ ...face, size: size * 0.69 }),
        );
      }),
    );
  }
  function ExpertPortrait({ iconUrl, iconName, size = 32, className, agent }) {
    const context = useAgent?.();
    agent =
      agent ||
      (iconUrl && context?.activeAgent?.icon_url === iconUrl
        ? context.activeAgent
        : null) ||
      (iconUrl && context?.agents?.find((item) => item.icon_url === iconUrl));
    const team =
      agent?.kind === "team" ||
      /\/(team-host|multi-agent-orchestrator)\.svg(?:[?#]|$)/.test(
        iconUrl || "",
      );
    if (team)
      return h(TeamPortrait, {
        members: (agent?.member_ids || []).map(
          (id) =>
            context?.agents?.find((item) => item.agent_id === id) || {
              agent_id: id,
            },
        ),
        size,
        className,
      });
    const face = agent
      ? memberFace(agent)
      : portraitFor(iconUrl || iconName, avatars);
    return avatars.renderAvatar({
      ...face,
      size,
      className,
      style: { maxWidth: "100%", maxHeight: "100%", flexShrink: 0 },
    });
  }
  function HiddenRestore({ agents = [], onRestore, label }) {
    if (!agents.length) return null;
    return h(
      "details",
      { className: "octop-hidden-restore" },
      h("summary", null, label),
      agents.map((agent) =>
        h(
          "button",
          {
            key: agent.agent_id,
            type: "button",
            onClick: () => onRestore(agent.agent_id),
          },
          agent.name,
        ),
      ),
    );
  }
  return { TeamPortrait, ExpertPortrait, HiddenRestore };
}

/** The designated primary is the account's own General Assistant, not a team persona. */
export function primaryExpertForTeam(experts, team) {
  const explicit = team?.primary_agent_id;
  return (
    (explicit && experts.find((item) => item.agent_id === explicit)) ||
    experts.find(
      (item) => item.is_owner !== false && item.is_team_primary === true,
    ) ||
    experts.find((item) => item.is_owner !== false && item.name === "小通") ||
    experts.find(
      (item) =>
        item.is_owner !== false && item.template_name === "general-assistant",
    )
  );
}
export function createPrimaryNotice({ React, Avatar }) {
  return function PrimaryExpertNotice({ expert, label }) {
    if (!expert) return null;
    return React.createElement(
      "div",
      {
        className: "octop-primary-expert-note",
        style: {
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 12,
        },
      },
      React.createElement(Avatar, {
        agent: expert,
        iconUrl: expert.icon_url,
        iconName: expert.icon_name,
        size: 24,
      }),
      React.createElement("span", null, label),
    );
  };
}
