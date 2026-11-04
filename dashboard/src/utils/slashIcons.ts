import type { LucideIcon } from "../components/arcIcons";
import {
  Activity,
  Archive,
  ArrowLeftRight,
  BarChart3,
  Bot,
  CircleHelp,
  Clock,
  Coins,
  Cpu,
  List,
  Pin,
  PinOff,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
  Type,
  Undo2,
  Zap,
} from "../components/arcIcons";

export const SLASH_ICONS: Record<string, LucideIcon> = {
  Activity,
  Archive,
  ArrowLeftRight,
  BarChart3,
  Bot,
  CircleHelp,
  Clock,
  Coins,
  Cpu,
  List,
  Pin,
  PinOff,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
  Type,
  Undo2,
  Zap,
};

export function resolveSlashIcon(name: string): LucideIcon {
  return SLASH_ICONS[name] ?? Zap;
}
