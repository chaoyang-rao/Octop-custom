import { Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
  Copy,
  Bot,
  Brain,
  MoreHorizontal,
  Notebook,
  Puzzle,
  Sparkles,
  Waypoints,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import ExpertReuseDialogs from "../../../components/expertReuse";
import type { OctopAgent } from "../../../context/AgentContext";

interface AgentMoreActionsProps {
  agent: OctopAgent;
  onCopied?: () => void;
  buttonClassName: string;
  onSkills: () => void;
  onSubagents: () => void;
  onTools: () => void;
  onPlugins: () => void;
  onMbti: () => void;
  onMemory: () => void;
  onChannels: () => void;
}

/** Overflow menu for expert catalog actions (skills / subagents / …). */
export default function AgentMoreActions({
  agent,
  onCopied,
  buttonClassName,
  onSkills,
  onSubagents,
  onTools,
  onPlugins,
  onMbti,
  onMemory,
  onChannels,
}: AgentMoreActionsProps) {
  const { t } = useTranslation();

  const items: MenuProps["items"] = [
    {
      key: "skills",
      icon: <Sparkles size={14} />,
      label: t("experts.skillsBtn"),
      onClick: onSkills,
    },
    {
      key: "subagents",
      icon: <Bot size={14} />,
      label: t("experts.subagentsBtn"),
      onClick: onSubagents,
    },
    {
      key: "tools",
      icon: <Wrench size={14} />,
      label: t("experts.toolsBtn"),
      onClick: onTools,
    },
    {
      key: "plugins",
      icon: <Puzzle size={14} />,
      label: t("experts.pluginsBtn"),
      onClick: onPlugins,
    },
    {
      key: "mbti",
      icon: <Brain size={14} />,
      label: t("experts.mbtiBtn"),
      onClick: onMbti,
    },
    {
      key: "memory",
      icon: <Notebook size={14} />,
      label: t("experts.memoryBtn"),
      onClick: onMemory,
    },
    {
      key: "channels",
      icon: <Waypoints size={14} />,
      label: t("experts.channelsBtn"),
      onClick: onChannels,
    },
  ];

  return (
    <ExpertReuseDialogs agent={agent} onCopied={onCopied}>
      {(actions: { copy: () => void; cli: () => void }) => (
        <Dropdown
          menu={{
            items: [
              ...items,
              ...(agent.is_owner && !agent.bridge
                ? [
                    { type: "divider" as const },
                    {
                      key: "copy-expert",
                      icon: <Copy size={14} />,
                      label: t("experts.reuse.copyTitle"),
                      onClick: actions.copy,
                    },
                    {
                      key: "reuse-cli",
                      icon: <Wrench size={14} />,
                      label: t("experts.reuse.cliTitle"),
                      onClick: actions.cli,
                    },
                  ]
                : []),
            ],
          }}
          trigger={["click"]}
          placement="bottomRight"
        >
          <Tooltip title={t("common.more")} mouseEnterDelay={0.5}>
            <button
              type="button"
              className={buttonClassName}
              aria-label={t("common.more")}
            >
              <MoreHorizontal size={13} />
            </button>
          </Tooltip>
        </Dropdown>
      )}
    </ExpertReuseDialogs>
  );
}
