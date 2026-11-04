import * as React from "react";
import { useTranslation } from "react-i18next";
import { createExpertAvatars } from "./avatar-library.mjs";
import {
  createExpertPresentation,
  createPrimaryNotice,
} from "./presentation.mjs";
import { useAgent } from "../../context/AgentContext";
import "./avatars.css";
import "./presentation.css";
import "./integration.css";
export { randomAvatar, primaryExpertForTeam } from "./presentation.mjs";
export const avatarUi = createExpertAvatars({ React });
function usePrimaryLabels() {
  const { t } = useTranslation();
  return {
    label: t("chat.primaryExpertBadge"),
    title: t("chat.primaryExpertBadgeTitle"),
  };
}
export const { ExpertPortrait, TeamPortrait, HiddenRestore } =
  createExpertPresentation({
    React,
    avatars: avatarUi,
    useAgent,
    usePrimaryLabels,
  });

export const PrimaryExpertNotice = createPrimaryNotice({
  React,
  Avatar: ExpertPortrait,
});
