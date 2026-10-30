import { ExpertIcon } from "../../Experts/components/iconForName";

export interface ChatAgentOption {
  agent_id: string;
  name: string;
  icon_name?: string | null;
  icon_url?: string | null;
  color?: string | null;
  is_shared?: boolean;
  is_owner?: boolean;
  owner_username?: string | null;
  /** Remote cloud-collab shadow expert. */
  bridge?: boolean;
  bridge_connection_id?: string | null;
  bridge_connection_name?: string | null;
  bridge_connection_icon?: string | null;
  bridge_disconnected?: boolean;
  bridge_inbound?: boolean;
}

interface ExpertAgentAvatarProps {
  iconName?: string | null;
  iconUrl?: string | null;
  color?: string | null;
  /** Lucide icon size inside the circle. */
  iconSize?: number;
  /** Avatar circle diameter in px. */
  size?: number;
  className?: string;
  /** Neutral styling for read-only history tags. */
  muted?: boolean;
}

export default function ExpertAgentAvatar({
  iconName,
  iconUrl,
  size = 32,
  className,
}: ExpertAgentAvatarProps) {
  return (
    <ExpertIcon
      iconUrl={iconUrl}
      iconName={iconName}
      size={size}
      className={className}
    />
  );
}
