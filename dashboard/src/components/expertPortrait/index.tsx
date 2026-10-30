import * as React from "react";
import { createExpertAvatars } from "./avatar-library.mjs";
import { createExpertPresentation } from "./presentation.mjs";
import { useAgent } from "../../context/AgentContext";
import "./avatars.css";
import "./presentation.css";
export { randomAvatar } from "./presentation.mjs";
export const avatarUi = createExpertAvatars({ React });
export const { ExpertPortrait, TeamPortrait, HiddenRestore } =
  createExpertPresentation({ React, avatars: avatarUi, useAgent });
