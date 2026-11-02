import type { ComponentType } from "react";
import type { OctopUser } from "../../api/modules/auth";
export function accountDisplayName(
  user: Partial<OctopUser> | null | undefined,
): string;
export function accountInitials(
  user: Partial<OctopUser> | null | undefined,
): string;
export function initialsFromName(value: string): string;
export function createAccountAvatar(options: unknown): ComponentType<{
  user: Partial<OctopUser> | null | undefined;
  className?: string;
}>;
