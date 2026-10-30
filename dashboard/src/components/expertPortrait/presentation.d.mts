export function randomAvatar(random?: () => number): {
  shape: string;
  color: string;
};
export function portraitFor(
  seed: unknown,
  avatars: any,
): { shape: string; color: string };
export function createExpertPresentation(options: any): any;

export function primaryExpertForTeam<
  T extends {
    agent_id: string;
    name: string;
    is_owner?: boolean;
    is_team_primary?: boolean;
    template_name?: string | null;
  },
>(
  experts: T[],
  team?: { primary_agent_id?: string | null } | null,
): T | undefined;
export function createPrimaryNotice(options: any): any;
