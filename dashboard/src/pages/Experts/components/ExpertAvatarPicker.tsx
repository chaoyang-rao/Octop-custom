import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { avatarUi, randomAvatar } from "../../../components/expertPortrait";
export const AVATAR_MAX_BYTES = 5 * 1024 * 1024;
const AVATAR_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

export function validateAvatarFile(
  file: File,
  t: (key: string) => string,
): string | null {
  if (file.size > AVATAR_MAX_BYTES) {
    return t("experts.avatarTooLarge");
  }
  const type = (file.type || "").split(";")[0].trim().toLowerCase();
  if (
    type &&
    type !== "application/octet-stream" &&
    !AVATAR_ACCEPT.split(",").includes(type)
  ) {
    return t("experts.avatarBadType");
  }
  return null;
}

interface ExpertAvatarPickerProps {
  iconUrl?: string | null;
  iconName?: string | null;
  color?: string | null;
  disabled?: boolean;
  onPick: (file: File) => void | Promise<void>;
  onRemove?: () => void | Promise<void>;
  avatar?: { shape: string; color: string };
  onAvatarChange?: (value: { shape: string; color: string }) => void;
}
export default function ExpertAvatarPicker({
  avatar,
  onAvatarChange,
  disabled = false,
}: ExpertAvatarPickerProps) {
  const { t } = useTranslation();
  const [fallback, setFallback] = useState(randomAvatar);
  const value = avatar ?? fallback;
  const change = (next: typeof value) => {
    setFallback(next);
    onAvatarChange?.(next);
  };
  return (
    <div>
      <avatarUi.ShapeColorPicker
        shape={value.shape}
        color={value.color}
        onShapeChange={(shape: string) => change({ ...value, shape })}
        onColorChange={(color: string) => change({ ...value, color })}
        disabled={disabled}
      />
      <Button disabled={disabled} onClick={() => change(randomAvatar())}>
        {t("experts.randomAvatar")}
      </Button>
    </div>
  );
}
